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
    if mode not in ("always", "threshold"):
        mode = "always"

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
    }


def describe(cfg: dict | None) -> str:
    """把触发条件翻译成一句人话，用于预览提示和消息标题。"""
    trigger = normalize(cfg)
    if trigger["mode"] == "always":
        return MODE_LABELS["always"]

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


def evaluate(rows: list[dict], cfg: dict | None) -> TriggerResult:
    """对取数结果做触发判定，返回命中行。"""
    trigger = normalize(cfg)
    total = len(rows)

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


def cooldown_remaining(last_fired_at, cooldown_minutes: int, now=None) -> float:
    """距离下次允许发送还剩多少分钟，0 表示可以发。"""
    from datetime import datetime

    if not last_fired_at or not cooldown_minutes:
        return 0.0
    now = now or datetime.now()
    elapsed = (now - last_fired_at).total_seconds() / 60.0
    return max(0.0, cooldown_minutes - elapsed)