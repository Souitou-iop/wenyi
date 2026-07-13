import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)

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

    @patch("trans_novel.web.OpenAI")
    def test_connection_lists_and_validates_unique_models_without_saving_draft(self, openai):
        openai.return_value.models.list.return_value = SimpleNamespace(data=[
            SimpleNamespace(id="strong-model"),
            SimpleNamespace(id="shared-model"),
        ])

        response = self.client.post("/api/settings/test-connection", json={
            "base_url": "https://draft.example/v1",
            "api_key": "temporary-secret",
            "models": {
                "strong": "strong-model",
                "cheap": "shared-model",
                "fast": "shared-model",
            },
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "models")
        self.assertEqual(response.json()["checked_models"], ["strong-model", "shared-model"])
        self.assertNotIn("api_key", response.json())
        openai.assert_called_once_with(
            api_key="temporary-secret",
            base_url="https://draft.example/v1",
            timeout=15,
            max_retries=0,
        )
        self.assertFalse((self.root / "settings.json").exists())

    @patch("trans_novel.web.OpenAI")
    def test_connection_uses_saved_key_and_reports_missing_models(self, openai):
        self.client.put("/api/settings", json=WebSettings(api_key="saved-secret").model_dump())
        openai.return_value.models.list.return_value = SimpleNamespace(data=[
            SimpleNamespace(id="strong-model"),
        ])

        response = self.client.post("/api/settings/test-connection", json={
            "base_url": "https://draft.example/v1",
            "api_key": "",
            "models": {
                "strong": "strong-model",
                "cheap": "cheap-model",
                "fast": "fast-model",
            },
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "模型不存在: cheap-model, fast-model")
        self.assertEqual(openai.call_args.kwargs["api_key"], "saved-secret")
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["base_url"], WebSettings().base_url)

    @patch("trans_novel.web.OpenAI")
    def test_connection_falls_back_only_when_model_list_is_unsupported(self, openai):
        request = httpx.Request("GET", "https://example.test/v1/models")
        response = httpx.Response(404, request=request)
        openai.return_value.models.list.side_effect = NotFoundError(
            "missing", response=response, body=None
        )

        result = self.client.post("/api/settings/test-connection", json={
            "base_url": "https://example.test/v1",
            "api_key": "secret",
            "models": {"strong": "a", "cheap": "b", "fast": "fast-model"},
        })

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["mode"], "completion")
        self.assertEqual(result.json()["checked_models"], ["fast-model"])
        openai.return_value.chat.completions.create.assert_called_once_with(
            model="fast-model",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )

    @patch("trans_novel.web.OpenAI")
    def test_connection_reports_missing_fast_model_during_fallback(self, openai):
        request = httpx.Request("GET", "https://example.test/v1/models")
        openai.return_value.models.list.side_effect = NotFoundError(
            "missing endpoint",
            response=httpx.Response(404, request=request),
            body=None,
        )
        openai.return_value.chat.completions.create.side_effect = NotFoundError(
            "missing model",
            response=httpx.Response(404, request=request),
            body=None,
        )

        response = self.client.post("/api/settings/test-connection", json={
            "base_url": "https://example.test/v1",
            "api_key": "secret",
            "models": {"strong": "a", "cheap": "b", "fast": "missing-fast"},
        })

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "模型不存在: missing-fast")

    @patch("trans_novel.web.OpenAI")
    def test_connection_error_mapping(self, openai):
        request = httpx.Request("GET", "https://example.test/v1/models")
        cases = [
            (
                AuthenticationError(
                    "bad key",
                    response=httpx.Response(401, request=request),
                    body=None,
                ),
                401,
            ),
            (
                PermissionDeniedError(
                    "forbidden",
                    response=httpx.Response(403, request=request),
                    body=None,
                ),
                403,
            ),
            (APITimeoutError(request), 504),
            (APIConnectionError(request=request), 502),
        ]
        payload = {
            "base_url": "https://example.test/v1",
            "api_key": "secret",
            "models": {"strong": "a", "cheap": "b", "fast": "c"},
        }

        for error, status in cases:
            with self.subTest(error=type(error).__name__):
                openai.return_value.models.list.side_effect = error
                response = self.client.post("/api/settings/test-connection", json=payload)
                self.assertEqual(response.status_code, status)

    def test_connection_rejects_missing_key(self):
        response = self.client.post("/api/settings/test-connection", json={
            "base_url": "https://example.test/v1",
            "api_key": "",
            "models": {"strong": "a", "cheap": "b", "fast": "c"},
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "缺少 API Key")

    def test_connection_rejects_invalid_endpoint_and_empty_model(self):
        invalid_endpoint = self.client.post("/api/settings/test-connection", json={
            "base_url": "not-a-url",
            "api_key": "secret",
            "models": {"strong": "a", "cheap": "b", "fast": "c"},
        })
        self.assertEqual(invalid_endpoint.status_code, 400)
        self.assertEqual(invalid_endpoint.json()["detail"], "模型服务地址无效")

        empty_model = self.client.post("/api/settings/test-connection", json={
            "base_url": "https://example.test/v1",
            "api_key": "secret",
            "models": {"strong": "a", "cheap": " ", "fast": "c"},
        })
        self.assertEqual(empty_model.status_code, 400)
        self.assertEqual(empty_model.json()["detail"], "模型名称不能为空")

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
        self.assertIsNone(book["group_id"])

    def test_book_with_unknown_group_is_returned_as_ungrouped(self):
        (self.root / "books.json").write_text(json.dumps([{
            "id": "old-id",
            "filename": "old.epub",
            "path": "/tmp/old.epub",
            "title": "Old Book",
            "metadata": {},
            "group_id": "missing-group",
        }]), encoding="utf-8")

        book = self.client.get("/api/books").json()[0]

        self.assertIsNone(book["group_id"])

    def test_group_crud_trims_names_and_rejects_duplicates(self):
        created = self.client.post("/api/groups", json={"name": "  Favorites  "})
        self.assertEqual(created.status_code, 200)
        group = created.json()
        self.assertEqual(group["name"], "Favorites")
        self.assertEqual(group["book_count"], 0)
        self.assertEqual(self.client.get("/api/groups").json(), [group])
        self.assertEqual(
            self.client.post("/api/groups", json={"name": "favorites"}).status_code,
            409,
        )
        self.assertEqual(self.client.post("/api/groups", json={"name": "  "}).status_code, 400)

        renamed = self.client.patch(
            f"/api/groups/{group['id']}",
            json={"name": "  Reading  "},
        )
        self.assertEqual(renamed.json()["name"], "Reading")
        self.assertEqual(
            self.client.patch("/api/groups/missing", json={"name": "Other"}).status_code,
            404,
        )
        other = self.client.post("/api/groups", json={"name": "Other"}).json()
        self.assertEqual(
            self.client.patch(
                f"/api/groups/{other['id']}",
                json={"name": "reading"},
            ).status_code,
            409,
        )

    def test_move_book_validates_group_and_persists_assignment(self):
        (self.root / "books.json").write_text(json.dumps([{
            "id": "book-id",
            "filename": "book.txt",
            "path": str(self.root / "book.txt"),
            "title": "Book",
            "metadata": {},
        }]), encoding="utf-8")
        group = self.client.post("/api/groups", json={"name": "Reading"}).json()

        moved = self.client.patch(
            "/api/books/book-id/group",
            json={"group_id": group["id"]},
        )

        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["group_id"], group["id"])
        persisted = json.loads((self.root / "books.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted[0]["group_id"], group["id"])
        ungrouped = self.client.patch("/api/books/book-id/group", json={"group_id": None})
        self.assertIsNone(ungrouped.json()["group_id"])
        self.assertEqual(
            self.client.patch("/api/books/book-id/group", json={"group_id": "missing"}).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch("/api/books/missing/group", json={"group_id": None}).status_code,
            404,
        )

    def test_delete_group_unassigns_books_without_deleting_them(self):
        group = self.client.post("/api/groups", json={"name": "Reading"}).json()
        (self.root / "books.json").write_text(json.dumps([{
            "id": "book-id",
            "filename": "book.txt",
            "path": str(self.root / "book.txt"),
            "title": "Book",
            "metadata": {},
            "group_id": group["id"],
        }]), encoding="utf-8")

        response = self.client.delete(f"/api/groups/{group['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/groups").json(), [])
        books = self.client.get("/api/books").json()
        self.assertEqual(len(books), 1)
        self.assertIsNone(books[0]["group_id"])
        self.assertEqual(self.client.delete("/api/groups/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
