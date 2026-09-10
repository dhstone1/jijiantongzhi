"""推送规则接口：增删改查、预览、试跑、样例上传。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from ..config import IMAGE_URL_PREFIX
from ..db import get_db
from ..models import DataSource, PushRule, Staff
from ..schemas import PreviewIn, RuleIn
from ..services import (
    executor,
    field_matcher,
    image_renderer,
    image_store,
    metadata,
    renderer,
    sample_parser,
    scheduler,
    trigger,
)
from ..services.region_norm import RegionNormalizer
from ..services.sql_builder import build_query

router = APIRouter()


def _loads(raw: str, default):
    try:
        value = json.loads(raw or "")
        return value if value is not None else default
    except json.JSONDecodeError:
        return default


def _to_dict(rule: PushRule) -> dict:
    return {
        "id": rule.id,
        "name": rule.name,
        "created_by": rule.created_by,
        "region_name": rule.region_name,
        "data_source_id": rule.data_source_id,
        "table_name": rule.table_name,
        "query": _loads(rule.query_json, {}),
        "region_field": rule.region_field,
        "time_field": rule.time_field,
        "template": rule.template,
        "msg_type": rule.msg_type,
        "bot_ids": _loads(rule.bot_ids_json, []),
        "at_config": _loads(rule.at_json, {}),
        "image": _loads(rule.image_json, {}),
        "schedule_type": rule.schedule_type,
        "schedule": _loads(rule.schedule_json, {}),
        "enabled": rule.enabled,
        "sample": _loads(rule.sample_json, {}),
        "last_run_at": rule.last_run_at,
        "last_fired_at": rule.last_fired_at,
        "last_status": rule.last_status,
        "last_error": rule.last_error,
        "updated_at": rule.updated_at,
    }


def _resolve_caller(db: Session, mobile: str) -> Staff | None:
    if not mobile:
        return None
    return db.query(Staff).filter(Staff.mobile == mobile).first()


@router.get("/rules")
def list_rules(mobile: str = Query(""), db: Session = Depends(get_db)):
    query = db.query(PushRule)
    caller = _resolve_caller(db, mobile)
    if caller is not None and caller.role != "admin":
        # 非管理员只能看到自己归属地的规则
        query = query.filter(PushRule.region_name == caller.region_name)
    rules = query.order_by(PushRule.id.desc()).all()
    return [_to_dict(rule) for rule in rules]


@router.get("/rules/{rule_id}")
def get_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(PushRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return _to_dict(rule)


@router.post("/rules")
def create_rule(payload: RuleIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    caller = _resolve_caller(db, mobile)
    region_name = payload.region_name or (caller.region_name if caller and caller.role != "admin" else "")

    rule = PushRule(
        name=payload.name,
        created_by=mobile or (caller.mobile if caller else ""),
        region_name=region_name,
        data_source_id=payload.data_source_id,
        table_name=payload.table_name,
        query_json=json.dumps(payload.query, ensure_ascii=False),
        region_field=payload.region_field,
        time_field=payload.time_field,
        template=payload.template,
        msg_type=payload.msg_type,
        bot_ids_json=json.dumps(payload.bot_ids),
        at_json=json.dumps(payload.at_config, ensure_ascii=False),
        image_json=json.dumps(payload.image, ensure_ascii=False),
        schedule_type=payload.schedule_type,
        schedule_json=json.dumps(payload.schedule, ensure_ascii=False),
        enabled=payload.enabled,
        sample_json=json.dumps(payload.sample, ensure_ascii=False),
    )
    db.add(rule)
    db.commit()
    scheduler.sync_rule(rule)
    return {"id": rule.id}


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    rule = db.get(PushRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")

    caller = _resolve_caller(db, mobile)
    if caller is not None and caller.role != "admin" and rule.region_name and rule.region_name != caller.region_name:
        raise HTTPException(status_code=403, detail="无权修改其他归属地的规则")

    rule.name = payload.name
    rule.data_source_id = payload.data_source_id
    rule.table_name = payload.table_name
    rule.query_json = json.dumps(payload.query, ensure_ascii=False)
    rule.region_field = payload.region_field
    rule.time_field = payload.time_field
    rule.template = payload.template
    rule.msg_type = payload.msg_type
    rule.bot_ids_json = json.dumps(payload.bot_ids)
    rule.at_json = json.dumps(payload.at_config, ensure_ascii=False)
    rule.image_json = json.dumps(payload.image, ensure_ascii=False)
    rule.schedule_type = payload.schedule_type
    rule.schedule_json = json.dumps(payload.schedule, ensure_ascii=False)
    rule.enabled = payload.enabled
    rule.sample_json = json.dumps(payload.sample, ensure_ascii=False)
    if payload.region_name:
        rule.region_name = payload.region_name
    db.commit()
    scheduler.sync_rule(rule)
    return {"ok": True}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(PushRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    try:
        scheduler.scheduler.remove_job(f"rule_{rule_id}")
    except Exception:  # noqa: BLE001
        pass
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/rules/{rule_id}/toggle")
def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(PushRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    rule.enabled = not rule.enabled
    db.commit()
    scheduler.sync_rule(rule)
    return {"enabled": rule.enabled}


@router.post("/rules/{rule_id}/run")
def run_rule_now(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(PushRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return executor.run_rule(db, rule, trigger="manual")


@router.post("/rules/preview")
def preview_rule(payload: PreviewIn, db: Session = Depends(get_db)):
    """按当前配置取数并渲染，不发送。用于编辑时的实时预览。"""
    ds = db.get(DataSource, payload.data_source_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="数据源不存在")

    normalizer = RegionNormalizer.from_db(db)
    cfg = dict(payload.query or {})
    cfg["limit"] = payload.limit

    try:
        table = cfg.get("table") or ""
        if (cfg.get("mode") or "builder") == "sql":
            table_columns: list[str] = []
        else:
            table_columns = [c["name"] for c in metadata.list_columns(ds, table)]

        built = build_query(
            cfg,
            table_columns,
            metadata.get_engine(ds),
            region_field=payload.region_field,
            region_value=payload.region_name,
            normalizer=normalizer,
            max_rows=payload.limit,
        )

        from sqlalchemy import text

        with metadata.get_engine(ds).connect() as conn:
            result = conn.execute(text(built.sql), built.params)
            columns = list(result.keys())
            rows = [dict(zip(columns, row)) for row in result.fetchall()]

        for row in rows:
            for key, value in row.items():
                if hasattr(value, "strftime"):
                    row[key] = value.strftime("%Y-%m-%d %H:%M:%S")

        # 触发判定：表格里展示全部取数结果，但只有命中行会真正发出去
        trigger_cfg = trigger.normalize(cfg.get("trigger"))
        outcome = trigger.evaluate(rows, trigger_cfg)
        hit_rows = outcome.rows
        hit_set = set(outcome.hit_indexes)

        image_cfg = dict(payload.image or {})
        # 图片真能发出去时，文字部分才去掉数据表；本机模式要先配好「图片服务地址」
        image_ready = (
            image_store.upload_mode(db) == image_store.MODE_BEEIMG
            or bool(image_store.base_url(db))
        )
        image_will_send = bool(image_cfg.get("enabled")) and image_ready
        suppress_table = image_will_send and bool(image_cfg.get("with_text", True))

        rendered = ""
        render_warnings: list[str] = []
        if payload.template:
            rendered, render_warnings = renderer.render_template(
                payload.template,
                hit_rows,
                columns,
                highlight=cfg.get("highlight") or None,
                suppress_table=suppress_table,
            )
        if suppress_table:
            render_warnings.append("已开启图片发送，文字部分只保留标题和说明，不再重复发数据表")
            if image_store.upload_mode(db) == image_store.MODE_BEEIMG:
                render_warnings.append("预览里的图片是本机临时图，真正发送时会先上传到图床再发公网链接")

        image_path = ""
        image_url = ""
        if image_cfg.get("enabled"):
            try:
                png, image_warnings_msg = image_renderer.render_report(
                    image_cfg.get("title") or "数据通报",
                    hit_rows,
                    columns,
                    subtitle=image_cfg.get("subtitle")
                    or image_renderer.default_subtitle(len(hit_rows)),
                    highlight=cfg.get("highlight") or None,
                    max_rows=int(image_cfg.get("max_rows") or 30),
                    footer=image_cfg.get("footer") or "",
                )
                filename = image_store.save(png, tag=image_store.PREVIEW_TAG)
                image_path = f"{IMAGE_URL_PREFIX}/{filename}"
                base = image_store.base_url(db)
                image_url = image_store.url_for(base, filename) if base else ""
                render_warnings.extend(image_warnings_msg)
                # 预览图是临时产物，只留 1 天
                image_store.cleanup(1, prefix=f"{image_store.PREVIEW_TAG}_")
            except Exception as exc:  # noqa: BLE001 - 预览出图失败不该拦住取数
                render_warnings.append(f"生成图片失败：{exc}")

        trigger_warnings = list(outcome.warnings)
        if trigger_cfg["mode"] == "threshold":
            trigger_warnings.append(
                f"触发条件：{trigger.describe(trigger_cfg)}"
                f"；命中 {outcome.hit_count} / {outcome.total} 行，只有命中行会发送"
            )

        return {
            "columns": columns,
            "rows": rows,
            "hit_indexes": sorted(hit_set),
            "hit_rows": hit_rows,
            "row_count": len(rows),
            "hit_count": outcome.hit_count,
            "trigger": {
                "mode": trigger_cfg["mode"],
                "summary": outcome.summary,
                "hit": outcome.hit,
                "hit_count": outcome.hit_count,
                "total": outcome.total,
                "cooldown_minutes": trigger_cfg["cooldown_minutes"],
            },
            "sql": built.sql,
            "warnings": built.warnings + trigger_warnings + render_warnings,
            "rendered": rendered,
            "image_path": image_path,
            "image_url": image_url,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"取数失败：{exc}") from exc


@router.post("/rules/suggest-template")
def suggest_template(payload: dict):
    title = payload.get("title") or "数据通报"
    columns = payload.get("columns") or []
    time_field = payload.get("time_field") or ""
    return {"template": renderer.default_template(title, columns, time_field)}


# ---------------------------------------------------------------- 样例报表（样式参考）

@router.post("/samples/parse")
async def parse_sample_file(
    file: UploadFile = File(...),
    data_source_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """上传一份「期望的报表样式」，系统解析它的结构与字段，用来推荐模板和字段。"""
    suffix = Path(file.filename or "sample.xlsx").suffix.lower() or ".xlsx"
    if suffix not in (".xlsx", ".xlsm", ".csv"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 或 .csv 文件")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(await file.read())
        temp_path = handle.name

    try:
        normalizer = RegionNormalizer.from_db(db)
        parsed = sample_parser.parse_sample(temp_path, normalizer)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"解析失败：{exc}") from exc
    finally:
        Path(temp_path).unlink(missing_ok=True)

    # 用样例的列名去推荐数据库字段
    recommendations: list[dict] = []
    if data_source_id:
        ds = db.get(DataSource, data_source_id)
        if ds is not None:
            snapshot = metadata.load_snapshot(ds)
            if not snapshot.get("tables"):
                try:
                    snapshot = metadata.build_metadata_snapshot(ds)
                    ds.meta_json = json.dumps(snapshot, ensure_ascii=False)
                    db.commit()
                except Exception:  # noqa: BLE001
                    snapshot = {}

            for sheet in parsed.get("sheets", []):
                sample_columns = [c["name"] for c in sheet["columns"] if not c["is_empty"]]
                matched_table = field_matcher.match_table(
                    sheet.get("title") or sheet["name"], snapshot.get("tables", [])
                )
                entry = {
                    "sheet": sheet["name"],
                    "sample_columns": sample_columns,
                    "suggested_table": matched_table["name"] if matched_table else "",
                    "table_score": matched_table["score"] if matched_table else 0,
                    "column_matches": [],
                }
                if matched_table:
                    db_columns = next(
                        (t["columns"] for t in snapshot["tables"] if t["name"] == matched_table["name"]),
                        [],
                    )
                    entry["column_matches"] = field_matcher.match_columns(sample_columns, db_columns)
                recommendations.append(entry)

    parsed["recommendations"] = recommendations
    return parsed
