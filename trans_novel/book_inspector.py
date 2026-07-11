"""无需第三方依赖的图书元数据检查器，供 macOS App 导入时使用。"""

from __future__ import annotations

import argparse
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


def _opf_path(zf: zipfile.ZipFile) -> str:
    root = ET.fromstring(zf.read("META-INF/container.xml"))
    for el in root.iter():
        if _local(el.tag) == "rootfile":
            return el.attrib["full-path"]
    raise ValueError("EPUB 缺少 OPF rootfile")


def inspect_book(path: str, cover_directory: str, book_id: str) -> dict:
    source = Path(path)
    stat = source.stat()
    if source.suffix.lower() != ".epub":
        return {
            "title": source.stem,
            "authors": [],
            "language": "",
            "publisher": "",
            "publicationDate": "",
            "identifier": "",
            "description": "",
            "subjects": [],
            "chapterCount": 0,
            "fileSize": stat.st_size,
            "coverPath": None,
        }

    with zipfile.ZipFile(source) as zf:
        opf_path = _opf_path(zf)
        root = ET.fromstring(zf.read(opf_path))
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
                suffix = Path(href).suffix or ".img"
                destination = Path(cover_directory) / f"{book_id}{suffix.lower()}"
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, destination.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                cover_path = str(destination)

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
