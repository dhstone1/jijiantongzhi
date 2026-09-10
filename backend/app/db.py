"""系统自身数据库的连接与会话管理。"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import SYSTEM_DB_URL

logger = logging.getLogger("jijiantongzhi.db")

connect_args = {"check_same_thread": False} if SYSTEM_DB_URL.startswith("sqlite") else {}
engine = create_engine(SYSTEM_DB_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 建表之后新增的列，写在这里做轻量迁移：
# create_all 只管建新表，不会给已存在的表补列。
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "push_rule": {
        "last_fired_at": "TIMESTAMP",
        "image_json": "TEXT DEFAULT '{}'",
    },
}


def _migrate_columns() -> None:
    """给老库补上新增的列。SQLite 和 PostgreSQL 都支持 ADD COLUMN。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {item["name"] for item in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                logger.info("已为 %s 补充字段 %s", table, name)


def init_db() -> None:
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    _migrate_columns()

