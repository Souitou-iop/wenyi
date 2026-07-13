"""文译本机 Web UI 服务。"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import signal
import shutil
import socket
import sys
import threading
import time
import uuid
from contextlib import ExitStack, asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Literal
from urllib.parse import urlparse

import uvicorn
import yaml
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
)
from pydantic import BaseModel, Field, field_validator, model_validator

from .book_inspector import inspect_book
from .assemble.writer import assemble
from .glossary.store import GlossaryStore, GlossaryTerm
from .ingest.segmenter import load_document
from .pipeline.runstore import RunStore, STATUS_DONE

SUPPORTED_BOOK_TYPES = {".epub", ".fb2", ".txt"}
MAX_UPLOAD_BYTES = 256 * 1024 * 1024
KEY_OPTIONAL_PROVIDERS = {"openai-compatible", "ollama", "vllm"}
METADATA_DEFAULTS: dict[str, Any] = {
    "authors": [], "language": "", "publisher": "", "publicationDate": "",
    "identifier": "", "description": "", "subjects": [], "chapterCount": 0,
    "fileSize": 0,
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _public_book(book: dict[str, Any]) -> dict[str, Any]:
    result = dict(book)
    stored = book.get("metadata") if isinstance(book.get("metadata"), dict) else {}
    metadata = {key: stored.get(key, default) for key, default in METADATA_DEFAULTS.items()}
    metadata["coverUrl"] = f"/api/books/{book.get('id')}/cover" if stored.get("coverPath") else None
    result["metadata"] = metadata
    result["title"] = book.get("title") or stored.get("title") or Path(book.get("filename") or "").stem
    result["group_id"] = book.get("group_id")
    return result


class TierSettings(BaseModel):
    model: str
    thinking: bool = False

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模型名称不能为空")
        return value


def _tier_config(tier: TierSettings) -> dict[str, Any]:
    return {
        "model": tier.model,
        "options": {
            "thinking": tier.thinking,
        },
    }


class WebSettings(BaseModel):
    provider: Literal[
        "deepseek", "openai", "openrouter", "openai-compatible", "ollama", "vllm"
    ] = "deepseek"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    reasoning_style: Literal["none", "deepseek", "openai", "openrouter"] = "none"
    glow_mode: Literal["none", "symmetric", "corners"] = "none"
    source_lang: str = "auto"
    output_format: Literal["epub", "txt"] = "epub"
    timeout: int = Field(default=600, ge=1)
    max_retries: int = Field(default=4, ge=0)
    strong: TierSettings = Field(default_factory=lambda: TierSettings(model="deepseek-v4-pro", thinking=True))
    cheap: TierSettings = Field(default_factory=lambda: TierSettings(model="deepseek-v4-flash", thinking=True))
    fast: TierSettings = Field(default_factory=lambda: TierSettings(model="deepseek-v4-flash"))
    mono: bool = True
    bilingual: bool = False
    bilingual_order: Literal["target_first", "source_first"] = "target_first"
    polish: bool = True
    review: bool = True
    autofix_severe: bool = False
    book_understanding: bool = True
    consistency_qa: bool = False
    about_page: bool = True

    @field_validator("source_lang")
    @classmethod
    def validate_source_lang(cls, value: str) -> str:
        value = value.strip().lower()
        if value != "auto" and not (len(value) == 2 and value.isascii() and value.isalpha()):
            raise ValueError("源语言必须为 auto 或 ISO 639-1 两字母代码")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip()
        endpoint = urlparse(value)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ValueError("模型服务地址无效")
        return value

    @model_validator(mode="after")
    def ensure_output_enabled(self):
        if not self.mono and not self.bilingual:
            self.mono = True
        return self


class StartTaskRequest(BaseModel):
    book_id: str
    output_format: Literal["epub", "txt"] | None = None


class ConnectionModels(BaseModel):
    strong: str
    cheap: str
    fast: str


class TestConnectionRequest(BaseModel):
    provider: Literal[
        "deepseek", "openai", "openrouter", "openai-compatible", "ollama", "vllm"
    ] = "deepseek"
    base_url: str
    api_key: str = ""
    models: ConnectionModels


class GroupRequest(BaseModel):
    name: str


class BookGroupRequest(BaseModel):
    group_id: str | None = None


class GlossaryTermRequest(BaseModel):
    source: str
    target: str
    reading: str = ""
    type: str = "术语"
    gender: str = ""
    aliases: list[str] = Field(default_factory=list)
    first_chapter: int | None = None
    note: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    locked: bool = False

    @field_validator("source", "target")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("术语原文和译文不能为空")
        return value


class ConflictResolutionRequest(BaseModel):
    choice: Literal["current", "proposed"]


class AnalysisUpdateRequest(BaseModel):
    style_guide: str | None = None
    book_synopsis: str | None = None


class SegmentUpdateRequest(BaseModel):
    target: str

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("译文不能为空")
        return value


class ExportRequest(BaseModel):
    format: Literal["epub", "txt"] = "epub"
    mono: bool = True
    bilingual: bool = False
    bilingual_order: Literal["target_first", "source_first"] = "target_first"
    about_page: bool = True

    @model_validator(mode="after")
    def ensure_single_mode(self):
        if self.mono == self.bilingual:
            raise ValueError("每次重新导出必须选择单语或双语之一")
        return self


class WebStore:
    def __init__(self, root: Path):
        self.root = root
        self.books_dir = root / "books"
        self.covers_dir = root / "covers"
        self.outputs_dir = root / "outputs"
        self.state_dir = root / "state"
        self.tasks_dir = root / "tasks"
        self.settings_file = root / "settings.json"
        self.books_file = root / "books.json"
        self.groups_file = root / "groups.json"
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.root.chmod(0o700)

    def settings(self) -> WebSettings:
        if not self.settings_file.exists():
            return WebSettings()
        return WebSettings.model_validate_json(self.settings_file.read_text(encoding="utf-8"))

    def save_settings(self, settings: WebSettings) -> None:
        _atomic_json(self.settings_file, settings.model_dump())

    def books(self) -> list[dict[str, Any]]:
        if not self.books_file.exists():
            return []
        return json.loads(self.books_file.read_text(encoding="utf-8"))

    def save_books(self, books: list[dict[str, Any]]) -> None:
        _atomic_json(self.books_file, books)

    def groups(self) -> list[dict[str, Any]]:
        if not self.groups_file.exists():
            return []
        return json.loads(self.groups_file.read_text(encoding="utf-8"))

    def save_groups(self, groups: list[dict[str, Any]]) -> None:
        _atomic_json(self.groups_file, groups)

    def task_file(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def tasks(self) -> list[dict[str, Any]]:
        tasks = []
        for path in self.tasks_dir.glob("*.json"):
            try:
                tasks.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(tasks, key=lambda item: item.get("created_at", ""), reverse=True)

    def pause_running_tasks(self) -> None:
        for task in self.tasks():
            changed = False
            if task.get("status") == "running":
                task["status"] = "paused"
                task["phase"] = "服务已重新启动"
                changed = True
            for export in task.get("exports") or []:
                if export.get("status") != "pending":
                    continue
                export.update(
                    status="failed",
                    error="服务已重新启动，重新导出已中断，请重试",
                )
                export_id = str(export.get("id") or "")
                if export_id and Path(export_id).name == export_id:
                    shutil.rmtree(
                        self.outputs_dir / task["id"] / "exports" / export_id,
                        ignore_errors=True,
                    )
                changed = True
            if changed:
                task["updated_at"] = _now()
                _atomic_json(self.task_file(task["id"]), task)


class TaskManager:
    def __init__(self, store: WebStore):
        self.store = store
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.listeners: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self.jobs: dict[str, asyncio.Task[None]] = {}
        self.book_tasks: dict[str, str] = {}
        self.lifecycle_lock = asyncio.Lock()
        self._task_locks: dict[str, threading.RLock] = {}
        self._task_locks_guard = threading.Lock()

    def task_lock(self, task_id: str) -> threading.RLock:
        with self._task_locks_guard:
            return self._task_locks.setdefault(task_id, threading.RLock())

    def _get_unlocked(self, task_id: str) -> dict[str, Any]:
        path = self.store.task_file(task_id)
        if not path.exists():
            raise HTTPException(404, "任务不存在")
        return json.loads(path.read_text(encoding="utf-8"))

    def get(self, task_id: str) -> dict[str, Any]:
        with self.task_lock(task_id):
            return self._get_unlocked(task_id)

    def workspace(self, task: dict[str, Any]) -> RunStore | None:
        candidates: list[Path] = []
        if task.get("run_dir"):
            candidates.append(Path(task["run_dir"]))
        state_dir = Path(
            task.get("state_dir")
            or self.store.state_dir / task.get("book_id", "")
        )
        candidates.append(state_dir)
        if state_dir.is_dir():
            manifests = list(state_dir.glob("*/manifest.json"))
            if len(manifests) == 1:
                candidates.append(manifests[0].parent)
        for candidate in candidates:
            if (candidate / "manifest.json").is_file():
                return RunStore(str(candidate), create=False)
        return None

    def public(self, task: dict[str, Any]) -> dict[str, Any]:
        result = {
            key: value
            for key, value in task.items()
            if key not in {
                "config_path", "state_dir", "run_dir", "content_revision",
            }
        }
        result["outputs"] = [
            Path(path).name for path in task.get("outputs") or []
        ]
        if "exports" in result:
            result["exports"] = [
                {
                    key: value
                    for key, value in record.items()
                    if key != "path"
                }
                for record in task.get("exports") or []
            ]
        result["workspace_ready"] = self.workspace(task) is not None
        return result

    def save(self, task: dict[str, Any]) -> None:
        with self.task_lock(task["id"]):
            task["updated_at"] = _now()
            _atomic_json(self.store.task_file(task["id"]), task)

    def update(
        self,
        task_id: str,
        change,
    ) -> dict[str, Any]:
        with self.task_lock(task_id):
            task = self._get_unlocked(task_id)
            change(task)
            task["updated_at"] = _now()
            _atomic_json(self.store.task_file(task_id), task)
            return task

    async def publish(self, task_id: str, event: dict[str, Any]) -> None:
        for queue in tuple(self.listeners.get(task_id, ())):
            await queue.put(event)

    def _write_config(self, path: Path, settings: WebSettings, state_dir: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({
            "language": {"source": settings.source_lang, "target": "zh"},
            "llm": {
                "provider": settings.provider,
                "base_url": settings.base_url,
                "reasoning_style": settings.reasoning_style,
                "api_key_env": (
                    "WENYI_WEB_API_KEY"
                    if settings.api_key or settings.provider not in KEY_OPTIONAL_PROVIDERS
                    else None
                ),
                "timeout": settings.timeout,
                "max_retries": settings.max_retries,
                "tiers": {
                    "strong": _tier_config(settings.strong),
                    "cheap": _tier_config(settings.cheap),
                    "fast": _tier_config(settings.fast),
                },
            },
            "pipeline": {
                "polish": settings.polish,
                "review": settings.review,
                "autofix_severe": settings.autofix_severe,
                "book_understanding": settings.book_understanding,
                "consistency_qa": settings.consistency_qa,
            },
            "output": {
                "mono": settings.mono,
                "bilingual": settings.bilingual,
                "bilingual_order": settings.bilingual_order,
                "about_page": settings.about_page,
            },
            "paths": {"state_dir": str(state_dir)},
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")

    async def start(self, book: dict[str, Any], output_format: str = "epub", task_id: str | None = None) -> dict[str, Any]:
        async with self.lifecycle_lock:
            return await self._start(book, output_format, task_id)

    async def _start(self, book: dict[str, Any], output_format: str, task_id: str | None) -> dict[str, Any]:
        if output_format not in {"epub", "txt"}:
            raise HTTPException(400, "输出格式仅支持 epub 或 txt")
        if not any(item["id"] == book["id"] for item in self.store.books()):
            raise HTTPException(404, "图书不存在")
        if task_id and task_id in self.jobs:
            raise HTTPException(409, "任务已在运行")
        if book["id"] in self.book_tasks:
            raise HTTPException(409, "该图书已有运行中的任务")

        previous = self.get(task_id) if task_id and self.store.task_file(task_id).exists() else None
        task_id = task_id or str(uuid.uuid4())
        config_path = Path(
            previous.get("config_path") if previous and previous.get("config_path")
            else self.store.tasks_dir / f"{task_id}.yaml"
        )
        state_dir = Path(
            previous.get("state_dir") if previous and previous.get("state_dir")
            else self.store.state_dir / (book["id"] if previous else task_id)
        )
        settings = self.store.settings()
        if previous and config_path.exists():
            snapshot = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            snapshot_llm = snapshot.get("llm") or {}
            snapshot_provider = snapshot_llm.get("provider", "deepseek")
            snapshot_base_url = str(snapshot_llm.get("base_url") or "").rstrip("/")
            current_base_url = settings.base_url.rstrip("/")
            if (
                snapshot_provider != settings.provider
                or snapshot_base_url != current_base_url
            ):
                raise HTTPException(
                    409,
                    "任务的模型服务或 API 端点与当前设置不一致，请恢复原设置后继续",
                )
        if not config_path.exists():
            self._write_config(config_path, settings, state_dir)
        output_dir = self.store.outputs_dir / task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{Path(book['filename']).stem}.zh.{output_format}"
        task = {
            "id": task_id,
            "book_id": book["id"],
            "title": book["title"],
            "status": "running",
            "phase": "准备启动",
            "phase_code": "preparing",
            "label": "",
            "fraction": None,
            "completed": 0,
            "total": 0,
            "outputs": list(previous.get("outputs") or []) if previous else [],
            "exports": list(previous.get("exports") or []) if previous else [],
            "outputs_stale": bool(previous.get("outputs_stale")) if previous else False,
            "content_revision": int(previous.get("content_revision") or 0) if previous else 0,
            "output_format": output_format,
            "config_path": str(config_path),
            "state_dir": str(state_dir),
            "run_dir": previous.get("run_dir") if previous else None,
            "error": None,
            "created_at": previous.get("created_at", _now()) if previous else _now(),
            "updated_at": _now(),
        }
        self.save(task)
        self.book_tasks[book["id"]] = task_id
        job = asyncio.create_task(self._run_job(task, book, output, output_format))
        self.jobs[task_id] = job
        return task

    async def _run_job(
        self,
        task: dict[str, Any],
        book: dict[str, Any],
        output: Path,
        output_format: str,
    ) -> None:
        try:
            await self._run(task, book, output, output_format)
        except Exception as exc:
            latest = self.get(task["id"])
            if latest.get("status") == "running":
                latest.update(status="failed", error=str(exc)[-2000:])
                self.save(latest)
                await self.publish(
                    task["id"],
                    {"type": "failed", "message": latest["error"]},
                )
        finally:
            self.processes.pop(task["id"], None)
            self.jobs.pop(task["id"], None)
            if self.book_tasks.get(book["id"]) == task["id"]:
                self.book_tasks.pop(book["id"], None)

    async def _run(self, task: dict[str, Any], book: dict[str, Any], output: Path, output_format: str) -> None:
        settings = self.store.settings()
        config_path = Path(task.get("config_path") or self.store.tasks_dir / f"{task['id']}.yaml")
        state_dir = Path(task.get("state_dir") or self.store.state_dir / book["id"])
        if not config_path.exists():
            self._write_config(config_path, settings, state_dir)
        env = os.environ.copy()
        env["WENYI_WEB_API_KEY"] = settings.api_key
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "trans_novel.app_worker",
            "--task-id", task["id"],
            "--input", book["path"],
            "--output", str(output),
            "--state-dir", str(state_dir),
            "--config", str(config_path),
            "--format", output_format,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self.processes[task["id"]] = process
        try:
            assert process.stdout is not None
            assert process.stderr is not None

            async def stderr_tail() -> str:
                tail = bytearray()
                while chunk := await process.stderr.read(8192):
                    tail.extend(chunk)
                    del tail[:-8192]
                return tail.decode(errors="replace").strip()

            stderr_job = asyncio.create_task(stderr_tail())
            while line := await process.stdout.readline():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "phase":
                    task["phase"] = event.get("label") or event.get("phase") or ""
                    task["phase_code"] = event.get("phase") or ""
                elif event_type == "progress":
                    task.update(
                        fraction=event.get("fraction"),
                        completed=event.get("completed") or 0,
                        total=event.get("total") or 0,
                        label=event.get("label") or "",
                    )
                elif event_type == "completed":
                    task.update(
                        status="completed",
                        fraction=1.0,
                        outputs=event.get("outputs") or [],
                        outputs_stale=False,
                        run_dir=event.get("stateDirectory") or task.get("run_dir"),
                    )
                elif event_type == "failed":
                    task.update(status="paused" if event.get("code") == "cancelled" else "failed", error=event.get("message"))
                self.save(task)
                public_event = dict(event)
                public_event.pop("stateDirectory", None)
                public_event.pop("executable", None)
                if "outputs" in public_event:
                    public_event["outputs"] = [
                        Path(path).name for path in public_event["outputs"] or []
                    ]
                await self.publish(task["id"], public_event)
            await process.wait()
            message = await stderr_job
            if process.returncode and task["status"] == "running":
                task.update(status="failed", error=message[-2000:] or f"worker exited {process.returncode}")
                self.save(task)
                await self.publish(task["id"], {"type": "failed", "message": task["error"]})
        finally:
            self.processes.pop(task["id"], None)

    async def stop(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        if task.get("status") != "running":
            raise HTTPException(409, "任务当前不可暂停")
        job = self.jobs.get(task_id)
        process = self.processes.get(task_id)
        if process and process.returncode is None:
            process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=8)
            except asyncio.TimeoutError:
                process.kill()
            if job and not job.done():
                await job
        elif job and not job.done():
            job.cancel()
            try:
                await job
            except asyncio.CancelledError:
                pass
            finally:
                self.jobs.pop(task_id, None)
                if self.book_tasks.get(task["book_id"]) == task_id:
                    self.book_tasks.pop(task["book_id"], None)
        latest = self.get(task_id)
        if latest.get("status") == "running":
            latest = self.update(
                task_id,
                lambda current: current.update(
                    status="paused",
                    phase="已暂停",
                ) if current.get("status") == "running" else None,
            )
            if latest.get("status") == "paused":
                await self.publish(
                    task_id,
                    {"type": "failed", "code": "cancelled", "message": "任务已停止"},
                )
        return latest

    async def shutdown(self) -> None:
        await asyncio.gather(*(self.stop(task_id) for task_id in tuple(self.jobs)), return_exceptions=True)

    async def events(self, task_id: str) -> AsyncIterator[str]:
        self.get(task_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        listeners = self.listeners.setdefault(task_id, set())
        listeners.add(queue)
        try:
            yield f"data: {json.dumps({'type': 'snapshot', 'task': self.public(self.get(task_id))}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            listeners.discard(queue)
            if not listeners:
                self.listeners.pop(task_id, None)


def _term_data(term: GlossaryTerm) -> dict[str, Any]:
    return {
        "source": term.source,
        "target": term.target,
        "reading": term.reading,
        "type": term.type,
        "gender": term.gender,
        "aliases": term.aliases,
        "first_chapter": term.first_chapter,
        "note": term.note,
        "confidence": term.confidence,
        "locked": term.locked,
        "status": term.status,
    }


def _workspace_or_409(
    manager: TaskManager,
    task_id: str,
) -> tuple[dict[str, Any], RunStore]:
    task = manager.get(task_id)
    workspace = manager.workspace(task)
    if workspace is None:
        raise HTTPException(409, "任务工作区尚未就绪")
    return task, workspace


def _chapter_entry(workspace: RunStore, chapter_index: int) -> dict[str, Any]:
    for chapter in workspace.load_manifest().get("chapters", []):
        if chapter.get("index") == chapter_index:
            return chapter
    raise HTTPException(404, "章节不存在")


def _editable_translation(task: dict[str, Any]) -> bool:
    return task.get("status") in {"paused", "failed", "completed"}


def _public_event(row: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "ts", "event", "chapter", "start_index", "count", "reason", "scope",
        "issue_count", "sample_count", "segment_count", "total_segments",
        "qa_issue_count", "chapters", "steps", "out_format",
    }
    result = {
        "type": str(row.get("event") or "event"),
        "timestamp": row.get("ts"),
    }
    result.update(
        {
            key: value
            for key, value in row.items()
            if key in allowed and key not in {"ts", "event"}
        }
    )
    return result


def _public_usage(usage: dict[str, Any]) -> dict[str, Any]:
    def normalize(slot: dict[str, Any]) -> dict[str, Any]:
        result = dict(slot)
        result["input_tokens"] = int(slot.get("prompt_tokens") or 0)
        result["output_tokens"] = int(slot.get("completion_tokens") or 0)
        result["cache_hits"] = int(slot.get("cache_hit_tokens") or 0)
        result["cache_misses"] = int(slot.get("cache_miss_tokens") or 0)
        return result

    return {
        "totals": normalize(usage.get("totals") or {}),
        "by_tier": {
            name: normalize(slot)
            for name, slot in (usage.get("by_tier") or {}).items()
        },
        "by_stage": {
            name: normalize(slot)
            for name, slot in (usage.get("by_stage") or {}).items()
        },
    }


def create_app(data_dir: Path | None = None, web_dir: Path | None = None) -> FastAPI:
    store = WebStore(data_dir or Path(os.environ.get("WENYI_WEB_DATA", Path.home() / ".wenyi-webui")))
    store.pause_running_tasks()
    manager = TaskManager(store)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await manager.shutdown()

    app = FastAPI(title="文译 Web UI", lifespan=lifespan)
    app.state.store = store
    app.state.manager = manager

    @app.middleware("http")
    async def reject_cross_site_writes(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            hostname = urlparse(origin).hostname if origin else None
            if (
                request.headers.get("sec-fetch-site") == "cross-site"
                or (origin is not None and hostname not in {"localhost", "127.0.0.1", "::1"})
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "仅允许本机页面修改数据"},
                )
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/settings")
    def get_settings():
        settings = store.settings().model_dump()
        settings["api_key"] = ""
        settings["has_api_key"] = bool(store.settings().api_key)
        return settings

    @app.put("/api/settings")
    def put_settings(settings: WebSettings):
        saved = store.settings()
        if not settings.api_key and settings.provider == saved.provider:
            settings.api_key = saved.api_key
        store.save_settings(settings)
        return {"saved": True, "has_api_key": bool(settings.api_key)}

    @app.post("/api/settings/test-connection")
    def test_connection(request: TestConnectionRequest):
        key_optional = request.provider in KEY_OPTIONAL_PROVIDERS
        saved = store.settings()
        api_key = request.api_key or (
            saved.api_key if request.provider == saved.provider else ""
        )
        if not api_key and not key_optional:
            raise HTTPException(400, "缺少 API Key")
        endpoint = urlparse(request.base_url)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise HTTPException(400, "模型服务地址无效")

        started = time.perf_counter()
        requested_models = list(dict.fromkeys(model.strip() for model in [
            request.models.strong, request.models.cheap, request.models.fast,
        ]))
        if any(not model for model in requested_models):
            raise HTTPException(400, "模型名称不能为空")
        mode = "models"
        try:
            client = OpenAI(
                api_key=api_key or "local",
                base_url=request.base_url,
                timeout=15,
                max_retries=0,
            )
            try:
                available = {model.id for model in client.models.list().data}
            except APIStatusError as exc:
                if exc.status_code not in {404, 405, 501}:
                    raise
                mode = "completion"
                client.chat.completions.create(
                    model=request.models.fast,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1,
                )
                requested_models = [request.models.fast]
            else:
                missing = [model for model in requested_models if model not in available]
                if missing:
                    raise HTTPException(400, f"模型不存在: {', '.join(missing)}")
        except AuthenticationError as exc:
            raise HTTPException(401, "API Key 认证失败") from exc
        except PermissionDeniedError as exc:
            raise HTTPException(403, "API Key 无权访问该服务") from exc
        except APITimeoutError as exc:
            raise HTTPException(504, "连接检测超时") from exc
        except APIConnectionError as exc:
            raise HTTPException(502, "无法连接模型服务") from exc
        except APIStatusError as exc:
            if mode == "completion" and exc.status_code == 404:
                raise HTTPException(400, f"模型不存在: {request.models.fast.strip()}") from exc
            raise HTTPException(502, f"模型服务返回错误 ({exc.status_code})") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "模型服务地址无效") from exc

        return {
            "ok": True,
            "mode": mode,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "checked_models": requested_models,
        }

    @app.get("/api/books")
    def get_books():
        group_ids = {group["id"] for group in store.groups()}
        return [
            _public_book({
                **book,
                "group_id": book.get("group_id") if book.get("group_id") in group_ids else None,
            })
            for book in store.books()
        ]

    @app.post("/api/books")
    async def upload_book(file: UploadFile = File(...)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in SUPPORTED_BOOK_TYPES:
            raise HTTPException(400, "仅支持 EPUB、FB2 和 TXT")
        book_id = str(uuid.uuid4())
        destination = store.books_dir / f"{book_id}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            written = 0
            with destination.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "图书文件不能超过 256 MB")
                    target.write(chunk)
            metadata = inspect_book(str(destination), str(store.covers_dir), book_id)
            document = load_document(str(destination), "auto", "zh")
            if not any(
                segment.source.strip()
                for chapter in document.chapters
                for segment in chapter.segments
            ):
                raise HTTPException(400, "图书中没有可翻译正文")
        except Exception as exc:
            destination.unlink(missing_ok=True)
            for cover in store.covers_dir.glob(f"{book_id}.*"):
                cover.unlink(missing_ok=True)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(400, "无法读取图书") from exc
        if suffix == ".txt":
            metadata["title"] = Path(file.filename or destination.name).stem
        book = {
            "id": book_id,
            "filename": file.filename,
            "path": str(destination),
            "title": metadata["title"],
            "metadata": metadata,
            "created_at": _now(),
        }
        books = store.books()
        books.insert(0, book)
        store.save_books(books)
        return _public_book(book)

    @app.get("/api/books/{book_id}/cover")
    def get_book_cover(book_id: str):
        book = next((item for item in store.books() if item.get("id") == book_id), None)
        if not book:
            raise HTTPException(404, "图书不存在")
        cover = book.get("metadata", {}).get("coverPath")
        if not cover or not Path(cover).is_file():
            raise HTTPException(404, "图书封面不存在")
        media_type = mimetypes.guess_type(cover)[0] or "application/octet-stream"
        return FileResponse(cover, media_type=media_type)

    @app.delete("/api/books/{book_id}")
    async def delete_book(book_id: str):
        async with manager.lifecycle_lock:
            books = store.books()
            book = next((item for item in books if item["id"] == book_id), None)
            if not book:
                raise HTTPException(404, "图书不存在")
            task_ids = sorted(
                task["id"]
                for task in store.tasks()
                if task.get("book_id") == book_id
            )
            with ExitStack() as locks:
                for task_id in task_ids:
                    locks.enter_context(manager.task_lock(task_id))
                tasks = [manager._get_unlocked(task_id) for task_id in task_ids]
                if any(task.get("status") == "running" for task in tasks):
                    raise HTTPException(409, "运行中的图书不能删除")
                if any(
                    any(
                        export.get("status") == "pending"
                        for export in task.get("exports") or []
                    )
                    for task in tasks
                ):
                    raise HTTPException(409, "重新导出完成前不能删除图书")
                for task in tasks:
                    config_path = Path(task.get("config_path") or store.tasks_dir / f"{task['id']}.yaml")
                    state_dir = Path(task.get("state_dir") or store.state_dir / book_id)
                    config_path.unlink(missing_ok=True)
                    shutil.rmtree(state_dir, ignore_errors=True)
                    shutil.rmtree(store.outputs_dir / task["id"], ignore_errors=True)
                    store.task_file(task["id"]).unlink(missing_ok=True)
            Path(book["path"]).unlink(missing_ok=True)
            cover = book.get("metadata", {}).get("coverPath")
            if cover:
                Path(cover).unlink(missing_ok=True)
            store.save_books([item for item in books if item["id"] != book_id])
            return {"deleted": True}

    @app.patch("/api/books/{book_id}/group")
    def move_book_to_group(book_id: str, request: BookGroupRequest):
        books = store.books()
        book = next((item for item in books if item["id"] == book_id), None)
        if not book:
            raise HTTPException(404, "图书不存在")
        if request.group_id is not None and not any(
            group["id"] == request.group_id for group in store.groups()
        ):
            raise HTTPException(404, "分组不存在")
        if request.group_id is None:
            book.pop("group_id", None)
        else:
            book["group_id"] = request.group_id
        store.save_books(books)
        return _public_book(book)

    @app.get("/api/groups")
    def get_groups():
        counts: dict[str, int] = {}
        for book in store.books():
            if group_id := book.get("group_id"):
                counts[group_id] = counts.get(group_id, 0) + 1
        return [
            {**group, "book_count": counts.get(group["id"], 0)}
            for group in store.groups()
        ]

    @app.post("/api/groups")
    def create_group(request: GroupRequest):
        name = request.name.strip()
        if not name:
            raise HTTPException(400, "分组名称不能为空")
        groups = store.groups()
        if any(group["name"].casefold() == name.casefold() for group in groups):
            raise HTTPException(409, "分组名称已存在")
        group = {"id": str(uuid.uuid4()), "name": name}
        groups.append(group)
        store.save_groups(groups)
        return {**group, "book_count": 0}

    @app.patch("/api/groups/{group_id}")
    def rename_group(group_id: str, request: GroupRequest):
        name = request.name.strip()
        if not name:
            raise HTTPException(400, "分组名称不能为空")
        groups = store.groups()
        group = next((item for item in groups if item["id"] == group_id), None)
        if not group:
            raise HTTPException(404, "分组不存在")
        if any(
            item["id"] != group_id and item["name"].casefold() == name.casefold()
            for item in groups
        ):
            raise HTTPException(409, "分组名称已存在")
        group["name"] = name
        store.save_groups(groups)
        return {
            **group,
            "book_count": sum(
                book.get("group_id") == group_id for book in store.books()
            ),
        }

    @app.delete("/api/groups/{group_id}")
    def delete_group(group_id: str):
        groups = store.groups()
        if not any(group["id"] == group_id for group in groups):
            raise HTTPException(404, "分组不存在")
        books = store.books()
        changed = False
        for book in books:
            if book.get("group_id") == group_id:
                book.pop("group_id")
                changed = True
        if changed:
            store.save_books(books)
        store.save_groups([group for group in groups if group["id"] != group_id])
        return {"deleted": True}

    @app.get("/api/tasks")
    def get_tasks():
        return [manager.public(task) for task in store.tasks()]

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        return manager.public(manager.get(task_id))

    @app.post("/api/tasks")
    async def start_task(request: StartTaskRequest):
        book = next((item for item in store.books() if item["id"] == request.book_id), None)
        if not book:
            raise HTTPException(404, "图书不存在")
        return manager.public(
            await manager.start(
                book,
                request.output_format or store.settings().output_format,
            )
        )

    @app.post("/api/tasks/{task_id}/stop")
    async def stop_task(task_id: str):
        return manager.public(await manager.stop(task_id))

    @app.post("/api/tasks/{task_id}/resume")
    async def resume_task(task_id: str):
        task = manager.get(task_id)
        if task.get("status") not in {"paused", "failed"}:
            raise HTTPException(409, "任务当前不可继续")
        book = next((item for item in store.books() if item["id"] == task["book_id"]), None)
        if not book:
            raise HTTPException(404, "原始图书不存在")
        return manager.public(
            await manager.start(
                book,
                task.get("output_format", "epub"),
                task_id=task_id,
            )
        )

    @app.get("/api/tasks/{task_id}/stream")
    async def task_stream(task_id: str):
        return StreamingResponse(manager.events(task_id), media_type="text/event-stream")

    @app.get("/api/tasks/{task_id}/chapters")
    def get_task_chapters(task_id: str):
        task = manager.get(task_id)
        workspace = manager.workspace(task)
        if workspace is None:
            return {
                "workspace_ready": False,
                "editable": False,
                "chapters": [],
            }
        chapters = []
        for entry in workspace.load_manifest().get("chapters", []):
            chapter = workspace.load_chapter(entry["index"])
            chapters.append({
                "index": entry["index"],
                "title": entry.get("title") or chapter.title,
                "title_translated": entry.get("title_translated") or "",
                "status": entry.get("status", "pending"),
                "segment_count": len(chapter.text_segments),
                "review_complete": bool(chapter.meta.get("human_reviewed")),
            })
        return {
            "workspace_ready": True,
            "editable": _editable_translation(task),
            "chapters": chapters,
        }

    @app.get("/api/tasks/{task_id}/chapters/{chapter_index}")
    def get_task_chapter(task_id: str, chapter_index: int):
        task, workspace = _workspace_or_409(manager, task_id)
        entry = _chapter_entry(workspace, chapter_index)
        if entry.get("status") != STATUS_DONE:
            raise HTTPException(409, "章节尚未翻译完成")
        chapter = workspace.load_chapter(chapter_index)
        return {
            "workspace_ready": True,
            "editable": _editable_translation(task),
            "chapter": {
                "index": chapter.index,
                "title": entry.get("title") or chapter.title,
                "title_translated": entry.get("title_translated") or "",
                "status": entry.get("status"),
                "review_complete": bool(chapter.meta.get("human_reviewed")),
                "source_digest": chapter.meta.get("source_digest") or "",
                "segments": [
                    {
                        "index": segment.index,
                        "source": segment.source,
                        "target": segment.target or "",
                        "kind": segment.kind,
                    }
                    for segment in chapter.text_segments
                ],
                "review_issues": chapter.meta.get("review_issues") or [],
                "backtranslation_issues": chapter.meta.get("backtranslation_issues") or [],
            },
        }

    @app.patch("/api/tasks/{task_id}/chapters/{chapter_index}/segments/{segment_index}")
    def update_task_segment(
        task_id: str,
        chapter_index: int,
        segment_index: int,
        request: SegmentUpdateRequest,
    ):
        with manager.task_lock(task_id):
            task, workspace = _workspace_or_409(manager, task_id)
            if not _editable_translation(task):
                raise HTTPException(409, "请先暂停任务再编辑译文")
            if _chapter_entry(workspace, chapter_index).get("status") != STATUS_DONE:
                raise HTTPException(409, "章节尚未翻译完成")
            chapter = workspace.load_chapter(chapter_index)
            segment = next(
                (item for item in chapter.segments if item.index == segment_index),
                None,
            )
            if segment is None or not segment.source.strip():
                raise HTTPException(404, "段落不存在")
            segment.target = request.target
            chapter.meta["human_reviewed"] = False
            workspace.save_chapter(chapter)
            workspace.log_event(
                "web_segment_edited",
                chapter=chapter_index,
                segment=segment_index,
            )
            task["outputs_stale"] = True
            task["content_revision"] = int(task.get("content_revision") or 0) + 1
            manager.save(task)
        return {"saved": True, "outputs_stale": True}

    @app.post("/api/tasks/{task_id}/chapters/{chapter_index}/review-complete")
    def mark_chapter_review_complete(task_id: str, chapter_index: int):
        with manager.task_lock(task_id):
            task, workspace = _workspace_or_409(manager, task_id)
            if not _editable_translation(task):
                raise HTTPException(409, "请先暂停任务再完成人工审校")
            if _chapter_entry(workspace, chapter_index).get("status") != STATUS_DONE:
                raise HTTPException(409, "章节尚未翻译完成")
            chapter = workspace.load_chapter(chapter_index)
            chapter.meta["human_reviewed"] = True
            workspace.save_chapter(chapter)
            workspace.log_event("web_chapter_review_completed", chapter=chapter_index)
        return {"saved": True, "review_complete": True}

    @app.get("/api/tasks/{task_id}/analysis")
    def get_task_analysis(task_id: str):
        task = manager.get(task_id)
        workspace = manager.workspace(task)
        if workspace is None:
            return {
                "workspace_ready": False,
                "editable": False,
                "analysis": None,
            }
        analysis = workspace.load_analysis()
        if analysis is None:
            return {
                "workspace_ready": True,
                "editable": False,
                "analysis": None,
            }
        chapter_summaries = []
        for entry in workspace.load_manifest().get("chapters", []):
            chapter = workspace.load_chapter(entry["index"])
            chapter_summaries.append({
                "index": entry["index"],
                "title": entry.get("title") or chapter.title,
                "summary": chapter.meta.get("source_digest") or "",
            })
        return {
            "workspace_ready": True,
            "editable": task.get("status") != "running"
            or task.get("phase_code") not in {"preparing", "prescan"},
            "analysis": {
                "genre": analysis.get("genre") or "",
                "tone": analysis.get("tone") or "",
                "narration": analysis.get("narration") or "",
                "pacing": analysis.get("pacing") or "",
                "register": analysis.get("register") or "",
                "dialogue_style": analysis.get("dialogue_style") or "",
                "rhetoric": analysis.get("rhetoric") or "",
                "characters": analysis.get("characters") or [],
                "style_guide": analysis.get("style_guide") or "",
                "book_synopsis": analysis.get("book_synopsis") or "",
                "chapter_summaries": chapter_summaries,
            },
        }

    @app.patch("/api/tasks/{task_id}/analysis")
    def update_task_analysis(task_id: str, request: AnalysisUpdateRequest):
        task, workspace = _workspace_or_409(manager, task_id)
        if (
            task.get("status") == "running"
            and task.get("phase_code") in {"preparing", "prescan"}
        ):
            raise HTTPException(409, "全书预扫完成后才能编辑风格概要")
        analysis = workspace.load_analysis()
        if analysis is None:
            raise HTTPException(409, "风格概要尚未生成")
        updates = request.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(400, "没有可保存的字段")
        analysis.update(updates)
        workspace.save_analysis(analysis)
        workspace.log_event(
            "web_analysis_edited",
            fields=sorted(updates),
        )
        return get_task_analysis(task_id)

    @app.get("/api/tasks/{task_id}/glossary/terms")
    def get_glossary_terms(
        task_id: str,
        q: str = "",
        term_type: str | None = Query(default=None, alias="type"),
    ):
        task = manager.get(task_id)
        workspace = manager.workspace(task)
        if workspace is None:
            return {
                "workspace_ready": False,
                "editable": False,
                "terms": [],
            }
        if not Path(workspace.glossary_path).is_file():
            return {
                "workspace_ready": False,
                "editable": False,
                "terms": [],
            }
        glossary = GlossaryStore(workspace.glossary_path)
        try:
            terms = glossary.all_terms()
        finally:
            glossary.close()
        needle = q.strip().casefold()
        if needle:
            terms = [
                term for term in terms
                if needle in term.source.casefold()
                or needle in term.target.casefold()
                or any(needle in alias.casefold() for alias in term.aliases)
            ]
        if term_type:
            type_aliases = {
                "person": "人物",
                "place": "地名",
                "organization": "组织",
                "term": "术语",
            }
            selected_type = type_aliases.get(term_type, term_type)
            terms = [term for term in terms if term.type == selected_type]
        return {
            "workspace_ready": True,
            "editable": True,
            "terms": [_term_data(term) for term in terms],
        }

    @app.post("/api/tasks/{task_id}/glossary/terms")
    def create_glossary_term(task_id: str, request: GlossaryTermRequest):
        _, workspace = _workspace_or_409(manager, task_id)
        if not Path(workspace.glossary_path).is_file():
            raise HTTPException(409, "术语表尚未生成")
        glossary = GlossaryStore(workspace.glossary_path)
        try:
            term = GlossaryTerm(**request.model_dump())
            result = glossary.upsert_term(term)
            saved = glossary.get_term(term.source)
        finally:
            glossary.close()
        workspace.log_event("web_glossary_term_saved", result=result)
        return _term_data(saved or term)

    @app.delete("/api/tasks/{task_id}/glossary/terms/{source}")
    def delete_glossary_term(task_id: str, source: str):
        _, workspace = _workspace_or_409(manager, task_id)
        if not Path(workspace.glossary_path).is_file():
            raise HTTPException(409, "术语表尚未生成")
        glossary = GlossaryStore(workspace.glossary_path)
        try:
            deleted = glossary.delete_term(source)
            glossary.mark_conflicts_resolved(source)
        finally:
            glossary.close()
        if not deleted:
            raise HTTPException(404, "术语不存在")
        workspace.log_event("web_glossary_term_deleted")
        return {"deleted": True}

    @app.post("/api/tasks/{task_id}/glossary/terms/{source}/lock")
    def lock_glossary_term(task_id: str, source: str):
        _, workspace = _workspace_or_409(manager, task_id)
        if not Path(workspace.glossary_path).is_file():
            raise HTTPException(409, "术语表尚未生成")
        glossary = GlossaryStore(workspace.glossary_path)
        try:
            if glossary.get_term(source) is None:
                raise HTTPException(404, "术语不存在")
            glossary.lock_term(source)
            term = glossary.get_term(source)
        finally:
            glossary.close()
        return _term_data(term)

    @app.post("/api/tasks/{task_id}/glossary/terms/{source}/unlock")
    def unlock_glossary_term(task_id: str, source: str):
        _, workspace = _workspace_or_409(manager, task_id)
        if not Path(workspace.glossary_path).is_file():
            raise HTTPException(409, "术语表尚未生成")
        glossary = GlossaryStore(workspace.glossary_path)
        try:
            if glossary.get_term(source) is None:
                raise HTTPException(404, "术语不存在")
            glossary.unlock_term(source)
            term = glossary.get_term(source)
        finally:
            glossary.close()
        return _term_data(term)

    @app.get("/api/tasks/{task_id}/glossary/conflicts")
    def get_glossary_conflicts(task_id: str):
        task = manager.get(task_id)
        workspace = manager.workspace(task)
        if workspace is None:
            return {"workspace_ready": False, "conflicts": []}
        if not Path(workspace.glossary_path).is_file():
            return {"workspace_ready": False, "conflicts": []}
        glossary = GlossaryStore(workspace.glossary_path)
        try:
            conflicts = glossary.open_conflicts()
        finally:
            glossary.close()
        return {
            "workspace_ready": True,
            "conflicts": [
                {
                    "id": conflict["id"],
                    "source": conflict["source"],
                    "current": conflict.get("existing_target") or "",
                    "proposed": conflict.get("proposed_target") or "",
                    "reason": conflict.get("note") or "",
                    "chapter": conflict.get("chapter"),
                }
                for conflict in conflicts
            ],
        }

    @app.post("/api/tasks/{task_id}/glossary/conflicts/{conflict_id}/resolve")
    def resolve_glossary_conflict(
        task_id: str,
        conflict_id: int,
        request: ConflictResolutionRequest,
    ):
        _, workspace = _workspace_or_409(manager, task_id)
        if not Path(workspace.glossary_path).is_file():
            raise HTTPException(409, "术语表尚未生成")
        glossary = GlossaryStore(workspace.glossary_path)
        try:
            conflict = next(
                (
                    item for item in glossary.open_conflicts()
                    if item["id"] == conflict_id
                ),
                None,
            )
            if conflict is None:
                raise HTTPException(404, "术语冲突不存在")
            target = (
                conflict["existing_target"]
                if request.choice == "current"
                else conflict["proposed_target"]
            )
            glossary.lock_term(conflict["source"], target)
            glossary.mark_conflicts_resolved(conflict["source"])
            term = glossary.get_term(conflict["source"])
        finally:
            glossary.close()
        workspace.log_event("web_glossary_conflict_resolved")
        return _term_data(term)

    @app.get("/api/tasks/{task_id}/usage")
    def get_task_usage(task_id: str):
        task = manager.get(task_id)
        workspace = manager.workspace(task)
        if workspace is None:
            return {
                "workspace_ready": False,
                "usage": _public_usage({}),
                "has_usage": False,
                "cache_available": False,
            }
        stored_usage = workspace.load_usage()
        stored = stored_usage or {
            "totals": {},
            "by_tier": {},
            "by_stage": {},
        }
        totals = stored.get("totals") or {}
        return {
            "workspace_ready": True,
            "usage": _public_usage(stored),
            "has_usage": stored_usage is not None,
            "cache_available": (
                int(totals.get("cache_hit_tokens") or 0)
                + int(totals.get("cache_miss_tokens") or 0)
            ) > 0,
        }

    @app.get("/api/tasks/{task_id}/events")
    def get_task_event_log(
        task_id: str,
        event_type: str | None = Query(default=None, alias="type"),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        task = manager.get(task_id)
        workspace = manager.workspace(task)
        if workspace is None:
            return {
                "workspace_ready": False,
                "events": [],
                "types": [],
            }
        events: list[dict[str, Any]] = []
        event_types: set[str] = set()
        path = Path(workspace.event_log_path)
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("event"):
                    event_types.add(str(row["event"]))
                if event_type and row.get("event") != event_type:
                    continue
                events.append(_public_event(row))
        events = events[-limit:]
        return {
            "workspace_ready": True,
            "events": events,
            "types": sorted(event_types),
        }

    def public_export(record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in record.items()
            if key != "path"
        }

    def task_exports(task: dict[str, Any]) -> list[dict[str, Any]]:
        records = list(task.get("exports") or [])
        known_paths = {record.get("path") for record in records}
        for index, raw_path in enumerate(task.get("outputs") or []):
            path = Path(raw_path)
            if raw_path in known_paths or not path.is_file():
                continue
            records.append({
                "id": f"historical-{index}",
                "format": path.suffix.lstrip(".").lower(),
                "mode": "historical",
                "bilingual_order": "",
                "about_page": False,
                "status": "completed",
                "size": path.stat().st_size,
                "created_at": task.get("updated_at") or task.get("created_at"),
                "error": None,
                "filename": path.name,
                "download_url": (
                    f"/api/tasks/{task['id']}/exports/historical-{index}/download"
                ),
                "historical": True,
                "path": raw_path,
            })
        return records

    @app.get("/api/tasks/{task_id}/exports")
    def get_task_exports(task_id: str):
        task = manager.get(task_id)
        if manager.workspace(task) is None:
            return {
                "workspace_ready": False,
                "outputs_stale": bool(task.get("outputs_stale")),
                "exports": [],
            }
        return {
            "workspace_ready": True,
            "outputs_stale": bool(task.get("outputs_stale")),
            "exports": [public_export(record) for record in task_exports(task)],
        }

    @app.post("/api/tasks/{task_id}/exports")
    async def create_task_export(task_id: str, request: ExportRequest):
        export_id = str(uuid.uuid4())
        export_dir = store.outputs_dir / task_id / "exports" / export_id
        with manager.task_lock(task_id):
            task, workspace = _workspace_or_409(manager, task_id)
            if task.get("status") == "running":
                raise HTTPException(409, "请先暂停任务再重新导出")
            if workspace.pending_chapters():
                raise HTTPException(409, "全部章节翻译完成后才能重新导出")
            book = next(
                (item for item in store.books() if item["id"] == task.get("book_id")),
                None,
            )
            if not book or not Path(book["path"]).is_file():
                raise HTTPException(404, "原始图书不存在")
            export_dir.mkdir(parents=True, exist_ok=True)
            suffix = request.format
            mode = "bilingual" if request.bilingual else "mono"
            output = export_dir / f"{Path(book['filename']).stem}.zh{'-bi' if request.bilingual else ''}.{suffix}"
            record = {
                "id": export_id,
                "format": request.format,
                "mode": mode,
                "bilingual_order": request.bilingual_order if request.bilingual else None,
                "about_page": request.about_page,
                "status": "pending",
                "size": 0,
                "created_at": _now(),
                "error": None,
                "filename": output.name,
                "download_url": f"/api/tasks/{task_id}/exports/{export_id}/download",
                "historical": False,
                "path": str(output),
            }
            revision = int(task.get("content_revision") or 0)
            task.setdefault("exports", []).append(record)
            manager.save(task)
        try:
            await asyncio.to_thread(
                assemble,
                workspace,
                book["path"],
                str(output),
                request.format,
                bilingual=request.bilingual,
                order=request.bilingual_order,
                about_page=request.about_page,
            )
        except Exception as exc:
            shutil.rmtree(export_dir, ignore_errors=True)
            def fail(current):
                saved = next(
                    item for item in current.get("exports") or []
                    if item.get("id") == export_id
                )
                saved.update(status="failed", error=str(exc)[-2000:])

            manager.update(task_id, fail)
            raise HTTPException(500, "重新导出失败") from exc

        def complete(current):
            saved = next(
                item for item in current.get("exports") or []
                if item.get("id") == export_id
            )
            saved.update(status="completed", size=output.stat().st_size)
            if int(current.get("content_revision") or 0) == revision:
                current["outputs_stale"] = False

        completed_task = manager.update(task_id, complete)
        completed_record = next(
            item for item in completed_task.get("exports") or []
            if item.get("id") == export_id
        )
        workspace.log_event(
            "web_export_completed",
            out_format=request.format,
        )
        return public_export(completed_record)

    @app.get("/api/tasks/{task_id}/exports/{export_id}/download")
    def download_task_export(task_id: str, export_id: str):
        task = manager.get(task_id)
        record = next(
            (
                item for item in task_exports(task)
                if item.get("id") == export_id
            ),
            None,
        )
        output = Path(record["path"]) if record and record.get("path") else None
        if (
            record is None
            or record.get("status") != "completed"
            or output is None
            or not output.is_file()
        ):
            raise HTTPException(404, "产物不存在")
        return FileResponse(output, filename=record["filename"])

    @app.get("/api/tasks/{task_id}/outputs/{name}")
    def download_output(task_id: str, name: str):
        task = manager.get(task_id)
        output = next((Path(path) for path in task.get("outputs", []) if Path(path).name == name), None)
        if not output or not output.is_file():
            raise HTTPException(404, "产物不存在")
        return FileResponse(output, filename=output.name)

    packaged_dir = Path(__file__).with_name("web_dist")
    source_dir = Path(__file__).resolve().parents[1] / "web" / "dist"
    static_dir = web_dir or (packaged_dir if packaged_dir.is_dir() else source_dir)
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app


def available_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 100):
        with socket.socket() as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError("没有可用端口")


def main() -> None:
    host = "127.0.0.1"
    port = available_port(host, int(os.environ.get("WENYI_WEB_PORT", "8787")))
    print(f"WENYI_WEB_URL=http://{host}:{port}", flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
