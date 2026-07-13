"""文译本机 Web UI 服务。"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import signal
import socket
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import uvicorn
import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
)
from pydantic import BaseModel, Field

from .book_inspector import inspect_book

SUPPORTED_BOOK_TYPES = {".epub", ".fb2", ".txt"}
METADATA_DEFAULTS: dict[str, Any] = {
    "authors": [], "language": "", "publisher": "", "publicationDate": "",
    "identifier": "", "description": "", "subjects": [], "chapterCount": 0,
    "fileSize": 0,
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        temporary.chmod(0o600)
    temporary.replace(path)


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


def _tier_config(tier: TierSettings) -> dict[str, Any]:
    return {
        "model": tier.model,
        "options": {
            "thinking": tier.thinking,
        },
    }


class WebSettings(BaseModel):
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    timeout: int = 600
    max_retries: int = 4
    strong: TierSettings = Field(default_factory=lambda: TierSettings(model="deepseek-v4-pro", thinking=True))
    cheap: TierSettings = Field(default_factory=lambda: TierSettings(model="deepseek-v4-flash", thinking=True))
    fast: TierSettings = Field(default_factory=lambda: TierSettings(model="deepseek-v4-flash"))
    mono: bool = True
    bilingual: bool = False
    bilingual_order: str = "target_first"
    polish: bool = True
    review: bool = True
    autofix_severe: bool = False
    book_understanding: bool = True
    consistency_qa: bool = False
    about_page: bool = True


class StartTaskRequest(BaseModel):
    book_id: str
    output_format: str = "epub"


class ConnectionModels(BaseModel):
    strong: str
    cheap: str
    fast: str


class TestConnectionRequest(BaseModel):
    base_url: str
    api_key: str = ""
    models: ConnectionModels


class GroupRequest(BaseModel):
    name: str


class BookGroupRequest(BaseModel):
    group_id: str | None = None


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
            if task.get("status") == "running":
                task["status"] = "paused"
                task["phase"] = "服务已重新启动"
                _atomic_json(self.task_file(task["id"]), task)


class TaskManager:
    def __init__(self, store: WebStore):
        self.store = store
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.listeners: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self.jobs: dict[str, asyncio.Task[None]] = {}
        self.book_tasks: dict[str, str] = {}

    def get(self, task_id: str) -> dict[str, Any]:
        path = self.store.task_file(task_id)
        if not path.exists():
            raise HTTPException(404, "任务不存在")
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, task: dict[str, Any]) -> None:
        task["updated_at"] = _now()
        _atomic_json(self.store.task_file(task["id"]), task)

    async def publish(self, task_id: str, event: dict[str, Any]) -> None:
        for queue in tuple(self.listeners.get(task_id, ())):
            await queue.put(event)

    async def start(self, book: dict[str, Any], output_format: str = "epub", task_id: str | None = None) -> dict[str, Any]:
        if output_format not in {"epub", "txt"}:
            raise HTTPException(400, "输出格式仅支持 epub 或 txt")
        if task_id and task_id in self.jobs:
            raise HTTPException(409, "任务已在运行")
        if book["id"] in self.book_tasks:
            raise HTTPException(409, "该图书已有运行中的任务")

        task_id = task_id or str(uuid.uuid4())
        output_dir = self.store.outputs_dir / task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{Path(book['filename']).stem}.zh.{output_format}"
        task = {
            "id": task_id,
            "book_id": book["id"],
            "title": book["title"],
            "status": "running",
            "phase": "准备启动",
            "label": "",
            "fraction": None,
            "completed": 0,
            "total": 0,
            "outputs": [],
            "error": None,
            "created_at": self.get(task_id).get("created_at", _now()) if self.store.task_file(task_id).exists() else _now(),
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
        finally:
            self.processes.pop(task["id"], None)
            self.jobs.pop(task["id"], None)
            if self.book_tasks.get(book["id"]) == task["id"]:
                self.book_tasks.pop(book["id"], None)

    async def _run(self, task: dict[str, Any], book: dict[str, Any], output: Path, output_format: str) -> None:
        settings = self.store.settings()
        config_path = self.store.tasks_dir / f"{task['id']}.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(yaml.safe_dump({
            "language": {"source": "auto", "target": "zh"},
            "llm": {
                "provider": "openai-compatible",
                "base_url": settings.base_url,
                "api_key_env": "WENYI_WEB_API_KEY",
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
            "paths": {"state_dir": str(self.store.state_dir / book["id"])},
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")
        env = os.environ.copy()
        env["WENYI_WEB_API_KEY"] = settings.api_key
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "trans_novel.app_worker",
            "--task-id", task["id"],
            "--input", book["path"],
            "--output", str(output),
            "--state-dir", str(self.store.state_dir / book["id"]),
            "--config", str(config_path),
            "--format", output_format,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self.processes[task["id"]] = process
        try:
            assert process.stdout is not None
            while line := await process.stdout.readline():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "phase":
                    task["phase"] = event.get("label") or event.get("phase") or ""
                elif event_type == "progress":
                    task.update(
                        fraction=event.get("fraction"),
                        completed=event.get("completed") or 0,
                        total=event.get("total") or 0,
                        label=event.get("label") or "",
                    )
                elif event_type == "completed":
                    task.update(status="completed", fraction=1.0, outputs=event.get("outputs") or [])
                elif event_type == "failed":
                    task.update(status="paused" if event.get("code") == "cancelled" else "failed", error=event.get("message"))
                self.save(task)
                await self.publish(task["id"], event)
            await process.wait()
            if process.returncode and task["status"] == "running":
                assert process.stderr is not None
                message = (await process.stderr.read()).decode(errors="replace").strip()
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
        task.update(status="paused", phase="已暂停")
        self.save(task)
        await self.publish(task_id, {"type": "failed", "code": "cancelled", "message": "任务已停止"})
        return task

    async def shutdown(self) -> None:
        await asyncio.gather(*(self.stop(task_id) for task_id in tuple(self.jobs)), return_exceptions=True)

    async def events(self, task_id: str) -> AsyncIterator[str]:
        self.get(task_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        listeners = self.listeners.setdefault(task_id, set())
        listeners.add(queue)
        try:
            yield f"data: {json.dumps({'type': 'snapshot', 'task': self.get(task_id)}, ensure_ascii=False)}\n\n"
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
        if not settings.api_key and store.settings().api_key:
            settings.api_key = store.settings().api_key
        store.save_settings(settings)
        return {"saved": True, "has_api_key": bool(settings.api_key)}

    @app.post("/api/settings/test-connection")
    def test_connection(request: TestConnectionRequest):
        api_key = request.api_key or store.settings().api_key
        if not api_key:
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
                api_key=api_key,
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
        with destination.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                target.write(chunk)
        metadata = inspect_book(str(destination), str(store.covers_dir), book_id)
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
    def delete_book(book_id: str):
        books = store.books()
        book = next((item for item in books if item["id"] == book_id), None)
        if not book:
            raise HTTPException(404, "图书不存在")
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
        return store.tasks()

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        return manager.get(task_id)

    @app.post("/api/tasks")
    async def start_task(request: StartTaskRequest):
        book = next((item for item in store.books() if item["id"] == request.book_id), None)
        if not book:
            raise HTTPException(404, "图书不存在")
        return await manager.start(book, request.output_format)

    @app.post("/api/tasks/{task_id}/stop")
    async def stop_task(task_id: str):
        return await manager.stop(task_id)

    @app.post("/api/tasks/{task_id}/resume")
    async def resume_task(task_id: str):
        task = manager.get(task_id)
        if task.get("status") not in {"paused", "failed"}:
            raise HTTPException(409, "任务当前不可继续")
        book = next((item for item in store.books() if item["id"] == task["book_id"]), None)
        if not book:
            raise HTTPException(404, "原始图书不存在")
        return await manager.start(book, task_id=task_id)

    @app.get("/api/tasks/{task_id}/events")
    async def task_events(task_id: str):
        return StreamingResponse(manager.events(task_id), media_type="text/event-stream")

    @app.get("/api/tasks/{task_id}/outputs/{name}")
    def download_output(task_id: str, name: str):
        task = manager.get(task_id)
        output = next((Path(path) for path in task.get("outputs", []) if Path(path).name == name), None)
        if not output or not output.is_file():
            raise HTTPException(404, "产物不存在")
        return FileResponse(output, filename=output.name)

    static_dir = web_dir or Path(__file__).resolve().parents[1] / "web" / "dist"
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
    host = os.environ.get("WENYI_WEB_HOST", "127.0.0.1")
    port = available_port(host, int(os.environ.get("WENYI_WEB_PORT", "8787")))
    print(f"WENYI_WEB_URL=http://{host}:{port}", flush=True)
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
