@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 启动前端页面  http://localhost:5173
call npm run dev
echo.
echo 前端已退出。
pause