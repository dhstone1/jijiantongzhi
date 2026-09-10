"""数据源元数据服务：浏览表、字段、样例数据。

支持 PostgreSQL（生产）与 SQLite（本地演示）。
所有标识符都来自 SQLAlchemy inspector，并经过 dialect 的 quote 处理，
不接受用户直接传入的裸 SQL 片段，避免注入。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from ..models import DataSource
from ..security import decrypt

_ENGINE_CACHE: dict[str, Engine] = {}

DEFAULT_LIMIT = 20
MAX_LIMIT = 500


def build_url(ds: DataSource) -> str:
    if ds.db_type == "sqlite":
        return f"sqlite:///{ds.file_path}"
    password = decrypt(ds.password_enc)
    return (
        f"postgresql+psycopg://{ds.username}:{password}"
        f"@{ds.host}:{ds.port}/{ds.database}"
    )


def get_engine(ds: DataSource) -> Engine:
    key = f"{ds.id}:{ds.db_type}:{ds.host}:{ds.port}:{ds.database}:{ds.file_path}:{ds.password_enc}"
    engine = _ENGINE_CACHE.get(key)
    if engine is None:
        connect_args = {"connect_timeout": 8} if ds.db_type == "postgresql" else {}
        engine = create_engine(build_url(ds), pool_pre_ping=True, connect_args=connect_args)
        _ENGINE_CACHE[key] = engine
    return engine


def drop_engine(ds: DataSource) -> None:
    for key in [k for k in _ENGINE_CACHE if k.startswith(f"{ds.id}:")]:
        _ENGINE_CACHE.pop(key).dispose()


def test_connection(ds: DataSource) -> tuple[bool, str]:
    try:
        engine = get_engine(ds)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "连接成功"
    except Exception as exc:  # noqa: BLE001 - 需要把真实错误原样回显给管理员
        return False, f"{type(exc).__name__}: {exc}"


def list_tables(ds: DataSource) -> list[dict[str, Any]]:
    engine = get_engine(ds)
    inspector = inspect(engine)
    tables: list[dict[str, Any]] = []

    for name in inspector.get_table_names():
        tables.append({"name": name, "kind": "table", "comment": _table_comment(inspector, name)})
    for name in inspector.get_view_names():
        tables.append({"name": name, "kind": "view", "comment": _table_comment(inspector, name)})

    tables.sort(key=lambda item: item["name"])
    return tables


def _table_comment(inspector, name: str) -> str:
    try:
        comment = inspector.get_table_comment(name) or {}
        return (comment.get("text") or "").strip()
    except Exception:  # noqa: BLE001 - 部分方言不支持表注释
        return ""


def list_columns(ds: DataSource, table: str) -> list[dict[str, Any]]:
    engine = get_engine(ds)
    inspector = inspect(engine)
    known = set(inspector.get_table_names()) | set(inspector.get_view_names())
    if table not in known:
        raise ValueError(f"表不存在：{table}")

    columns: list[dict[str, Any]] = []
    for column in inspector.get_columns(table):
        columns.append(
            {
                "name": column["name"],
                "type": str(column.get("type", "")),
                "comment": (column.get("comment") or "").strip(),
                "nullable": bool(column.get("nullable", True)),
            }
        )
    return columns


def preview_table(ds: DataSource, table: str, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """取表的前 N 行，让用户选字段时能看到真实数据。"""
    engine = get_engine(ds)
    columns = list_columns(ds, table)
    names = [c["name"] for c in columns]

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    preparer = engine.dialect.identifier_preparer
    quoted_table = preparer.quote(table)
    quoted_columns = ", ".join(preparer.quote(name) for name in names)
    sql = text(f"SELECT {quoted_columns} FROM {quoted_table} LIMIT {limit}")

    with engine.connect() as conn:
        result = conn.execute(sql)
        rows = [[_jsonable(v) for v in row] for row in result.fetchall()]

    return {"table": table, "columns": names, "rows": rows, "limit": limit}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_metadata_snapshot(ds: DataSource, max_tables: int = 200) -> dict[str, Any]:
    """把整库的表与字段缓存下来，供字段推荐和编辑器使用。"""
    tables = list_tables(ds)[:max_tables]
    snapshot: dict[str, Any] = {"tables": []}
    for item in tables:
        try:
            columns = list_columns(ds, item["name"])
        except Exception:  # noqa: BLE001 - 个别表无权限时跳过，不影响整体
            continue
        snapshot["tables"].append(
            {
                "name": item["name"],
                "kind": item["kind"],
                "comment": item["comment"],
                "columns": columns,
            }
        )
    return snapshot


def load_snapshot(ds: DataSource) -> dict[str, Any]:
    try:
        return json.loads(ds.meta_json or "{}")
    except json.JSONDecodeError:
        return {}

