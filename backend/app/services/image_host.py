"""第三方图床上传（蜜蜂图床 /api/v2/upload）。

钉钉客户端要自己去拉图片，如果本系统部署在内网、钉钉手机端访问不到，
就可以先把图片传到图床，把返回的 public_url 塞进 markdown。

接口文档：https://beeimg.apifox.cn/450605912e0
- 必填：file（二进制图片）、storage_id（存储 ID）
- 可选：expired_at（yyyy-MM-dd HH:mm:ss）、intro、tags[]、is_public、
        is_remove_exif、album_id（后三项需要登录态才生效）
- 频率限制：撞上会返回 429
"""
from __future__ import annotations

import os
import time
import urllib.parse

import requests

UPLOAD_URL = "https://www.beeimg.cn/api/v2/upload"
TIMEOUT = 30
# 撞上频率限制时等一会儿再试一次，运营人员不必关心限流
RETRY_WAIT = 6

# 只允许往白名单里的图床域名上传。上传地址是可以在系统设置里改的，
# 不限制的话，把地址改成一个内网服务，就能拿服务端当代理去请求它。
ALLOWED_UPLOAD_HOSTS = tuple(
    item.strip().lower()
    for item in (
        os.getenv("APP_IMAGE_HOST_ALLOWLIST") or "beeimg.cn,boltp.com"
    ).split(",")
    if item.strip()
)


def validate_target(url: str) -> str:
    """上传目标必须是 https 且在白名单域名下。"""
    raw = (url or "").strip() or UPLOAD_URL
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme != "https":
        raise UploadError("图床上传地址必须是 https")
    host = (parsed.hostname or "").lower()
    if not host or not any(
        host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_UPLOAD_HOSTS
    ):
        raise UploadError(
            "图床上传地址不在允许的域名里，请在「系统设置」里改成受信任的图床"
        )
    return raw

# 图床可能把这些话术放在 429 里，也可能放在 200 + status != success 里
RATE_LIMIT_HINTS = ("429", "频率", "只能上传", "too many", "rate limit")


def _is_rate_limited(status_code: int, message: str) -> bool:
    if status_code == 429:
        return True
    lowered = message.lower()
    return any(hint.lower() in lowered for hint in RATE_LIMIT_HINTS)


def _rate_limit_message(message: str) -> str:
    detail = f"：{message}" if message else ""
    return f"图床限流{detail}（隔 {RETRY_WAIT} 秒自动重试过，仍然被限流）"


# 各家图床（同一套 /api/v2/upload 接口）对令牌的写法并不统一，文档里也常常不写。
# 按这个顺序试，命中一次就记住，后续都直接用它。
AUTH_STYLES = ("bearer", "raw", "x-token", "form")
_working_style = ""


def _token_styles() -> list[str]:
    if _working_style:
        return [_working_style] + [s for s in AUTH_STYLES if s != _working_style]
    return list(AUTH_STYLES)


def _auth_headers(style: str, token: str) -> dict:
    if style == "bearer":
        return {"Authorization": f"Bearer {token}"}
    if style == "raw":
        return {"Authorization": token}
    if style == "x-token":
        return {"X-Token": token}
    return {}


def _auth_fields(style: str, token: str) -> dict:
    return {"token": token} if style == "form" else {}


def _storage_missing(message: str) -> bool:
    """图床说存储不存在时，多半是「没认出你是谁」，值得换个鉴权写法再试。"""
    lowered = message.lower()
    return "不存在的储存驱动" in message or "不存在的存储驱动" in message or "unauthorized" in lowered


def _field_errors(response) -> str:
    """把图床的字段级报错挖出来，直接告诉用户是哪个参数不对。"""
    try:
        payload = response.json()
    except ValueError:
        return f"：{response.text[:200]}"
    data = payload.get("data")
    errors = data.get("errors") if isinstance(data, dict) else None
    if isinstance(errors, dict) and errors:
        parts = []
        for field, messages in errors.items():
            text = "；".join(str(m) for m in messages) if isinstance(messages, list) else str(messages)
            parts.append(f"{field}：{text}")
        return "（" + "，".join(parts) + "）"
    message = payload.get("message")
    return f"：{message}" if message else f"：{response.text[:200]}"


class UploadError(RuntimeError):
    """上传失败，消息直接展示给运营人员看。"""


def _fields(
    storage_id: str,
    *,
    expired_at: str = "",
    intro: str = "",
    tags=None,
    is_public=None,
    is_remove_exif=None,
    album_id: str = "",
) -> dict:
    """按文档组装表单字段，没填的一律不传，免得图床把空值当非法参数。"""
    data: dict = {"storage_id": str(storage_id or "1")}
    if expired_at:
        data["expired_at"] = expired_at
    if intro:
        data["intro"] = intro
    if album_id:
        data["album_id"] = str(album_id)
    if is_public is not None:
        # 图床是按 0/1 校验布尔的，传 true/false 会被判「必须为布尔值」
        data["is_public"] = "1" if is_public else "0"
    if is_remove_exif is not None:
        data["is_remove_exif"] = "1" if is_remove_exif else "0"
    if tags:
        # 同名字段重复提交即数组，requests 支持 list 值
        data["tags[]"] = [str(tag) for tag in list(tags)[:10] if str(tag).strip()]
    return data


def upload_file(
    content: bytes,
    *,
    filename: str = "report.png",
    content_type: str = "image/png",
    url: str = UPLOAD_URL,
    storage_id: str = "1",
    token: str = "",
    expired_at: str = "",
    intro: str = "",
    tags=None,
    is_public=None,
    is_remove_exif=None,
    album_id: str = "",
) -> str:
    """上传一个文件，返回公网可访问地址。

    图床是以图片为前提的，非图片格式能不能传要看图床放不放行（多半会被判 422）。
    """
    global _working_style

    target = validate_target(url or UPLOAD_URL)

    base_data = _fields(
        storage_id,
        expired_at=expired_at,
        intro=intro,
        tags=tags,
        is_public=is_public,
        is_remove_exif=is_remove_exif,
        album_id=album_id,
    )

    styles = _token_styles() if token else [""]
    message = ""

    for index, style in enumerate(styles):
        headers = {"Accept": "application/json"}
        headers.update(_auth_headers(style, token))
        data = dict(base_data)
        data.update(_auth_fields(style, token))

        for attempt in range(2):
            try:
                response = requests.post(
                    target,
                    files={"file": (filename, content, content_type)},
                    data=data,
                    headers=headers,
                    timeout=TIMEOUT,
                    # 不跟随重定向：否则允许的域名可以 30x 把我们带到任意内网地址
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise UploadError(f"网络错误：{type(exc).__name__}") from exc

            if response.status_code == 422:
                raise UploadError(f"图床返回 422：参数不对{_field_errors(response)}")
            if response.status_code == 429:
                message = "请求过于频繁"
                if attempt == 0:
                    time.sleep(RETRY_WAIT)
                    continue
                raise UploadError(_rate_limit_message(message))
            if response.status_code >= 400:
                # 不回显上游响应正文：目标地址由设置决定，正文可能来自被探测的内网服务
                raise UploadError(f"图床返回 HTTP {response.status_code}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise UploadError(
                    f"图床返回内容无法解析（HTTP {response.status_code}）"
                ) from exc

            if str(payload.get("status", "")).lower() != "success":
                message = str(payload.get("message") or str(payload)[:200])
                if _is_rate_limited(response.status_code, message):
                    if attempt == 0:
                        time.sleep(RETRY_WAIT)
                        continue
                    raise UploadError(_rate_limit_message(message))
                break

            public_url = str((payload.get("data") or {}).get("public_url") or "").strip()
            if not public_url:
                raise UploadError(f"图床没有返回图片地址：{str(payload)[:200]}")
            _working_style = style
            return public_url

        # 图床说存储不存在，多半是没认出身份，换个鉴权写法再试
        if token and _storage_missing(message) and index < len(styles) - 1:
            continue
        break

    if _storage_missing(message):
        message += "（请检查「存储 ID」是否是图床里真实存在的存储；也可能是令牌无效或鉴权写法不匹配）"
    elif "储存" in message or "存储" in message or "storage" in message.lower():
        message += "（请检查「存储 ID」是否是图床里真实存在的存储）"
    raise UploadError(f"图床返回：{message}")


def upload_png(png: bytes, **kwargs) -> str:
    """上传一张 PNG，返回公网可访问地址。"""
    return upload_file(png, **kwargs)
