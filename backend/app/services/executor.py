"""规则执行器：取数 → 渲染 → 解析 @ 人员 → 发送 → 记录。"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import MAX_ROWS_HARD_LIMIT
from ..models import DataSource, DingTalkBot, PushRule, SendLog, Staff
from ..security import decrypt
from . import dingtalk, image_host, image_renderer, image_store, metadata, renderer
from . import scope as scope_service
# 注意：run_rule 的形参也叫 trigger，模块必须用别名，否则会被遮蔽
from . import trigger as trigger_engine
from .region_norm import RegionNormalizer
from .sql_builder import build_query


def _loads(raw: str, default):
    try:
        value = json.loads(raw or "")
        return value if value is not None else default
    except json.JSONDecodeError:
        return default


def load_query(rule: PushRule) -> dict:
    return _loads(rule.query_json, {})


def load_at_config(rule: PushRule) -> dict:
    return _loads(rule.at_json, {})


def load_image_config(rule: PushRule) -> dict:
    return _loads(rule.image_json, {})


def load_card_config(rule: PushRule) -> dict:
    return _loads(rule.card_json, {})


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def execute_query(
    db: Session,
    ds: DataSource,
    query_cfg: dict,
    region_field: str,
    region_value: str,
    normalizer: RegionNormalizer,
) -> tuple[list[str], list[dict], list[str]]:
    """执行取数，返回 (列名, 行数据, 告警)。"""
    table = (query_cfg.get("table") or "").strip()
    if (query_cfg.get("mode") or "builder") == "sql":
        columns_meta = []
        table_columns: list[str] = []
    else:
        columns_meta = metadata.list_columns(ds, table)
        table_columns = [c["name"] for c in columns_meta]

    built = build_query(
        query_cfg,
        table_columns,
        metadata.get_engine(ds),
        region_field=region_field,
        region_value=region_value,
        normalizer=normalizer,
        max_rows=MAX_ROWS_HARD_LIMIT,
    )

    engine = metadata.get_engine(ds)
    with engine.connect() as conn:
        result = conn.execute(text(built.sql), built.params)
        keys = list(result.keys())
        rows = [{k: v for k, v in zip(keys, raw)} for raw in result.fetchall()]

    for row in rows:
        for key, value in row.items():
            if isinstance(value, datetime):
                row[key] = value.strftime("%Y-%m-%d %H:%M:%S")

    limit_used = int(built.params.get("_limit") or 0)
    trigger_mode = str((query_cfg.get("trigger") or {}).get("mode") or "always").lower()
    if limit_used and len(rows) >= limit_used and trigger_mode != "always":
        built.warnings.append(
            f"取数达到扫描上限 {limit_used} 行，后面的数据没取到，判定结果可能不全，"
            "建议缩小时间范围"
        )

    return keys, rows, built.warnings


def resolve_at_mobiles(
    db: Session,
    at_config: dict,
    rows: list[dict],
    normalizer: RegionNormalizer,
) -> tuple[list[str], list[str]]:
    """解析本次要 @ 的手机号，返回 (手机号列表, 说明)。"""
    mode = at_config.get("mode") or "none"
    notes: list[str] = []
    mobiles: list[str] = []

    if mode == "none":
        return [], notes

    if mode == "fixed":
        mobiles = [m for m in (at_config.get("mobiles") or []) if m]
        if mobiles:
            notes.append(f"固定 @ {len(mobiles)} 人")
        return mobiles, notes

    if mode == "region":
        regions = set()
        for row in rows:
            result = normalizer.normalize(row.get(at_config.get("field") or "", ""))
            if result.ok:
                regions.add(result.standard)
        if not regions:
            notes.append("按归属地 @：未匹配到归属地")
            return [], notes
        staff = (
            db.query(Staff)
            .filter(Staff.region_name.in_(regions), Staff.receive_alert.is_(True))
            .all()
        )
        mobiles = sorted({s.mobile for s in staff if s.mobile})
        notes.append(f"按归属地 @ {len(mobiles)} 人（{'、'.join(sorted(regions))}）")
        return mobiles, notes

    if mode == "field":
        field = at_config.get("field") or ""
        names = {str(row.get(field) or "").strip() for row in rows}
        names.discard("")
        if not names:
            notes.append(f"按字段 @：字段「{field}」无有效值")
            return [], notes
        staff = db.query(Staff).filter(Staff.name.in_(names)).all()
        mobiles = sorted({s.mobile for s in staff if s.mobile})
        notes.append(f"按「{field}」@ {len(mobiles)} 人")
        return mobiles, notes

    return [], notes


def evaluate_condition(rows: list[dict], condition: dict) -> bool:
    field = condition.get("field")
    if not field:
        return True
    try:
        threshold = float(condition.get("value"))
    except (TypeError, ValueError):
        return True

    op = condition.get("op") or ">"
    for row in rows:
        try:
            current = float(str(row.get(field, "")).replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        hit = {
            ">": current > threshold,
            ">=": current >= threshold,
            "<": current < threshold,
            "<=": current <= threshold,
            "=": current == threshold,
            "!=": current != threshold,
        }.get(op, False)
        if hit:
            return True
    return False


def run_rule(
    db: Session,
    rule: PushRule,
    trigger: str = "auto",
    identity_region: str | None = None,
    dry_run: bool = False,
) -> dict:
    """执行一条规则。dry_run=True 时只取数和渲染，不发送。"""
    started = time.time()
    result: dict = {
        "rule_id": rule.id,
        "rule_name": rule.name,
        "success": False,
        "sent": False,
        "rows": [],
        "columns": [],
        "rendered": "",
        "warnings": [],
        "error": "",
        "message": "",
        "image_url": "",
        "trigger": {},
    }

    try:
        ds = db.get(DataSource, rule.data_source_id) if rule.data_source_id else None
        if ds is None:
            raise ValueError("规则未绑定数据源")

        normalizer = RegionNormalizer.from_db(db)
        query_cfg = load_query(rule)
        image_cfg = load_image_config(rule)

        # 归属地：规则自身绑定的归属地优先，否则用当前访客的归属地。
        # 挂在地市上的规则要连带下属区县一起取，所以这里展开成作用域。
        region_value = scope_service.region_filter_value(
            db, rule.region_name or identity_region or ""
        )

        columns, rows, warnings = execute_query(
            db, ds, query_cfg, rule.region_field, region_value, normalizer
        )
        result["columns"] = columns
        result["rows"] = rows
        result["warnings"].extend(warnings)

        if not rows:
            empty_action = (query_cfg.get("empty_action") or "skip").lower()
            if empty_action == "skip":
                result.update(success=True, sent=False, message="无数据，按配置跳过发送")
                _write_log(db, rule, trigger, True, 0, 0, "", "无数据，已跳过")
                return result

        # ---- 触发判定：报表类原样通过，告警类只保留命中的行 ----
        trigger_cfg = query_cfg.get("trigger") or {}
        outcome = trigger_engine.evaluate(rows, trigger_cfg, columns)
        result["warnings"].extend(outcome.warnings)
        result["trigger"] = {
            "mode": trigger_engine.normalize(trigger_cfg)["mode"],
            "hit": outcome.hit,
            "hit_count": outcome.hit_count,
            "total": outcome.total,
            "summary": outcome.summary,
        }

        if not outcome.hit:
            message = f"未达到触发条件，本次不发送（{outcome.summary}）"
            result.update(success=True, sent=False, message=message)
            _write_log(db, rule, trigger, True, 0, 0, "", message)
            return result

        rows = outcome.rows
        if outcome.columns:
            # 分组统计会自己算出一列（比如「出现次数」），列名要跟着一起换
            columns = outcome.columns
        # 取数是按扫描上限取全的，真正发出去的行数按「最多发送条数」截
        send_limit = min(max(int(query_cfg.get("limit") or 50), 1), MAX_ROWS_HARD_LIMIT)
        if len(rows) > send_limit:
            result["warnings"].append(
                f"命中 {len(rows)} 行，按「最多发送条数」只发前 {send_limit} 行"
            )
            rows = rows[:send_limit]
        result["rows"] = rows

        # ---- 冷却：同一条告警在冷却期内不重复推送 ----
        cooldown = trigger_engine.normalize(trigger_cfg)["cooldown_minutes"]
        remaining = trigger_engine.cooldown_remaining(rule.last_fired_at, cooldown)
        if remaining > 0 and trigger == "manual":
            # 手动点「立即发送」是明确要发一次，冷却只拦自动推送
            result["warnings"].append(
                f"手动运行，已忽略 {cooldown} 分钟冷却（定时推送仍按冷却执行，"
                f"距上次发送 {cooldown - remaining:.0f} 分钟）"
            )
        elif remaining > 0:
            message = f"距上次发送不足 {cooldown} 分钟（还剩约 {remaining:.0f} 分钟），本次跳过"
            result.update(success=True, sent=False, message=message)
            _write_log(db, rule, trigger, True, 0, 0, "", message)
            return result

        highlight = query_cfg.get("highlight") or None
        rendered, render_warnings = renderer.render_template(
            rule.template or renderer.default_template(rule.name, columns),
            rows,
            columns,
            highlight=highlight,
            table_style=renderer.resolve_table_style(rule.msg_type, query_cfg),
        )
        result["rendered"] = rendered
        result["warnings"].extend(render_warnings)

        if dry_run:
            result.update(success=True, sent=False, message="预览完成（未发送）")
            return result

        at_config = load_at_config(rule)
        condition = at_config.get("condition") or {}
        skip_at = condition and not evaluate_condition(rows, condition)
        if skip_at:
            mobiles, notes = [], ["条件未满足，本次不 @ 任何人"]
        else:
            mobiles, notes = resolve_at_mobiles(db, at_config, rows, normalizer)
        result["warnings"].extend(notes)

        bot_ids = _loads(rule.bot_ids_json, [])
        bots = db.query(DingTalkBot).filter(DingTalkBot.id.in_(bot_ids)).all() if bot_ids else []
        if not bots:
            raise ValueError("规则未配置钉钉发送目标")

        title = rule.name
        body, image_url = build_body(
            db, rule, image_cfg, title, rendered, rows, columns, highlight, result
        )
        result["image_url"] = image_url

        excel_url = ""
        if rule.send_excel and rows:
            excel_url = build_excel(db, rule, rows, columns, result)
            if excel_url:
                body += f"\n\n📎 **数据文件**：[点击下载]({excel_url})"

        card_cfg = load_card_config(rule)
        # 卡片没配按钮但这次生成了 Excel，就拿下载地址当按钮，省得用户再填一遍
        if not (card_cfg.get("btn_url") or "") and excel_url:
            card_cfg["btn_title"] = card_cfg.get("btn_title") or "下载完整数据"
            card_cfg["btn_url"] = excel_url

        msg_type = (rule.msg_type or "markdown").lower()
        errors: list[str] = []
        ok_count = 0
        for bot in bots:
            webhook = decrypt(bot.webhook_enc)
            secret = decrypt(bot.secret_enc)
            at_all = bool(at_config.get("at_all"))
            if msg_type == "text" and not image_url:
                send_result = dingtalk.send_text(webhook, secret, body, mobiles, at_all)
            elif msg_type == "actioncard":
                send_result = dingtalk.send_action_card(
                    webhook,
                    secret,
                    card_cfg.get("title") or title,
                    body,
                    mobiles,
                    at_all,
                    btn_title=card_cfg.get("btn_title") or "",
                    btn_url=card_cfg.get("btn_url") or "",
                    btn_orientation=str(card_cfg.get("btn_orientation") or "0"),
                )
            else:
                send_result = dingtalk.send_markdown(webhook, secret, title, body, mobiles, at_all)
            if send_result.ok:
                ok_count += 1
            else:
                errors.append(f"{bot.name}: {send_result.message}")

        duration = int((time.time() - started) * 1000)
        success = ok_count > 0 and not errors
        if ok_count > 0:
            # 只有真正发出去才算「触发过」，跳过的执行不刷新冷却计时
            rule.last_fired_at = datetime.now()
        result.update(
            success=success,
            sent=ok_count > 0,
            message=f"已发送到 {ok_count}/{len(bots)} 个群",
            error="; ".join(errors),
        )
        _write_log(
            db, rule, trigger, success, len(rows), duration,
            body, "; ".join(errors), ",".join(b.name for b in bots),
        )
        return result

    except Exception as exc:  # noqa: BLE001 - 统一转成可展示的错误信息
        duration = int((time.time() - started) * 1000)
        result.update(success=False, error=f"{type(exc).__name__}: {exc}", message="执行失败")
        try:
            _write_log(db, rule, trigger, False, 0, duration, result.get("rendered", ""), result["error"])
        except Exception:  # noqa: BLE001
            pass
        return result


def build_body(
    db: Session,
    rule: PushRule,
    image_cfg: dict,
    title: str,
    rendered: str,
    rows: list[dict],
    columns: list[str],
    highlight: dict | None,
    result: dict,
) -> tuple[str, str]:
    """把渲染结果加工成最终要发出去的 markdown，开了图片就先出图。

    返回 (消息正文, 图片地址)。出图或地址没配好时退回纯文字，不影响这次推送。
    """
    if not image_cfg.get("enabled"):
        return rendered, ""

    if rule.msg_type == "text":
        result["warnings"].append("图片形式只能走 Markdown，本次已自动改用 Markdown 发送")

    caption = image_cfg.get("title") or title
    try:
        png, image_warnings = image_renderer.render_report(
            caption,
            rows,
            columns,
            subtitle=image_cfg.get("subtitle") or image_renderer.default_subtitle(len(rows)),
            highlight=highlight,
            max_rows=_int(image_cfg.get("max_rows"), 30),
            footer=image_cfg.get("footer") or "",
        )
    except Exception as exc:  # noqa: BLE001 - 出图失败不该让整条推送失败
        result["warnings"].append(f"生成图片失败，本次改发文字消息：{exc}")
        return rendered, ""

    result["warnings"].extend(image_warnings)

    image_url = ""
    if image_store.upload_mode(db) == image_store.MODE_BEEIMG:
        # 传到图床，拿公网地址，钉钉一定拉得到
        digest = hashlib.md5(png).hexdigest()
        image_url = image_store.cache_lookup(digest)
        if image_url:
            result["warnings"].append("报表内容与上次相同，已直接复用上传过的图片链接（不再占用图床额度）")
        else:
            try:
                image_url = image_host.upload_png(
                    png, **image_store.beeimg_config(db, intro=caption)
                )
            except image_host.UploadError as exc:
                result["warnings"].append(f"上传图床失败，本次改发文字消息：{exc}")
                return rendered, ""
            image_store.cache_remember(
                digest, image_url, image_store.beeimg_expired_at(db), rule.id
            )
    else:
        base = image_store.base_url(db)
        if not base:
            result["warnings"].append("还没配置「图片服务地址」，本次改发文字消息（可在「系统设置」里补上）")
            return rendered, ""
        if image_store.is_local_url(base):
            result["warnings"].append(
                f"图片服务地址是 {base}，钉钉手机端可能加载不出来，建议改成局域网地址或改用图床"
            )
        filename = image_store.save(png, rule.id)
        image_url = image_store.url_for(base, filename)
        try:
            image_store.cleanup(image_store.retention_days(db))
        except OSError:
            pass

    # 图片里已经有完整表格了，文字部分只留标题和说明，不再重复发一遍数据
    text_part = ""
    if image_cfg.get("with_text", True) and rendered:
        text_part, text_warnings = renderer.render_template(
            rule.template or renderer.default_template(rule.name, columns),
            rows,
            columns,
            highlight=highlight,
            suppress_table=True,
        )
        result["warnings"].extend(
            warning for warning in text_warnings if warning not in result["warnings"]
        )

    image_line = f"![{caption}]({image_url})"
    if text_part.strip():
        return f"{text_part}\n\n{image_line}", image_url
    return f"#### {caption}\n\n{image_line}", image_url


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_excel(
    db: Session,
    rule: PushRule,
    rows: list[dict],
    columns: list[str],
    result: dict,
) -> str:
    """把本次数据导出成 Excel，返回可下载地址；生成不出来就返回空串。

    图床模式优先传图床（钉钉手机端才拉得到），图床不收 xlsx 就退回本系统地址，
    两种情况都往 warnings 里写清楚，免得运营人员以为附件发出去了。
    """
    import pandas as pd  # 只有开了 Excel 的规则才需要它
    from io import BytesIO

    try:
        buffer = BytesIO()
        pd.DataFrame(rows, columns=columns).to_excel(buffer, index=False, engine="openpyxl")
        content = buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 - 导出失败不该让整条推送失败
        result["warnings"].append(f"生成 Excel 文件失败：{exc}")
        return ""

    safe_name = "".join(ch for ch in (rule.name or "report") if ch not in '\\/:*?"<>|').strip()
    filename = f"{safe_name or 'report'}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

    if image_store.upload_mode(db) == image_store.MODE_BEEIMG:
        try:
            url = image_host.upload_file(
                content,
                filename=filename,
                content_type=XLSX_MIME,
                **image_store.beeimg_config(db, intro=f"{rule.name} 数据文件"),
            )
        except image_host.UploadError as exc:
            result["warnings"].append(f"Excel 上传图床失败，改用本系统地址：{exc}")
        else:
            result["warnings"].append("已生成 Excel 数据文件（已上传图床）")
            return url

    base = image_store.base_url(db)
    if not base:
        result["warnings"].append(
            "还没配置「图片服务地址」，Excel 下载链接发不出去，本次只发文字（可在「系统设置」里补上）"
        )
        return ""
    if image_store.is_local_url(base):
        result["warnings"].append(
            f"文件地址是 {base}，钉钉手机端可能下载不了，建议改成局域网地址或改用图床"
        )
    name = image_store.save(content, rule.id, suffix=".xlsx")
    try:
        image_store.cleanup(image_store.retention_days(db))
    except OSError:
        pass
    result["warnings"].append("已生成 Excel 数据文件")
    return image_store.url_for(base, name)


def _write_log(
    db: Session,
    rule: PushRule,
    trigger: str,
    success: bool,
    row_count: int,
    duration_ms: int,
    message_text: str,
    error: str = "",
    bot_names: str = "",
) -> None:
    db.add(
        SendLog(
            rule_id=rule.id,
            rule_name=rule.name,
            bot_names=bot_names,
            trigger=trigger,
            success=success,
            row_count=row_count,
            duration_ms=duration_ms,
            message_text=message_text[:8000],
            error=error[:2000],
        )
    )
    rule.last_run_at = datetime.now()
    rule.last_status = "success" if success else "failed"
    rule.last_error = error[:2000]
    db.commit()
