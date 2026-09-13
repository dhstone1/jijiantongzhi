# -*- coding: utf-8 -*-
"""把一个 Excel 报表导入演示业务库（backend/data/demo_business.db），每个工作表一张表。

运营人员平时拿到的就是这种报表，导进演示库就能在里面试规则。

用法：
    cd backend
    python -X utf8 tools/import_report_xlsx.py "G:\\codex\\某报表.xlsx"
    python -X utf8 tools/import_report_xlsx.py "报表.xlsx" --prefix "9月8日_" --dry-run

说明：
- 表头默认取前 5 行里非空单元格最多的那一行，所以「首行是标题」的报表也能认出来
- 空字段名的列（报表右侧常见的空白列）直接丢掉
- 同名字段自动加 _2、_3 后缀，可以用 --rename 改成更好认的名字
- 同名表会被覆盖，重复导入同一份报表是安全的
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

try:
    import openpyxl
except ImportError:  # pragma: no cover
    sys.exit("需要 openpyxl：python -m pip install openpyxl")

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "demo_business.db"
HEADER_SCAN_ROWS = 5


def cell_text(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value).strip()


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def detect_header_row(rows: list[tuple]) -> int:
    """前几行里非空单元格最多的那行就是表头。"""
    best_index, best_count = 0, -1
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        count = sum(1 for v in row if not is_blank(v))
        if count > best_count:
            best_index, best_count = index, count
    return best_index


def build_headers(raw: list) -> list[str]:
    """去掉空字段名的列，给重名字段加后缀。返回的表头与 keep 的位置一一对应。"""
    names, seen = [], Counter()
    for value in raw:
        name = cell_text(value) if not is_blank(value) else ""
        if not name:
            names.append("")  # 占位，后面按位置丢弃
            continue
        seen[name] += 1
        names.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return names


def infer_type(values: list) -> str:
    filled = [v for v in values if not is_blank(v)]
    if not filled:
        return "TEXT"
    if all(isinstance(v, bool) for v in filled):
        return "INTEGER"
    if all(isinstance(v, int) for v in filled):
        return "INTEGER"
    if all(isinstance(v, (int, float)) for v in filled):
        return "REAL"
    return "TEXT"


def normalize(value):
    if is_blank(value):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return int(value)
    return value


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def safe_table_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\[\]]', "_", name).strip()
    return cleaned or "sheet"


def import_sheet(con: sqlite3.Connection, sheet_name: str, rows: list[tuple], prefix: str,
                 renames: dict, force: bool) -> tuple[str, int, int]:
    header_index = detect_header_row(rows)
    headers = build_headers(list(rows[header_index]))
    keep = [i for i, name in enumerate(headers) if name]
    columns = [renames.get(headers[i], headers[i]) for i in keep]
    body = [
        [normalize(row[i]) if i < len(row) else None for i in keep]
        for row in rows[header_index + 1:]
        if any(not is_blank(v) for v in row)
    ]

    table = safe_table_name(prefix + sheet_name)
    types = [infer_type([row[i] for row in body]) for i in range(len(columns))]
    schema = ", ".join(f"{quote(c)} {t}" for c, t in zip(columns, types))

    existing = con.execute(
        "select name from sqlite_master where type='table' and name=?", (table,)
    ).fetchone()
    if existing and not force:
        raise SystemExit(f"表 {table} 已存在；加 --force 覆盖，或换个 --prefix")

    con.execute(f"DROP TABLE IF EXISTS {quote(table)}")
    con.execute(f"CREATE TABLE {quote(table)} ({schema})")
    placeholders = ", ".join("?" for _ in columns)
    con.executemany(f"INSERT INTO {quote(table)} VALUES ({placeholders})", body)
    return table, len(columns), len(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="把 Excel 报表导入演示业务库")
    parser.add_argument("xlsx", help="Excel 文件路径")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"目标 SQLite 库（默认 {DEFAULT_DB}）")
    parser.add_argument("--prefix", default="", help="表名前缀，例如 9月8日_")
    parser.add_argument("--rename", default="", help="重命名字段，如 '序时进度_2=序时进度_时长,序时进度=序时进度_时长'")
    parser.add_argument("--force", action="store_true", help="同名表已存在时直接覆盖")
    parser.add_argument("--dry-run", action="store_true", help="只看会发生什么，不写库")
    args = parser.parse_args()

    renames = {}
    for pair in filter(None, (p.strip() for p in args.rename.split(","))):
        if "=" not in pair:
            sys.exit(f"--rename 写法不对：{pair}")
        old, new = pair.split("=", 1)
        renames[old.strip()] = new.strip()

    path = Path(args.xlsx)
    if not path.exists():
        sys.exit(f"文件不存在：{path}")

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    con = sqlite3.connect(args.db)
    try:
        for sheet_name in workbook.sheetnames:
            rows = [list(row) for row in workbook[sheet_name].iter_rows(values_only=True)]
            if not rows:
                print(f"跳过空工作表：{sheet_name}")
                continue
            table, n_cols, n_rows = import_sheet(con, sheet_name, rows, args.prefix, renames, args.force)
            print(f"{'[试运行] ' if args.dry_run else ''}工作表「{sheet_name}」-> 表「{table}」：{n_cols} 列 / {n_rows} 行")
        if args.dry_run:
            con.rollback()
            print("试运行结束，未写入。")
        else:
            con.commit()
            print(f"已写入 {args.db}")
    finally:
        con.close()
        workbook.close()


if __name__ == "__main__":
    main()
