#!/usr/bin/env bash
# 一键部署：导入镜像 -> 生成 .env -> 启动
# 用法：sudo bash install.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
    echo "没有找到 docker，请先安装 Docker（apt install docker.io，或官方安装脚本）"
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "docker 没在运行（或当前用户没权限）：试试用 sudo，或把用户加进 docker 组"
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "缺少 docker compose 插件，请先安装"
    exit 1
fi

TAR=""
for f in jijiantongzhi-images*.tar; do
    if [ -f "$f" ]; then TAR="$f"; break; fi
done
if [ -z "$TAR" ]; then
    echo "当前目录没找到 jijiantongzhi-images*.tar 镜像包"
    exit 1
fi

echo "==> 导入镜像 $TAR（几百 MB，需要一两分钟）"
docker load -i "$TAR"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ ! -f .env ]; then
    cp env.example .env
    if [ -n "$IP" ]; then
        sed -i "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=http://$IP#" .env
    fi
    echo "==> 已生成 .env（图片服务地址用 ${IP:-未识别}），要改直接编辑 .env"
fi

PORT="$(grep -E '^WEB_PORT=' .env | head -n1 | cut -d= -f2)"
PORT="${PORT:-80}"

echo "==> 启动容器"
$COMPOSE up -d

echo ""
echo "==> 状态"
$COMPOSE ps
echo ""
echo "部署完成，浏览器访问：http://${IP:-<服务器IP>}:$PORT/jijiantongzhi/"
echo "首次打开用演示手机号 13900000000 登录（省级管理员）"
echo "看日志：$COMPOSE logs -f"
echo "要发图片到钉钉：把 .env 里的 PUBLIC_BASE_URL 改成钉钉能访问的地址，再 $COMPOSE up -d"
