import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from trans_novel.config import TierConfig
from trans_novel.web import TierSettings, WebSettings, _tier_config, create_app


class TestWebAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_health_and_settings_hide_saved_api_key(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        settings = WebSettings(api_key="secret", base_url="https://example.test")
        self.assertEqual(self.client.put("/api/settings", json=settings.model_dump()).status_code, 200)
        loaded = self.client.get("/api/settings").json()
        self.assertEqual(loaded["base_url"], "https://example.test")
        self.assertEqual(loaded["api_key"], "")
        self.assertTrue(loaded["has_api_key"])

    def test_tier_settings_use_provider_options_shape(self):
        payload = _tier_config(TierSettings(
            model="model-id",
            thinking=True,
            reasoning_effort="medium",
        ))

        tier = TierConfig.model_validate(payload)

        self.assertEqual(tier.model, "model-id")
        self.assertEqual(tier.options, {
            "thinking": True,
            "reasoning_effort": "medium",
        })

    def test_upload_lists_and_deletes_text_book(self):
        uploaded = self.client.post(
            "/api/books",
            files={"file": ("novel.txt", b"hello", "text/plain")},
        )
        self.assertEqual(uploaded.status_code, 200)
        book = uploaded.json()
        self.assertEqual(book["title"], "novel")
        self.assertEqual(len(self.client.get("/api/books").json()), 1)
        self.assertEqual(self.client.delete(f"/api/books/{book['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/books").json(), [])

    def test_rejects_unsupported_book(self):
        response = self.client.post(
            "/api/books",
            files={"file": ("notes.pdf", b"%PDF", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)

    def test_cover_endpoint_and_delete_remove_files(self):
        source = self.root / "books" / "book.epub"
        cover = self.root / "covers" / "book.png"
        source.parent.mkdir()
        cover.parent.mkdir()
        source.write_bytes(b"book")
        cover.write_bytes(b"\x89PNG\r\n\x1a\n")
        (self.root / "books.json").write_text(json.dumps([{
            "id": "book-id", "filename": "book.epub", "path": str(source),
            "title": "Book", "metadata": {"coverPath": str(cover)},
        }]), encoding="utf-8")

        response = self.client.get("/api/books/book-id/cover")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(self.client.get("/api/books/missing/cover").status_code, 404)
        self.assertEqual(self.client.delete("/api/books/book-id").status_code, 200)
        self.assertFalse(source.exists())
        self.assertFalse(cover.exists())

    def test_cover_endpoint_returns_404_when_book_has_no_cover(self):
        (self.root / "books.json").write_text(json.dumps([{
            "id": "book-id", "filename": "book.txt", "path": str(self.root / "book.txt"),
            "title": "Book", "metadata": {},
        }]), encoding="utf-8")
        self.assertEqual(self.client.get("/api/books/book-id/cover").status_code, 404)

    def test_old_book_records_are_normalized_without_exposing_cover_path(self):
        cover = self.root / "old.jpg"
        cover.write_bytes(b"jpeg")
        (self.root / "books.json").write_text(json.dumps([{
            "id": "old-id", "filename": "old.epub", "path": "/tmp/old.epub",
            "metadata": {"title": "Old Book", "coverPath": str(cover)},
        }]), encoding="utf-8")

        book = self.client.get("/api/books").json()[0]

        self.assertEqual(book["title"], "Old Book")
        self.assertEqual(book["metadata"]["authors"], [])
        self.assertEqual(book["metadata"]["chapterCount"], 0)
        self.assertEqual(book["metadata"]["coverUrl"], "/api/books/old-id/cover")
        self.assertNotIn("coverPath", book["metadata"])


if __name__ == "__main__":
    unittest.main()
