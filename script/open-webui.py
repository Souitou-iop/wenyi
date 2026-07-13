#!/usr/bin/env python3
"""使用系统默认浏览器打开文译 Web UI。"""

from __future__ import annotations

import sys
import webbrowser


if __name__ == "__main__":
    raise SystemExit(0 if webbrowser.open(sys.argv[1]) else 1)
