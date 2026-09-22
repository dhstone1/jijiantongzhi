#!/usr/bin/env bash
# 运营数据推送系统 —— Ubuntu 一键部署
#
# 用法（在服务器上、仓库根目录里执行）：
#   sudo bash deploy/deploy.sh
#
# 可用环境变量覆盖：
#   SERVER_IP   对外访问地址，默认 192.168.220.132
#   APP_USER    跑服务的系统用户，默认当前 sudo 用户
#   PORT        后端监听端口，默认 18080
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVER_IP="${SERVER_IP:-192.168.220.132}"
APP_USER="${APP_USER:-${SUDO_USER:-$(whoami)}}"
PORT="${PORT:-18080}"
VENV="$REPO_DIR/.venv"
DATA_DIR="$REPO_DIR/backend/data"
SERVICE=/etc/systemd/system/jijiantongzhi.service
NGINX_SITE=/etc/nginx/sites-available/jijiantongzhi

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[1;32m✓\033[0m %s\n' "$1"; }
warn() { printf '    \033[1;33m!\033[0m %s\n' "$1"; }
die()  { printf '\n\033[1;31m[错误] %s\033[0m\n' "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "需要 root 权限，请用：sudo bash deploy/deploy.sh"
[ -f "$REPO_DIR/backend/app/main.py" ] || die "没找到 backend/app/main.py，请在仓库根目录执行"

log "1/6 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx curl ca-certificates
ok "python3 / nginx 就绪"

log "2/6 准备 Python 虚拟环境"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$REPO_DIR/backend/requirements.txt"
ok "依赖装好了（$VENV）"

log "3/6 准备前端产物"
if [ -f "$REPO_DIR/frontend/dist/index.html" ]; then
  ok "已有 frontend/dist，直接用（部署包里带的就是构建好的）"
else
  NODE_MAJOR=0
  if command -v node >/dev/null 2>&1; then
    NODE_MAJOR="$(node -v | sed 's/^v\([0-9]*\).*/\1/')"
  fi
  if [ "$NODE_MAJOR" -lt 18 ]; then
    warn "没找到 Node 18+，从 NodeSource 装一个 Node 20"
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y -qq nodejs
  fi
  log "    正在构建前端（首次会慢一点）"
  pushd "$REPO_DIR/frontend" >/dev/null
  npm install --no-audit --no-fund
  npm run build
  popd >/dev/null
  [ -f "$REPO_DIR/frontend/dist/index.html" ] || die "前端构建失败，没有产出 frontend/dist/index.html"
  ok "前端构建完成"
fi

log "4/6 准备数据目录"
mkdir -p "$DATA_DIR/images"
chown -R "$APP_USER":"$APP_USER" "$DATA_DIR" 2>/dev/null || true
ok "数据目录：$DATA_DIR"

log "5/6 注册后端服务（systemd）"
cat > "$SERVICE" <<UNIT
[Unit]
Description=运营数据推送系统 (jijiantongzhi)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$REPO_DIR/backend
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONIOENCODING=utf-8
# 钉钉客户端要能拉到报表图片，这里给出本机对外地址；
# 也可以在「系统设置 - 图片服务地址」里覆盖
Environment=PUBLIC_BASE_URL=http://$SERVER_IP
ExecStart=$VENV/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q jijiantongzhi
systemctl restart jijiantongzhi
sleep 3
if ! systemctl is-active --quiet jijiantongzhi; then
  journalctl -u jijiantongzhi -n 30 --no-pager || true
  die "后端没起来，日志见上"
fi
ok "后端已启动：127.0.0.1:$PORT"

log "6/6 配置 Nginx"
cat > "$NGINX_SITE" <<NGINX
server {
    listen 80 default_server;
    server_name $SERVER_IP _;

    root $REPO_DIR/frontend/dist;
    index index.html;

    # 前端是单页应用，刷新任何路由都回 index.html
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # 报表图片和 Excel 由后端直接提供（钉钉客户端会来拉）
    location /static/ {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 300s;
    }
}
NGINX
ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/jijiantongzhi
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable -q nginx
systemctl reload nginx
ok "Nginx 已就绪"

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null 2>&1 || true
  ok "ufw 已放行 80 端口"
fi

cat <<EOF

============================================================
 部署完成
============================================================
 访问地址：   http://$SERVER_IP/
 后端日志：   journalctl -u jijiantongzhi -f
 重启后端：   sudo systemctl restart jijiantongzhi
 重启前端：   sudo systemctl reload nginx
 数据目录：   $DATA_DIR

 加密密钥：   $DATA_DIR/secret.key
              ^ 备份它。丢了里面的钉钉 webhook 和口令就解不开了

 演示账号（首次启动会自动写入）：
     13900000000  陈静   省级管理员
     13900000006  孙磊   地市管理员（邢台市）
     13900000001  张伟   普通人员（襄都区）

 上线后建议马上做三件事：
   1. 登录后到「人员信息」改掉演示账号，或删掉不用的
   2. 到「系统设置 - 图片服务地址」确认是 http://$SERVER_IP
      （钉钉要能访问到这个地址，否则群里只见裂图）
   3. 这个系统是「手机号即身份」，同网段的人知道手机号就能冒充。
      只在内网用，或让运维在 Nginx 上加一层认证
============================================================
EOF
