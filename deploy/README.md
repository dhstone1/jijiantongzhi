# 部署到 Ubuntu 服务器

目标机器：`192.168.220.132`（Ubuntu，VMnet8 网段）
部署形态：Nginx 托管前端 `dist/`，`/api` 与 `/static` 反代到本机 `127.0.0.1:18080` 的 uvicorn，后端由 systemd 常驻。

## 一、把代码送到服务器

### 方式 A：打整包拷过去（推荐，服务器不用装 Node）

在 Windows 的仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
```

产物是 `deploy\jijiantongzhi-deploy.zip`，里面**已经包含构建好的 `frontend\dist`**。
把它拷到服务器（VMware 共享目录、U 盘、现有文件通道都行），然后：

```bash
sudo apt-get install -y unzip
unzip jijiantongzhi-deploy.zip -d /opt
cd /opt/jijiantongzhi
sudo bash deploy/deploy.sh
```

### 方式 B：服务器上直接从 git 拉

```bash
sudo apt-get update && sudo apt-get install -y git
cd /opt
sudo git clone -b fenquan https://github.com/dhstone1/jijiantongzhi.git
cd jijiantongzhi
sudo bash deploy/deploy.sh
```

注意：仓库里**不含** `frontend/dist`（被 gitignore 了），所以这条路径下 `deploy.sh` 会在服务器上现场构建前端，
需要 Node 18+。脚本检测不到会自动从 NodeSource 装 Node 20。服务器不通外网的话，走方式 A。

## 二、deploy.sh 会做什么

1. `apt install python3-venv nginx curl`
2. 建虚拟环境 `.venv`，装 `backend/requirements.txt`
3. 前端：有 `frontend/dist` 就直接用，没有就现场构建
4. 建数据目录 `backend/data/images`
5. 写 `/etc/systemd/system/jijiantongzhi.service` 并启动
6. 写 `/etc/nginx/sites-available/jijiantongzhi`、启用并 reload
7. 开了 ufw 的话放行 80 端口

脚本是幂等的，重跑没问题。

## 三、部署后

访问 `http://192.168.220.132/`，用演示账号登录：

| 手机号 | 姓名 | 角色 |
|---|---|---|
| `13900000000` | 陈静 | 省级管理员 |
| `13900000006` | 孙磊 | 地市管理员（邢台市） |
| `13900000001` | 张伟 | 普通人员（襄都区） |

**上线后立刻做这三件事**：

1. **备份 `backend/data/secret.key`**——它是加密钉钉 webhook、数据库口令、图床令牌的密钥，丢了这些就解不开了。
2. 到「系统设置 → 图片服务地址」确认是 `http://192.168.220.132`。
   钉钉客户端要能访问到这个地址，否则群里只会显示裂图。如果钉钉拉不到内网地址，就用图床模式。
3. 改掉或删掉演示账号。

## 四、常用命令

```bash
journalctl -u jijiantongzhi -f        # 看后端日志
sudo systemctl restart jijiantongzhi  # 重启后端
sudo systemctl reload nginx           # 重载前端配置
sudo systemctl status nginx jijiantongzhi
```

改了代码要生效：

```bash
cd /opt/jijiantongzhi
sudo git pull                        # 或重新解压部署包
cd frontend && npm run build && cd .. # 只有前端改了才需要
sudo systemctl restart jijiantongzhi
```

## 五、上生产前必读

- **这个系统目前是「手机号即身份」**：登录只要填一个已登记的手机号，不需要密码。
  在同一网段里，知道别人手机号的人就能以他的身份操作。
  只在内网用，或让运维在 Nginx 上加一层认证（`auth_basic` / 公司 SSO）。
- **后端只监听 127.0.0.1**，外部只能通过 Nginx 的 80 端口进来。不要改成 `--host 0.0.0.0`。
- **业务库账号必须是只读的**。系统的「自定义 SQL」模式只对省级管理员开放，但仍然建议在数据库侧收口。
- 系统自身的库默认是 `backend/data/system.db`（SQLite）。数据量大或要多人同时写，把 `SYSTEM_DB_URL`
  换成 PostgreSQL。
