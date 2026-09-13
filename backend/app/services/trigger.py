"""触发判定：决定「这一批数据到底要不要推」。

报表类和告警类走的是同一套取数 / 归集逻辑，差别只在最后一格：

    always     只要有数据就推        —— 日报、周报、月报
    threshold  指标命中阈值才推      —— 次数触发 / 时长触发 / 数量触发

配置存在 query_json["trigger"] 里，不额外增加数据库字段。
阈值判定作用在「归集之后的结果行」上，所以配合分组汇总就能实现：

    按小区分组 + 计数 -> 告警次数 >= 3           （次数触发）
    按小区分组 + 最长时长 -> 持续时长 >= 240 分钟  （时长触发）
    按区县分组 + 计数 -> 故障数 >= 10            （数量触发）
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 数值比较
NUMERIC_OPS = (">", ">=", "<", "<=", "=", "!=")
# 文本比较（数值解析失败时回退到字符串比较）
TEXT_OPS = ("=", "!=", "contains", "not contains")

OP_LABELS = {
    ">": ">",
    ">=": "≥",
    "<": "<",
    "<=": "≤",
    "=": "=",
    "!=": "≠",
    "contains": "包含",
    "not contains": "不包含",
}

MODE_LABELS = {
    "always": "有数据就发送",
    "threshold": "满足触发条件才发送",
    "group": "同一字段累计达到标准才发送",
}

# 分组统计的算法。count 数行数，其余作用在指定的数值字段上。
GROUP_FUNCS = ("count", "count_distinct", "sum", "avg", "max", "min")

GROUP_FUNC_LABELS = {
    "count": "出现次数",
    "count_distinct": "去重数",
    "sum": "合计",
    "avg": "平均",
    "max": "最大值",
    "min": "最小值",
}


@dataclass
class TriggerResult:
    """一次触发判定的结果。"""

    hit: bool = True
    rows: list = field(default_factory=list)
    # 命中行在原始结果里的下标，前端据此高亮
    hit_indexes: list = field(default_factory=list)
    total: int = 0
    summary: str = ""
    warnings: list = field(default_factory=list)
    detail: list = field(default_factory=list)
    # 触发判定自己算出来的列（分组统计会加一列），None 表示沿用取数结果的列
    columns: list | None = None

    @property
    def hit_count(self) -> int:
        return len(self.rows)

    @property
    def filtered_count(self) -> int:
        return self.total - len(self.rows)


def normalize(cfg: dict | None) -> dict:
    """补齐默认值，保证执行器拿到的一定是完整结构。"""
    cfg = dict(cfg or {})
    mode = str(cfg.get("mode") or "always").lower()
    if mode not in ("always", "threshold", "group"):
        mode = "always"

    func = str(cfg.get("func") or "count").lower()
    if func not in GROUP_FUNCS:
        func = "count"

    group_op = str(cfg.get("op") or ">=").strip()
    if group_op not in NUMERIC_OPS:
        group_op = ">="

    detail_mode = str(cfg.get("detail") or "summary").lower()
    if detail_mode not in ("summary", "rows"):
        detail_mode = "summary"

    logic = str(cfg.get("logic") or "or").lower()
    if logic not in ("and", "or"):
        logic = "or"

    conditions = []
    for item in cfg.get("conditions") or []:
        if not isinstance(item, dict):
            continue
        column = str(item.get("field") or "").strip()
        if not column:
            continue
        value = item.get("value")
        if isinstance(value, str):
            value = value.strip()
        conditions.append(
            {
                "field": column,
                "op": str(item.get("op") or ">=").lower().strip(),
                "value": value,
            }
        )

    try:
        cooldown = int(cfg.get("cooldown_minutes") or 0)
    except (TypeError, ValueError):
        cooldown = 0

    return {
        "mode": mode,
        "logic": logic,
        "conditions": conditions,
        "cooldown_minutes": max(0, cooldown),
        # ---- 分组统计（mode = group）----
        "group_field": str(cfg.get("group_field") or "").strip(),
        "func": func,
        "value_field": str(cfg.get("value_field") or "").strip(),
        # 汇总模式只留统计字段和指标，带一个「附带字段」（比如区县）才好 @人 和区分
        "extra_field": str(cfg.get("extra_field") or "").strip(),
        "op": group_op,
        "value": cfg.get("value"),
        "detail": detail_mode,
    }


def describe(cfg: dict | None) -> str:
    """把触发条件翻译成一句人话，用于预览提示和消息标题。"""
    trigger = normalize(cfg)
    if trigger["mode"] == "always":
        return MODE_LABELS["always"]

    if trigger["mode"] == "group":
        field = trigger["group_field"] or "（未选字段）"
        label = GROUP_FUNC_LABELS[trigger["func"]]
        metric = label if trigger["func"] == "count" else f"{trigger['value_field'] or '（未选字段）'}{label}"
        op = OP_LABELS.get(trigger["op"], trigger["op"])
        return f"{field} 的{metric} {op} {trigger['value']}"

    parts = []
    for item in trigger["conditions"]:
        label = OP_LABELS.get(item["op"], item["op"])
        parts.append(f"{item['field']} {label} {item['value']}")

    if not parts:
        return MODE_LABELS["threshold"]
    joiner = " 且 " if trigger["logic"] == "and" else " 或 "
    return joiner.join(parts)


def _to_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _compare(current, op: str, target) -> bool:
    """单个条件的比较。数值优先，解析不了就退化成字符串比较。"""
    left = _to_number(current)
    right = _to_number(target)

    if left is not None and right is not None:
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        if op == "=":
            return left == right
        if op == "!=":
            return left != right

    text = "" if current is None else str(current)
    other = "" if target is None else str(target)

    if op == "=":
        return text == other
    if op == "!=":
        return text != other
    if op == "contains":
        return bool(other) and other in text
    if op == "not contains":
        return not other or other not in text
    return False


def match_row(row: dict, conditions: list[dict], logic: str) -> bool:
    """一行数据是否满足全部 / 任一条件。"""
    if not conditions:
        return True

    results = [_compare(row.get(item["field"]), item["op"], item["value"]) for item in conditions]

    if logic == "and":
        return all(results)
    return any(results)


def evaluate(rows: list[dict], cfg: dict | None, columns: list | None = None) -> TriggerResult:
    """对取数结果做触发判定，返回命中行。

    columns 是取数结果的列名，分组统计要靠它判断字段在不在、以及拼出结果列。
    """
    trigger = normalize(cfg)
    total = len(rows)

    if trigger["mode"] == "group":
        return _evaluate_group(rows, trigger, columns)

    if trigger["mode"] == "always":
        summary = f"{total} 行全部发送" if total else "无数据"
        return TriggerResult(
            hit=True,
            rows=list(rows),
            hit_indexes=list(range(total)),
            total=total,
            summary=summary,
        )

    warnings: list[str] = []
    fields = set()
    for row in rows:
        fields.update(row.keys())

    usable = []
    for item in trigger["conditions"]:
        if item["field"] in fields:
            usable.append(item)
        else:
            warnings.append(f"触发条件里的字段「{item['field']}」不在取数结果中，该条件被忽略")

    if not usable:
        warnings.append("触发条件没有一处可用，已按「不发送」处理")
        return TriggerResult(
            hit=False,
            rows=[],
            total=total,
            summary="触发条件无效",
            warnings=warnings,
        )

    hit_indexes = [i for i, row in enumerate(rows) if match_row(row, usable, trigger["logic"])]
    hits = [rows[i] for i in hit_indexes]
    detail = [
        {
            "field": item["field"],
            "op": item["op"],
            "value": item["value"],
            "label": f"{item['field']} {OP_LABELS.get(item['op'], item['op'])} {item['value']}",
        }
        for item in usable
    ]

    summary = describe({**trigger, "conditions": usable})
    if hits:
        summary = f"命中 {len(hits)} / {total} 行：{summary}"
    else:
        summary = f"无命中（共 {total} 行）：{summary}"

    return TriggerResult(
        hit=bool(hits),
        rows=hits,
        hit_indexes=hit_indexes,
        total=total,
        summary=summary,
        warnings=warnings,
        detail=detail,
    )


def _text_of(row: dict, field: str) -> str:
    value = row.get(field)
    return "" if value is None else str(value).strip()


def _first_value(rows: list[dict], indexes: list[int], field: str) -> str:
    """取一组行里第一个非空的附带字段值，用来标出这组数据属于哪个区县。"""
    for index in indexes:
        value = _text_of(rows[index], field)
        if value:
            return value
    return ""


def _display(number: float | int | None):
    """3.0 显示成 3，别让表格里出现一堆小数点后一位。"""
    if number is None:
        return ""
    value = float(number)
    if value.is_integer():
        return int(value)
    return round(value, 2)


def _group_metric(rows: list[dict], indexes: list[int], func: str, value_field: str) -> float | None:
    """算一个分组在当前这轮数据里的统计值。"""
    if func == "count":
        return float(len(indexes))

    if func == "count_distinct":
        values = {_text_of(rows[i], value_field) for i in indexes}
        values.discard("")
        return float(len(values))

    numbers = [_to_number(rows[i].get(value_field)) for i in indexes]
    numbers = [n for n in numbers if n is not None]
    if not numbers:
        return None
    if func == "sum":
        return float(sum(numbers))
    if func == "avg":
        return float(sum(numbers)) / len(numbers)
    if func == "max":
        return float(max(numbers))
    if func == "min":
        return float(min(numbers))
    return None


def _evaluate_group(rows: list[dict], trigger: dict, columns: list | None) -> TriggerResult:
    """分组统计：按某个字段把数据归堆，算一个简单指标，达到标准的组才发出去。

    「同一个小区退服 ≥ 3 次」「某个区县故障合计时长 ≥ 600 分钟」都是它。
    """
    total = len(rows)
    field = trigger["group_field"]
    func = trigger["func"]
    value_field = trigger["value_field"]
    extra_field = trigger["extra_field"]
    threshold = _to_number(trigger["value"])

    source_columns = list(columns or (list(rows[0].keys()) if rows else []))
    warnings: list[str] = []

    if not field:
        warnings.append("分组统计没选统计字段，已按「不发送」处理")
    elif source_columns and field not in source_columns:
        warnings.append(f"统计字段「{field}」不在取数结果里，本次不发送")
    if extra_field and source_columns and extra_field not in source_columns:
        warnings.append(f"附带字段「{extra_field}」不在取数结果里，本次不发送")
    if threshold is None:
        warnings.append("分组统计没填标准值，已按「不发送」处理")
    if func != "count" and not value_field:
        warnings.append("这个统计方式要选一个数值字段，本次不发送")
    if func != "count" and value_field and source_columns and value_field not in source_columns:
        warnings.append(f"数值字段「{value_field}」不在取数结果里，本次不发送")

    if warnings:
        return TriggerResult(
            hit=False, rows=[], total=total, summary="触发条件无效", warnings=warnings
        )

    metric_label = GROUP_FUNC_LABELS[func]
    metric_column = metric_label if func == "count" else f"{value_field}{metric_label}"

    buckets: dict[str, list[int]] = {}
    order: list[str] = []
    for index, row in enumerate(rows):
        key = _text_of(row, field)
        if not key:
            continue
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(index)

    hits: list[tuple[str, list[int], float]] = []
    for key in order:
        indexes = buckets[key]
        metric = _group_metric(rows, indexes, func, value_field)
        if metric is None:
            continue
        if _compare(metric, trigger["op"], threshold):
            hits.append((key, indexes, metric))
    hits.sort(key=lambda item: item[2], reverse=True)

    if trigger["detail"] == "rows":
        # 明细模式：把命中组的原始行都发出去，并在每行后面附上该组的统计值
        picked = []
        for key, indexes, metric in hits:
            for index in indexes:
                row = dict(rows[index])
                row[metric_column] = _display(metric)
                picked.append((index, row))
        picked.sort(key=lambda item: item[0])
        out_rows = [row for _, row in picked]
        out_columns = [*source_columns, metric_column]
        # 明细模式发出来的每一行都来自命中组，所以整张表都是命中行
        hit_indexes = list(range(len(out_rows)))
    else:
        # 汇总模式：一个值一行，只看「谁、多少次」
        out_rows = []
        for key, indexes, metric in hits:
            row = {field: key, metric_column: _display(metric)}
            if extra_field:
                row[extra_field] = _first_value(rows, indexes, extra_field)
            out_rows.append(row)
        out_columns = ([extra_field] if extra_field else []) + [field, metric_column]
        hit_indexes = list(range(len(out_rows)))

    condition = describe(trigger)
    if hits:
        summary = f"{len(hits)} 个{field}达到标准（共 {total} 行）：{condition}"
    else:
        summary = f"没有{field}达到标准（共 {total} 行）：{condition}"

    return TriggerResult(
        hit=bool(hits),
        rows=out_rows,
        hit_indexes=hit_indexes,
        total=total,
        summary=summary,
        warnings=warnings,
        columns=out_columns,
        detail=[
            {"field": field, "func": func, "value_field": value_field,
             "op": trigger["op"], "value": trigger["value"], "label": condition}
        ],
    )


def cooldown_remaining(last_fired_at, cooldown_minutes: int, now=None) -> float:
    """距离下次允许发送还剩多少分钟，0 表示可以发。"""
    from datetime import datetime

    if not last_fired_at or not cooldown_minutes:
        return 0.0
    now = now or datetime.now()
    elapsed = (now - last_fired_at).total_seconds() / 60.0
    return max(0.0, cooldown_minutes - elapsed)
