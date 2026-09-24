"""本机客户端使用的 JSON Lines worker。stdout 只承载协议事件。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .config import Config
from .pipeline.orchestrator import Orchestrator

PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class WorkerRequest:
    task_id: str
    input_path: str
    output_path: str
    state_dir: str
    config_path: str
    out_format: str = "epub"


class EventWriter:
    def __init__(self, task_id: str, *, stream: TextIO = sys.stdout):
        self.task_id = task_id
        self.stream = stream

    def emit(self, event_type: str, **payload) -> None:
        row = {
            "protocolVersion": PROTOCOL_VERSION,
            "taskID": self.task_id,
            "type": event_type,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            **payload,
        }
        self.stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.stream.flush()


def run_worker(request: WorkerRequest, *, stream: TextIO = sys.stdout) -> int:
    writer = EventWriter(request.task_id, stream=stream)
    writer.emit(
        "ready",
        workerVersion="0.1.0",
        pythonVersion=platform.python_version(),
        executable=sys.executable,
    )
    try:
        config = Config.load(request.config_path)
        config.state_dir = request.state_dir
        Path(request.output_path).parent.mkdir(parents=True, exist_ok=True)

        def on_phase(name: str, label: str) -> None:
            writer.emit("phase", phase=name, label=label)

        def on_progress(done: int, total: int, label: str) -> None:
            fraction = done / total if total else None
            writer.emit(
                "progress",
                completed=done,
                total=total,
                fraction=fraction,
                label=label,
            )

        result = Orchestrator(config).run_all(
            request.input_path,
            progress=on_progress,
            phase=on_phase,
            out_format=request.out_format,
            out_path=request.output_path,
        )
        report = result.get("report") or {}
        store = result.get("store")
        writer.emit(
            "completed",
            outputs=result.get("outputs") or [],
            summary=report.get("summary") or {},
            stateDirectory=getattr(store, "run_dir", request.state_dir),
        )
        return 0
    except KeyboardInterrupt:
        writer.emit("failed", code="cancelled", message="任务已停止")
        return 130
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        writer.emit("failed", code="worker_error", message=str(exc))
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="文译本机客户端 worker")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--format", default="epub", choices=("epub", "txt"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return run_worker(
        WorkerRequest(
            task_id=args.task_id,
            input_path=os.path.abspath(args.input),
            output_path=os.path.abspath(args.output),
            state_dir=os.path.abspath(args.state_dir),
            config_path=os.path.abspath(args.config),
            out_format=args.format,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
