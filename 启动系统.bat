@echo off
chcp 65001 >nul
setlocal

echo.
echo   ==========================================
echo    运营数据推送系统  正在启动
echo   ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo  [错误] 未找到 python，请先安装 Python 3.11+ 并加入 PATH
  pause & exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo  [错误] 未找到 npm，请先安装 Node.js 18+
  pause & exit /b 1
)

if not exist "%~dp0backend\data\system.db" (
  echo  [首次运行] 安装后端依赖...
  pushd "%~dp0backend"
  python -m pip install -r requirements.txt
  popd
)

if not exist "%~dp0frontend\node_modules" (
  echo  [首次运行] 安装前端依赖...
  pushd "%~dp0frontend"
  call npm install
  popd
)

start "推送系统-后端" cmd /k "%~dp0backend\run.bat"
start "推送系统-前端" cmd /k "%~dp0frontend\run.bat"

echo  等待服务就绪...
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173/"

echo.
echo  已启动。如果浏览器没有自动打开，请手动访问：
echo      http://localhost:5173/
echo.
echo  演示账号：
echo      13900000000  陈静   管理员，可见全部归属地
echo      13900000001  张伟   襄都区
echo      13900000004  赵敏   宁晋县
echo.
echo  停止服务请运行「停止系统.bat」。
echo.
pause