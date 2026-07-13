import asyncio
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)

from trans_novel.config import Config, TierConfig
from trans_novel.glossary.store import GlossaryStore, GlossaryTerm
from trans_novel.ingest.models import Chapter, Document, Segment
from trans_novel.pipeline.runstore import RunStore, STATUS_DONE
from trans_novel.web import (
    TaskManager,
    TierSettings,
    WebSettings,
    WebStore,
    _tier_config,
    create_app,
)


class TestWebAPI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def _make_workspace(
        self,
        *,
        task_status: str = "completed",
        chapter_status: str = STATUS_DONE,
        save_run_dir: bool = False,
    ) -> tuple[dict, RunStore]:
        source = self.root / "books" / "book.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("Source paragraph", encoding="utf-8")
        book = {
            "id": "book-id",
            "filename": "book.txt",
            "path": str(source),
            "title": "Book",
            "metadata": {},
        }
        (self.root / "books.json").write_text(
            json.dumps([book]),
            encoding="utf-8",
        )
        state_dir = self.root / "state" / "task-id"
        workspace = RunStore(str(state_dir / "Book"))
        workspace.init_from_document(Document(
            title="Book",
            source_lang="en",
            target_lang="zh",
            fmt="text",
            source_path=str(source),
            chapters=[Chapter(
                index=0,
                title="Chapter One",
                segments=[
                    Segment(index=0, source="Hello", target="你好"),
                    Segment(index=1, source="World", target="世界"),
                ],
                meta={
                    "source_digest": "Chapter summary",
                    "review_issues": [{"type": "tone", "detail": "check"}],
                    "backtranslation_issues": [{"detail": "back"}],
                },
            )],
        ))
        manifest = workspace.load_manifest()
        manifest["chapters"][0]["status"] = chapter_status
        workspace.save_manifest(manifest)
        workspace.save_analysis({
            "genre": "fiction",
            "tone": "calm",
            "style_guide": "Keep it concise",
            "book_synopsis": "A short book",
        })
        workspace.save_usage({
            "totals": {
                "calls": 2,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cache_hit_tokens": 30,
                "cache_miss_tokens": 70,
                "cache_hit_rate": 0.3,
            },
            "by_tier": {"strong": {
                "calls": 2,
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cache_hit_tokens": 30,
                "cache_miss_tokens": 70,
                "cache_hit_rate": 0.3,
            }},
            "by_stage": {},
        })
        glossary = GlossaryStore(workspace.glossary_path)
        glossary.upsert_term(GlossaryTerm(source="Alice", target="爱丽丝"))
        glossary.close()
        task = {
            "id": "task-id",
            "book_id": "book-id",
            "title": "Book",
            "status": task_status,
            "phase": "正文翻译",
            "phase_code": "translating",
            "state_dir": str(state_dir),
            "config_path": str(self.root / "tasks" / "task-id.yaml"),
            "outputs": [],
            "outputs_stale": False,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        if save_run_dir:
            task["run_dir"] = workspace.run_dir
        self.client.app.state.manager.save(task)
        return task, workspace

    def test_health_and_settings_hide_saved_api_key(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        settings = WebSettings(
            provider="ollama",
            api_key="secret",
            base_url="http://127.0.0.1:11434/v1",
            glow_mode="corners",
            source_lang="ja",
            output_format="txt",
            timeout=321,
            max_retries=2,
            strong=TierSettings(model="strong-model", thinking=False),
            cheap=TierSettings(model="cheap-model", thinking=True),
            fast=TierSettings(model="fast-model", thinking=True),
            mono=False,
            bilingual=True,
            bilingual_order="source_first",
            autofix_severe=True,
        )
        self.assertEqual(self.client.put("/api/settings", json=settings.model_dump()).status_code, 200)
        loaded = self.client.get("/api/settings").json()
        self.assertEqual(loaded["base_url"], "http://127.0.0.1:11434/v1")
        self.assertEqual(loaded["provider"], "ollama")
        self.assertEqual(loaded["glow_mode"], "corners")
        self.assertEqual(loaded["source_lang"], "ja")
        self.assertEqual(loaded["output_format"], "txt")
        self.assertEqual(loaded["timeout"], 321)
        self.assertEqual(loaded["max_retries"], 2)
        self.assertFalse(loaded["strong"]["thinking"])
        self.assertTrue(loaded["fast"]["thinking"])
        self.assertFalse(loaded["mono"])
        self.assertTrue(loaded["bilingual"])
        self.assertEqual(loaded["bilingual_order"], "source_first")
        self.assertTrue(loaded["autofix_severe"])
        self.assertEqual(loaded["api_key"], "")
        self.assertTrue(loaded["has_api_key"])

        for glow_mode in ("none", "symmetric", "corners"):
            updated = WebSettings(
                provider="ollama",
                base_url="http://localhost:8080/v1",
                glow_mode=glow_mode,
            )
            response = self.client.put("/api/settings", json=updated.model_dump())
            self.assertEqual(response.status_code, 200)
            loaded = self.client.get("/api/settings").json()
            self.assertEqual(loaded["base_url"], "http://localhost:8080/v1")
            self.assertEqual(loaded["glow_mode"], glow_mode)
            saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["api_key"], "secret")

    def test_switching_provider_without_key_does_not_reuse_previous_secret(self):
        self.client.put(
            "/api/settings",
            json=WebSettings(api_key="deepseek-secret").model_dump(),
        )

        switched = WebSettings(
            provider="ollama",
            base_url="http://127.0.0.1:11434/v1",
        )
        response = self.client.put("/api/settings", json=switched.model_dump())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["has_api_key"])
        saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["provider"], "ollama")
        self.assertEqual(saved["api_key"], "")

    def test_legacy_settings_use_new_defaults(self):
        legacy = WebSettings().model_dump()
        for key in (
            "provider",
            "reasoning_style",
            "glow_mode",
            "source_lang",
            "output_format",
        ):
            legacy.pop(key)
        (self.root / "settings.json").write_text(json.dumps(legacy), encoding="utf-8")

        loaded = self.client.get("/api/settings").json()

        self.assertEqual(loaded["glow_mode"], "none")
        self.assertEqual(loaded["provider"], "deepseek")
        self.assertEqual(loaded["reasoning_style"], "none")
        self.assertEqual(loaded["source_lang"], "auto")
        self.assertEqual(loaded["output_format"], "epub")

    def test_settings_validate_fields_and_keep_an_output_enabled(self):
        payload = WebSettings().model_dump()
        payload.update(mono=False, bilingual=False)
        normalized = self.client.put("/api/settings", json=payload)
        self.assertEqual(normalized.status_code, 200)
        loaded = self.client.get("/api/settings").json()
        self.assertTrue(loaded["mono"])
        self.assertFalse(loaded["bilingual"])

        invalid_values = [
            ("base_url", "localhost:11434"),
            ("source_lang", "japanese"),
            ("output_format", "pdf"),
            ("bilingual_order", "side_by_side"),
            ("timeout", 0),
            ("max_retries", -1),
            ("provider", "unknown"),
            ("reasoning_style", "unknown"),
        ]
        for key, value in invalid_values:
            with self.subTest(key=key):
                invalid = WebSettings().model_dump()
                invalid[key] = value
                self.assertEqual(
                    self.client.put("/api/settings", json=invalid).status_code,
                    422,
                )

        empty_model = WebSettings().model_dump()
        empty_model["cheap"]["model"] = " "
        self.assertEqual(
            self.client.put("/api/settings", json=empty_model).status_code,
            422,
        )

    def test_tier_settings_use_provider_options_shape(self):
        payload = _tier_config(TierSettings(
            model="model-id",
            thinking=True,
        ))

        tier = TierConfig.model_validate(payload)

        self.assertEqual(tier.model, "model-id")
        self.assertEqual(tier.options, {
            "thinking": True,
        })

    def test_running_tasks_are_only_paused_when_service_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task_file = root / "tasks" / "task-id.json"
            task_file.parent.mkdir(parents=True)
            task = {
                "id": "task-id",
                "book_id": "book-id",
                "status": "running",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            task_file.write_text(json.dumps(task), encoding="utf-8")

            with TestClient(create_app(root)) as client:
                paused = client.get("/api/tasks").json()[0]
                self.assertEqual(paused["status"], "paused")
                self.assertEqual(paused["phase"], "服务已重新启动")

                task_file.write_text(json.dumps(task), encoding="utf-8")
                self.assertEqual(client.get("/api/tasks").json()[0]["status"], "running")

    def test_completed_task_cannot_be_stopped_or_resumed(self):
        task_file = self.root / "tasks" / "task-id.json"
        task_file.parent.mkdir(parents=True)
        task_file.write_text(json.dumps({
            "id": "task-id",
            "book_id": "book-id",
            "status": "completed",
            "outputs": [],
        }), encoding="utf-8")

        self.assertEqual(self.client.post("/api/tasks/task-id/stop").status_code, 409)
        self.assertEqual(self.client.post("/api/tasks/task-id/resume").status_code, 409)

    def test_resume_keeps_original_output_format(self):
        book = {
            "id": "book-id",
            "filename": "book.txt",
            "title": "Book",
            "path": str(self.root / "books" / "book.txt"),
            "metadata": {},
        }
        (self.root / "books.json").write_text(json.dumps([book]), encoding="utf-8")
        task_file = self.root / "tasks" / "task-id.json"
        task_file.parent.mkdir(parents=True)
        task = {
            "id": "task-id",
            "book_id": "book-id",
            "status": "paused",
            "output_format": "txt",
        }
        task_file.write_text(json.dumps(task), encoding="utf-8")

        with patch.object(
            self.client.app.state.manager,
            "start",
            AsyncMock(return_value=task),
        ) as start:
            response = self.client.post("/api/tasks/task-id/resume")

        self.assertEqual(response.status_code, 200)
        start.assert_awaited_once_with(book, "txt", task_id="task-id")

    def test_start_uses_saved_output_format_when_request_omits_it(self):
        book = {
            "id": "book-id",
            "filename": "book.txt",
            "title": "Book",
            "path": str(self.root / "books" / "book.txt"),
            "metadata": {},
        }
        (self.root / "books.json").write_text(json.dumps([book]), encoding="utf-8")
        self.client.put(
            "/api/settings",
            json=WebSettings(output_format="txt").model_dump(),
        )

        with patch.object(
            self.client.app.state.manager,
            "start",
            AsyncMock(return_value={"id": "task-id"}),
        ) as start:
            response = self.client.post("/api/tasks", json={"book_id": "book-id"})

        self.assertEqual(response.status_code, 200)
        start.assert_awaited_once_with(book, "txt")

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

    @patch("trans_novel.web.OpenAI")
    def test_connection_allows_local_provider_without_key(self, openai):
        self.client.put(
            "/api/settings",
            json=WebSettings(api_key="saved-cloud-secret").model_dump(),
        )
        openai.return_value.models.list.return_value = SimpleNamespace(data=[
            SimpleNamespace(id="local-model"),
        ])

        response = self.client.post("/api/settings/test-connection", json={
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "models": {
                "strong": "local-model",
                "cheap": "local-model",
                "fast": "local-model",
            },
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(openai.call_args.kwargs["api_key"], "local")

    @patch("trans_novel.web.OpenAI")
    def test_connection_reuses_saved_key_for_same_compatible_provider(self, openai):
        self.client.put(
            "/api/settings",
            json=WebSettings(
                provider="openai-compatible",
                base_url="https://example.test/v1",
                api_key="compatible-secret",
            ).model_dump(),
        )
        openai.return_value.models.list.return_value = SimpleNamespace(data=[
            SimpleNamespace(id="model"),
        ])

        response = self.client.post("/api/settings/test-connection", json={
            "provider": "openai-compatible",
            "base_url": "https://example.test/v1",
            "api_key": "",
            "models": {"strong": "model", "cheap": "model", "fast": "model"},
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(openai.call_args.kwargs["api_key"], "compatible-secret")

    def test_connection_does_not_reuse_key_from_another_cloud_provider(self):
        self.client.put(
            "/api/settings",
            json=WebSettings(api_key="deepseek-secret").model_dump(),
        )

        response = self.client.post("/api/settings/test-connection", json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
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

    def test_rejects_cross_site_writes(self):
        for origin in ("https://evil.example", "null"):
            with self.subTest(origin=origin):
                response = self.client.post(
                    "/api/groups",
                    json={"name": "Cross-site"},
                    headers={"Origin": origin},
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["detail"], "仅允许本机页面修改数据")
        self.assertEqual(self.client.get("/api/groups").json(), [])

    @patch("trans_novel.web.MAX_UPLOAD_BYTES", 4)
    def test_upload_rejects_oversized_file_and_removes_partial_data(self):
        response = self.client.post(
            "/api/books",
            files={"file": ("large.txt", b"12345", "text/plain")},
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["detail"], "图书文件不能超过 256 MB")
        self.assertEqual(list((self.root / "books").iterdir()), [])

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

    @patch("trans_novel.web.inspect_book", side_effect=ValueError("broken"))
    def test_upload_rolls_back_file_when_inspection_fails(self, _inspect):
        response = self.client.post(
            "/api/books",
            files={"file": ("broken.epub", b"not-an-epub", "application/epub+zip")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "无法读取图书")
        self.assertEqual(list((self.root / "books").glob("*")), [])
        self.assertEqual(self.client.get("/api/books").json(), [])

    @patch("trans_novel.web.load_document")
    def test_upload_rejects_book_without_translatable_text(self, load_document):
        load_document.return_value = SimpleNamespace(chapters=[
            SimpleNamespace(segments=[]),
        ])

        response = self.client.post(
            "/api/books",
            files={"file": ("empty.txt", b"   ", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "图书中没有可翻译正文")
        self.assertEqual(list((self.root / "books").glob("*")), [])

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

    def test_delete_rejects_running_task_and_cleans_non_running_task_data(self):
        source = self.root / "books" / "book.txt"
        source.parent.mkdir()
        source.write_text("book", encoding="utf-8")
        book = {
            "id": "book-id",
            "filename": "book.txt",
            "path": str(source),
            "title": "Book",
            "metadata": {},
        }
        (self.root / "books.json").write_text(json.dumps([book]), encoding="utf-8")
        task_dir = self.root / "tasks"
        task_dir.mkdir()
        task_file = task_dir / "task-id.json"
        config_path = task_dir / "task-id.yaml"
        state_dir = self.root / "state" / "task-id"
        output_dir = self.root / "outputs" / "task-id"
        state_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        config_path.write_text("config", encoding="utf-8")
        (state_dir / "state.json").write_text("{}", encoding="utf-8")
        (output_dir / "book.zh.txt").write_text("translated", encoding="utf-8")
        task = {
            "id": "task-id",
            "book_id": "book-id",
            "status": "running",
            "config_path": str(config_path),
            "state_dir": str(state_dir),
        }
        task_file.write_text(json.dumps(task), encoding="utf-8")

        self.assertEqual(self.client.delete("/api/books/book-id").status_code, 409)
        self.assertTrue(source.exists())

        task["status"] = "paused"
        task_file.write_text(json.dumps(task), encoding="utf-8")
        self.assertEqual(self.client.delete("/api/books/book-id").status_code, 200)
        for path in (source, task_file, config_path, state_dir, output_dir):
            self.assertFalse(path.exists())

    def test_restart_marks_orphan_export_failed_and_allows_delete(self):
        task, _ = self._make_workspace()
        task["exports"] = [
            {
                "id": "interrupted-export",
                "status": "pending",
                "path": str(
                    self.root
                    / "outputs"
                    / "task-id"
                    / "exports"
                    / "interrupted-export"
                    / "book.txt"
                ),
            },
            {"id": "completed-export", "status": "completed"},
            {"id": "failed-export", "status": "failed", "error": "old error"},
        ]
        self.client.app.state.manager.save(task)
        partial_dir = (
            self.root
            / "outputs"
            / "task-id"
            / "exports"
            / "interrupted-export"
        )
        partial_dir.mkdir(parents=True)
        (partial_dir / "book.txt").write_text("partial", encoding="utf-8")

        with TestClient(create_app(self.root)) as restarted:
            recovered = restarted.app.state.manager.get("task-id")
            records = {
                record["id"]: record
                for record in recovered["exports"]
            }
            self.assertEqual(records["interrupted-export"]["status"], "failed")
            self.assertIn("已中断", records["interrupted-export"]["error"])
            self.assertEqual(records["completed-export"]["status"], "completed")
            self.assertEqual(records["failed-export"]["error"], "old error")
            self.assertFalse(partial_dir.exists())
            self.assertEqual(
                restarted.delete("/api/books/book-id").status_code,
                200,
            )

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

    def test_task_api_hides_internal_paths_and_resolves_legacy_workspace(self):
        _, workspace = self._make_workspace()
        stale = self.client.app.state.manager.get("task-id")
        stale["status"] = "running"

        task = self.client.get("/api/tasks/task-id").json()
        resolved = self.client.app.state.manager.workspace(stale)

        self.assertTrue(task["workspace_ready"])
        self.assertEqual(resolved.run_dir, workspace.run_dir)
        for key in ("config_path", "state_dir", "run_dir"):
            self.assertNotIn(key, task)
        saved = self.client.app.state.manager.get("task-id")
        self.assertEqual(saved["status"], "completed")
        self.assertNotIn("run_dir", saved)

    def test_advanced_workspace_is_not_created_before_worker_prepares_it(self):
        task = {
            "id": "task-id",
            "book_id": "book-id",
            "status": "running",
            "state_dir": str(self.root / "state" / "task-id"),
        }
        self.client.app.state.manager.save(task)

        response = self.client.get("/api/tasks/task-id/chapters")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["workspace_ready"])
        self.assertEqual(response.json()["chapters"], [])
        self.assertFalse((self.root / "state" / "task-id").exists())

    def test_concurrent_task_updates_keep_both_changes(self):
        manager = self.client.app.state.manager
        manager.save({
            "id": "task-id",
            "book_id": "book-id",
            "status": "paused",
        })
        barrier = threading.Barrier(3)

        def update_field(name: str):
            barrier.wait()
            manager.update(
                "task-id",
                lambda task: task.__setitem__(name, True),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(update_field, "first"),
                executor.submit(update_field, "second"),
            ]
            barrier.wait()
            for future in futures:
                future.result(timeout=2)

        saved = manager.get("task-id")
        self.assertTrue(saved["first"])
        self.assertTrue(saved["second"])
        self.assertEqual(list((self.root / "tasks").glob("*.tmp")), [])

    def test_chapter_review_editing_marks_outputs_stale(self):
        _, workspace = self._make_workspace()

        chapters = self.client.get("/api/tasks/task-id/chapters").json()
        self.assertEqual(chapters["chapters"][0]["segment_count"], 2)
        detail = self.client.get("/api/tasks/task-id/chapters/0").json()
        self.assertEqual(detail["chapter"]["review_issues"][0]["type"], "tone")

        edited = self.client.patch(
            "/api/tasks/task-id/chapters/0/segments/1",
            json={"target": "新世界"},
        )
        self.assertEqual(edited.status_code, 200)
        self.assertTrue(edited.json()["outputs_stale"])
        self.assertEqual(workspace.load_chapter(0).segments[1].target, "新世界")
        self.assertTrue(
            self.client.post(
                "/api/tasks/task-id/chapters/0/review-complete"
            ).json()["review_complete"]
        )

        task = self.client.app.state.manager.get("task-id")
        task["status"] = "running"
        self.client.app.state.manager.save(task)
        blocked = self.client.patch(
            "/api/tasks/task-id/chapters/0/segments/0",
            json={"target": "blocked"},
        )
        self.assertEqual(blocked.status_code, 409)

    def test_analysis_patch_only_changes_editable_fields(self):
        _, workspace = self._make_workspace()

        loaded = self.client.get("/api/tasks/task-id/analysis").json()
        self.assertEqual(loaded["analysis"]["genre"], "fiction")
        self.assertEqual(
            loaded["analysis"]["chapter_summaries"][0]["summary"],
            "Chapter summary",
        )
        saved = self.client.patch(
            "/api/tasks/task-id/analysis",
            json={
                "style_guide": "Use short sentences",
                "book_synopsis": "Updated synopsis",
                "genre": "ignored",
            },
        )

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["analysis"]["genre"], "fiction")
        analysis = workspace.load_analysis()
        self.assertEqual(analysis["genre"], "fiction")
        self.assertEqual(analysis["style_guide"], "Use short sentences")
        self.assertEqual(analysis["book_synopsis"], "Updated synopsis")

    def test_glossary_crud_lock_unlock_and_conflict_resolution(self):
        _, workspace = self._make_workspace()

        created = self.client.post(
            "/api/tasks/task-id/glossary/terms",
            json={
                "source": "Rabbit",
                "target": "兔子",
                "reading": "rabbit",
                "type": "人物",
                "confidence": "high",
            },
        )
        self.assertEqual(created.status_code, 200)
        filtered = self.client.get(
            "/api/tasks/task-id/glossary/terms",
            params={"q": "rab", "type": "人物"},
        ).json()
        self.assertEqual([item["source"] for item in filtered["terms"]], ["Rabbit"])
        locked = self.client.post(
            "/api/tasks/task-id/glossary/terms/Rabbit/lock"
        ).json()
        self.assertTrue(locked["locked"])
        unlocked = self.client.post(
            "/api/tasks/task-id/glossary/terms/Rabbit/unlock"
        ).json()
        self.assertFalse(unlocked["locked"])

        glossary = GlossaryStore(workspace.glossary_path)
        glossary.upsert_term(GlossaryTerm(
            source="Alice",
            target="艾丽丝",
            confidence="low",
        ))
        glossary.close()
        conflict = self.client.get(
            "/api/tasks/task-id/glossary/conflicts"
        ).json()["conflicts"][0]
        resolved = self.client.post(
            f"/api/tasks/task-id/glossary/conflicts/{conflict['id']}/resolve",
            json={"choice": "proposed"},
        ).json()
        self.assertEqual(resolved["target"], "艾丽丝")
        self.assertTrue(resolved["locked"])
        self.assertEqual(
            self.client.delete(
                "/api/tasks/task-id/glossary/terms/Rabbit"
            ).status_code,
            200,
        )

    def test_usage_and_event_log_are_normalized_and_do_not_expose_paths(self):
        _, workspace = self._make_workspace()
        Path(workspace.event_log_path).write_text(
            "\n".join([
                json.dumps({
                    "ts": "2026-01-01T00:00:00+00:00",
                    "event": "chapter_done",
                    "chapter": 0,
                    "run_dir": "/secret/state",
                    "segments": [{"source": "secret text"}],
                }),
                '{"event":',
            ]),
            encoding="utf-8",
        )

        usage = self.client.get("/api/tasks/task-id/usage").json()
        self.assertTrue(usage["has_usage"])
        self.assertTrue(usage["cache_available"])
        self.assertEqual(usage["usage"]["totals"]["input_tokens"], 100)
        self.assertEqual(usage["usage"]["totals"]["output_tokens"], 20)
        events = self.client.get(
            "/api/tasks/task-id/events",
            params={"type": "chapter_done", "limit": 1},
        ).json()
        self.assertEqual(events["types"], ["chapter_done"])
        self.assertEqual(events["events"][0]["chapter"], 0)
        self.assertEqual(events["events"][0]["type"], "chapter_done")
        self.assertIsInstance(events["events"][0]["timestamp"], str)
        self.assertNotIn("run_dir", events["events"][0])
        self.assertNotIn("segments", events["events"][0])

    def test_empty_analysis_and_usage_distinguish_ready_workspace(self):
        _, workspace = self._make_workspace()
        Path(workspace.analysis_path).unlink()
        Path(workspace.usage_path).unlink()

        analysis = self.client.get("/api/tasks/task-id/analysis").json()
        self.assertTrue(analysis["workspace_ready"])
        self.assertIsNone(analysis["analysis"])

        usage = self.client.get("/api/tasks/task-id/usage").json()
        self.assertTrue(usage["workspace_ready"])
        self.assertFalse(usage["has_usage"])

    def test_reexport_and_historical_output_download(self):
        task, _ = self._make_workspace()
        historical = self.root / "outputs" / "task-id" / "old.txt"
        historical.parent.mkdir(parents=True)
        historical.write_text("old output", encoding="utf-8")
        task["outputs"] = [str(historical)]
        task["outputs_stale"] = True
        self.client.app.state.manager.save(task)

        exports = self.client.get("/api/tasks/task-id/exports").json()
        self.assertTrue(exports["outputs_stale"])
        self.assertTrue(exports["exports"][0]["historical"])
        self.assertEqual(
            self.client.get(
                "/api/tasks/task-id/exports/historical-0/download"
            ).text,
            "old output",
        )

        created = self.client.post(
            "/api/tasks/task-id/exports",
            json={
                "format": "txt",
                "mono": True,
                "bilingual": False,
                "bilingual_order": "target_first",
                "about_page": True,
            },
        )
        self.assertEqual(created.status_code, 200)
        record = created.json()
        self.assertEqual(record["status"], "completed")
        self.assertGreater(record["size"], 0)
        self.assertEqual(
            self.client.get(record["download_url"]).status_code,
            200,
        )
        self.assertFalse(
            self.client.get("/api/tasks/task-id/exports").json()["outputs_stale"]
        )

    def test_reexport_failure_is_recorded_and_partial_output_is_removed(self):
        self._make_workspace()

        with patch(
            "trans_novel.web.assemble",
            side_effect=RuntimeError("writer failed"),
        ):
            response = self.client.post(
                "/api/tasks/task-id/exports",
                json={
                    "format": "epub",
                    "mono": False,
                    "bilingual": True,
                    "bilingual_order": "source_first",
                    "about_page": False,
                },
            )

        self.assertEqual(response.status_code, 500)
        record = self.client.get(
            "/api/tasks/task-id/exports"
        ).json()["exports"][0]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"], "writer failed")
        self.assertFalse(
            (
                self.root
                / "outputs"
                / "task-id"
                / "exports"
                / record["id"]
            ).exists()
        )

    def test_segment_edit_during_export_keeps_outputs_stale(self):
        _, workspace = self._make_workspace()
        started = threading.Event()
        release = threading.Event()

        def blocking_assemble(_workspace, _source, out_path, *_args, **_kwargs):
            started.set()
            if not release.wait(timeout=2):
                raise RuntimeError("test export timed out")
            Path(out_path).write_text("exported", encoding="utf-8")
            return out_path

        async def scenario():
            transport = httpx.ASGITransport(app=self.client.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                export = asyncio.create_task(client.post(
                    "/api/tasks/task-id/exports",
                    json={
                        "format": "txt",
                        "mono": True,
                        "bilingual": False,
                        "bilingual_order": "target_first",
                        "about_page": True,
                    },
                ))
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                edited = await client.patch(
                    "/api/tasks/task-id/chapters/0/segments/0",
                    json={"target": "并发编辑"},
                )
                release.set()
                return edited, await export

        with patch("trans_novel.web.assemble", side_effect=blocking_assemble):
            edited, exported = asyncio.run(scenario())

        self.assertEqual(edited.status_code, 200)
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(workspace.load_chapter(0).segments[0].target, "并发编辑")
        self.assertTrue(
            self.client.get("/api/tasks/task-id/exports").json()["outputs_stale"]
        )

    def test_parallel_exports_preserve_both_records(self):
        self._make_workspace()
        all_started = threading.Event()
        release = threading.Event()
        count = 0
        count_lock = threading.Lock()

        def blocking_assemble(_workspace, _source, out_path, *_args, **_kwargs):
            nonlocal count
            with count_lock:
                count += 1
                if count == 2:
                    all_started.set()
            if not release.wait(timeout=2):
                raise RuntimeError("test export timed out")
            Path(out_path).write_text("exported", encoding="utf-8")
            return out_path

        async def scenario():
            transport = httpx.ASGITransport(app=self.client.app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                requests = [
                    asyncio.create_task(client.post(
                        "/api/tasks/task-id/exports",
                        json={
                            "format": output_format,
                            "mono": True,
                            "bilingual": False,
                            "bilingual_order": "target_first",
                            "about_page": True,
                        },
                    ))
                    for output_format in ("txt", "epub")
                ]
                self.assertTrue(await asyncio.to_thread(all_started.wait, 2))
                release.set()
                return await asyncio.gather(*requests)

        with patch("trans_novel.web.assemble", side_effect=blocking_assemble):
            responses = asyncio.run(scenario())

        self.assertTrue(all(response.status_code == 200 for response in responses))
        exports = self.client.get(
            "/api/tasks/task-id/exports"
        ).json()["exports"]
        self.assertEqual(len(exports), 2)
        self.assertEqual({record["format"] for record in exports}, {"txt", "epub"})
        self.assertTrue(all(record["status"] == "completed" for record in exports))

    def test_concurrent_glossary_first_write_preserves_conflict_rules(self):
        db_path = str(self.root / "concurrent-glossary.db")
        bootstrap = GlossaryStore(db_path)
        bootstrap.close()
        barrier = threading.Barrier(3)

        def insert(target: str):
            glossary = GlossaryStore(db_path)
            try:
                barrier.wait(timeout=2)
                return glossary.upsert_term(
                    GlossaryTerm(source="Alice", target=target),
                )
            finally:
                glossary.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(insert, "爱丽丝"),
                executor.submit(insert, "艾丽丝"),
            ]
            barrier.wait(timeout=2)
            results = [future.result(timeout=3) for future in futures]

        self.assertEqual(set(results), {"inserted", "conflict"})
        glossary = GlossaryStore(db_path)
        try:
            self.assertIn(
                glossary.get_term("Alice").target,
                {"爱丽丝", "艾丽丝"},
            )
            self.assertEqual(len(glossary.open_conflicts()), 1)
        finally:
            glossary.close()


class TestTaskManager(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = WebStore(Path(self.temp.name))
        self.manager = TaskManager(self.store)

    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.temp.cleanup()

    async def test_rejects_duplicate_book_and_cancels_starting_job(self):
        blocker = asyncio.Event()

        async def blocked_run(*_args):
            await blocker.wait()

        self.manager._run = blocked_run  # type: ignore[method-assign]
        book = {
            "id": "book-id",
            "filename": "book.epub",
            "title": "Book",
            "path": str(Path(self.temp.name) / "book.epub"),
        }
        self.store.save_books([book])

        task = await self.manager.start(book)
        with self.assertRaises(HTTPException) as duplicate:
            await self.manager.start(book)
        self.assertEqual(duplicate.exception.status_code, 409)

        stopped = await self.manager.stop(task["id"])

        self.assertEqual(stopped["status"], "paused")
        self.assertNotIn(task["id"], self.manager.jobs)
        self.assertNotIn(book["id"], self.manager.book_tasks)

    async def test_worker_config_uses_selected_provider(self):
        self.store.save_settings(WebSettings(
            provider="openrouter",
            source_lang="ja",
            timeout=321,
            max_retries=2,
            strong=TierSettings(model="strong-model", thinking=False),
            cheap=TierSettings(model="cheap-model", thinking=True),
            fast=TierSettings(model="fast-model", thinking=True),
            mono=False,
            bilingual=True,
            bilingual_order="source_first",
            autofix_severe=True,
        ))
        stream = SimpleNamespace(
            readline=AsyncMock(return_value=b""),
            read=AsyncMock(return_value=b""),
        )
        process = SimpleNamespace(
            stdout=stream,
            stderr=stream,
            returncode=0,
            wait=AsyncMock(return_value=0),
        )
        task = {"id": "task-id", "status": "running"}
        book = {
            "id": "book-id",
            "path": str(Path(self.temp.name) / "book.epub"),
        }

        with patch(
            "trans_novel.web.asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            await self.manager._run(
                task,
                book,
                Path(self.temp.name) / "book.zh.epub",
                "epub",
            )

        config = Config.load(str(self.store.tasks_dir / "task-id.yaml"))

        self.assertEqual(config.source_lang, "ja")
        self.assertEqual(config.llm.provider, "openrouter")
        self.assertEqual(config.llm.timeout, 321)
        self.assertEqual(config.llm.max_retries, 2)
        self.assertEqual(config.llm.tiers["strong"].model, "strong-model")
        self.assertEqual(config.llm.tiers["strong"].options, {"thinking": False})
        self.assertEqual(config.llm.tiers["fast"].options, {"thinking": True})
        self.assertFalse(config.output.mono)
        self.assertTrue(config.output.bilingual)
        self.assertEqual(config.output.bilingual_order, "source_first")
        self.assertTrue(config.pipeline.autofix_severe)

    async def test_resume_reuses_config_and_state_but_uses_current_api_key(self):
        self.store.save_settings(WebSettings(
            provider="openai",
            api_key="old-key",
            strong=TierSettings(model="old-model"),
        ))
        original_run = self.manager._run
        blocker = asyncio.Event()

        async def blocked_run(*_args):
            await blocker.wait()

        self.manager._run = blocked_run  # type: ignore[method-assign]
        book = {
            "id": "book-id",
            "filename": "book.epub",
            "title": "Book",
            "path": str(Path(self.temp.name) / "book.epub"),
        }
        self.store.save_books([book])
        task = await self.manager.start(book)
        await self.manager.stop(task["id"])
        first = self.manager.get(task["id"])
        config_path = Path(first["config_path"])
        state_dir = first["state_dir"]
        first.update(
            run_dir=str(Path(state_dir) / "Book"),
            exports=[{"id": "export-id", "path": "/old/export.epub"}],
            outputs_stale=True,
        )
        self.manager.save(first)
        self.assertEqual(Config.load(str(config_path)).llm.tiers["strong"].model, "old-model")

        self.store.save_settings(WebSettings(
            provider="openai",
            api_key="current-key",
            strong=TierSettings(model="new-model"),
        ))
        completed = json.dumps({"type": "completed", "outputs": []}).encode() + b"\n"
        stdout = SimpleNamespace(readline=AsyncMock(side_effect=[completed, b""]))
        stderr = SimpleNamespace(read=AsyncMock(return_value=b""))
        process = SimpleNamespace(
            stdout=stdout,
            stderr=stderr,
            returncode=0,
            wait=AsyncMock(return_value=0),
        )
        self.manager._run = original_run  # type: ignore[method-assign]
        with patch(
            "trans_novel.web.asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ) as spawn:
            resumed = await self.manager.start(book, task_id=task["id"])
            await self.manager.jobs[task["id"]]

        self.assertEqual(resumed["config_path"], str(config_path))
        self.assertEqual(resumed["state_dir"], state_dir)
        self.assertEqual(resumed["run_dir"], str(Path(state_dir) / "Book"))
        self.assertEqual(resumed["exports"][0]["id"], "export-id")
        self.assertFalse(resumed["outputs_stale"])
        config = Config.load(str(config_path))
        self.assertEqual(config.llm.provider, "openai")
        self.assertEqual(config.llm.tiers["strong"].model, "old-model")
        self.assertEqual(spawn.call_args.kwargs["env"]["WENYI_WEB_API_KEY"], "current-key")

    async def test_resume_rejects_key_from_a_different_provider(self):
        blocker = asyncio.Event()

        async def blocked_run(*_args):
            await blocker.wait()

        self.manager._run = blocked_run  # type: ignore[method-assign]
        self.store.save_settings(WebSettings(provider="openai", api_key="old-key"))
        book = {
            "id": "book-id",
            "filename": "book.epub",
            "title": "Book",
            "path": str(Path(self.temp.name) / "book.epub"),
        }
        self.store.save_books([book])
        task = await self.manager.start(book)
        await self.manager.stop(task["id"])
        self.store.save_settings(WebSettings(provider="openrouter", api_key="new-key"))

        with self.assertRaises(HTTPException) as mismatch:
            await self.manager.start(book, task_id=task["id"])

        self.assertEqual(mismatch.exception.status_code, 409)
        self.assertIn("API 端点", mismatch.exception.detail)

    async def test_resume_rejects_key_for_a_different_endpoint(self):
        blocker = asyncio.Event()

        async def blocked_run(*_args):
            await blocker.wait()

        self.manager._run = blocked_run  # type: ignore[method-assign]
        self.store.save_settings(WebSettings(
            provider="openai-compatible",
            base_url="https://old.example/v1/",
            api_key="old-key",
        ))
        book = {
            "id": "book-id",
            "filename": "book.epub",
            "title": "Book",
            "path": str(Path(self.temp.name) / "book.epub"),
        }
        self.store.save_books([book])
        task = await self.manager.start(book)
        await self.manager.stop(task["id"])
        self.store.save_settings(WebSettings(
            provider="openai-compatible",
            base_url="https://new.example/v1",
            api_key="new-key",
        ))

        with self.assertRaises(HTTPException) as mismatch:
            await self.manager.start(book, task_id=task["id"])

        self.assertEqual(mismatch.exception.status_code, 409)
        self.assertIn("API 端点", mismatch.exception.detail)

    async def test_optional_key_provider_snapshot_does_not_require_an_empty_env(self):
        for provider in ("openai-compatible", "ollama", "vllm"):
            with self.subTest(provider=provider):
                settings = WebSettings(
                    provider=provider,
                    base_url="http://127.0.0.1:8000/v1",
                    api_key="",
                )
                path = self.store.tasks_dir / f"{provider}.yaml"
                self.manager._write_config(path, settings, self.store.state_dir / provider)

                config = Config.load(str(path))
                self.assertIsNone(config.llm.api_key_env)

    async def test_task_snapshot_preserves_compatible_reasoning_style(self):
        settings = WebSettings(
            provider="openai-compatible",
            base_url="https://example.test/v1",
            reasoning_style="openrouter",
        )
        path = self.store.tasks_dir / "reasoning-style.yaml"

        self.manager._write_config(path, settings, self.store.state_dir / "reasoning-style")

        self.assertEqual(Config.load(str(path)).llm.reasoning_style, "openrouter")

    async def test_worker_drains_large_stderr_while_waiting_for_stdout(self):
        stderr_started = asyncio.Event()

        class Stdout:
            async def readline(self):
                await asyncio.wait_for(stderr_started.wait(), timeout=1)
                return b""

        chunks = [b"x" * 70000 + b"tail-message", b""]

        class Stderr:
            async def read(self, _size):
                stderr_started.set()
                return chunks.pop(0)

        process = SimpleNamespace(
            stdout=Stdout(),
            stderr=Stderr(),
            returncode=1,
            wait=AsyncMock(return_value=1),
        )
        task = {"id": "task-id", "status": "running"}
        book = {
            "id": "book-id",
            "path": str(Path(self.temp.name) / "book.epub"),
        }

        with patch(
            "trans_novel.web.asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            await self.manager._run(
                task,
                book,
                Path(self.temp.name) / "book.zh.epub",
                "epub",
            )

        saved = self.manager.get("task-id")
        self.assertEqual(saved["status"], "failed")
        self.assertTrue(saved["error"].endswith("tail-message"))
        self.assertLessEqual(len(saved["error"]), 2000)

    async def test_unexpected_worker_error_marks_task_failed(self):
        async def broken_run(*_args):
            raise RuntimeError("spawn failed")

        self.manager._run = broken_run  # type: ignore[method-assign]
        book = {
            "id": "book-id",
            "filename": "book.epub",
            "title": "Book",
            "path": str(Path(self.temp.name) / "book.epub"),
        }
        self.store.save_books([book])

        task = await self.manager.start(book)
        job = self.manager.jobs[task["id"]]
        await job
        saved = self.manager.get(task["id"])

        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["error"], "spawn failed")

    async def test_stop_does_not_overwrite_completed_task(self):
        completed = asyncio.Event()
        task = {
            "id": "task-id",
            "book_id": "book-id",
            "status": "running",
            "outputs": [],
        }
        self.manager.save(task)

        async def complete_task():
            await completed.wait()
            finished = self.manager.get(task["id"])
            finished.update(status="completed", outputs=["book.zh.epub"])
            self.manager.save(finished)

        async def wait_for_process():
            completed.set()
            return 0

        job = asyncio.create_task(complete_task())
        process = SimpleNamespace(
            returncode=None,
            send_signal=lambda _signal: None,
            wait=wait_for_process,
        )
        self.manager.jobs[task["id"]] = job
        self.manager.processes[task["id"]] = process
        self.manager.book_tasks[task["book_id"]] = task["id"]

        result = await self.manager.stop(task["id"])

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["outputs"], ["book.zh.epub"])
        self.manager.jobs.pop(task["id"], None)
        self.manager.processes.pop(task["id"], None)
        self.manager.book_tasks.pop(task["book_id"], None)

    async def test_sse_snapshot_does_not_expose_internal_paths(self):
        output = Path(self.temp.name) / "private" / "book.zh.epub"
        task = {
            "id": "task-id",
            "book_id": "book-id",
            "status": "completed",
            "outputs": [str(output)],
            "config_path": "/private/config.yaml",
            "state_dir": "/private/state",
            "run_dir": "/private/run",
        }
        self.manager.save(task)

        stream = self.manager.events("task-id")
        snapshot = json.loads((await anext(stream))[6:])
        await stream.aclose()

        public = snapshot["task"]
        self.assertEqual(public["outputs"], ["book.zh.epub"])
        for key in ("config_path", "state_dir", "run_dir"):
            self.assertNotIn(key, public)


if __name__ == "__main__":
    unittest.main()
