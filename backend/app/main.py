"""FastAPI 应用入口。"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import seed
from .api import basic, datasources, logs, rules
from .auth import IdentityMiddleware
from .config import IMAGE_DIR, IMAGE_URL_PREFIX
from .db import init_db
from .services import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("jijiantongzhi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed.ensure_seed()
    scheduler.start()
    logger.info("应用启动完成")
    yield
    scheduler.shutdown()


app = FastAPI(title="运营数据推送系统", version="1.0.0", lifespan=lifespan)

# 谁都不带凭据的跨站请求没理由读得到接口结果。前端是同源访问，不需要放开通配来源。
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("APP_CORS_ORIGINS", "").split(",") if os.getenv("APP_CORS_ORIGINS") else [],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)

# 认证在 CORS 之后注册：Starlette 后注册的中间件在最外层，身份闸门先跑，
# 401 也就能带上正确的 CORS 头。
app.add_middleware(IdentityMiddleware)

app.include_router(basic.router, prefix="/api", tags=["基础配置"])
app.include_router(datasources.router, prefix="/api", tags=["数据源"])
app.include_router(rules.router, prefix="/api", tags=["推送规则"])
app.include_router(logs.router, prefix="/api", tags=["记录与统计"])


# 推送出去的报表图片，用随机文件名对外提供（钉钉客户端要能直接访问到）
app.mount(IMAGE_URL_PREFIX, StaticFiles(directory=IMAGE_DIR), name="reports")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
