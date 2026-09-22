"""数据文件导入服务。

扫描目录里形如 {前缀}_{YYYYMMDD}.txt 的文件（UTF-8、| 分隔、首行表头），
每个文件名前缀对应一个本地 SQLite 库，导入时整表覆盖，作为「当月累计快照」。

导入成功后自动注册/更新数据源（db_type=sqlite, is_public=True），
普通用户也能直接拿它配置推送规则。
"""
from __future__ import annotations

import csv
import logging
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from ..config import DEFAULT_SCAN_DIR, IMPORT_DIR
from ..models import AppSetting, DataSource, FileImportLog
from . import metadata

logger = logging.getLogger("jijiantongzhi.file_import")

SETTING_DIR = "import_dir"
SETTING_TIME = "import_time"
DEFAULT_SCAN_TIME = "08:00"

_FILE_RE = re.compile(r"^(.*)_(\d{8})\.txt$", re.IGNORECASE)
_BATCH_SIZE = 5000
# 只认「纯数字」的整数 / 小数，避免把带下划线分隔符的字符串（如告警流水号）误判成数值
_RE_INT = re.compile(r"^-?\d+$")
_RE_NUM = re.compile(r"^-?\d+(\.\d+)?$")


# ---------------------------------------------------------------- 配置（AppSetting）

def get_setting(db: Session, key: str, default: str = "") -> str:
    item = db.query(AppSetting).filter(AppSetting.key == key).first()
    return item.value if item is not None else default


def set_setting(db: Session, key: str, value: str) -> None:
    item = db.query(AppSetting).filter(AppSetting.key == key).first()
    if item is None:
        db.add(AppSetting(key=key, value=value))
    else:
        item.value = value
    db.commit()


def get_config(db: Session) -> dict[str, str]:
    directory = get_setting(db, SETTING_DIR, str(DEFAULT_SCAN_DIR))
    scan_time = get_setting(db, SETTING_TIME, DEFAULT_SCAN_TIME)
    if not _is_valid_time(scan_time):
        scan_time = DEFAULT_SCAN_TIME
    return {"directory": directory, "scan_time": scan_time}


def save_config(db: Session, directory: str, scan_time: str) -> None:
    directory = directory.strip()
    if not directory:
        raise ValueError("扫描目录不能为空")
    if not Path(directory).is_dir():
        raise ValueError(f"扫描目录不存在：{directory}")
    if not _is_valid_time(scan_time):
        raise ValueError("扫描时间格式应为 HH:MM")
    set_setting(db, SETTING_DIR, directory)
    set_setting(db, SETTING_TIME, scan_time.strip())


def _is_valid_time(value: str) -> bool:
    try:
        hour, minute = value.strip().split(":")
        return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------- 扫描与导入

def parse_filename(name: str) -> tuple[str, str] | None:
    """从文件名解析 (前缀, 8 位日期)。"""
    match = _FILE_RE.match(name)
    if not match:
        return None
    return match.group(1), match.group(2)


def scan_files(directory: str) -> list[dict[str, str]]:
    """扫描目录并按前缀分组，返回每个前缀日期最新的文件信息。"""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"扫描目录不存在：{directory}")
    found: dict[str, dict[str, str]] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.suffix.lower() != ".txt":
            continue
        parsed = parse_filename(path.name)
        if parsed is None:
            continue
        prefix, file_date = parsed
        current = found.get(prefix)
        if current is None or file_date > current["file_date"]:
            found[prefix] = {
                "prefix": prefix,
                "file_name": path.name,
                "file_date": file_date,
                "path": str(path),
            }
    return sorted(found.values(), key=lambda item: item["prefix"])


def scan_status(db: Session, directory: str) -> list[dict[str, Any]]:
    """扫描目录并附带每个前缀的导入状态，供管理页展示。"""
    result: list[dict[str, Any]] = []
    for item in scan_files(directory):
        prefix = item["prefix"]
        last = (
            db.query(FileImportLog)
            .filter(FileImportLog.prefix == prefix, FileImportLog.status == "success")
            .order_by(FileImportLog.file_date.desc(), FileImportLog.id.desc())
            .first()
        )
        ds = db.query(DataSource).filter(DataSource.name == prefix).first()
        result.append(
            {
                "prefix": prefix,
                "file_name": item["file_name"],
                "file_date": item["file_date"],
                "imported_date": last.file_date if last else "",
                "status": "current"
                if last and last.file_date == item["file_date"]
                else ("imported" if last else "pending"),
                "row_count": last.row_count if last else 0,
                "ds_id": ds.id if ds else None,
                "db_path": str(IMPORT_DIR / f"{prefix}.db"),
            }
        )
    return result


def run_imports(db: Session, directory: str, prefix: str | None = None, force: bool = False) -> list[dict[str, Any]]:
    """按目录导入：不指定前缀时导入所有前缀的最新文件。"""
    files = scan_files(directory)
    if prefix:
        files = [item for item in files if item["prefix"] == prefix]
    return [import_file(db, item, force=force) for item in files]


def run_scheduled(db: Session) -> None:
    """定时任务入口：扫描目录并导入所有新版本文件，失败只记日志不中断。"""
    try:
        cfg = get_config(db)
        results = run_imports(db, cfg["directory"])
    except Exception as exc:  # noqa: BLE001 - 定时任务不能抛出去
        logger.error("定时导入失败：%s", exc)
        return
    imported = [r for r in results if r["status"] == "success"]
    if imported:
        logger.info("定时导入完成：新增/更新 %d 类文件", len(imported))


def import_file(db: Session, item: dict[str, str], force: bool = False) -> dict[str, Any]:
    """导入一个文件：整表覆盖写入对应前缀的 SQLite 库，并注册/更新数据源。"""
    start = time.time()
    prefix = item["prefix"]
    file_name = item["file_name"]
    file_date = item["file_date"]

    def finish(status: str, row_count: int = 0, error: str = "") -> dict[str, Any]:
        db.add(
            FileImportLog(
                prefix=prefix,
                file_name=file_name,
                file_date=file_date,
                status=status,
                row_count=row_count,
                duration_ms=int((time.time() - start) * 1000),
                error=error,
            )
        )
        db.commit()
        logger.info("文件导入 [%s] %s rows=%s err=%s", prefix, status, row_count, error or "-")
        return {
            "prefix": prefix,
            "file_name": file_name,
            "file_date": file_date,
            "status": status,
            "row_count": row_count,
            "error": error,
        }

    last = (
        db.query(FileImportLog)
        .filter(FileImportLog.prefix == prefix, FileImportLog.status == "success")
        .order_by(FileImportLog.file_date.desc(), FileImportLog.id.desc())
        .first()
    )
    if last is not None and not force and file_date <= last.file_date:
        return finish("skipped")

    header: list[str] = []
    rows: list[list[str]] = []
    try:
        with open(item["path"], "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh, delimiter="|")
            for index, record in enumerate(reader):
                if index == 0:
                    header = _dedupe_header([cell.strip() for cell in record])
                    continue
                if not record or all(cell.strip() == "" for cell in record):
                    continue
                if len(record) != len(header):
                    return finish(
                        "failed", error=f"第 {index + 1} 行字段数 {len(record)} 与表头 {len(header)} 不一致"
                    )
                rows.append([cell.strip() for cell in record])
    except Exception as exc:  # noqa: BLE001 - 把真实错误原样写给管理员
        return finish("failed", error=f"读取文件失败：{exc}")

    if not header:
        return finish("failed", error="文件为空或没有表头")
    if not rows:
        return finish("failed", error="文件只有表头，没有数据行")

    col_types = [_infer_column_type(rows, col_index) for col_index in range(len(header))]
    try:
        db_path = _write_sqlite(prefix, header, col_types, rows)
    except Exception as exc:  # noqa: BLE001
        return finish("failed", error=f"写库失败：{exc}")

    ds = db.query(DataSource).filter(DataSource.name == prefix).first()
    if ds is None:
        ds = DataSource(
            name=prefix,
            db_type="sqlite",
            file_path=str(db_path),
            is_active=True,
            is_public=True,
        )
        db.add(ds)
    else:
        ds.db_type = "sqlite"
        ds.file_path = str(db_path)
        ds.is_active = True
        ds.is_public = True
    db.commit()
    metadata.drop_engine(ds)
    return finish("success", row_count=len(rows))


# ---------------------------------------------------------------- 解析与写库

def _dedupe_header(header: list[str]) -> list[str]:
    """表头重名时追加 _2/_3 后缀，保证列唯一。"""
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in header:
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        result.append(name)
    return result


def _is_int(value: str) -> bool:
    return _RE_INT.match(value) is not None


def _is_float(value: str) -> bool:
    return _RE_NUM.match(value) is not None


def _infer_column_type(rows: list[list[str]], index: int) -> str:
    """整列推断：全整数 -> INTEGER，全数值 -> REAL，否则 TEXT。"""
    non_empty = 0
    all_int = True
    for row in rows:
        value = row[index]
        if value == "":
            continue
        non_empty += 1
        if not _is_int(value):
            all_int = False
            break
    if all_int and non_empty:
        return "INTEGER"
    all_real = True
    for row in rows:
        value = row[index]
        if value == "":
            continue
        if not _is_float(value):
            all_real = False
            break
    return "REAL" if all_real and non_empty else "TEXT"


def _convert(value: str, col_type: str) -> Any:
    if value == "":
        return None
    if col_type == "INTEGER":
        return int(value)
    if col_type == "REAL":
        return float(value)
    return value


def _write_sqlite(prefix: str, header: list[str], col_types: list[str], rows: list[list[str]]) -> Path:
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    db_path = IMPORT_DIR / f"{prefix}.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    try:
        quoted_table = _quote(prefix)
        ddl = ", ".join(f"{_quote(name)} {ctype}" for name, ctype in zip(header, col_types))
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {quoted_table}"))
            conn.execute(text(f"CREATE TABLE {quoted_table} ({ddl})"))
            for batch_start in range(0, len(rows), _BATCH_SIZE):
                batch = rows[batch_start : batch_start + _BATCH_SIZE]
                fields = ", ".join(_quote(name) for name in header)
                param_names = [f"p{index}" for index in range(len(header))]
                placeholders = ", ".join(f":{name}" for name in param_names)
                rows_as_dicts = [
                    {param_names[i]: _convert(row[i], col_types[i]) for i in range(len(header))}
                    for row in batch
                ]
                conn.execute(
                    text(f"INSERT INTO {quoted_table} ({fields}) VALUES ({placeholders})"),
                    rows_as_dicts,
                )
    finally:
        engine.dispose()
    return db_path


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
