@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo 启动后端 API  http://127.0.0.1:8080
python -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
echo.
echo 后端已退出。
pause