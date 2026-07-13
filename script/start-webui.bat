@echo off
setlocal
cd /d "%~dp0\.."
uv run python script\webui.py
if errorlevel 1 pause
