"""发送记录与概览统计接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DataSource, DingTalkBot, PushRule, SendLog, Staff
from ..services import executor, scheduler

router = APIRouter()


@router.get("/logs")
def list_logs(
    rule_id: int | None = Query(None),
    status: str = Query(""),
    limit: int = Query(50),
    db: Session = Depends(get_db),
):
    query = db.query(SendLog)
    if rule_id:
        query = query.filter(SendLog.rule_id == rule_id)
    if status == "success":
        query = query.filter(SendLog.success.is_(True))
    elif status == "failed":
        query = query.filter(SendLog.success.is_(False))

    items = query.order_by(SendLog.id.desc()).limit(max(1, min(limit, 300))).all()
    return [
        {
            "id": item.id,
            "rule_id": item.rule_id,
            "rule_name": item.rule_name,
            "bot_names": item.bot_names,
            "trigger": item.trigger,
            "success": item.success,
            "row_count": item.row_count,
            "duration_ms": item.duration_ms,
            "error": item.error,
            "created_at": item.created_at,
        }
        for item in items
    ]


@router.get("/logs/{log_id}")
def get_log(log_id: int, db: Session = Depends(get_db)):
    item = db.get(SendLog, log_id)
    if item is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {
        "id": item.id,
        "rule_id": item.rule_id,
        "rule_name": item.rule_name,
        "bot_names": item.bot_names,
        "trigger": item.trigger,
        "success": item.success,
        "row_count": item.row_count,
        "duration_ms": item.duration_ms,
        "message_text": item.message_text,
        "error": item.error,
        "created_at": item.created_at,
    }


@router.post("/logs/{log_id}/resend")
def resend(log_id: int, db: Session = Depends(get_db)):
    item = db.get(SendLog, log_id)
    if item is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    rule = db.get(PushRule, item.rule_id) if item.rule_id else None
    if rule is None:
        raise HTTPException(status_code=400, detail="原始规则已删除，无法重发")
    return executor.run_rule(db, rule, trigger="retry")


@router.get("/stats")
def stats(mobile: str = Query(""), db: Session = Depends(get_db)):
    caller = db.query(Staff).filter(Staff.mobile == mobile).first() if mobile else None

    rule_query = db.query(PushRule)
    log_query = db.query(SendLog)
    if caller is not None and caller.role != "admin":
        rule_query = rule_query.filter(PushRule.region_name == caller.region_name)
        rule_ids = [r.id for r in rule_query.all()]
        log_query = log_query.filter(SendLog.rule_id.in_(rule_ids or [-1]))

    total_rules = rule_query.count()
    enabled_rules = rule_query.filter(PushRule.enabled.is_(True)).count()
    total_logs = log_query.count()
    failed_logs = log_query.filter(SendLog.success.is_(False)).count()

    today_start = func.date(SendLog.created_at)
    today_count = log_query.filter(today_start == func.current_date()).count()

    return {
        "datasource_count": db.query(DataSource).count(),
        "bot_count": db.query(DingTalkBot).count(),
        "staff_count": db.query(Staff).count(),
        "total_rules": total_rules,
        "enabled_rules": enabled_rules,
        "total_logs": total_logs,
        "failed_logs": failed_logs,
        "today_logs": today_count,
        "scheduler_jobs": scheduler.list_jobs(),
    }
