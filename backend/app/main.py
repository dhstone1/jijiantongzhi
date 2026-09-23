"""FastAPI 应用入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import seed
from .api import basic, datasources, imports, logs, rules
from .config import APP_BASE_PATH, IMAGE_DIR, IMAGE_URL_PREFIX
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(basic.router, prefix="/api", tags=["基础配置"])
app.include_router(datasources.router, prefix="/api", tags=["数据源"])
app.include_router(imports.router, prefix="/api", tags=["数据文件导入"])
app.include_router(rules.router, prefix="/api", tags=["推送规则"])
app.include_router(logs.router, prefix="/api", tags=["记录与统计"])


# 推送出去的报表图片，用随机文件名对外提供（钉钉客户端要能直接访问到）
app.mount(IMAGE_URL_PREFIX, StaticFiles(directory=IMAGE_DIR), name="reports")
if APP_BASE_PATH:
    # 站点挂在子路径下时，nginx 可能把带前缀的请求原样转给后端，这里再挂一份
    app.mount(
        f"{APP_BASE_PATH}{IMAGE_URL_PREFIX}",
        StaticFiles(directory=IMAGE_DIR),
        name="reports_prefixed",
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}

