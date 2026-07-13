from __future__ import annotations

import os
import base64
import tempfile
import unittest
import zipfile
from pathlib import Path

from trans_novel.book_inspector import inspect_book


class TestBookInspector(unittest.TestCase):
    def test_extracts_epub_metadata_and_cover(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "book.epub")
            covers = os.path.join(d, "covers")
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("META-INF/container.xml", """<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'><rootfiles><rootfile full-path='OEBPS/content.opf'/></rootfiles></container>""")
                zf.writestr("OEBPS/content.opf", """<package xmlns='http://www.idpf.org/2007/opf'><metadata xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:title>Book Title</dc:title><dc:creator>Alice</dc:creator><dc:language>en</dc:language><dc:publisher>Press</dc:publisher><dc:date>2024</dc:date><dc:identifier>urn:isbn:1</dc:identifier><dc:description>A book.</dc:description><dc:subject>Fiction</dc:subject></metadata><manifest><item id='cover' href='cover.jpg' media-type='image/jpeg' properties='cover-image'/><item id='c1' href='c1.xhtml' media-type='application/xhtml+xml'/></manifest><spine><itemref idref='c1'/></spine></package>""")
                zf.writestr("OEBPS/cover.jpg", b"jpeg-data")
                zf.writestr("OEBPS/c1.xhtml", "<html><body><p>Hello</p></body></html>")

            result = inspect_book(path, covers, "book-id")

            self.assertEqual(result["title"], "Book Title")
            self.assertEqual(result["authors"], ["Alice"])
            self.assertEqual(result["chapterCount"], 1)
            self.assertEqual(result["subjects"], ["Fiction"])
            self.assertTrue(os.path.isfile(result["coverPath"]))

    def test_extracts_fb2_metadata_and_cover(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "book.fb2")
            cover = b"\x89PNG\r\n\x1a\nimage"
            Path(path).write_text(f"""<FictionBook xmlns:xlink="http://www.w3.org/1999/xlink">
              <description><title-info><genre>fiction</genre><author><first-name>Alice</first-name>
              <last-name>Writer</last-name></author><book-title>FB2 Book</book-title>
              <annotation><p>A useful book.</p></annotation><lang>en</lang>
              <coverpage><image xlink:href="#cover"/></coverpage></title-info>
              <publish-info><publisher>Press</publisher><year>2025</year><isbn>978-1</isbn></publish-info></description>
              <body><section/><section/></body>
              <binary id="cover" content-type="image/png">{base64.b64encode(cover).decode()}</binary>
            </FictionBook>""", encoding="utf-8")

            result = inspect_book(path, os.path.join(d, "covers"), "fb2-id")

            self.assertEqual(result["title"], "FB2 Book")
            self.assertEqual(result["authors"], ["Alice Writer"])
            self.assertEqual(result["publisher"], "Press")
            self.assertEqual(result["publicationDate"], "2025")
            self.assertEqual(result["identifier"], "978-1")
            self.assertEqual(result["description"], "A useful book.")
            self.assertEqual(result["subjects"], ["fiction"])
            self.assertEqual(result["chapterCount"], 2)
            self.assertEqual(Path(result["coverPath"]).read_bytes(), cover)

    def test_text_book_has_uniform_empty_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "plain.txt"
            path.write_text("hello", encoding="utf-8")

            result = inspect_book(str(path), str(Path(d) / "covers"), "txt-id")

            self.assertEqual(result["title"], "plain")
            self.assertEqual(result["authors"], [])
            self.assertEqual(result["publisher"], "")
            self.assertEqual(result["subjects"], [])
            self.assertEqual(result["chapterCount"], 0)
            self.assertEqual(result["fileSize"], 5)
            self.assertIsNone(result["coverPath"])

    def test_damaged_book_metadata_falls_back_without_failing_import(self):
        with tempfile.TemporaryDirectory() as d:
            for suffix in (".epub", ".fb2"):
                path = Path(d) / f"damaged{suffix}"
                path.write_bytes(b"not a valid book")

                result = inspect_book(str(path), str(Path(d) / "covers"), suffix[1:])

                self.assertEqual(result["title"], "damaged")
                self.assertEqual(result["authors"], [])
                self.assertEqual(result["fileSize"], path.stat().st_size)
                self.assertIsNone(result["coverPath"])


if __name__ == "__main__":
    unittest.main()
