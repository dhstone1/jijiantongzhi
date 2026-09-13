"""初始化数据：归属地字典、演示业务库、演示人员与规则。

首次启动时自动执行；已存在数据时跳过，不会覆盖用户配置。
"""
from __future__ import annotations

import json
import logging
import random
import sqlite3
from datetime import datetime, timedelta

from .config import DEMO_DB_PATH
from .db import SessionLocal
from .models import DataSource, PushRule, Region, Staff
from .services.region_norm import DEFAULT_REGIONS, PARENT_CITY

logger = logging.getLogger("jijiantongzhi.seed")

DEMO_SOURCE_NAME = "演示数据源（本地样例库）"
DEMO_SUMMARY_TABLE = "移动网故障通报"
DEMO_DETAIL_TABLE = "当日移动网故障"
DEMO_ALARM_TABLE = "基站告警明细"

DEMO_STAFF = [
    ("张伟", "13900000001", "襄都区", "user", "网络运营"),
    ("李强", "13900000002", "信都区", "user", "网络运营"),
    ("王芳", "13900000003", "内丘县", "user", "网络运营"),
    ("赵敏", "13900000004", "宁晋县", "user", "网络运营"),
    ("刘洋", "13900000005", "沙河市", "user", "网络运营"),
    ("陈静", "13900000000", "", "admin", "系统管理员"),
]


def ensure_regions(db) -> int:
    if db.query(Region).count() > 0:
        return 0
    created = 0
    for order, (standard, short, aliases) in enumerate(DEFAULT_REGIONS):
        is_city = standard == PARENT_CITY
        db.add(
            Region(
                standard_name=standard,
                short_name=short,
                parent="" if is_city else PARENT_CITY,
                level="市" if is_city else "区县",
                aliases_json=json.dumps(aliases, ensure_ascii=False),
                sort_order=order,
            )
        )
        created += 1
    db.commit()
    logger.info("已写入 %d 条归属地字典", created)
    return created


def _region_variant_map() -> dict[str, list[str]]:
    """构造「标准名 → 可能出现的写法」，模拟真实报表里的名称混乱。"""
    mapping = {}
    for standard, short, aliases in DEFAULT_REGIONS:
        mapping[standard] = [standard, short, *aliases]
    return mapping


def _write_synthetic_tables(conn) -> None:
    """生成三张合成演示表，时间以当前为基准；重复执行会整表重建。"""
    rng = random.Random(20260910)
    variants = _region_variant_map()
    standards = [item[0] for item in DEFAULT_REGIONS]
    now = datetime.now().replace(minute=0, second=0, microsecond=0)

    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS 移动网故障通报")
    cur.execute(
        """
        CREATE TABLE 移动网故障通报 (
            单位 TEXT, 小区总数 INTEGER, 平均退服时长 REAL, 序时进度_时长 REAL,
            平均退服次数 REAL, 序时进度_次数 REAL, 当日退服次数 INTEGER, 当日超频小区数 INTEGER
        )
        """
    )
    for standard in standards:
        short = next(item[1] for item in DEFAULT_REGIONS if item[0] == standard)
        cells = rng.randint(800, 6800)
        cur.execute(
            "INSERT INTO 移动网故障通报 VALUES (?,?,?,?,?,?,?,?)",
            (
                short,
                cells,
                round(rng.uniform(0.3, 7.5), 2),
                round(rng.uniform(0.02, 0.55), 4),
                round(rng.uniform(0.0, 0.06), 2),
                round(rng.uniform(0.0, 0.45), 4),
                rng.choice([0, 1, 2, 3, 5, 10, 13, 16, 19, 23, 25, 26, 56, 106]),
                rng.choice([0, 0, 0, 1, 3, 6, 9]),
            ),
        )

    cur.execute("DROP TABLE IF EXISTS 当日移动网故障")
    cur.execute(
        """
        CREATE TABLE 当日移动网故障 (
            区县 TEXT, 基站名称 TEXT, 小区名称 TEXT, 发生时间 TEXT, 清除时间 TEXT
        )
        """
    )
    rows = []
    for _ in range(260):
        standard = rng.choice(standards)
        # 故意混用别名，模拟「同一份报表里 内邱 / 内丘 并存」的真实情况
        name = rng.choice(variants[standard])
        occurred = now - timedelta(hours=rng.randint(0, 72), minutes=rng.randint(0, 59))
        duration = rng.randint(5, 220)
        cleared = occurred + timedelta(minutes=duration)
        rows.append(
            (
                name,
                f"XT{name}{rng.choice(['素邱', '交通局', '一中', '光明路', '达活泉', '顺德局'])}"
                f"({rng.choice(['2.1G', '1.8G', '900M'])})ZXNR-share",
                f"XT{name}测试小区-{rng.randint(1, 9)}-share",
                occurred.strftime("%Y-%m-%d %H:%M:%S"),
                cleared.strftime("%Y-%m-%d %H:%M:%S") if rng.random() > 0.25 else "",
            )
        )
    cur.executemany("INSERT INTO 当日移动网故障 VALUES (?,?,?,?,?)", rows)

    cur.execute("DROP TABLE IF EXISTS 基站告警明细")
    cur.execute(
        """
        CREATE TABLE 基站告警明细 (
            告警流水号 TEXT, 城市 TEXT, 区县 TEXT, 网格名称 TEXT, 厂家名称 TEXT,
            网络类型 TEXT, 设备类型 TEXT, 基站名称 TEXT, 基站等级 TEXT, 小区名称 TEXT,
            发生时间 TEXT, 清除时间 TEXT, 故障原因 TEXT, 处理时长_分钟 REAL, 是否超频 TEXT
        )
        """
    )
    alarms = []
    reasons = ["传输故障", "市电停电", "设备复位", "光缆中断", "板卡故障", "软件异常"]
    # 留一批「反复出问题」的小区，最近 24 小时集中在它们身上，
    # 这样「同一小区告警 ≥ 3 次」之类的规则能取到真实样例。
    repeat_pool = [
        (rng.choice(variants[rng.choice(standards)]), rng.randint(1, 60)) for _ in range(15)
    ]
    for index in range(600):
        standard = rng.choice(standards)
        name = rng.choice(variants[standard])
        base_no = rng.randint(1, 60)
        occurred = now - timedelta(hours=rng.randint(0, 240), minutes=rng.randint(0, 59))
        if index % 4 == 0:
            name, base_no = repeat_pool[index % len(repeat_pool)]
            occurred = now - timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
        duration = rng.randint(3, 600)
        alarms.append(
            (
                f"{rng.randint(10**9, 10**10)}",
                PARENT_CITY,
                name,
                f"{name}网格{rng.randint(1, 6)}",
                rng.choice(["中兴", "华为", "爱立信"]),
                rng.choice(["4G", "5G"]),
                rng.choice(["Eutrancell", "NRCell"]),
                f"XT{name}基站{base_no}",
                rng.choice(["A类基站", "B类基站", "C类基站"]),
                f"XT{name}基站{base_no}-{rng.randint(1, 9)}-share",
                occurred.strftime("%Y-%m-%d %H:%M:%S"),
                (occurred + timedelta(minutes=duration)).strftime("%Y-%m-%d %H:%M:%S"),
                rng.choice(reasons),
                float(duration),
                "是" if duration > 180 else "否",
            )
        )
    cur.executemany("INSERT INTO 基站告警明细 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", alarms)

    conn.commit()
    _ = index


def build_demo_business_db() -> None:
    if DEMO_DB_PATH.exists():
        return
    conn = sqlite3.connect(DEMO_DB_PATH)
    try:
        _write_synthetic_tables(conn)
    finally:
        conn.close()
    logger.info("演示业务库已生成：%s", DEMO_DB_PATH)


# 演示库比当前时间旧 6 小时以上才滚动，避免每次重启都把数据往前挪
DEMO_ROLL_STALE_SECONDS = 6 * 3600


def _demo_age_seconds(conn) -> int | None:
    """演示库最新一条告警距现在多久（秒）；表不存在或时间取不出来就返回 None。"""
    cur = conn.cursor()
    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if DEMO_ALARM_TABLE not in tables:
        return None
    age = cur.execute(
        f"SELECT strftime('%s','now') - strftime('%s', MAX(发生时间)) FROM {DEMO_ALARM_TABLE}"
    ).fetchone()[0]
    return None if age is None else int(age)


def refresh_demo_business_db() -> None:
    """演示库是「生成那一刻」造的，放几天之后「最近 24 小时」就什么都查不到。

    检测到数据过期就按当前时间重建三张合成表，样例规则才一直有数据可取。
    只动合成表，用户自己导入到同一个库里的表不受影响。
    """
    if not DEMO_DB_PATH.exists():
        return
    conn = sqlite3.connect(DEMO_DB_PATH)
    try:
        age = _demo_age_seconds(conn)
        if age is not None and age <= DEMO_ROLL_STALE_SECONDS:
            return
        _write_synthetic_tables(conn)
        logger.info("演示业务库已按当前时间重建")
    finally:
        conn.close()


def ensure_datasource(db) -> None:
    if db.query(DataSource).count() > 0:
        return
    db.add(
        DataSource(
            name=DEMO_SOURCE_NAME,
            db_type="sqlite",
            file_path=str(DEMO_DB_PATH),
            is_active=True,
            meta_json="{}",
        )
    )
    db.commit()


def ensure_staff(db) -> None:
    if db.query(Staff).count() > 0:
        return
    for name, mobile, region, role, position in DEMO_STAFF:
        db.add(Staff(name=name, mobile=mobile, region_name=region, role=role, position=position))
    db.commit()


def ensure_demo_rule(db) -> None:
    if db.query(PushRule).count() > 0:
        return
    datasource = db.query(DataSource).order_by(DataSource.id).first()
    if datasource is None:
        return

    query = {
        "mode": "builder",
        "table": DEMO_SUMMARY_TABLE,
        "select": ["单位", "小区总数", "平均退服时长", "当日退服次数", "当日超频小区数"],
        "filters": [],
        "group_by": [],
        "aggregations": [],
        "order_by": [{"column": "当日退服次数", "direction": "desc"}],
        "time_range": {"type": "none", "field": "", "n": 1},
        "limit": 50,
        "empty_action": "skip",
        "highlight": {"field": "当日超频小区数", "op": ">", "value": 0, "color": "#FF0000"},
    }
    template = (
        "#### 移动网故障日通报\n"
        "> 数据来源：移动网故障通报\n\n"
        "{{表格}}\n\n"
        "共 {{行数}} 个区县"
    )
    db.add(
        PushRule(
            name="移动网故障日通报（示例）",
            created_by="13900000000",
            region_name="",
            data_source_id=datasource.id,
            table_name=DEMO_SUMMARY_TABLE,
            query_json=json.dumps(query, ensure_ascii=False),
            region_field="单位",
            time_field="",
            template=template,
            msg_type="markdown",
            bot_ids_json="[]",
            at_json=json.dumps({"mode": "none", "at_all": False}, ensure_ascii=False),
            schedule_type="daily",
            schedule_json=json.dumps({"hour": 8, "minute": 30}, ensure_ascii=False),
            enabled=False,
        )
    )
    db.commit()


DEMO_ALERT_RULE_NAME = "小区重复告警提醒（示例）"


def demo_alert_query() -> dict:
    """演示规则「同一字段累计达到标准」的取数与触发配置。

    select 只取原始字段，分组和计数交给触发条件自己算，比「分组汇总 + 阈值」两步走简短得多。
    """
    return {
        "mode": "builder",
        "table": DEMO_ALARM_TABLE,
        "select": ["区县", "小区名称", "发生时间", "处理时长_分钟"],
        "filters": [],
        "group_by": [],
        "aggregations": [],
        "order_by": [],
        "time_range": {"type": "last_n_hours", "field": "发生时间", "n": 24},
        "limit": 1000,
        "empty_action": "skip",
        "normalize_region": True,
        "highlight": {"field": "出现次数", "op": ">=", "value": 3, "color": "#FF0000"},
        "trigger": {
            "mode": "group",
            "group_field": "小区名称",
            "extra_field": "区县",
            "func": "count",
            "op": ">=",
            "value": 3,
            "detail": "summary",
            "cooldown_minutes": 120,
        },
    }


def _upgrade_demo_alert_rule(db, rule) -> None:
    """演示规则还停在新旧交替的写法上时，升级成当前版本。

    只认我们自己写出来的两种形态：老的「分组汇总 + 阈值」，以及没带附带字段的分组统计。
    用户自己改过的配置一律不动。
    """
    try:
        old = json.loads(rule.query_json or "{}")
    except ValueError:
        return
    trigger_cfg = old.get("trigger") or {}
    mode = trigger_cfg.get("mode")
    if mode == "group" and "extra_field" in trigger_cfg:
        return
    if mode not in ("threshold", "group"):
        return
    refreshed = demo_alert_query()
    refreshed["time_range"] = old.get("time_range") or refreshed["time_range"]
    rule.query_json = json.dumps(refreshed, ensure_ascii=False)
    rule.table_name = DEMO_ALARM_TABLE
    db.commit()
    logger.info("已升级演示告警规则为「同一字段累计达到标准」：%s", DEMO_ALERT_RULE_NAME)


def ensure_demo_alert_rule(db) -> None:
    """补一条「同一字段累计达到标准」演示规则。

    每次启动都检查一次，缺失才补，所以老库升级上来也能看到新功能的样例。
    """
    exists = db.query(PushRule).filter(PushRule.name == DEMO_ALERT_RULE_NAME).first()
    if exists is not None:
        _upgrade_demo_alert_rule(db, exists)
        return

    datasource = db.query(DataSource).order_by(DataSource.id).first()
    if datasource is None:
        return

    query = demo_alert_query()
    template = (
        "#### 小区重复告警提醒\n"
        "> 统计范围：最近 24 小时\n\n"
        "{{表格}}\n\n"
        "共 {{行数}} 个小区需要关注"
    )
    db.add(
        PushRule(
            name=DEMO_ALERT_RULE_NAME,
            created_by="13900000000",
            region_name="",
            data_source_id=datasource.id,
            table_name=DEMO_ALARM_TABLE,
            query_json=json.dumps(query, ensure_ascii=False),
            region_field="区县",
            time_field="发生时间",
            template=template,
            msg_type="markdown",
            bot_ids_json="[]",
            at_json=json.dumps(
                {"mode": "region", "field": "区县", "at_all": False}, ensure_ascii=False
            ),
            schedule_type="hourly",
            schedule_json=json.dumps({"interval_hours": 1}, ensure_ascii=False),
            enabled=False,
        )
    )
    db.commit()
    logger.info("已补充演示告警规则：%s", DEMO_ALERT_RULE_NAME)


def ensure_seed() -> None:
    db = SessionLocal()
    try:
        ensure_regions(db)
        build_demo_business_db()
        refresh_demo_business_db()
        ensure_datasource(db)
        ensure_staff(db)
        ensure_demo_rule(db)
        ensure_demo_alert_rule(db)
    finally:
        db.close()
