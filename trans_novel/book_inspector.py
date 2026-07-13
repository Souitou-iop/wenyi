"""无需第三方依赖的图书元数据检查器，供本机客户端导入时使用。"""

from __future__ import annotations

import argparse
import base64
import json
import os
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


def _empty_metadata(source: Path, stat_size: int) -> dict:
    return {"title": source.stem, "authors": [], "language": "", "publisher": "",
            "publicationDate": "", "identifier": "", "description": "", "subjects": [],
            "chapterCount": 0, "fileSize": stat_size, "coverPath": None}


def _opf_path(zf: zipfile.ZipFile) -> str:
    root = ET.fromstring(zf.read("META-INF/container.xml"))
    for el in root.iter():
        if _local(el.tag) == "rootfile":
            return el.attrib["full-path"]
    raise ValueError("EPUB 缺少 OPF rootfile")


def inspect_book(path: str, cover_directory: str, book_id: str) -> dict:
    source = Path(path)
    stat = source.stat()
    if source.suffix.lower() not in {".epub", ".fb2"}:
        return _empty_metadata(source, stat.st_size)

    if source.suffix.lower() == ".fb2":
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
                    ext = "." + media.split("/")[-1].split(";")[0].replace("jpeg", "jpg")
                    destination = Path(cover_directory) / f"{book_id}{ext}"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--cover-directory", required=True)
    parser.add_argument("--book-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(inspect_book(args.input, args.cover_directory, args.book_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
