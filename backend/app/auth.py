"""请求身份闸门。

系统不设密码，但这不等于「没有身份就是最高权限」：
除登录与健康检查外，所有 /api 请求都必须带一个**已登记**的手机号，
否则一律 401。各端点自己的角色守卫在这之后还会再判一次，这里是第一道闸。

背景：原来 mobile 缺省或填了未登记号码时，调用者会被解析成 None，
而各守卫都写成 `if caller is None: return`（失败开放），
结果不带身份反而拿到比省级管理员还宽的范围。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .db import SessionLocal
from .models import Staff

# 还没建立身份就能访问的接口
PUBLIC_API_PATHS = ("/api/session/login", "/api/health")
API_PREFIX = "/api"


class IdentityMiddleware(BaseHTTPMiddleware):
    """挡住一切没有有效身份的 /api 请求。"""

    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith(API_PREFIX):
            return await call_next(request)
        if path.rstrip("/") in PUBLIC_API_PATHS:
            return await call_next(request)

        mobile = (request.query_params.get("mobile") or "").strip()
        if not mobile:
            return JSONResponse(
                {"detail": "缺少身份参数 mobile，请先登录"}, status_code=401
            )

        db = SessionLocal()
        try:
            staff = db.query(Staff).filter(Staff.mobile == mobile).first()
            if staff is None:
                return JSONResponse(
                    {"detail": "该手机号未在人员信息表中登记，请联系管理员"},
                    status_code=401,
                )
            request.state.staff = staff
        finally:
            db.close()

        return await call_next(request)
