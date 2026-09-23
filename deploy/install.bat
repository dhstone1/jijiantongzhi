@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo 没有找到 docker，请先安装 Docker Desktop
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop 没启动，请先打开它再跑本脚本
  pause
  exit /b 1
)

set TAR=
for %%f in (jijiantongzhi-images*.tar) do set TAR=%%f
if "%TAR%"=="" (
  echo 当前目录没找到 jijiantongzhi-images*.tar 镜像包
  pause
  exit /b 1
)

echo ==^> 导入镜像 %TAR%（几百 MB，需要一两分钟）
docker load -i "%TAR%"
if errorlevel 1 (
  pause
  exit /b 1
)

if not exist .env (
  copy /y env.example .env >nul
  echo ==^> 已生成 .env，图片服务地址请按需改成钉钉能访问的 IP
)

echo ==^> 启动容器
docker compose up -d
if errorlevel 1 (
  pause
  exit /b 1
)

echo.
docker compose ps
echo.
echo 部署完成，浏览器访问：http://localhost/jijiantongzhi/
echo 首次打开用演示手机号 13900000000 登录（省级管理员）
pause
