"""无第三方依赖的对称加密，用于数据库密码、钉钉密钥的存储。

实现方式：HMAC-SHA256 构造密钥流，与明文按字节异或（CTR 模式）。
安全性弱于 AES-GCM，但对「防止配置文件被直接读走明文」这一目标是够用的。
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from .config import SECRET_KEY

_PREFIX = "enc:v1:"


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
    key = hashlib.sha256(SECRET_KEY.encode("utf-8")).digest()
    nonce = hashlib.sha256((SECRET_KEY + plain[:8]).encode("utf-8")).digest()[:12]
    raw = plain.encode("utf-8")
    blob = bytes(a ^ b for a, b in zip(raw, _keystream(key, nonce, len(raw))))
    return _PREFIX + base64.urlsafe_b64encode(nonce + blob).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    if not token.startswith(_PREFIX):
        # 兼容历史明文数据
        return token
    try:
        payload = base64.urlsafe_b64decode(token[len(_PREFIX):].encode("ascii"))
        nonce, blob = payload[:12], payload[12:]
        key = hashlib.sha256(SECRET_KEY.encode("utf-8")).digest()
        raw = bytes(a ^ b for a, b in zip(blob, _keystream(key, nonce, len(blob))))
        return raw.decode("utf-8")
    except Exception:
        return ""


def mask(value: str) -> str:
    """用于接口回显时脱敏。"""
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "*" * (len(value) - 6) + value[-3:]

