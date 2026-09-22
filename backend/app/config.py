"""系统配置。所有配置项均可通过环境变量覆盖。"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 系统自身数据库（SQLite 起步，可换成 PostgreSQL）
SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", f"sqlite:///{DATA_DIR / 'system.db'}")

# 敏感信息加密密钥。生产环境务必通过环境变量设置。
SECRET_KEY = os.getenv("APP_SECRET_KEY", "jijiantongzhi-dev-secret-key-change-me")

# 演示业务库（模拟公共数据库）的位置
DEMO_DB_PATH = DATA_DIR / "demo_business.db"

# 数据文件导入：生成的本地 SQLite 库存放目录
IMPORT_DIR = Path(os.getenv("APP_IMPORT_DATA_DIR", DATA_DIR / "imports"))
IMPORT_DIR.mkdir(parents=True, exist_ok=True)

# 数据文件导入：默认扫描目录（项目根目录下的「数据源」文件夹），运行期可在页面配置
DEFAULT_SCAN_DIR = Path(os.getenv("APP_SCAN_DIR", Path(__file__).resolve().parent.parent.parent / "数据源"))

# 单次推送最大行数上限，防止刷屏
MAX_ROWS_HARD_LIMIT = int(os.getenv("MAX_ROWS_HARD_LIMIT", "200"))

# 后端监听端口，只用于给「图片服务地址」生成候选值
SERVER_PORT = int(os.getenv("APP_PORT", "8080"))

# 推送出去的报表图片存放目录，通过 /static/reports 对外提供
IMAGE_DIR = Path(os.getenv("APP_IMAGE_DIR", DATA_DIR / "images"))
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_URL_PREFIX = "/static/reports"

# 钉钉客户端访问图片用的地址，留空表示未配置（运行期可在「系统设置」里改）
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

# 图片保留天数，超期自动清理
IMAGE_RETENTION_DAYS = int(os.getenv("IMAGE_RETENTION_DAYS", "7"))
