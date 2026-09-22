# Docker 部署文件

本文档介绍如何使用 Docker 容器化部署运营数据推送系统。

## 前置要求

- Docker >= 24.0
- Docker Compose >= 2.20

## 快速开始

### 1. 在项目根目录执行

`ash
# 可选：配置环境变量
cp docker/.env.example .env
# 编辑 .env 文件，设置 PUBLIC_BASE_URL 为服务器地址

# 构建并启动服务
docker compose -f docker-compose.yml up -d
`

### 2. 访问系统

打开浏览器访问 http://<服务器IP>/，使用演示账号登录：

| 手机号 | 姓名 | 角色 |
|---|---|---|
| 13900000000 | 陈静 | 省级管理员 |
| 13900000006 | 孙磊 | 地市管理员（邢台市） |
| 13900000001 | 张伟 | 普通人员（襄都区） |

### 3. 查看日志

`ash
# 后端日志
docker compose logs -f backend

# 前端日志
docker compose logs -f frontend
`

## 常用命令

`ash
# 启动服务
docker compose -f docker-compose.yml up -d

# 停止服务
docker compose -f docker-compose.yml down

# 重启后端（代码更新后）
docker compose -f docker-compose.yml restart backend

# 重新构建并启动（Dockerfile 或代码有变更时）
docker compose -f docker-compose.yml up -d --build

# 查看运行状态
docker compose -f docker-compose.yml ps
`

## 数据持久化

系统数据存储在 Docker 卷 jijiantongzhi_data 中，包含：
- system.db — 系统自身数据库
- demo_business.db — 演示业务库
- images/ — 报表图片
- secret.key — 加密密钥

`ash
# 查看数据卷位置
docker volume inspect jijiantongzhi_jijiantongzhi_data
`

## 使用 PostgreSQL（可选）

默认使用 SQLite。如需 PostgreSQL，修改 docker-compose.yml 中的 SYSTEM_DB_URL
环境变量，并添加 PostgreSQL 服务：

`yaml
services:
  # ... existing services ...

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: jijiantongzhi
      POSTGRES_USER: jijiantongzhi
      POSTGRES_PASSWORD: change-me
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - jijiantongzhi_net

  backend:
    # ... existing config ...
    environment:
      SYSTEM_DB_URL: "postgresql://jijiantongzhi:change-me@postgres:5432/jijiantongzhi"
      # ... other env vars ...

volumes:
  jijiantongzhi_data:
  postgres_data:
`

## 上线前必读

1. **备份 secret.key** — 它加密了钉钉 webhook、数据库口令等敏感信息
2. 登录后到「系统设置 → 图片服务地址」确认地址正确
3. 修改或删除演示账号
4. 本项目基于"手机号即身份"设计，建议配合 Nginx 反向代理加一层认证
