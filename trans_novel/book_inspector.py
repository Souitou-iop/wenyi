"""无需第三方依赖的图书元数据检查器，供本机客户端与 Web UI 导入时使用。"""

from __future__ import annotations

import base64
import posixpath
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _texts(root: ET.Element, name: str) -> list[str]:
    return [(el.text or "").strip() for el in root.iter() if _local(el.tag) == name and (el.text or "").strip()]


def _first(root: ET.Element, name: str) -> str:
    return (_texts(root, name) or [""])[0]


def _element_text(root: ET.Element, name: str) -> str:
    element = next((el for el in root.iter() if _local(el.tag) == name), None)
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _attribute(element: ET.Element, name: str) -> str:
    return next((value for key, value in element.attrib.items() if _local(key) == name), "")


def _empty_metadata(source: Path, stat_size: int, *, chapter_count: int = 0) -> dict:
    return {
        "title": source.stem,
        "authors": [],
        "language": "",
        "publisher": "",
        "publicationDate": "",
        "identifier": "",
        "description": "",
        "subjects": [],
        "chapterCount": chapter_count,
        "fileSize": stat_size,
        "coverPath": None,
    }


def _opf_path(zf: zipfile.ZipFile) -> str:
    root = ET.fromstring(zf.read("META-INF/container.xml"))
    for el in root.iter():
        if _local(el.tag) == "rootfile":
            return el.attrib["full-path"]
    raise ValueError("EPUB 缺少 OPF rootfile")


def inspect_book(path: str, cover_directory: str, book_id: str) -> dict:
    source = Path(path)
    stat = source.stat()
    ext = source.suffix.lower()

    if ext == ".docx":
        try:
            with zipfile.ZipFile(source) as zf:
                title = source.stem
                authors: list[str] = []
                language = ""
                description = ""
                subjects: list[str] = []
                if "docProps/core.xml" in zf.namelist():
                    try:
                        core_root = ET.fromstring(zf.read("docProps/core.xml"))
                        title = _first(core_root, "title") or title
                        creator = _first(core_root, "creator")
                        if creator:
                            authors.append(creator)
                        language = _first(core_root, "language")
                        description = _first(core_root, "description")
                        subj = _first(core_root, "subject")
                        if subj:
                            subjects.append(subj)
                    except (ET.ParseError, KeyError):
                        pass

                chapter_count = 1
                if "word/document.xml" in zf.namelist():
                    try:
                        doc_root = ET.fromstring(zf.read("word/document.xml"))
                        # 统计 Heading 1 / 标题数量作为章节估算
                        headings = sum(
                            1
                            for p_style in doc_root.iter()
                            if _local(p_style.tag) == "pStyle"
                            and "heading" in _attribute(p_style, "val").lower()
                        )
                        if headings > 0:
                            chapter_count = headings
                    except (ET.ParseError, KeyError):
                        pass

                cover_path = None
                # 尝试提取缩略图或第一张图片作为封面
                thumb_candidates = [
                    name for name in zf.namelist()
                    if name.startswith("docProps/thumbnail") or (name.startswith("word/media/") and name.lower().endswith((".png", ".jpg", ".jpeg")))
                ]
                if thumb_candidates:
                    chosen = thumb_candidates[0]
                    suffix = Path(chosen).suffix or ".jpg"
                    destination = Path(cover_directory) / f"{book_id}{suffix.lower()}"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(chosen) as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    cover_path = str(destination)

                return {
                    "title": title,
                    "authors": authors,
                    "language": language,
                    "publisher": "",
                    "publicationDate": "",
                    "identifier": "",
                    "description": description,
                    "subjects": subjects,
                    "chapterCount": chapter_count,
                    "fileSize": stat.st_size,
                    "coverPath": cover_path,
                }
        except (zipfile.BadZipFile, OSError):
            return _empty_metadata(source, stat.st_size)

    if ext == ".srt":
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
            cue_count = text.count("-->")
            return _empty_metadata(source, stat.st_size, chapter_count=max(1, cue_count))
        except OSError:
            return _empty_metadata(source, stat.st_size)

    if ext in {".txt", ".md", ".markdown", ".pdf"}:
        return _empty_metadata(source, stat.st_size)

    if ext == ".fb2":
        try:
            root = ET.parse(source).getroot()
        except (ET.ParseError, OSError):
            return _empty_metadata(source, stat.st_size)
        title_info = next((el for el in root.iter() if _local(el.tag) == "title-info"), root)
        publish_info = next((el for el in root.iter() if _local(el.tag) == "publish-info"), root)
        authors = []
        for author in title_info.iter():
            if _local(author.tag) == "author":
                name = " ".join(_texts(author, "first-name") + _texts(author, "middle-name") + _texts(author, "last-name")).strip()
                if name:
                    authors.append(name)
        identifier = _first(root, "isbn") or _first(publish_info, "isbn")
        cover_path = None
        cover_link = next((_attribute(image, "href") for coverpage in title_info.iter()
                           if _local(coverpage.tag) == "coverpage" for image in coverpage.iter()
                           if _local(image.tag) == "image"), "")
        cover_id = cover_link.lstrip("#")
        if cover_id:
            binary = next((el for el in root.iter() if _local(el.tag) == "binary" and el.attrib.get("id") == cover_id), None)
            if binary is not None and binary.text:
                try:
                    media = binary.attrib.get("content-type", "image/jpeg")
                    ext_name = "." + media.split("/")[-1].split(";")[0].replace("jpeg", "jpg")
                    destination = Path(cover_directory) / f"{book_id}{ext_name}"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(base64.b64decode("".join(binary.text.split())))
                    cover_path = str(destination)
                except (ValueError, OSError):
                    cover_path = None
        return {
            "title": _first(title_info, "book-title") or source.stem,
            "authors": authors,
            "language": _first(title_info, "lang"),
            "publisher": _first(publish_info, "publisher"),
            "publicationDate": _first(publish_info, "year"),
            "identifier": identifier,
            "description": _element_text(title_info, "annotation"),
            "subjects": _texts(title_info, "genre"),
            "chapterCount": sum(1 for el in root.iter() if _local(el.tag) == "section"),
            "fileSize": stat.st_size,
            "coverPath": cover_path,
        }

    try:
        archive = zipfile.ZipFile(source)
        opf_path = _opf_path(archive)
        root = ET.fromstring(archive.read(opf_path))
    except (ET.ParseError, KeyError, OSError, ValueError, zipfile.BadZipFile):
        return _empty_metadata(source, stat.st_size)

    with archive as zf:
        manifest: dict[str, tuple[str, str, str]] = {}
        spine_count = 0
        cover_id = ""
        for el in root.iter():
            name = _local(el.tag)
            if name == "item":
                manifest[el.attrib.get("id", "")] = (
                    el.attrib.get("href", ""),
                    el.attrib.get("media-type", ""),
                    el.attrib.get("properties", ""),
                )
            elif name == "itemref":
                spine_count += 1
            elif name == "meta" and el.attrib.get("name", "").lower() == "cover":
                cover_id = el.attrib.get("content", "")

        cover_item = None
        for item_id, item in manifest.items():
            href, media, props = item
            if "cover-image" in props.split() or item_id == cover_id or ("cover" in item_id.lower() and media.startswith("image/")):
                cover_item = item
                break

        cover_path = None
        if cover_item:
            href, _media, _props = cover_item
            member = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href))
            if member in zf.namelist():
                try:
                    suffix = Path(href).suffix or ".img"
                    destination = Path(cover_directory) / f"{book_id}{suffix.lower()}"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, destination.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    cover_path = str(destination)
                except (KeyError, OSError, zipfile.BadZipFile):
                    cover_path = None

        return {
            "title": (_texts(root, "title") or [source.stem])[0],
            "authors": _texts(root, "creator"),
            "language": (_texts(root, "language") or [""])[0],
            "publisher": (_texts(root, "publisher") or [""])[0],
            "publicationDate": (_texts(root, "date") or [""])[0],
            "identifier": (_texts(root, "identifier") or [""])[0],
            "description": (_texts(root, "description") or [""])[0],
            "subjects": _texts(root, "subject"),
            "chapterCount": spine_count,
            "fileSize": stat.st_size,
            "coverPath": cover_path,
        }
