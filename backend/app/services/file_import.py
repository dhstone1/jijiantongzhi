"""数据文件导入服务。

扫描目录里形如 {前缀}_{YYYYMMDD}.txt 的文件（UTF-8、| 分隔、首行表头），
每个文件名前缀对应一个本地 SQLite 库，导入时整表覆盖，作为「当月累计快照」。

导入成功后自动注册/更新数据源（db_type=sqlite, is_public=True），
普通用户也能直接拿它配置推送规则。

扫描的文件名格式可在「数据文件」页面自定义，例如 {前缀}_{YYYYMMDDHH}.csv；
导入成功后原件会自动改名为「已扫描_原文件名」，下次扫描不会重复处理。
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
SETTING_PATTERN = "import_pattern"
SETTING_RENAME = "import_rename"
DEFAULT_SCAN_TIME = "08:00"
# 默认识别的文件名格式：前缀 + 日期 + 后缀
DEFAULT_PATTERN = "{前缀}_{YYYYMMDD}.txt"
# 导入成功后是否把原件改名为「已扫描_原文件名」
DEFAULT_RENAME = True

_BATCH_SIZE = 5000
# 只认「纯数字」的整数 / 小数，避免把带下划线分隔符的字符串（如告警流水号）误判成数值
_RE_INT = re.compile(r"^-?\d+$")
_RE_NUM = re.compile(r"^-?\d+(\.\d+)?$")

# 文件名里支持的日期占位符；长的写在前面，避免 YYYYMMDD 抢走 YYYYMMDDHH
DATE_PLACEHOLDERS: tuple[tuple[str, int], ...] = (
    ("YYYYMMDDHHMM", 12),
    ("YYYYMMDDHH", 10),
    ("YYYYMMDD", 8),
    ("YYYYMM", 6),
)
PREFIX_TOKEN = "{前缀}"
# 扫描过的原件统一加这个前缀，一眼能看出哪些文件已经进过系统
RENAMED_PREFIX = "已扫描"


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


def get_config(db: Session) -> dict[str, Any]:
    directory = get_setting(db, SETTING_DIR, str(DEFAULT_SCAN_DIR))
    scan_time = get_setting(db, SETTING_TIME, DEFAULT_SCAN_TIME)
    if not _is_valid_time(scan_time):
        scan_time = DEFAULT_SCAN_TIME
    pattern = get_setting(db, SETTING_PATTERN, DEFAULT_PATTERN)
    if pattern_error(pattern):
        pattern = DEFAULT_PATTERN
    rename = get_setting(db, SETTING_RENAME, "1" if DEFAULT_RENAME else "0") == "1"
    return {
        "directory": directory,
        "scan_time": scan_time,
        "pattern": pattern,
        "rename": rename,
    }


def save_config(
    db: Session,
    directory: str,
    scan_time: str,
    pattern: str = DEFAULT_PATTERN,
    rename: bool = DEFAULT_RENAME,
) -> None:
    directory = directory.strip()
    if not directory:
        raise ValueError("扫描目录不能为空")
    if not Path(directory).is_dir():
        raise ValueError(f"扫描目录不存在：{directory}")
    if not _is_valid_time(scan_time):
        raise ValueError("扫描时间格式应为 HH:MM")
    pattern = (pattern or "").strip()
    error = pattern_error(pattern)
    if error:
        raise ValueError(f"文件格式无效：{error}")
    set_setting(db, SETTING_DIR, directory)
    set_setting(db, SETTING_TIME, scan_time.strip())
    set_setting(db, SETTING_PATTERN, pattern)
    set_setting(db, SETTING_RENAME, "1" if rename else "0")


def _is_valid_time(value: str) -> bool:
    try:
        hour, minute = value.strip().split(":")
        return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------- 文件名格式

def _token(name: str) -> str:
    """把 YYYYMMDD 这类日期名拼成 {YYYYMMDD} 占位符。"""
    return "{" + name + "}"


def pattern_error(pattern: str) -> str:
    """校验文件名格式：合法返回空串，否则返回给管理员看的错误说明。"""
    text = (pattern or "").strip()
    if not text:
        return "格式不能为空"
    if PREFIX_TOKEN not in text:
        return f"缺少 {PREFIX_TOKEN} 占位符（用它代表文件名前缀）"
    if not any(_token(name) in text for name, _ in DATE_PLACEHOLDERS):
        names = "、".join(_token(name) for name, _ in DATE_PLACEHOLDERS)
        return f"缺少日期占位符，支持：{names}"
    if not _get_suffix(text):
        return "末尾要带上文件后缀，如 .txt、.csv"
    return ""


def build_pattern_regex(pattern: str) -> re.Pattern[str] | None:
    """把文件名格式编译成正则：第 1 个捕获组是前缀，第 2 个捕获组是日期。

    格式不合法（缺 {前缀}、缺日期占位符）时返回 None。
    """
    text = (pattern or "").strip()
    if not text or PREFIX_TOKEN not in text:
        return None
    if not any(_token(name) in text for name, _ in DATE_PLACEHOLDERS):
        return None
    escaped = re.escape(text)
    escaped = escaped.replace(re.escape(PREFIX_TOKEN), "(.*)")
    for name, length in DATE_PLACEHOLDERS:
        if _token(name) in text:
            escaped = escaped.replace(re.escape(_token(name)), "([0-9]{" + str(length) + "})")
    return re.compile("^" + escaped + "$", re.IGNORECASE)


def _get_suffix(pattern: str) -> str:
    """从格式里取出文件后缀（小写、带点）；取不到时返回空串，表示不按后缀过滤。"""
    text = (pattern or "").strip()
    end = text.rfind("}")
    if end == -1 or end == len(text) - 1:
        return ""
    suffix = text[end + 1:].strip().lower()
    if not suffix:
        return ""
    return suffix if suffix.startswith(".") else "." + suffix


# ---------------------------------------------------------------- 扫描与导入

def parse_filename(name: str, pattern: str = DEFAULT_PATTERN) -> tuple[str, str] | None:
    """从文件名解析 (前缀, 日期)。日期占位符由 pattern 决定。"""
    compiled = build_pattern_regex(pattern)
    if compiled is None:
        return None
    match = compiled.match(name)
    if not match:
        return None
    return match.group(1), match.group(2)


def scan_files(directory: str, pattern: str = DEFAULT_PATTERN) -> list[dict[str, Any]]:
    """扫描目录并按前缀分组，返回每个前缀日期最新的文件信息。

    已经改名为「已扫描_原文件名」的文件也会被识别，这样导入完还能在页面上看到它。
    """
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"扫描目录不存在：{directory}")
    suffix = _get_suffix(pattern)
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue
        if suffix and path.suffix.lower() != suffix:
            continue
        renamed = path.name.startswith(RENAMED_PREFIX)
        name = path.name[len(RENAMED_PREFIX):].lstrip("_") if renamed else path.name
        parsed = parse_filename(name, pattern)
        if parsed is None:
            continue
        prefix, file_date = parsed
        current = found.get(prefix)
        if current is None or (file_date, not renamed) > (current["file_date"], not current["renamed"]):
            found[prefix] = {
                "prefix": prefix,
                "file_name": path.name,
                "file_date": file_date,
                "path": str(path),
                "renamed": renamed,
            }
    return sorted(found.values(), key=lambda item: item["prefix"])


def scan_status(db: Session, directory: str, pattern: str = DEFAULT_PATTERN) -> list[dict[str, Any]]:
    """扫描目录并附带每个前缀的导入状态，供管理页展示。"""
    result: list[dict[str, Any]] = []
    for item in scan_files(directory, pattern):
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
                "renamed": bool(item.get("renamed")),
                "ds_id": ds.id if ds else None,
                "db_path": str(IMPORT_DIR / f"{prefix}.db"),
            }
        )
    return result


def run_imports(
    db: Session,
    directory: str,
    pattern: str = DEFAULT_PATTERN,
    rename: bool = DEFAULT_RENAME,
    prefix: str | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """按目录导入：不指定前缀时导入所有前缀的最新文件。"""
    files = scan_files(directory, pattern)
    if prefix:
        files = [item for item in files if item["prefix"] == prefix]
    results: list[dict[str, Any]] = []
    for item in files:
        result = import_file(db, item, force=force)
        # 导入成功、或系统确认这文件已经是最新之后，给原件改名，标记它已经处理过
        if rename and result["status"] in ("success", "skipped"):
            renamed_to = _rename_scanned_file(item["path"])
            if renamed_to:
                result["renamed_to"] = renamed_to
        results.append(result)
    return results


def run_scheduled(db: Session) -> None:
    """定时任务入口：扫描目录并导入所有新版本文件，失败只记日志不中断。"""
    try:
        cfg = get_config(db)
        results = run_imports(
            db,
            cfg["directory"],
            pattern=cfg["pattern"],
            rename=cfg["rename"],
        )
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


# ---------------------------------------------------------------- 文件改名

def _rename_scanned_file(file_path: str) -> str:
    """把已扫描的原件改名为「已扫描_原文件名」，返回新文件名；失败或无需改名时返回空串。"""
    path = Path(str(file_path or ""))
    if not path.is_file():
        return ""
    if path.name.startswith(RENAMED_PREFIX):
        return ""
    target = path.parent / f"{RENAMED_PREFIX}_{path.name}"
    index = 2
    while target.exists():
        target = path.parent / f"{RENAMED_PREFIX}_{index}_{path.name}"
        index += 1
    try:
        path.rename(target)
    except OSError as exc:  # noqa: BLE001 - 改名失败不能影响导入结果
        logger.warning("文件改名失败 %s：%s", path.name, exc)
        return ""
    logger.info("文件已改名：%s -> %s", path.name, target.name)
    return target.name


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
