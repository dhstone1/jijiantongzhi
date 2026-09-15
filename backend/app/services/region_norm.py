"""归属地名称归一化。

真实报表里同一个区县有多种写法：简称、全称、旧名、异体字。
所有取数、过滤、权限、@ 人都必须走标准名，否则归属地权限会失效。

匹配顺序：精确别名 → 去后缀 → 别名+后缀 → 模糊推荐。
"""
from __future__ import annotations

import difflib
import json
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Region

# 行政区划后缀，按长度倒序匹配
SUFFIXES = ("自治县", "自治州", "自治区", "新区", "县", "市", "区", "旗", "盟")

# 邢台市标准归属地字典。
# 标准名取 2020 年行政区划调整后的现行名，报表里出现过的旧名/简称一律作为别名。
DEFAULT_REGIONS: list[tuple[str, str, list[str]]] = [
    ("襄都区", "襄都", ["桥东区", "桥东"]),
    ("信都区", "信都", ["桥西区", "桥西"]),
    ("任泽区", "任县", ["任泽"]),
    ("南和区", "南和", ["南和县"]),
    ("临城县", "临城", []),
    ("内丘县", "内丘", ["内邱", "内邱县"]),
    ("柏乡县", "柏乡", []),
    ("隆尧县", "隆尧", []),
    ("宁晋县", "宁晋", []),
    ("巨鹿县", "巨鹿", []),
    ("平乡县", "平乡", []),
    ("新河县", "新河", []),
    ("广宗县", "广宗", []),
    ("威县", "威", []),
    ("清河县", "清河", []),
    ("临西县", "临西", []),
    ("南宫市", "南宫", []),
    ("沙河市", "沙河", []),
    ("邢台市", "邢台", ["全市", "市区"]),
]

# 河北省 → 邢台市 → 18 个区县。省级管理员的归属地挂在省上，
# 地市管理员的归属地挂在地市上，往字典里加地市即可扩展。
PROVINCE = "河北省"
PARENT_CITY = "邢台市"

# 汇总行关键词：这些行不是真实的归属地明细，参与明细时应排除
SUMMARY_KEYWORDS = (
    "合计", "小计", "总计", "汇总", "全区", "全市", "全省", "全国",
    "当日指标", "月指标", "年度指标", "平均值", "累计", "总体", "整体", "其他",
)


def strip_suffix(text: str) -> str:
    for suffix in SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def clean(text: object) -> str:
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).strip()
    s = s.replace("\u3000", "").replace(" ", "")
    # 去掉「邢台」前缀，但剥完至少要剩 2 个字，避免把「邢台市」剥成「市」
    for prefix in ("邢台市", "邢台"):
        if s.startswith(prefix) and len(s) - len(prefix) >= 2:
            s = s[len(prefix):]
            break
    return s


@dataclass
class NormalizeResult:
    raw: str
    standard: str | None
    matched_by: str = "none"  # exact | suffix | fuzzy | none
    confidence: float = 0.0
    suggestion: str | None = None

    @property
    def ok(self) -> bool:
        return self.standard is not None


@dataclass
class ColumnAnalysis:
    """一列数据作为归属地列的判定结果。"""

    hit_ratio: float = 0.0
    known: dict[str, str] = field(default_factory=dict)
    unknown: dict[str, int] = field(default_factory=dict)
    is_summary_only: bool = False

    @property
    def is_region_column(self) -> bool:
        return self.hit_ratio >= 0.6 and not self.is_summary_only


class RegionNormalizer:
    def __init__(self, regions: list[Region] | list[tuple[str, str, list[str]]]):
        self.alias_map: dict[str, str] = {}
        self.standard_names: list[str] = []
        self.aliases: dict[str, list[str]] = {}

        for item in regions:
            if isinstance(item, Region):
                standard = item.standard_name
                short = item.short_name or ""
                try:
                    extra = json.loads(item.aliases_json or "[]")
                except json.JSONDecodeError:
                    extra = []
            else:
                standard, short, extra = item

            names = {standard, short, *extra}
            for name in filter(None, names):
                self.alias_map[clean(name)] = standard
            self.alias_map[strip_suffix(clean(standard))] = standard
            self.standard_names.append(standard)
            self.aliases[standard] = sorted(filter(None, {short, *extra} - {standard}))

    def add_region(self, standard: str, short: str = "", aliases: list[str] | None = None) -> None:
        """补一个还没进字典的归属地（例如省级）。"""
        if standard in self.aliases:
            return
        names = {standard, short, *(aliases or [])}
        for name in filter(None, names):
            self.alias_map[clean(name)] = standard
        self.alias_map[strip_suffix(clean(standard))] = standard
        self.standard_names.append(standard)
        self.aliases[standard] = sorted(filter(None, {short, *(aliases or [])} - {standard}))

    @classmethod
    def from_db(cls, db: Session) -> "RegionNormalizer":
        regions = db.query(Region).filter(Region.is_active.is_(True)).order_by(Region.sort_order).all()
        if not regions:
            regions = [Region(standard_name=s, short_name=h, aliases_json=json.dumps(a)) for s, h, a in DEFAULT_REGIONS]
        return cls(list(regions))

    def variants_of(self, standard: str) -> list[str]:
        """某个标准名在数据库里可能出现的所有写法。"""
        names = {standard, strip_suffix(clean(standard))}
        names.update(self.aliases.get(standard, []))
        for alias, target in self.alias_map.items():
            if target == standard:
                names.add(alias)
        return sorted(name for name in names if name)

    def case_expression(
        self,
        preparer,
        column: str,
        params: dict,
        key_prefix: str = "rg",
        max_variants: int = 200,
    ) -> str:
        """生成「把各种写法归一到标准名」的 CASE 表达式。

        用途：按归属地分组统计时，``襄都 / 襄都区 / 桥东 / 桥东区`` 必须算作同一组，
        否则一次统计会被拆成 4 行。CASE 表达式在所有方言下都可用，因此不做方言分支。
        """
        quoted = preparer.quote(column)
        branches: list[str] = []
        used = 0

        for index, standard in enumerate(self.standard_names):
            variants = self.variants_of(standard)
            if not variants or used + len(variants) > max_variants:
                continue
            used += len(variants)

            keys = []
            for offset, variant in enumerate(variants):
                key = "%s_v%d_%d" % (key_prefix, index, offset)
                params[key] = variant
                keys.append(":" + key)

            standard_key = "%s_s%d" % (key_prefix, index)
            params[standard_key] = standard
            branches.append("WHEN %s IN (%s) THEN :%s" % (quoted, ", ".join(keys), standard_key))

        if not branches:
            return quoted
        return "CASE %s ELSE %s END" % (" ".join(branches), quoted)

    def normalize(self, value: object) -> NormalizeResult:
        raw = clean(value)
        if not raw:
            return NormalizeResult(raw="", standard=None)

        if raw in self.alias_map:
            return NormalizeResult(raw=raw, standard=self.alias_map[raw], matched_by="exact", confidence=1.0)

        bare = strip_suffix(raw)
        if bare in self.alias_map:
            return NormalizeResult(raw=raw, standard=self.alias_map[bare], matched_by="suffix", confidence=0.95)

        # 简称补全后缀后再试一次（例如「襄都」→「襄都区」）
        for standard in self.standard_names:
            if strip_suffix(clean(standard)) == bare:
                return NormalizeResult(raw=raw, standard=standard, matched_by="suffix", confidence=0.95)

        close = difflib.get_close_matches(bare, list(self.alias_map.keys()), n=1, cutoff=0.75)
        if close:
            return NormalizeResult(
                raw=raw,
                standard=None,
                matched_by="fuzzy",
                confidence=0.6,
                suggestion=self.alias_map[close[0]],
            )
        return NormalizeResult(raw=raw, standard=None, matched_by="none", confidence=0.0)

    def analyze_column(self, values: list[object]) -> ColumnAnalysis:
        """判断一列是否可以作为归属地列。"""
        result = ColumnAnalysis()
        total = 0
        hits = 0
        summary_hits = 0

        for value in values:
            text = clean(value)
            if not text:
                continue
            total += 1
            if any(kw in text for kw in SUMMARY_KEYWORDS):
                summary_hits += 1
            normalized = self.normalize(text)
            if normalized.ok:
                hits += 1
                result.known[text] = normalized.standard
            else:
                result.unknown[text] = result.unknown.get(text, 0) + 1

        if total:
            result.hit_ratio = hits / total
            result.is_summary_only = summary_hits == total and total > 0
        return result


def is_summary_label(value: object) -> bool:
    text = clean(value)
    if not text:
        return False
    return any(kw in text for kw in SUMMARY_KEYWORDS)
