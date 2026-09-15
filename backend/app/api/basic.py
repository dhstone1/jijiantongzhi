"""基础配置接口：身份识别、归属地字典、人员信息表、钉钉机器人、权限管理。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import IMAGE_DIR, IMAGE_URL_PREFIX, SERVER_PORT
from ..db import get_db
from ..models import DingTalkBot, Region, ResourcePermission, Staff
from ..schemas import BotIn, LoginIn, RegionIn, SettingsIn, StaffIn, PermissionGrantIn
from ..security import decrypt, encrypt, mask
from ..services import dingtalk, image_store
from ..services import scope
from ..services.region_norm import DEFAULT_REGIONS, PARENT_CITY, RegionNormalizer

router = APIRouter()


def _resolve_caller(db: Session, mobile: str) -> Staff | None:
    if not mobile:
        return None
    return db.query(Staff).filter(Staff.mobile == mobile).first()


# ---------------------------------------------------------------- 身份识别

@router.post("/session/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    """手机号识别身份。系统不设密码，此接口同时承担"我是谁"和"我能看哪些数据"。"""
    mobile = payload.mobile.strip()
    staff = db.query(Staff).filter(Staff.mobile == mobile).first()
    if staff is None:
        raise HTTPException(status_code=404, detail="该手机号未在人员信息表中登记，请联系管理员")
    role = scope.normalize_role(staff.role)
    scope_names = scope.caller_scope(db, role, staff.region_name)
    return {
        "name": staff.name,
        "mobile": staff.mobile,
        "region_name": staff.region_name,
        "role": role,
        "role_label": scope.role_label(role),
        "menus": scope.menus_of(role),
        # None = 不限（省级管理员），否则是「自己 + 全部下级」的归属地列表
        "scope_regions": sorted(scope_names) if scope_names is not None else None,
        "position": staff.position,
        "is_admin": scope.is_province(role),
        "is_city_admin": scope.is_city(role),
    }


# ---------------------------------------------------------------- 归属地字典

@router.get("/regions")
def list_regions(mobile: str = Query(""), db: Session = Depends(get_db)):
    """归属地字典。地市管理员只看到本地市及下属区县，普通人员只能看自己那一条。"""
    caller = _resolve_caller(db, mobile) if mobile else None
    items = db.query(Region).order_by(Region.sort_order, Region.id).all()
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        items = [item for item in items if item.standard_name in allowed]
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
def create_region(payload: RegionIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    if db.query(Region).filter(Region.standard_name == payload.standard_name).first():
        raise HTTPException(status_code=400, detail="该归属地已存在")
    caller = _resolve_caller(db, mobile) if mobile else None
    _require_region_manager(_caller_role(caller))
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        # 地市管理员只能在本地市下面加区县，parent 必须落在自己作用域里
        if (payload.parent or "").strip() not in allowed:
            raise HTTPException(status_code=403, detail="只能在自己地市下面新增归属地")
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
def update_region(region_id: int, payload: RegionIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    region = db.get(Region, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="归属地不存在")
    caller = _resolve_caller(db, mobile) if mobile else None
    _require_region_manager(_caller_role(caller))
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        if region.standard_name not in allowed:
            raise HTTPException(status_code=403, detail="无权修改其他地市的归属地")
        if region.standard_name in scope.PROTECTED_REGIONS:
            raise HTTPException(status_code=403, detail=f"「{region.standard_name}」由省级维护，地市不能改")
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
def delete_region(region_id: int, mobile: str = Query(""), db: Session = Depends(get_db)):
    region = db.get(Region, region_id)
    if region is None:
        raise HTTPException(status_code=404, detail="归属地不存在")
    caller = _resolve_caller(db, mobile) if mobile else None
    _require_region_manager(_caller_role(caller))
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        if region.standard_name not in allowed or region.standard_name in scope.PROTECTED_REGIONS:
            raise HTTPException(status_code=403, detail="只能删除本地市下面的归属地")
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
        "role": scope.normalize_role(item.role),
        "role_label": scope.role_label(item.role),
        "position": item.position,
        "receive_alert": item.receive_alert,
    }


def _caller_role(caller: Staff | None) -> str | None:
    return scope.normalize_role(caller.role) if caller is not None else None


def _caller_region(caller: Staff | None) -> str:
    return (caller.region_name or "").strip() if caller is not None else ""


def _guard_staff_write(db, caller_role, caller_region, region_name, role) -> None:
    """人员信息的写权限：普通人员不能改；地市管理员只能动本地市的人，
    而且不能给自己或别人提成省级管理员（那是省级的事）。

    参数刻意收成纯值而不是 ORM 对象：改自己的时候 caller 和 staff 是同一个对象，
    拿对象进来会在赋完新角色后把自己认成省级，直接放行。
    """
    if caller_role is None:
        return
    if scope.is_province(caller_role):
        return
    if not scope.is_city(caller_role):
        raise HTTPException(status_code=403, detail="普通人员不能修改人员信息")
    allowed = scope.caller_scope(db, caller_role, caller_region) or set()
    if (region_name or "").strip() not in allowed:
        raise HTTPException(status_code=403, detail="只能维护本地市的人员")
    if scope.is_province(role):
        raise HTTPException(status_code=403, detail="省级管理员只能由省级设置")


def _require_region_manager(caller_role: str | None) -> None:
    """归属地字典 / 钉钉群的写操作：省级和地市管理员才能动。"""
    if caller_role is None:
        return
    if not scope.can_manage_region(caller_role):
        raise HTTPException(status_code=403, detail="普通人员不能修改这类配置")


@router.get("/staff")
def list_staff(mobile: str = Query(""), db: Session = Depends(get_db)):
    """人员信息。省级管理员看全部，地市管理员只看本地市的，普通人员只看自己。"""
    items = db.query(Staff).order_by(Staff.id).all()
    caller = _resolve_caller(db, mobile)
    if caller is not None:
        if scope.is_province(caller.role):
            pass
        elif scope.is_city(caller.role):
            allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
            items = [item for item in items if (item.region_name or "").strip() in allowed]
        else:
            items = [item for item in items if item.mobile == caller.mobile]
    return [_staff_dict(item) for item in items]


@router.post("/staff")
def create_staff(payload: StaffIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    if db.query(Staff).filter(Staff.mobile == payload.mobile).first():
        raise HTTPException(status_code=400, detail="该手机号已存在")
    caller = _resolve_caller(db, mobile)
    _require_region_manager(_caller_role(caller))
    data = payload.model_dump()
    data["role"] = scope.normalize_role(data.get("role"))
    staff = Staff(**data)
    _guard_staff_write(db, _caller_role(caller), _caller_region(caller), staff.region_name, staff.role)
    db.add(staff)
    db.commit()
    return {"id": staff.id}


@router.put("/staff/{staff_id}")
def update_staff(staff_id: int, payload: StaffIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    caller = _resolve_caller(db, mobile)
    data = payload.model_dump()
    data["role"] = scope.normalize_role(data.get("role"))
    # 原来的归属地也要在作用域内，否则能把外地人「骗」进自己的列表
    caller_role, caller_region = _caller_role(caller), _caller_region(caller)
    _guard_staff_write(db, caller_role, caller_region, staff.region_name, staff.role)
    for key, value in data.items():
        setattr(staff, key, value)
    _guard_staff_write(db, caller_role, caller_region, data.get("region_name"), data.get("role"))
    db.commit()
    return {"ok": True}


@router.delete("/staff/{staff_id}")
def delete_staff(staff_id: int, mobile: str = Query(""), db: Session = Depends(get_db)):
    staff = db.get(Staff, staff_id)
    if staff is None:
        raise HTTPException(status_code=404, detail="人员不存在")
    caller = _resolve_caller(db, mobile)
    _guard_staff_write(db, _caller_role(caller), _caller_region(caller), staff.region_name, staff.role)
    db.delete(staff)
    db.commit()
    return {"ok": True}


@router.post("/staff/import")
async def import_staff(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """从 Excel 批量导入/更新人员。要求列：姓名、手机号、归属地。"""
    suffix = Path(file.filename or "staff.xlsx").suffix.lower() or ".xlsx"
    if suffix not in (".xlsx", ".xlsm", ".csv"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 或 .csv 文件")

    import pandas as pd

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(await file.read())
        temp_path = handle.name

    try:
        df = pd.read_excel(temp_path, dtype=str).fillna("")
    except Exception as exc:
        Path(temp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"读取文件失败：{exc}") from exc

    header = list(df.columns)
    name_col = next((c for c in header if "姓名" in c), header[0] if header else "")
    mobile_col = next((c for c in header if "手机" in c or "电话" in c), header[1] if len(header) > 1 else "")
    region_col = next((c for c in header if "归属" in c or "区域" in c or "地区" in c), header[2] if len(header) > 2 else "")
    role_col = next((c for c in header if "角色" in c), None)
    position_col = next((c for c in header if "职位" in c or "岗位" in c), None)

    normalizer = RegionNormalizer.from_db(db)
    created = 0
    updated = 0
    unknown_regions: set[str] = set()

    for _, row in df.iterrows():
        name = str(row.get(name_col, "")).strip()
        mobile = str(row.get(mobile_col, "")).strip()
        region_raw = str(row.get(region_col, "")).strip()
        if not name or not mobile:
            continue

        region_name = ""
        if region_raw:
            outcome = normalizer.normalize(region_raw)
            if outcome.ok:
                region_name = outcome.standard
            else:
                unknown_regions.add(region_raw)

        kwargs = {
            "name": name,
            "region_name": region_name,
            "role": str(row.get(role_col, "user")).strip() if role_col else "user",
            "position": str(row.get(position_col, "")).strip() if position_col else "",
        }

        existing = db.query(Staff).filter(Staff.mobile == mobile).first()
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(Staff(mobile=mobile, **kwargs))
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
def list_bots(mobile: str = Query(""), db: Session = Depends(get_db)):
    query = db.query(DingTalkBot)
    if mobile:
        caller = db.query(Staff).filter(Staff.mobile == mobile).first()
        if caller is not None and caller.role != "admin":
            # 按资源判断可见性：没被人勾过的群对所有人开放；
            # 一旦有人被勾上，就只有勾上的人能看到（跟界面上的说明一致）
            granted = select(ResourcePermission.resource_id).where(
                ResourcePermission.resource_type == "dingtalk_bot"
            )
            mine = select(ResourcePermission.resource_id).where(
                ResourcePermission.resource_type == "dingtalk_bot",
                ResourcePermission.mobile == mobile,
            )
            query = query.filter(or_(~DingTalkBot.id.in_(granted), DingTalkBot.id.in_(mine)))
    items = query.order_by(DingTalkBot.id).all()
    caller = _resolve_caller(db, mobile)
    if caller is not None and not scope.is_province(caller.role):
        # 地市管理员只看到本地市建的群；归属地为空的群是全省共用的，只给省级看
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        items = [item for item in items if (item.region_name or "").strip() in allowed]
    return [
        {
            "id": item.id,
            "name": item.name,
            "region_name": item.region_name,
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
def create_bot(payload: BotIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    if db.query(DingTalkBot).filter(DingTalkBot.name == payload.name).first():
        raise HTTPException(status_code=400, detail="该名称已存在")
    caller = _resolve_caller(db, mobile)
    _require_region_manager(_caller_role(caller))
    region_name = (payload.region_name or "").strip()
    if caller is not None and not scope.is_province(caller.role):
        # 地市管理员建的群自动挂到本地市，不能挂到别处，也不能建全省共用的群
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        if region_name not in allowed:
            region_name = caller.region_name
    bot = DingTalkBot(
        name=payload.name,
        region_name=region_name,
        webhook_enc=encrypt(payload.webhook),
        secret_enc=encrypt(payload.secret),
        is_active=payload.is_active,
    )
    db.add(bot)
    db.commit()
    return {"id": bot.id}


@router.put("/bots/{bot_id}")
def update_bot(bot_id: int, payload: BotIn, mobile: str = Query(""), db: Session = Depends(get_db)):
    bot = db.get(DingTalkBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    caller = _resolve_caller(db, mobile)
    _require_region_manager(_caller_role(caller))
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        if (bot.region_name or "").strip() not in allowed:
            raise HTTPException(status_code=403, detail="无权修改其他地市的钉钉群")
        if (payload.region_name or "").strip() not in allowed:
            raise HTTPException(status_code=403, detail="只能把群挂到本地市的归属地")
    bot.name = payload.name
    bot.region_name = (payload.region_name or "").strip()
    bot.is_active = payload.is_active
    # 前端回显的是脱敏值，只有真正改动时才覆盖
    if payload.webhook and "*" not in payload.webhook:
        bot.webhook_enc = encrypt(payload.webhook)
    if payload.secret and "*" not in payload.secret:
        bot.secret_enc = encrypt(payload.secret)
    db.commit()
    return {"ok": True}


@router.delete("/bots/{bot_id}")
def delete_bot(bot_id: int, mobile: str = Query(""), db: Session = Depends(get_db)):
    bot = db.get(DingTalkBot, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="机器人不存在")
    caller = _resolve_caller(db, mobile)
    _require_region_manager(_caller_role(caller))
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        if (bot.region_name or "").strip() not in allowed:
            raise HTTPException(status_code=403, detail="无权删除其他地市的钉钉群")
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
        f"#### 推送配置测试\n> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
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


# ---------------------------------------------------------------- 资源可见权限

@router.get("/permissions")
def list_permissions(
    resource_type: str = Query(...),
    resource_id: int = Query(...),
    db: Session = Depends(get_db),
):
    items = (
        db.query(ResourcePermission)
        .filter(
            ResourcePermission.resource_type == resource_type,
            ResourcePermission.resource_id == resource_id,
        )
        .all()
    )
    return [{"id": item.id, "mobile": item.mobile} for item in items]


@router.post("/permissions")
def grant_permissions(payload: PermissionGrantIn, db: Session = Depends(get_db)):
    """全量覆盖：传入的手机号列表即为该资源所有可见人员。"""
    resource_type = payload.resource_type
    resource_id = payload.resource_id

    # 校验资源是否存在
    if resource_type == "datasource":
        from ..models import DataSource
        if not db.get(DataSource, resource_id):
            raise HTTPException(status_code=404, detail="数据源不存在")
    elif resource_type == "dingtalk_bot":
        if not db.get(DingTalkBot, resource_id):
            raise HTTPException(status_code=404, detail="钉钉群不存在")
    else:
        raise HTTPException(status_code=400, detail="不支持的资源类型")

    # 删除旧的权限记录
    db.query(ResourcePermission).filter(
        ResourcePermission.resource_type == resource_type,
        ResourcePermission.resource_id == resource_id,
    ).delete()

    # 批量新增
    for mobile in payload.mobiles:
        if mobile.strip():
            db.add(
                ResourcePermission(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    mobile=mobile.strip(),
                )
            )
    db.commit()
    return {"ok": True, "count": len(payload.mobiles)}


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
