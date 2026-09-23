# Docker 部署

两种用法：

- **本机构建运行**：在源码目录 `docker compose up -d --build`（本文档下面的内容）
- **打成镜像包去别的机器一键部署**：`powershell -ExecutionPolicy Bypass -File deploy\docker-pack.ps1`，
  产物在 `deploy\docker-dist\`，目标机器上跑 `install.sh` / `install.bat`，细节见 `deploy\安装说明.md`

## 组成

| 文件 | 说明 |
|---|---|
| `Dockerfile.backend` | FastAPI + uvicorn，端口 18080，代码在 `/app/backend`，数据在 `/app/data` |
| `Dockerfile.frontend` | 构建 Vue 产物后用 nginx 托管，按子路径 `/jijiantongzhi/` 构建 |
| `nginx.conf` | 站点挂在 `/jijiantongzhi/`，`/jijiantongzhi/api`、`/jijiantongzhi/static` 反代到后端 |
| `docker-compose.yml`（仓库根目录） | 本机构建 + 运行 |
| `deploy/docker-compose.yml` | 目标机器用，只引用镜像不构建 |

## 本机快速开始

```bash
cp docker/.env.example .env      # 可选，改端口和图片地址
docker compose up -d --build
```

访问 `http://<本机IP>/jijiantongzhi/`（访问根路径会自动 302 跳过去），演示账号：

| 手机号 | 姓名 | 角色 |
|---|---|---|
| 13900000000 | 陈静 | 省级管理员 |
| 13900000006 | 孙磊 | 地市管理员（邢台市） |
| 13900000001 | 张伟 | 普通人员（襄都区） |

看日志：

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

## 几个容易踩的坑（已经处理好了，改的时候注意别改回去）

1. **子路径**：前端用 `VITE_BASE=/jijiantongzhi/` 构建，后端 `APP_BASE_PATH=/jijiantongzhi` 必须一致。
   前端的 axios 地址取自 `import.meta.env.BASE_URL`，后端生成的图片 / Excel 链接也会自动带上这一层；
   少了它，钉钉群里的报表图会裂（日志详情里的预览图同理）。
2. **中文字体**：后端镜像装了 `fonts-wqy-microhei`，报表图片的中文才不是方块。
   渲染器找字体的路径是 `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`。
3. **数据目录固定 `/app/data`**：数据源表里存的是本地库的绝对路径（`/app/data/imports/xxx.db`），
   改目录会让已导入的库全部失效。`Dockerfile.backend` 里 `APP_DATA_DIR=/app/data`，卷也挂在 `/app/data`。
4. **nginx 配置里的 `$host`、`$remote_addr`**：写文件时别用双引号包裹的 here-string，
   PowerShell 会把 `$host` 展开成 `System.Management.Automation...`，导致 nginx 起不来。

## 数据持久化

命名卷 `jijiantongzhi_data`，容器内 `/app/data`，包含：

- `system.db` — 系统自身数据库（数据源、规则、人员…）
- `demo_business.db` — 演示业务库
- `imports/` — 数据文件导入生成的本地库
- `images/` — 报表图片、Excel 附件
- `secret.key` — 敏感信息加密密钥（**丢了钉钉 webhook 等密文就解不开了，注意备份**）

```bash
docker volume inspect jijiantongzhi_jijiantongzhi_data
```

## 换数据库（可选）

默认 SQLite。要换 PostgreSQL，在 compose 里加服务并给 backend 设 `SYSTEM_DB_URL`：

```yaml
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
```

```yaml
  backend:
    environment:
      SYSTEM_DB_URL: "postgresql://jijiantongzhi:change-me@postgres:5432/jijiantongzhi"
```

## 上线前必读

1. 备份 `secret.key`：它加密了钉钉 webhook、数据库口令这些敏感信息
2. 进「系统设置 → 图片服务地址」确认是钉钉客户端能访问到的地址（Docker 里 `PUBLIC_BASE_URL` 同义）
3. 改掉或删掉演示账号
4. 本系统是「手机号即身份」，公网暴露前建议在反向代理层再加一层认证
