"""钉钉自定义群机器人 Webhook 发送。

@ 人员通过 atMobiles 传手机号；同时钉钉要求在 markdown 正文里也出现 @手机号
才会真正高亮，因此这里在文本末尾统一追加。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from dataclasses import dataclass

import requests

TIMEOUT = 10


@dataclass
class SendResult:
    ok: bool
    message: str
    raw: dict | None = None


def sign(secret: str, timestamp: int) -> str:
    payload = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


def build_url(webhook: str, secret: str = "") -> str:
    url = webhook.strip()
    if not secret:
        return url
    timestamp = int(time.time() * 1000)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}timestamp={timestamp}&sign={sign(secret, timestamp)}"


def append_mentions(text: str, at_mobiles: list[str], at_all: bool) -> str:
    tokens = [f"@{mobile}" for mobile in at_mobiles]
    if at_all:
        tokens.insert(0, "@所有人")
    if not tokens:
        return text
    return text.rstrip() + "\n\n" + " ".join(tokens)


def send_markdown(
    webhook: str,
    secret: str,
    title: str,
    text: str,
    at_mobiles: list[str] | None = None,
    at_all: bool = False,
) -> SendResult:
    mobiles = [m for m in (at_mobiles or []) if m]
    body_text = append_mentions(text, mobiles, at_all)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": body_text},
        "at": {"atMobiles": mobiles, "isAtAll": bool(at_all)},
    }
    return _post(webhook, secret, payload)


def send_text(
    webhook: str,
    secret: str,
    text: str,
    at_mobiles: list[str] | None = None,
    at_all: bool = False,
) -> SendResult:
    mobiles = [m for m in (at_mobiles or []) if m]
    payload = {
        "msgtype": "text",
        "text": {"content": append_mentions(text, mobiles, at_all)},
        "at": {"atMobiles": mobiles, "isAtAll": bool(at_all)},
    }
    return _post(webhook, secret, payload)


def send_action_card(
    webhook: str,
    secret: str,
    title: str,
    text: str,
    at_mobiles: list[str] | None = None,
    at_all: bool = False,
    btn_title: str = "",
    btn_url: str = "",
    btn_orientation: str = "0",
) -> SendResult:
    """ActionCard：正文同样是 markdown，外面套一层带标题栏的卡片，还能挂一个按钮。

    钉钉的 actionCard 要求 text 里有 @手机号 才会真正高亮，所以同样走 append_mentions。
    """
    mobiles = [m for m in (at_mobiles or []) if m]
    card = {
        "title": title,
        "text": append_mentions(text, mobiles, at_all),
        "btnOrientation": btn_orientation or "0",
    }
    # 钉钉规定按钮标题和链接必须成对出现，只填一半等于没有按钮
    if btn_title and btn_url:
        card["singleTitle"] = btn_title
        card["singleURL"] = btn_url
    payload = {
        "msgtype": "actionCard",
        "actionCard": card,
        "at": {"atMobiles": mobiles, "isAtAll": bool(at_all)},
    }
    return _post(webhook, secret, payload)


def _post(webhook: str, secret: str, payload: dict) -> SendResult:
    if not webhook:
        return SendResult(ok=False, message="未配置 Webhook 地址")
    try:
        response = requests.post(build_url(webhook, secret), json=payload, timeout=TIMEOUT)
        data = response.json()
    except requests.RequestException as exc:
        return SendResult(ok=False, message=f"网络错误：{exc}")
    except ValueError:
        return SendResult(ok=False, message=f"返回内容无法解析：{response.text[:200]}")

    if data.get("errcode") == 0:
        return SendResult(ok=True, message="发送成功", raw=data)
    return SendResult(ok=False, message=f"errcode={data.get('errcode')} {data.get('errmsg')}", raw=data)
