from __future__ import annotations

import os
import tempfile
import unittest
import zipfile

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


if __name__ == "__main__":
    unittest.main()
