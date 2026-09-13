"""推送图片的落盘、访问地址与清理。

图片以随机文件名存放在 data/images 下，通过 /static/reports/<文件名> 对外提供。
钉钉里发的是 ![](地址) 的 markdown 图片链接，所以「图片服务地址」必须是
钉钉客户端（手机/PC）能访问到的地址。
"""
from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import DATA_DIR, IMAGE_DIR, IMAGE_RETENTION_DAYS, IMAGE_URL_PREFIX, PUBLIC_BASE_URL
from ..models import AppSetting
from . import image_host

SETTING_BASE_URL = "public_base_url"
SETTING_RETENTION = "image_retention_days"
SETTING_UPLOAD_MODE = "image_upload_mode"
SETTING_BEEIMG_URL = "beeimg_url"
SETTING_BEEIMG_STORAGE = "beeimg_storage_id"
SETTING_BEEIMG_TOKEN = "beeimg_token"
SETTING_BEEIMG_EXPIRE = "beeimg_expire_days"
SETTING_BEEIMG_PUBLIC = "beeimg_is_public"
SETTING_BEEIMG_EXIF = "beeimg_remove_exif"

# 图片放到哪：本系统服务器 / 第三方图床
MODE_LOCAL = "local"
MODE_BEEIMG = "beeimg"

LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")


def get_setting(db: Session, key: str, default: str = "") -> str:
    item = db.query(AppSetting).filter(AppSetting.key == key).first()
    if item is None or item.value in (None, ""):
        return default
    return item.value


def set_setting(db: Session, key: str, value: str) -> None:
    item = db.query(AppSetting).filter(AppSetting.key == key).first()
    if item is None:
        db.add(AppSetting(key=key, value=str(value)))
    else:
        item.value = str(value)
    db.commit()


def base_url(db: Session) -> str:
    """系统设置优先，其次环境变量 PUBLIC_BASE_URL。"""
    return (get_setting(db, SETTING_BASE_URL, PUBLIC_BASE_URL) or "").strip().rstrip("/")


def retention_days(db: Session) -> int:
    raw = get_setting(db, SETTING_RETENTION, str(IMAGE_RETENTION_DAYS))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return IMAGE_RETENTION_DAYS


def upload_mode(db: Session) -> str:
    value = (get_setting(db, SETTING_UPLOAD_MODE, MODE_LOCAL) or MODE_LOCAL).strip().lower()
    return MODE_BEEIMG if value == MODE_BEEIMG else MODE_LOCAL


def beeimg_expire_days(db: Session) -> int:
    """图床上图片的过期天数。没单独设置就跟随「图片保留天数」，0 表示永不过期。"""
    raw = get_setting(db, SETTING_BEEIMG_EXPIRE, "").strip()
    if raw == "":
        return retention_days(db)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return retention_days(db)


def beeimg_expired_at(db: Session, now: datetime | None = None) -> str:
    """算成图床要的 yyyy-MM-dd HH:mm:ss；永不过期时返回空串（该字段就不传了）。"""
    days = beeimg_expire_days(db)
    if days <= 0:
        return ""
    moment = (now or datetime.now()) + timedelta(days=days)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _flag(db: Session, key: str, default: bool) -> bool:
    raw = get_setting(db, key, "").strip().lower()
    if raw == "":
        return default
    return raw in ("1", "true", "yes", "on")


def beeimg_config(db: Session, intro: str = "") -> dict:
    """组装 image_host.upload_png 的参数。

    tags / album_id / is_public 只有登录态（配了令牌）才生效，
    没配令牌时就不传，免得匿名上传被图床判成参数错误。
    """
    token = get_setting(db, SETTING_BEEIMG_TOKEN, "")
    config = {
        "url": get_setting(db, SETTING_BEEIMG_URL, image_host.UPLOAD_URL) or image_host.UPLOAD_URL,
        "storage_id": get_setting(db, SETTING_BEEIMG_STORAGE, "4") or "4",
        "token": token,
        "expired_at": beeimg_expired_at(db),
        "intro": intro,
        "is_remove_exif": _flag(db, SETTING_BEEIMG_EXIF, True),
    }
    if token:
        config["is_public"] = _flag(db, SETTING_BEEIMG_PUBLIC, False)
    return config


def is_ready(db: Session) -> bool:
    """图片推送能不能用：本机模式要配访问地址，图床模式不用。"""
    if upload_mode(db) == MODE_BEEIMG:
        return True
    return bool(base_url(db))


def is_local_url(url: str) -> bool:
    """本机地址钉钉客户端访问不到，发之前先提醒一句。"""
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return host.lower() in LOCAL_HOSTS


PREVIEW_TAG = "preview"


def save(payload: bytes, rule_id: int | None = None, tag: str = "", suffix: str = ".png") -> str:
    prefix = f"{tag}_" if tag else f"r{rule_id or 0}_"
    name = f"{prefix}{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}{suffix}"
    (IMAGE_DIR / name).write_bytes(payload)
    return name


def url_for(base: str, filename: str) -> str:
    return f"{base.rstrip('/')}{IMAGE_URL_PREFIX}/{filename}"


def path_for(filename: str) -> Path:
    return IMAGE_DIR / filename


def cleanup(days: int, prefix: str = "", suffixes: tuple[str, ...] = (".png", ".xlsx")) -> int:
    """删掉超过保留期的报表文件（图片 + Excel），返回删除个数。

    prefix 用于只清理某一类文件，suffixes 限定扩展名，免得误删目录里的其他东西。
    """
    deadline = datetime.now() - timedelta(days=days)
    removed = 0
    for item in IMAGE_DIR.glob(f"{prefix}*"):
        if item.suffix.lower() not in suffixes:
            continue
        try:
            if datetime.fromtimestamp(item.stat().st_mtime) < deadline:
                item.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# ---------------------------------------------------------------- 上传去重缓存
# 免费图床普遍限流（蜜蜂图床匿名上传 1 小时只给 3 张），同样的报表没必要重复上传：
# 图片字节完全一样就直接复用上次拿到的链接。
CACHE_FILE = DATA_DIR / "image_cache.json"
CACHE_MAX = 300


def _read_cache() -> dict:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _expired(expired_at: str, now: datetime | None = None) -> bool:
    if not expired_at:
        return False
    try:
        moment = datetime.strptime(expired_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False
    return moment < (now or datetime.now())


def cache_lookup(digest: str) -> str:
    """按图片内容找上次上传的地址；链接快到期（1 小时内）就不复用了。"""
    if not digest:
        return ""
    entry = _read_cache().get(digest) or {}
    url = str(entry.get("url") or "")
    if not url:
        return ""
    expired_at = str(entry.get("expired_at") or "")
    if _expired(expired_at, datetime.now() + timedelta(hours=1)):
        return ""
    return url


def cache_remember(digest: str, url: str, expired_at: str = "", rule_id: int | None = None) -> None:
    if not digest or not url:
        return
    cache = _read_cache()
    cache[digest] = {
        "url": url,
        "expired_at": expired_at,
        "rule_id": rule_id or 0,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    alive = {key: value for key, value in cache.items() if not _expired(str((value or {}).get("expired_at") or ""))}
    if len(alive) > CACHE_MAX:
        ordered = sorted(alive.items(), key=lambda pair: str((pair[1] or {}).get("at") or ""))
        alive = dict(ordered[-CACHE_MAX:])
    try:
        CACHE_FILE.write_text(json.dumps(alive, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def local_ipv4() -> list[str]:
    """列出本机可能的局域网地址，给「图片服务地址」做候选。"""
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = info[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    return sorted(addresses)
