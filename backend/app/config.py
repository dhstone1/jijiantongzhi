"""系统配置。所有配置项均可通过环境变量覆盖。"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 系统自身数据库（SQLite 起步，可换成 PostgreSQL）
SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", f"sqlite:///{DATA_DIR / 'system.db'}")

# 敏感信息加密密钥。
# 以前这里直接兜底成源码里的固定字符串，等于所有部署共用一把公开的钥匙。
# 现在改成：环境变量优先；没设置就在数据目录里生成一把随机密钥并持久化。
SECRET_KEY_FILE = DATA_DIR / "secret.key"

# 旧版本写死的默认密钥，只用于解开历史密文，解密后会自动用新密钥重新加密
LEGACY_SECRET_KEY = "jijiantongzhi-dev-secret-key-change-me"


def _resolve_secret_key() -> tuple[str, bool]:
    env_value = (os.getenv("APP_SECRET_KEY") or "").strip()
    if env_value:
        return env_value, False
    if SECRET_KEY_FILE.exists():
        stored = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
        if stored:
            return stored, True
    generated = secrets.token_urlsafe(48)
    SECRET_KEY_FILE.write_text(generated, encoding="utf-8")
    try:
        SECRET_KEY_FILE.chmod(0o600)
    except OSError:  # Windows 上 chmod 语义有限，忽略
        pass
    return generated, True


SECRET_KEY, SECRET_KEY_AUTO_GENERATED = _resolve_secret_key()

# 演示业务库（模拟公共数据库）的位置
DEMO_DB_PATH = DATA_DIR / "demo_business.db"

# 数据文件导入：生成的本地 SQLite 库存放目录
IMPORT_DIR = Path(os.getenv("APP_IMPORT_DATA_DIR", DATA_DIR / "imports"))
IMPORT_DIR.mkdir(parents=True, exist_ok=True)

# 数据文件导入：默认扫描目录（项目根目录下的「数据源」文件夹），运行期可在页面配置
DEFAULT_SCAN_DIR = Path(os.getenv("APP_SCAN_DIR", Path(__file__).resolve().parent.parent.parent / "数据源"))

# 单次推送最大行数上限，防止刷屏
MAX_ROWS_HARD_LIMIT = int(os.getenv("MAX_ROWS_HARD_LIMIT", "200"))

# 触发判定（阈值条件 / 分组统计）的取数上限。
# 「最多发送条数」限制的是发出去的行数，不是扫描行数：分组统计如果只取几十行，
# 「同一个基站出现 3 次」这种结论就会被截断。所以判定类的取数单独放开上限。
TRIGGER_SCAN_ROWS = int(os.getenv("TRIGGER_SCAN_ROWS", "20000"))

# 后端监听端口，只用于给「图片服务地址」生成候选值。
# 默认避开 Windows 保留段：Hyper-V/WSL 会在 1024-15000 里动态划走成段端口，
# 8080、8000 这类常用端口随时可能被占住（绑定报 WinError 10013）。
SERVER_PORT = int(os.getenv("APP_PORT", "18080"))

# 推送出去的报表图片存放目录，通过 /static/reports 对外提供
IMAGE_DIR = Path(os.getenv("APP_IMAGE_DIR", DATA_DIR / "images"))
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_URL_PREFIX = "/static/reports"

# 钉钉客户端访问图片用的地址，留空表示未配置（运行期可在「系统设置」里改）
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")

# 图片保留天数，超期自动清理
IMAGE_RETENTION_DAYS = int(os.getenv("IMAGE_RETENTION_DAYS", "7"))
