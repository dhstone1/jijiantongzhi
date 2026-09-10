"""调度器：按规则的频率配置自动执行。

进度说明：一期支持小时级，架构上预留分钟级（把 interval 的 hours 换成 minutes 即可）。
"""
from __future__ import annotations

import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..db import SessionLocal
from ..models import PushRule
from . import executor

logger = logging.getLogger("jijiantongzhi.scheduler")

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _job_id(rule_id: int) -> str:
    return f"rule_{rule_id}"


def _loads(raw: str) -> dict:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _run(rule_id: int) -> None:
    db = SessionLocal()
    try:
        rule = db.get(PushRule, rule_id)
        if rule is None or not rule.enabled:
            return
        result = executor.run_rule(db, rule, trigger="auto")
        if result.get("success"):
            logger.info("规则 %s 执行成功", rule.name)
        else:
            logger.warning("规则 %s 执行失败：%s", rule.name, result.get("error"))
    finally:
        db.close()


def build_trigger(rule: PushRule):
    cfg = _loads(rule.schedule_json)
    kind = (rule.schedule_type or "manual").lower()

    if kind == "hourly":
        hours = max(1, int(cfg.get("interval_hours") or 1))
        return IntervalTrigger(hours=hours)

    if kind == "minutely":  # 预留：分钟级
        minutes = max(1, int(cfg.get("interval_minutes") or 30))
        return IntervalTrigger(minutes=minutes)

    if kind == "daily":
        return CronTrigger(hour=int(cfg.get("hour", 8)), minute=int(cfg.get("minute", 30)))

    if kind == "weekly":
        return CronTrigger(
            day_of_week=str(cfg.get("day_of_week", "mon")),
            hour=int(cfg.get("hour", 8)),
            minute=int(cfg.get("minute", 30)),
        )

    return None


def sync_rule(rule: PushRule) -> None:
    job_id = _job_id(rule.id)
    try:
        scheduler.remove_job(job_id)
    except Exception:  # noqa: BLE001 - 任务不存在
        pass

    if not rule.enabled:
        return

    trigger = build_trigger(rule)
    if trigger is None:
        return

    scheduler.add_job(
        _run,
        trigger=trigger,
        id=job_id,
        args=[rule.id],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        replace_existing=True,
    )


def reload_all() -> int:
    for job in scheduler.get_jobs():
        try:
            scheduler.remove_job(job.id)
        except Exception:  # noqa: BLE001
            pass

    db = SessionLocal()
    count = 0
    try:
        for rule in db.query(PushRule).filter(PushRule.enabled.is_(True)).all():
            sync_rule(rule)
            if build_trigger(rule) is not None:
                count += 1
    finally:
        db.close()
    return count


def start() -> None:
    if not scheduler.running:
        scheduler.start()
    count = reload_all()
    logger.info("调度器已启动，共 %d 条定时规则", count)


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def list_jobs() -> list[dict]:
    return [
        {
            "id": job.id,
            "next_run": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "",
        }
        for job in scheduler.get_jobs()
    ]

