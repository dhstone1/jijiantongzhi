@echo off
chcp 65001 >nul
echo 正在停止运营数据推送系统...

for %%P in (8080 5173) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
    taskkill /PID %%A /F >nul 2>nul
    echo   已停止端口 %%P 上的进程 %%A
  )
)

echo.
echo  完成。
pause