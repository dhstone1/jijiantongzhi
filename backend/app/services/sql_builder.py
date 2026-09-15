"""取数 SQL 构建。

两条路径：
1. builder —— 可视化配置（选表、选字段、条件、分组、排序），全程生成安全 SQL；
2. raw     —— 高级用户手写 SELECT，只做白名单校验 + 强制注入归属地过滤。

归属地过滤会带上该区县的全部别名，解决「报表里叫桥东区、字典里叫襄都区」这类问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..config import TRIGGER_SCAN_ROWS
from .region_norm import RegionNormalizer

ALLOWED_OPS = ("=", "!=", ">", ">=", "<", "<=", "like", "not like", "in", "not in", "between", "is null", "is not null")
AGG_FUNCS = {"sum", "avg", "count", "max", "min"}

# 归属地过滤时额外接受的别名上限，防止 IN 列表过长
MAX_REGION_VARIANTS = 24

# 作用域可能是「一个地市 + 它的所有区县」，别名要一起带上，所以整片区域的
# 写法总量单独给一个上限。
MAX_SCOPE_VARIANTS = 400


@dataclass
class BuiltQuery:
    sql: str
    params: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def region_variants(standard: str, normalizer: RegionNormalizer) -> list[str]:
    """标准名 → 该区县在数据库里可能出现的所有写法。"""
    variants = {standard}
    for alias, target in normalizer.alias_map.items():
        if target == standard:
            variants.add(alias)
    # 标准名本身再去掉后缀试一次
    for suffix in ("自治县", "县", "市", "区"):
        if standard.endswith(suffix) and len(standard) > len(suffix):
            variants.add(standard[: -len(suffix)])
    return sorted(v for v in variants if v)[:MAX_REGION_VARIANTS]


def region_scope_variants(names, normalizer: RegionNormalizer | None) -> list[str]:
    """把作用域里的每个标准名展开成它在库里可能出现的全部写法。

    names 可以是单个字符串，也可以是「地市 + 下属区县」这样的集合。
    """
    if isinstance(names, str):
        names = [names]
    variants: set[str] = set()
    for name in names:
        if not name:
            continue
        if normalizer is None:
            variants.add(name)
        else:
            variants.update(region_variants(name, normalizer))
    return sorted(v for v in variants if v)[:MAX_SCOPE_VARIANTS]


def resolve_time_range(cfg: dict, now: datetime | None = None) -> tuple[datetime | None, datetime | None]:
    """把「昨天 / 近 7 天 / 近 3 小时」翻译成具体的时间边界。

    边界在 Python 侧算好再作为参数传给数据库，避免不同方言的日期函数差异。
    """
    now = now or datetime.now()
    kind = (cfg or {}).get("type") or "none"
    count = int((cfg or {}).get("n") or 1)

    if kind in ("none", "", None):
        return None, None
    if kind == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if kind == "yesterday":
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return today - timedelta(days=1), today
    if kind == "last_n_days":
        return now - timedelta(days=count), now
    if kind == "last_n_hours":
        return now - timedelta(hours=count), now
    if kind == "this_week":
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return today - timedelta(days=today.weekday()), now
    if kind == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    if kind == "custom":
        start = cfg.get("start")
        end = cfg.get("end")
        return (_to_dt(start), _to_dt(end))
    return None, None


def _to_dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def build_query(
    cfg: dict,
    table_columns: list[str],
    engine,
    region_field: str = "",
    region_value: str | list[str] | set[str] = "",
    normalizer: RegionNormalizer | None = None,
    max_rows: int = 200,
) -> BuiltQuery:
    preparer = engine.dialect.identifier_preparer
    warnings: list[str] = []
    params: dict = {}

    if (cfg.get("mode") or "builder") == "sql":
        return _build_raw(cfg, region_field, region_value, normalizer, max_rows, preparer)

    table = (cfg.get("table") or "").strip()
    if not table:
        raise ValueError("请先选择数据表")

    select = [c for c in (cfg.get("select") or []) if c]
    aggregations = [
        a for a in (cfg.get("aggregations") or []) if a.get("column") or _is_duration(a)
    ]
    group_by = [c for c in (cfg.get("group_by") or []) if c]

    if not select and not aggregations:
        raise ValueError("请至少选择一个字段")

    _ensure_columns(select + group_by + [a["column"] for a in aggregations if a.get("column")], table_columns)
    for agg in aggregations:
        if _is_duration(agg):
            _ensure_columns([agg.get("from") or "", agg.get("to") or ""], table_columns)

    # 归属地列统一成标准名：数据库里同时存在 襄都 / 襄都区 / 桥东 / 桥东区 时，
    # 不归一就会被拆成 4 行，统计结果直接失真。
    normalized: dict[str, str] = {}
    if (
        normalizer is not None
        and region_field
        and cfg.get("normalize_region", True) is not False
        and region_field in table_columns
        and (region_field in select or region_field in group_by)
    ):
        normalized[region_field] = normalizer.case_expression(preparer, region_field, params)
        warnings.append(f"归属地字段「{region_field}」已按标准名归一，多种写法会合并成一行")

    projections: list[str] = []
    for name in select:
        expression = normalized.get(name)
        if expression:
            projections.append(f"{expression} AS {preparer.quote(name)}")
        else:
            projections.append(preparer.quote(name))
    for agg in aggregations:
        alias = _agg_alias(agg)
        if _is_duration(agg):
            inner = str(agg.get("func", "")).lower().split("_", 1)[1]
            if inner not in AGG_FUNCS:
                raise ValueError(f"不支持的时长统计方式：{inner}")
            expression = duration_expression(
                engine,
                agg.get("from") or "",
                agg.get("to") or "",
                preparer,
                unit=str(agg.get("unit") or "minute").lower(),
                open_means_now=agg.get("open_means_now", True) is not False,
            )
            projections.append(f"{inner.upper()}({expression}) AS {preparer.quote(alias)}")
            continue

        func = str(agg.get("func", "sum")).lower()
        if func not in AGG_FUNCS:
            raise ValueError(f"不支持的聚合函数：{func}")
        projections.append(f"{func.upper()}({preparer.quote(agg['column'])}) AS {preparer.quote(alias)}")

    agg_aliases = frozenset(_agg_alias(a) for a in aggregations)
    output_columns = list(select) + [_agg_alias(a) for a in aggregations]

    sql = f"SELECT {', '.join(projections)} FROM {preparer.quote(table)}"
    # 分组汇总字段（聚合别名）不能写在 WHERE 里，_build_where 会把它们挑出来放进 HAVING
    where, having, params = _build_where(
        cfg,
        table_columns,
        region_field,
        region_value,
        normalizer,
        params,
        warnings,
        preparer,
        agg_aliases,
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    if group_by:
        _ensure_columns(group_by, table_columns)
        sql += " GROUP BY " + ", ".join(normalized.get(c) or preparer.quote(c) for c in group_by)
    if having:
        sql += " HAVING " + " AND ".join(having)

    order_by = [o for o in (cfg.get("order_by") or []) if o.get("column")]
    if order_by:
        clauses = []
        for item in order_by:
            column = item["column"]
            if column not in table_columns and column not in output_columns:
                continue
            direction = "DESC" if str(item.get("direction", "desc")).lower().startswith("desc") else "ASC"
            clauses.append(f"{preparer.quote(column)} {direction}")
        if clauses:
            sql += " ORDER BY " + ", ".join(clauses)

    limit = effective_limit(cfg, max_rows)
    params["_limit"] = limit
    sql += " LIMIT :_limit"

    return BuiltQuery(sql=sql, params=params, warnings=warnings)


def effective_limit(cfg: dict, max_rows: int) -> int:
    """取数上限。

    「最多发送条数」限制的是发出去的行数，不是扫描行数：触发判定（尤其分组统计的
    「同一个值出现 N 次」）必须在整批数据上算，只取几十行就下结论必然算错。
    所以判定类规则按 TRIGGER_SCAN_ROWS 取数，真正发出去的行数在外面再截。
    """
    limit = max(int(cfg.get("limit") or 50), 1)
    mode = str((cfg.get("trigger") or {}).get("mode") or "always").lower()
    if mode in ("threshold", "group"):
        return min(max(limit, TRIGGER_SCAN_ROWS), max(max_rows, TRIGGER_SCAN_ROWS))
    return min(limit, max_rows)


def _as_number(value):
    """能当数字用就转成数字，否则原样返回。"""
    if isinstance(value, bool) or not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return value


def _filter_value(value, numeric: bool):
    """筛选值来自输入框，都是字符串。

    分组汇总的结果（聚合别名）没有字段亲和性，SQLite 里拿它跟字符串比大小会永远判成假，
    所以 HAVING 的筛选值必须转成真正的数字。
    """
    return _as_number(value) if numeric else value


def _build_where(
    cfg: dict,
    table_columns: list[str],
    region_field: str,
    region_value: str | list[str] | set[str],
    normalizer: RegionNormalizer | None,
    params: dict,
    warnings: list[str],
    preparer,
    agg_aliases: frozenset[str] = frozenset(),
) -> tuple[list[str], list[str], dict]:
    """拆成 WHERE（表字段）和 HAVING（分组汇总算出来的字段）两段条件。

    分组汇总的字段（如「告警次数」）在 SQL 里是聚合别名，写在 WHERE 里数据库不认，
    所以统一放到 HAVING，位置在 GROUP BY 之后。
    """
    where: list[str] = []
    having: list[str] = []

    # --- 归属地过滤：始终第一个条件，任何配置都无法绕过 ---
    if region_field and region_value:
        if region_field not in table_columns:
            warnings.append(f"归属地字段「{region_field}」不在所选表中，未生效")
        else:
            variants = region_scope_variants(region_value, normalizer)
            keys = []
            for index, variant in enumerate(variants):
                key = f"_region_{index}"
                params[key] = variant
                keys.append(f":{key}")
            where.append(f"{preparer.quote(region_field)} IN ({', '.join(keys)})")
            scope_size = len(region_value) if not isinstance(region_value, str) else 1
            if scope_size > 1:
                warnings.append(
                    f"归属地按 {scope_size} 个行政区的 {len(variants)} 种写法匹配"
                    "（含下属区县与别名）"
                )
            elif len(variants) > 1:
                warnings.append(f"归属地按 {len(variants)} 种写法匹配（含别名）")

    # --- 用户自定义条件 ---
    for filter_item in cfg.get("filters") or []:
        column = (filter_item.get("column") or "").strip()
        op = str(filter_item.get("op") or "=").lower().strip()
        if not column or op not in ALLOWED_OPS:
            continue
        # 分组汇总算出来的字段走 HAVING，其余按表字段走 WHERE
        in_having = column in agg_aliases
        if not in_having and column not in table_columns:
            warnings.append(f"忽略不存在的字段条件：{column}")
            continue

        clause = having if in_having else where
        quoted = preparer.quote(column)
        key = f"_f{len(params)}"

        if op in ("is null", "is not null"):
            clause.append(f"{quoted} IS {'NOT ' if op == 'is not null' else ''}NULL")
        elif op in ("in", "not in"):
            values = filter_item.get("values") or []
            if isinstance(values, str):
                values = [v.strip() for v in values.replace("，", ",").split(",") if v.strip()]
            if not values:
                continue
            keys = []
            for index, value in enumerate(values):
                sub_key = f"{key}_{index}"
                params[sub_key] = _filter_value(value, in_having)
                keys.append(f":{sub_key}")
            clause.append(f"{quoted} {'NOT IN' if op == 'not in' else 'IN'} ({', '.join(keys)})")
        elif op == "between":
            start, end = filter_item.get("value"), filter_item.get("value2")
            if start in (None, "") or end in (None, ""):
                continue
            params[f"{key}_a"] = _filter_value(start, in_having)
            params[f"{key}_b"] = _filter_value(end, in_having)
            clause.append(f"{quoted} BETWEEN :{key}_a AND :{key}_b")
        else:
            value = filter_item.get("value")
            if value in (None, "") and op not in ("=", "!="):
                continue
            params[key] = _filter_value(value, in_having)
            sql_op = "LIKE" if op == "like" else ("NOT LIKE" if op == "not like" else op)
            clause.append(f"{quoted} {sql_op} :{key}")

    # --- 时间范围 ---
    time_cfg = cfg.get("time_range") or {}
    time_field = (time_cfg.get("field") or "").strip()
    if time_field and time_field in table_columns:
        start, end = resolve_time_range(time_cfg)
        if start is not None:
            params["_t_start"] = start
            where.append(f"{preparer.quote(time_field)} >= :_t_start")
        if end is not None:
            params["_t_end"] = end
            where.append(f"{preparer.quote(time_field)} < :_t_end")
    elif time_field:
        warnings.append(f"忽略不存在的时间字段：{time_field}")

    return where, having, params


def duration_expression(
    engine,
    from_col: str,
    to_col: str,
    preparer,
    unit: str = "minute",
    open_means_now: bool = True,
):
    """构造「持续时长（分钟）」表达式。

    真实报表里时间列常见两种存法：真正的 timestamp，或者 TEXT 字符串。
    统一先转成文本再判空，兼容两种；结束时间为空（还没恢复）时按当前时间计，
    这正是「故障持续多久还没好」的算法。
    """
    dialect = engine.dialect.name
    quote = preparer.quote
    start_col = quote(from_col)
    end_col = quote(to_col) if to_col else ""

    if dialect in ("postgresql", "postgres"):
        start = f"NULLIF({start_col}::text, '')::timestamp"
        end = f"NULLIF({end_col}::text, '')::timestamp"
        fallback = "NOW()"
        minutes = "EXTRACT(EPOCH FROM ({end} - {start})) / 60.0"
    elif dialect in ("mysql", "mariadb"):
        start = f"{start_col}"
        end = f"{end_col}"
        fallback = "NOW()"
        minutes = "TIMESTAMPDIFF(MINUTE, {start}, {end})"
    else:
        # SQLite（以及其它走文本时间存储的方言）
        start = f"julianday(NULLIF({start_col}, ''))"
        end = f"julianday(NULLIF({end_col}, ''))"
        fallback = "julianday('now', 'localtime')"
        minutes = "(({end} - {start}) * 1440.0)"

    if open_means_now:
        end = f"COALESCE({end}, {fallback})"
    minutes = minutes.format(start=start, end=end)
    if unit == "hour":
        minutes = f"({minutes} / 60.0)"
    # 时间差在各方言里都会带浮点噪声（358.0000001192093），统一保留 1 位小数
    return f"ROUND({minutes}, 1)"


def _agg_alias(agg: dict) -> str:
    alias = str(agg.get("alias") or "").strip()
    if alias:
        return alias
    func = str(agg.get("func", "sum")).lower()
    if func.startswith("duration_"):
        return "时长_" + func.split("_", 1)[1]
    return f"{func}_{agg.get('column', '')}"


def _is_duration(agg: dict) -> bool:
    return str(agg.get("func", "")).lower().startswith("duration_")


def _build_raw(
    cfg: dict,
    region_field: str,
    region_value: str | list[str] | set[str],
    normalizer: RegionNormalizer | None,
    max_rows: int,
    preparer,
) -> BuiltQuery:
    raw = (cfg.get("raw_sql") or "").strip()
    if not raw:
        raise ValueError("自定义 SQL 不能为空")

    lowered = raw.lower().lstrip("(").strip()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError("自定义 SQL 只允许 SELECT 查询")
    if ";" in raw.rstrip().rstrip(";"):
        raise ValueError("自定义 SQL 不允许多条语句")

    warnings: list[str] = []
    params: dict = {}

    if region_field and region_value:
        if "{region}" not in raw:
            raise ValueError("自定义 SQL 必须包含 {region} 占位符，系统需要据此注入归属地过滤")
        variants = region_scope_variants(region_value, normalizer)
        keys = []
        for index, variant in enumerate(variants):
            key = f"_region_{index}"
            params[key] = variant
            keys.append(f":{key}")
        raw = raw.replace("{region}", ", ".join(keys))
        warnings.append(f"已注入归属地过滤（{len(variants)} 种写法）")

    limit = max(1, min(int(cfg.get("limit") or 50), max_rows))
    params["_limit"] = limit
    sql = f"SELECT * FROM (\n{raw.rstrip().rstrip(';')}\n) AS _preview LIMIT :_limit"
    return BuiltQuery(sql=sql, params=params, warnings=warnings)


def _ensure_columns(columns: list[str], table_columns: list[str]) -> None:
    unknown = [c for c in columns if c not in table_columns]
    if unknown:
        raise ValueError(f"字段不存在：{', '.join(unknown)}")

