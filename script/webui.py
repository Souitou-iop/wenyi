#!/usr/bin/env python3
"""跨平台启动文译 Web UI，并在服务就绪后打开浏览器。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def free_port(start: int = 8787) -> int:
    for port in range(start, start + 100):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("没有可用端口")


def main() -> int:
    port = free_port(int(os.environ.get("WENYI_WEB_PORT", "8787")))
    env = os.environ.copy()
    env["WENYI_WEB_PORT"] = str(port)
    command = [sys.executable, "-m", "trans_novel.web"]
    process = subprocess.Popen(command, cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen(f"{url}/api/health", timeout=0.4) as response:
                    if response.status == 200:
                        subprocess.run(
                            [sys.executable, str(ROOT / "script" / "open-webui.py"), url],
                            check=False,
                        )
                        print(f"文译 Web UI: {url}", flush=True)
                        return process.wait()
            except OSError:
                time.sleep(0.15)
        process.terminate()
        print("Web UI 服务启动超时", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
