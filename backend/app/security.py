"""无第三方依赖的对称加密，用于数据库密码、钉钉密钥、图床令牌的存储。

格式 v2（当前）：随机 16 字节 nonce + HMAC-SHA256 密钥流异或 + 32 字节 HMAC 校验，
即 encrypt-then-MAC。随机 nonce 保证同样的明文每次密文不同，MAC 保证密文被改过能被发现。

v1 是旧格式：nonce 由明文前 8 字节派生（相同明文产生相同密文、同前缀密文复用密钥流），
且没有完整性校验。只保留解密能力，新写入一律用 v2；启动时会自动把存量 v1 重加密成 v2。

想换成标准实现的话，把 encrypt/decrypt 换成 cryptography 的 AES-GCM 即可，
格式前缀已经是可区分的版本号。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from .config import LEGACY_SECRET_KEY, SECRET_KEY

V1_PREFIX = "enc:v1:"
V2_PREFIX = "enc:v2:"
_NONCE_BYTES = 16
_TAG_BYTES = 32


def _key(key_text: str) -> bytes:
    return hashlib.sha256(key_text.encode("utf-8")).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(out[:length])


def encrypt(plain: str) -> str:
    if plain is None or plain == "":
        return ""
    key = _key(SECRET_KEY)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    raw = plain.encode("utf-8")
    blob = bytes(a ^ b for a, b in zip(raw, _keystream(key, nonce, len(raw))))
    tag = hmac.new(key, nonce + blob, hashlib.sha256).digest()
    return V2_PREFIX + base64.urlsafe_b64encode(nonce + blob + tag).decode("ascii")


def _decrypt_v1(token: str) -> str:
    """旧格式。密文可能是用当前密钥或旧默认密钥加的，两把都试。"""
    try:
        payload = base64.urlsafe_b64decode(token[len(V1_PREFIX):].encode("ascii"))
        nonce, blob = payload[:12], payload[12:]
    except Exception:  # noqa: BLE001
        return ""
    for candidate in dict.fromkeys([SECRET_KEY, LEGACY_SECRET_KEY]):
        key = _key(candidate)
        raw = bytes(a ^ b for a, b in zip(blob, _keystream(key, nonce, len(blob))))
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return ""


def _decrypt_v2(token: str) -> str:
    try:
        payload = base64.urlsafe_b64decode(token[len(V2_PREFIX):].encode("ascii"))
    except Exception:  # noqa: BLE001
        return ""
    if len(payload) <= _NONCE_BYTES + _TAG_BYTES:
        return ""
    nonce = payload[:_NONCE_BYTES]
    blob, tag = payload[_NONCE_BYTES:-_TAG_BYTES], payload[-_TAG_BYTES:]
    key = _key(SECRET_KEY)
    expected = hmac.new(key, nonce + blob, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        # 密文被改过或者换了密钥，一律当解不开处理，不要吐半截数据
        return ""
    raw = bytes(a ^ b for a, b in zip(blob, _keystream(key, nonce, len(blob))))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    if token.startswith(V2_PREFIX):
        return _decrypt_v2(token)
    if token.startswith(V1_PREFIX):
        return _decrypt_v1(token)
    # 兼容历史明文数据
    return token


def needs_reencrypt(token: str) -> bool:
    """还不是当前格式的密文，启动时会重加密。"""
    return bool(token) and not token.startswith(V2_PREFIX)


def reencrypt_stored_secrets(db) -> int:
    """把存量 v1 密文用当前密钥重加密成 v2。

    这样即使用了很久的旧默认密钥，升级后也会自动把「用公开密钥加密的密文」换掉，
    不需要运维手工重填 webhook 和数据库口令。
    """
    from .models import DataSource, DingTalkBot
    from .models import AppSetting

    changed = 0
    # 图床令牌历史上是明文存的，一并加密
    setting = db.query(AppSetting).filter(AppSetting.key == "beeimg_token").first()
    if setting is not None:
        value = (setting.value or "").strip()
        if value and not value.startswith(V2_PREFIX):
            setting.value = encrypt(value)
            changed += 1
    for bot in db.query(DingTalkBot).all():
        for attr in ("webhook_enc", "secret_enc"):
            value = getattr(bot, attr) or ""
            if not needs_reencrypt(value):
                continue
            plain = decrypt(value)
            if not plain:
                continue
            setattr(bot, attr, encrypt(plain))
            changed += 1
    for item in db.query(DataSource).all():
        value = item.password_enc or ""
        if not needs_reencrypt(value):
            continue
        plain = decrypt(value)
        if not plain:
            continue
        item.password_enc = encrypt(plain)
        changed += 1
    if changed:
        db.commit()
    return changed


def mask(value: str) -> str:
    """用于接口回显时脱敏。"""
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]
