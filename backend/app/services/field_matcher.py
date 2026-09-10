"""字段智能匹配。

用途：用户上传了一份「想要的报表样式」，系统用它来
1) 推荐数据库里应该勾选哪些字段；
2) 匹配最可能的表。

注意：字段的最终来源永远是数据库，样例只做推荐。
"""
from __future__ import annotations

import difflib
import re

# 业务同义词组：组内任意两个词视为同义
SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("区县", "地市", "归属地", "区域", "单位", "城市", "县区", "地市公司"),
    ("时间", "日期", "发生时间", "统计日期", "时间点", "开始时间", "时间戳"),
    ("基站", "站点", "网元", "基站名称", "站址"),
    ("小区", "扇区", "小区名称", "cell"),
    ("厂家", "厂商", "供应商", "设备厂家"),
    ("原因", "故障原因", "告警原因", "原因描述"),
    ("类型", "网络类型", "设备类型", "告警类型", "分类"),
    ("次数", "数量", "计数", "条数", "告警数"),
    ("时长", "历时", "持续时间", "退服时长"),
    ("状态", "网元状态", "基站状态", "处理状态"),
    ("等级", "基站等级", "优先级", "级别"),
    ("人员", "负责人", "责任人", "处理人"),
]

_PUNCT = re.compile(r"[\s_\-—·、，,。.／/()（）\[\]【】:：]+")
# 常见的字段修饰词，匹配时可以先去掉
NOISE = ("名称", "编号", "描述", "值", "数", "量")


def normalize_name(name: str) -> str:
    text = _PUNCT.sub("", str(name or "")).lower()
    return text


def _synonym_key(token: str) -> str | None:
    for group in SYNONYM_GROUPS:
        if any(token == normalize_name(word) or token in normalize_name(word) for word in group):
            return normalize_name(group[0])
    return None


def score_pair(sample_name: str, db_name: str) -> tuple[float, str]:
    """给一对「样例列名 / 数据库列名」打分。"""
    left = normalize_name(sample_name)
    right = normalize_name(db_name)
    if not left or not right:
        return 0.0, "empty"

    if left == right:
        return 1.0, "同名"

    left_key = _synonym_key(left)
    right_key = _synonym_key(right)
    if left_key and left_key == right_key:
        return 0.88, "同义词"

    ratio = difflib.SequenceMatcher(None, left, right).ratio()
    if ratio >= 0.9:
        return ratio, "高度相似"
    if ratio >= 0.62:
        return ratio, "相似"

    if left in right or right in left:
        shorter, longer = sorted((left, right), key=len)
        if len(shorter) >= 2:
            return 0.7 + 0.2 * (len(shorter) / len(longer)), "包含"

    return ratio, "低"


def match_columns(
    sample_columns: list[str],
    db_columns: list[dict],
    threshold: float = 0.55,
) -> list[dict]:
    """为样例里的每一列推荐数据库字段。"""
    results: list[dict] = []
    for sample_name in sample_columns:
        best: dict | None = None
        for column in db_columns:
            score, reason = score_pair(sample_name, column["name"])
            if column.get("comment"):
                comment_score, comment_reason = score_pair(sample_name, column["comment"])
                if comment_score > score:
                    score, reason = comment_score, f"{comment_reason}(注释)"
            if best is None or score > best["score"]:
                best = {
                    "sample_column": sample_name,
                    "db_column": column["name"],
                    "db_type": column.get("type", ""),
                    "db_comment": column.get("comment", ""),
                    "score": round(score, 3),
                    "reason": reason,
                }
        if best is None:
            best = {"sample_column": sample_name, "db_column": None, "score": 0.0, "reason": "无候选"}
        best["recommended"] = best["score"] >= threshold
        results.append(best)
    return results


def match_table(hint: str, tables: list[dict]) -> dict | None:
    """根据 sheet 名或标题，猜最可能的表。"""
    if not hint:
        return None
    best: tuple[float, dict] | None = None
    for table in tables:
        score, _ = score_pair(hint, table["name"])
        if table.get("comment"):
            comment_score, _ = score_pair(hint, table["comment"])
            score = max(score, comment_score)
        if best is None or score > best[0]:
            best = (score, table)
    if best and best[0] >= 0.4:
        return {**best[1], "score": round(best[0], 3)}
    return None

