"""基础配置接口：身份识别、归属地字典、人员信息表、钉钉机器人。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..config import IMAGE_DIR, IMAGE_URL_PREFIX, SERVER_PORT
from ..db import get_db
from ..models import DingTalkBot, Region, Staff
from ..schemas import BotIn, LoginIn, RegionIn, SettingsIn, StaffIn
from ..security import decrypt, encrypt, mask
from ..services import dingtalk, image_store
from ..services.region_norm import DEFAULT_REGIONS, PARENT_CITY, RegionNormalizer

router = APIRouter()


# ---------------------------------------------------------------- 身份识别

@router.post("/session/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    """手机号识别身份。系统不设密码，此接口同时承担「我是谁」和「我能看哪些数据」。"""
    mobile = payload.mobile.strip()
    staff = db.query(Staff).filter(Staff.mobile == mobile).first()
    if staff is None:
        raise HTTPException(status_code=404, detail="该手机号未在人员信息表中登记，请联系管理员")
    return {
        "name": staff.name,
        "mobile": staff.mobile,
        "region_name": staff.region_name,
        "role": staff.role,
        "position": staff.position,
        "is_admin": staff.role == "admin",
    }


# ---------------------------------------------------------------- 归属地字典

@router.get("/regions")
def list_regions(db: Session = Depends(get_db)):
    items = db.query(Region).order_by(Region.sort_order, Region.id).all()
    return [
        {
            "id": item.id,
            "standard_name": item.standard_name,
            "short_name": item.short_name,
            "parent": item.parent,
            "level": item.level,
            "aliases": json.loads(item.aliases_json or "[]"),
            "is_active": item.is_active,
        }
        for item in items
    ]


@router.post("/regions")
def create_region(payload: RegionIn, db: Session = Depends(get_db)):
    if db.query(Region).filter(Region.standard_name == payload.standard_name).first():
        raise HTTPException(status_code=400, detail="该归属地已存在")
    region = Region(
        standard_name=payload.standard_name,
        short_name=payload.short_name,
        parent=payload.parent,
        level=payload.level,
        aliases_json=json.dumps(payload.aliases, ensure_ascii=False),
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    db.add(region)
    db.commit()
    return {"id": region.id}


@router.put("/regions/{region_id}")
def update_region(region_id: int, payload: RegionIn, db: Session = Depends(get_db)):
    region = db.get(Region, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="归属地不存在")
    region.standard_name = payload.standard_name
    region.short_name = payload.short_name
    region.parent = payload.parent
    region.level = payload.level
    region.aliases_json = json.dumps(payload.aliases, ensure_ascii=False)
    region.sort_order = payload.sort_order
    region.is_active = payload.is_active
    db.commit()
    return {"ok": True}


@router.delete("/regions/{region_id}")
def delete_region(region_id: int, db: Session = Depends(get_db)):
    region = db.get(Region, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="归属地不存在")
    db.delete(region)
    db.commit()
    return {"ok": True}


@router.post("/regions/check")
def check_regions(payload: dict, db: Session = Depends(get_db)):
    """把一批名称做归一化，用来排查报表里的脏数据。"""
    values: list[str] = payload.get("values") or []
    normalizer = RegionNormalizer.from_db(db)
    results = []
    for value in values:
        outcome = normalizer.normalize(value)
        results.append(
            {
                "raw": value,
                "standard": outcome.standard,
                "matched_by": outcome.matched_by,
                "suggestion": outcome.suggestion,
                "ok": outcome.ok,
            }
        )
    unknown = sorted({r["raw"] for r in results if not r["ok"]})
    return {"results": results, "unknown": unknown}


# ---------------------------------------------------------------- 人员信息表

def _staff_dict(item: Staff) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "mobile": item.mobile,
        "region_name": item.region_name,
        "role": item.role,
        "position": item.position,
        "receive_alert": item.receive_alert,
    }


@router.get("/staff")
def list_staff(db: Session = Depends(get_db)):
    items = db.query(Staff).order_by(Staff.region_name, Staff.id).all()
    return [_staff_dict(item) for item in items]


@router.post("/staff")
def create_staff(payload: StaffIn, db: Session = Depends(get_db)):
    if db.query(Staff).filter(Staff.mobile == payload.mobile).first():
        raise HTTPException(status_code=400, detail="该手机号已存在")
    staff = Staff(**payload.model_dump())
    db.add(staff)
    db.commit()
    return {"id": staff.id}


@router.put("/staff/{staff_id}")
def update_staff(staff_id: int, payload: StaffIn, db: Session = Depends(get_db)):
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    for key, value in payload.model_dump().items():
        setattr(staff, key, value)
    db.commit()
    return {"ok": True}


@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: int, db: Session = Depends(get_db)):
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    db.delete(staff)
    db.commit()
    return {"ok": True}


@router.post("/staff/import")
async def import_staff(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """从 Excel 批量导入人员信息表：姓名 / 手机号 / 归属地。"""
    from openpyxl import load_workbook

    suffix = Path(file.filename or "upload.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(await file.read())
        temp_path = handle.name

    try:
        workbook = load_workbook(temp_path, data_only=True)
        worksheet = workbook.worksheets[0]
        rows = [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        Path(temp_path).unlink(missing_ok=True)

    if not rows:
        raise HTTPException(status_code=400, detail="文件为空")

    header = [(str(c).strip() if c is not None else "") for c in rows[0]]
    index_of = {}
    for position, name in enumerate(header):
        for key, words in (
            ("name", ("姓名", "名字", "人员", "name")),
            ("mobile", ("手机", "电话", "联系方式", "mobile", "phone")),
            ("region", ("归属地", "区县", "区域", "单位", "region")),
            ("position", ("岗位", "职位", "职务")),
        ):
            if key not in index_of and any(word in name for word in words):
                index_of[key] = position

    if "name" not in index_of or "mobile" not in index_of:
        raise HTTPException(status_code=400, detail="未识别到「姓名」或「手机号」列")

    normalizer = RegionNormalizer.from_db(db)
    created, updated, unknown_regions = 0, 0, set()

    for row in rows[1:]:
        def cell(key: str) -> str:
            position = index_of.get(key)
            if position is None or position >= len(row) or row[position] is None:
                return ""
            return str(row[position]).strip()

        name, mobile = cell("name"), cell("mobile")
        if not name or not mobile:
            continue
        raw_region = cell("region")
        region_name = ""
        if raw_region:
            outcome = normalizer.normalize(raw_region)
            region_name = outcome.standard or ""
            if not outcome.ok:
                unknown_regions.add(raw_region)

        existing = db.query(Staff).filter(Staff.mobile == mobile).first()
        if existing:
            existing.name = name
            existing.region_name = region_name or existing.region_name
            if cell("position"):
                existing.position = cell("position")
            updated += 1
        else:
            db.add(
                Staff(
                    name=name,
                    mobile=mobile,
                    region_name=region_name,
                    position=cell("position"),
                )
            )
            created += 1

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "unknown_regions": sorted(unknown_regions),
        "columns": header,
    }


# ---------------------------------------------------------------- 钉钉机器人

@router.get("/bots")
def list_bots(db: Session = Depends(get_db)):
    items = db.query(DingTalkBot).order_by(DingTalkBot.id).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "webhook": mask(decrypt(item.webhook_enc)),
            "has_secret": bool(item.secret_enc),
            "is_active": item.is_active,
            "last_test_at": item.last_test_at,
            "last_test_ok": item.last_test_ok,
            "last_test_msg": item.last_test_msg,
        }
        for item in items
    ]


@router.post("/bots")
def create_bot(payload: BotIn, db: Session = Depends(get_db)):
    if db.query(DingTalkBot).filter(DingTalkBot.name == payload.name).first():
        raise HTTPException(status_code=400, detail="该名称已存在")
    bot = DingTalkBot(
        name=payload.name,
        webhook_enc=encrypt(payload.webhook),
        secret_enc=encrypt(payload.secret),
        is_active=payload.is_active,
    )
    db.add(bot)
    db.commit()
    return {"id": bot.id}


@router.put("/bots/{bot_id}")
def update_bot(bot_id: int, payload: BotIn, db: Session = Depends(get_db)):
    bot = db.get(DingTalkBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    bot.name = payload.name
    bot.is_active = payload.is_active
    # 前端回显的是脱敏值，只有真正改动时才覆盖
    if payload.webhook and "*" not in payload.webhook:
        bot.webhook_enc = encrypt(payload.webhook)
    if payload.secret and "*" not in payload.secret:
        bot.secret_enc = encrypt(payload.secret)
    db.commit()
    return {"ok": True}


@router.delete("/bots/{bot_id}")
def delete_bot(bot_id: int, db: Session = Depends(get_db)):
    bot = db.get(DingTalkBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    db.delete(bot)
    db.commit()
    return {"ok": True}


@router.post("/bots/{bot_id}/test")
def test_bot(bot_id: int, payload: dict | None = None, db: Session = Depends(get_db)):
    from datetime import datetime

    bot = db.get(DingTalkBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")

    text = (payload or {}).get("text") or (
        f"#### 推送配置测试\n\n> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "这条消息来自「运营数据推送系统」，说明 Webhook 配置正确。"
    )
    result = dingtalk.send_markdown(decrypt(bot.webhook_enc), decrypt(bot.secret_enc), "配置测试", text)

    from datetime import datetime as dt

    bot.last_test_at = dt.now()
    bot.last_test_ok = result.ok
    bot.last_test_msg = result.message
    db.commit()

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.message)
    return {"ok": True, "message": result.message}


# ---------------------------------------------------------------- 系统设置

@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict:
    """图片推送相关的系统级设置。"""
    base = image_store.get_setting(db, image_store.SETTING_BASE_URL, "")
    days = image_store.get_setting(db, image_store.SETTING_RETENTION, str(image_store.IMAGE_RETENTION_DAYS))
    try:
        retention = max(1, int(days))
    except (TypeError, ValueError):
        retention = image_store.IMAGE_RETENTION_DAYS

    beeimg = image_store.beeimg_config(db)
    mode = image_store.upload_mode(db)
    return {
        "public_base_url": base,
        "effective_base_url": image_store.base_url(db),
        "image_upload_mode": mode,
        "image_ready": image_store.is_ready(db),
        "beeimg_url": beeimg["url"],
        "beeimg_storage_id": beeimg["storage_id"],
        "beeimg_token": mask(beeimg["token"]) if beeimg["token"] else "",
        "has_beeimg_token": bool(beeimg["token"]),
        "beeimg_expire_days": image_store.beeimg_expire_days(db),
        "beeimg_expired_at": image_store.beeimg_expired_at(db),
        "beeimg_is_public": image_store.beeimg_config(db).get("is_public", False),
        "beeimg_remove_exif": image_store.get_setting(
            db, image_store.SETTING_BEEIMG_EXIF, "1"
        ).lower() in ("1", "true", "yes", "on"),
        "image_retention_days": retention,
        "image_dir": str(IMAGE_DIR),
        "image_url_prefix": IMAGE_URL_PREFIX,
        "suggested_urls": [f"http://{ip}:{SERVER_PORT}" for ip in image_store.local_ipv4()],
        "font_available": image_renderer_font_ok(),
    }


def image_renderer_font_ok() -> bool:
    from ..services import image_renderer

    return image_renderer.font_available()


@router.put("/settings")
def update_settings(payload: SettingsIn, db: Session = Depends(get_db)) -> dict:
    if payload.public_base_url is not None:
        image_store.set_setting(db, image_store.SETTING_BASE_URL, payload.public_base_url.strip())
    if payload.image_retention_days is not None:
        image_store.set_setting(
            db, image_store.SETTING_RETENTION, str(max(1, int(payload.image_retention_days)))
        )
    if payload.image_upload_mode is not None:
        mode = payload.image_upload_mode.strip().lower()
        if mode in (image_store.MODE_LOCAL, image_store.MODE_BEEIMG):
            image_store.set_setting(db, image_store.SETTING_UPLOAD_MODE, mode)
    if payload.beeimg_url is not None:
        image_store.set_setting(db, image_store.SETTING_BEEIMG_URL, payload.beeimg_url.strip())
    if payload.beeimg_storage_id is not None:
        image_store.set_setting(db, image_store.SETTING_BEEIMG_STORAGE, payload.beeimg_storage_id.strip())
    if payload.beeimg_expire_days is not None:
        image_store.set_setting(
            db, image_store.SETTING_BEEIMG_EXPIRE, str(max(0, int(payload.beeimg_expire_days)))
        )
    if payload.beeimg_is_public is not None:
        image_store.set_setting(
            db, image_store.SETTING_BEEIMG_PUBLIC, "1" if payload.beeimg_is_public else "0"
        )
    if payload.beeimg_remove_exif is not None:
        image_store.set_setting(
            db, image_store.SETTING_BEEIMG_EXIF, "1" if payload.beeimg_remove_exif else "0"
        )
    # 回显的是脱敏值，只有真正改动时才覆盖
    if payload.beeimg_token and "*" not in payload.beeimg_token:
        image_store.set_setting(db, image_store.SETTING_BEEIMG_TOKEN, payload.beeimg_token.strip())
    return get_settings(db)


@router.post("/settings/test-image-host")
def test_image_host(db: Session = Depends(get_db)) -> dict:
    """真传一张小图上去，验证图床配置能不能用。"""
    from datetime import datetime as dt

    from ..services import image_host, image_renderer

    png, _ = image_renderer.render_report(
        "图床连通性测试",
        [{"项目": "上传测试", "结果": "成功"}],
        ["项目", "结果"],
        subtitle=dt.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    try:
        public_url = image_host.upload_png(
            png, **image_store.beeimg_config(db, intro="图床连通性测试")
        )
    except image_host.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "public_url": public_url,
        "expired_at": image_store.beeimg_expired_at(db) or "不过期",
    }
