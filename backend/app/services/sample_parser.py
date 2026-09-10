"""样例报表解析。

上传一份 Excel / CSV，解析出可用于生成推送规则的结构化信息。

必须处理的 6 类脏数据（对应需求说明 5.2）：
1. 表头不在第一行    —— 自动探测表头行
2. 重复列名          —— 自动加后缀去重
3. 汇总行混在明细中  —— 关键词识别并单独标记
4. 归属地名称不统一  —— 交给 RegionNormalizer 归一化
5. 时间是日期时间    —— 识别 datetime 列，支持按天/按小时取数
6. 空列与空值        —— 统计空值率，高空的列降权
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from .region_norm import RegionNormalizer, is_summary_label

MAX_SCAN_ROWS = 12
MAX_ANALYZE_ROWS = 400
PREVIEW_ROWS = 30
NULL_RATIO_HIDE = 0.85

# 列名里出现这些词，更可能是主归属地列
REGION_NAME_HINTS = ("区县", "地市", "归属", "单位", "区域", "县区")

# 列名里出现这些词，说明它是衍生/映射列，不该作为主归属地列
REGION_NAME_PENALTY = ("映射", "人力", "负责人", "责任人", "备注", "描述", "说明", "编码", "id", "ID")

DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y%m%d",
    "%Y年%m月%d日",
)


def region_score(name: str, hit_ratio: float, null_ratio: float) -> float:
    """归属地列打分：命中率为主，空值率扣分，列名命中关键词加权。"""
    score = hit_ratio * (1.0 - null_ratio)
    if any(hint in name for hint in REGION_NAME_HINTS):
        score *= 1.15
    if any(hint in name for hint in REGION_NAME_PENALTY):
        score *= 0.5
    return score


def is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time())
    if isinstance(value, str):
        text = value.strip()
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _parse_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("%", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def infer_dtype(values: list[object]) -> str:
    """推断一列的数据类型。"""
    samples = [v for v in values if not is_blank(v)]
    if not samples:
        return "empty"

    text_count = sum(1 for v in samples if isinstance(v, str) and v.strip().endswith("%"))
    if text_count / len(samples) > 0.6:
        return "percent"

    dt_count = sum(1 for v in samples if _parse_datetime(v) is not None)
    if dt_count / len(samples) >= 0.9:
        has_time = any(
            isinstance(v, datetime) and (v.hour or v.minute or v.second)
            for v in samples
        )
        if not has_time:
            has_time = any(
                isinstance(v, str) and any(ch in v for ch in (":",)) for v in samples
            )
        return "datetime" if has_time else "date"

    num_count = sum(1 for v in samples if _parse_number(v) is not None)
    if num_count / len(samples) >= 0.9:
        return "number"

    return "text"


def detect_header_row(rows: list[list[object]]) -> int:
    """探测表头所在行（0 基）。返回最佳候选，找不到时返回 0。"""
    best_score: tuple | None = None
    best_index = 0

    for index, row in enumerate(rows[:MAX_SCAN_ROWS]):
        filled = [c for c in row if not is_blank(c)]
        if len(filled) < 2:
            continue
        text_ratio = sum(1 for c in filled if isinstance(c, str)) / len(filled)
        if text_ratio < 0.6:
            continue

        following = 0
        for later in rows[index + 1 : index + 6]:
            if sum(1 for c in later if not is_blank(c)) >= max(2, len(filled) * 0.4):
                following += 1
        if following == 0:
            continue

        score = (len(filled), following)
        if best_score is None or score > best_score:
            best_score = score
            best_index = index

    return best_index


def dedupe_headers(names: list[str]) -> list[str]:
    """重复列名自动加后缀：序时进度 / 序时进度_2 / 序时进度_3。"""
    seen: dict[str, int] = {}
    result: list[str] = []
    for position, name in enumerate(names):
        base = (name or "").strip() or f"列{position + 1}"
        if base in seen:
            seen[base] += 1
            result.append(f"{base}_{seen[base]}")
        else:
            seen[base] = 1
            result.append(base)
    return result


def read_xlsx(path: Path) -> list[tuple[str, list[list[object]]]]:
    workbook = load_workbook(path, data_only=True, read_only=False)
    sheets: list[tuple[str, list[list[object]]]] = []
    for worksheet in workbook.worksheets:
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
        sheets.append((worksheet.title, rows))
    workbook.close()
    return sheets


def read_csv(path: Path) -> list[tuple[str, list[list[object]]]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    return [(path.stem, [list(row) for row in reader])]


def parse_sheet(
    sheet_name: str,
    rows: list[list[object]],
    normalizer: RegionNormalizer,
) -> dict:
    if not rows:
        return {"name": sheet_name, "empty": True, "columns": [], "preview_rows": []}

    width = max((len(r) for r in rows), default=0)
    grid = [list(r) + [None] * (width - len(r)) for r in rows]

    header_index = detect_header_row(grid)
    title = ""
    for row in grid[:header_index]:
        for cell in row:
            if not is_blank(cell) and isinstance(cell, str) and len(cell.strip()) > 3:
                title = cell.strip()
                break
        if title:
            break

    headers = dedupe_headers([to_text(c) for c in grid[header_index]])
    body = grid[header_index + 1 :]

    summary_rows: list[dict] = []
    data_rows: list[list[object]] = []
    for offset, row in enumerate(body):
        if all(is_blank(c) for c in row):
            continue
        first_text = to_text(row[0]) if row else ""
        if first_text and is_summary_label(first_text):
            summary_rows.append({"row": header_index + 1 + offset + 1, "label": first_text})
            continue
        data_rows.append(row)

    columns: list[dict] = []
    region_candidates: list[tuple[float, int]] = []

    for index, name in enumerate(headers):
        values = [row[index] for row in data_rows]
        non_null = [v for v in values if not is_blank(v)]
        null_ratio = 1.0 - (len(non_null) / len(values)) if values else 1.0
        dtype = infer_dtype(values[:MAX_ANALYZE_ROWS])

        column = {
            "index": index,
            "name": name,
            "dtype": dtype,
            "null_ratio": round(null_ratio, 4),
            "is_empty": dtype == "empty" or null_ratio >= NULL_RATIO_HIDE,
            "sample_values": [to_text(v) for v in non_null[:5]],
            "distinct_count": len({to_text(v) for v in non_null[:MAX_ANALYZE_ROWS]}),
            "is_region_candidate": False,
            "is_time_candidate": dtype in ("date", "datetime"),
        }

        # 文本列才可能是归属地列
        if dtype == "text" and non_null:
            analysis = normalizer.analyze_column([to_text(v) for v in non_null[:MAX_ANALYZE_ROWS]])
            column["region_hit_ratio"] = round(analysis.hit_ratio, 3)
            column["unknown_values"] = sorted(analysis.unknown.keys())[:10]
            if analysis.is_region_column:
                column["is_region_candidate"] = True
                region_candidates.append((region_score(name, analysis.hit_ratio, null_ratio), index))

        columns.append(column)

    # 归属地列：命中率最高的一列
    region_column = None
    if region_candidates:
        region_candidates.sort(key=lambda item: (-item[0], item[1]))
        region_column = headers[region_candidates[0][1]]
        for column in columns:
            if column["name"] == region_column:
                column["is_region_candidate"] = True

    time_column = next((c["name"] for c in columns if c["is_time_candidate"] and not c["is_empty"]), None)

    unknown_regions: list[str] = []
    if region_column is not None:
        target = next(c for c in columns if c["name"] == region_column)
        unknown_regions = target.get("unknown_values", [])

    preview = [[to_text(cell) for cell in row[:width]] for row in data_rows[:PREVIEW_ROWS]]

    return {
        "name": sheet_name,
        "title": title,
        "header_row": header_index + 1,
        "column_count": len(headers),
        "row_count": len(data_rows),
        "summary_rows": summary_rows[:10],
        "summary_row_count": len(summary_rows),
        "columns": columns,
        "preview_rows": preview,
        "region_column": region_column,
        "time_column": time_column,
        "unknown_regions": unknown_regions,
        "empty": len(data_rows) == 0,
    }


def parse_sample(path: str | Path, normalizer: RegionNormalizer) -> dict:
    """解析样例文件，返回可直接存库和前端展示的结构。"""
    file_path = Path(path)
    suffix = file_path.suffix.lower()

    if suffix in (".xlsx", ".xlsm"):
        sheets = read_xlsx(file_path)
    elif suffix == ".csv":
        sheets = read_csv(file_path)
    else:
        raise ValueError(f"暂不支持的文件类型：{suffix}，请上传 .xlsx 或 .csv")

    parsed = [parse_sheet(name, rows, normalizer) for name, rows in sheets]
    parsed = [item for item in parsed if not item.get("empty")]

    primary = 0
    if parsed:
        # 主表：优先有归属地列、行数适中（像汇总表）的那张
        ranked = sorted(
            range(len(parsed)),
            key=lambda i: (
                parsed[i]["region_column"] is not None,
                parsed[i]["row_count"] <= 200,
                parsed[i]["row_count"],
            ),
            reverse=True,
        )
        primary = ranked[0]

    return {
        "file_name": file_path.name,
        "sheet_count": len(parsed),
        "sheets": parsed,
        "primary_sheet_index": primary,
    }
