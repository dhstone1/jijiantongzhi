"""发送记录与概览统计接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DataSource, DingTalkBot, PushRule, SendLog, Staff
from ..services import executor, scheduler, scope

router = APIRouter()


def _guard_log(db: Session, mobile: str, item: SendLog) -> None:
    """单条记录的读权限：省级随便看，其他人只能看自己作用域内规则的记录。"""
    caller = db.query(Staff).filter(Staff.mobile == mobile).first() if mobile else None
    if caller is None:
        raise HTTPException(status_code=401, detail="未识别到身份，请重新登录")
    if scope.is_province(caller.role):
        return
    rule = db.get(PushRule, item.rule_id) if item.rule_id else None
    allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
    if rule is None or not scope.can_see_region(allowed, rule.region_name):
        raise HTTPException(status_code=403, detail="无权查看其他地市的发送记录")


@router.get("/logs")
def list_logs(
    rule_id: int | None = Query(None),
    status: str = Query(""),
    limit: int = Query(50),
    mobile: str = Query(""),
    db: Session = Depends(get_db),
):
    query = db.query(SendLog)
    caller = db.query(Staff).filter(Staff.mobile == mobile).first() if mobile else None
    if caller is not None and not scope.is_province(caller.role):
        # 记录跟着规则走：只看得到自己作用域内那些规则发出的记录
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        visible_ids = [
            r.id
            for r in db.query(PushRule).all()
            if scope.can_see_region(allowed, r.region_name)
        ]
        query = query.filter(SendLog.rule_id.in_(visible_ids or [-1]))
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
def get_log(log_id: int, mobile: str = Query(""), db: Session = Depends(get_db)):
    item = db.get(SendLog, log_id)
    if item is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    _guard_log(db, mobile, item)
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
def resend(log_id: int, mobile: str = Query(""), db: Session = Depends(get_db)):
    item = db.get(SendLog, log_id)
    if item is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    _guard_log(db, mobile, item)
    rule = db.get(PushRule, item.rule_id) if item.rule_id else None
    if rule is None:
        raise HTTPException(status_code=400, detail="原始规则已删除，无法重发")
    return executor.run_rule(db, rule, trigger="retry")


@router.get("/stats")
def stats(mobile: str = Query(""), db: Session = Depends(get_db)):
    caller = db.query(Staff).filter(Staff.mobile == mobile).first() if mobile else None

    rule_query = db.query(PushRule)
    log_query = db.query(SendLog)
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        rule_ids = [
            r.id for r in rule_query.all() if scope.can_see_region(allowed, r.region_name)
        ]
        rule_query = rule_query.filter(PushRule.id.in_(rule_ids or [-1]))
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
