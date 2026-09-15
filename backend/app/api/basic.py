"""基础配置接口：身份识别、归属地字典、人员信息表、钉钉机器人、权限管理。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import IMAGE_DIR, IMAGE_URL_PREFIX, SERVER_PORT
from ..db import get_db
from ..models import DingTalkBot, Region, ResourcePermission, Staff
from ..schemas import BotIn, LoginIn, RegionIn, SettingsIn, StaffIn, PermissionGrantIn
from ..security import decrypt, encrypt, mask
from ..services import dingtalk, image_store, import_templates
from ..services import scope
from ..services.region_norm import DEFAULT_REGIONS, PARENT_CITY, RegionNormalizer

router = APIRouter()


def _xlsx_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            # 中文文件名要走 filename*，否则浏览器下来的名字是乱码
            "Content-Disposition": "attachment; filename=template.xlsx; filename*=UTF-8''%s"
            % quote(filename),
        },
    )


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

def _scope_options(db: Session, caller: Staff | None) -> list[str]:
    """模板「可选值」那一页列什么。按调用者的作用域给，免得填了导不进去。"""
    items = db.query(Region).filter(Region.is_active.is_(True)).order_by(Region.sort_order).all()
    if caller is not None and not scope.is_province(caller.role):
        allowed = scope.caller_scope(db, caller.role, caller.region_name) or set()
        items = [item for item in items if item.standard_name in allowed]
    return [item.standard_name for item in items]


@router.get("/templates/{kind}")
def download_template(kind: str, mobile: str = Query(""), db: Session = Depends(get_db)):
    """下载导入模板：kind 取 regions（归属地字典）或 staff（人员信息）。"""
    caller = _resolve_caller(db, mobile)
    _require_region_manager(_caller_role(caller), action="下载导入模板")
    options = _scope_options(db, caller)

    if kind in ("regions", "region"):
        # 示例行跟着当前作用域走：地市管理员看到的是自己市下面的区县
        parent = caller.region_name if (caller and not scope.is_province(caller.role)) else scope.PROVINCE_REGION
        content = import_templates.build_regions_template(options, parent=parent)
        return _xlsx_response(content, "归属地字典导入模板.xlsx")

    if kind in ("staff", "people"):
        content = import_templates.build_staff_template(
            options, region=caller.region_name if caller is not None else ""
        )
        return _xlsx_response(content, "人员信息导入模板.xlsx")

    raise HTTPException(status_code=404, detail="没有这种模板")


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


@router.post("/regions/import")
async def import_regions(
    file: UploadFile = File(...),
    mobile: str = Query(""),
    db: Session = Depends(get_db),
):
    """按「归属地字典导入模板」批量导入/更新归属地。

    认这些列（顺序无所谓，列名带关键字即可）：标准名、简称、上级归属地、级别、别名、排序。
    """
    caller = _resolve_caller(db, mobile)
    _require_region_manager(_caller_role(caller))

    df, header = _read_table(file)
    cols = _map_columns(header, {
        "standard": ("标准名", "归属地", "名称"),
        "short": ("简称", "短名"),
        "parent": ("上级", "父级"),
        "level": ("级别", "层级"),
        "aliases": ("别名", "其他写法"),
        "sort": ("排序", "顺序"),
    })
    if not cols.get("standard"):
        raise HTTPException(
            status_code=400,
            detail="没找到「标准名」列，请用「归属地字典」页面下载的模板填写",
        )

    caller_role = _caller_role(caller)
    allowed = scope.caller_scope(db, caller_role, _caller_region(caller))
    is_province = scope.is_province(caller_role)

    created = 0
    updated = 0
    skipped: list[str] = []

    for _, row in df.iterrows():
        standard = str(row.get(cols["standard"], "")).strip()
        if not standard:
            continue
        if standard == import_templates.EXAMPLE_REGION_NAME:
            # 模板自带的示例行，不用用户手动删
            continue
        if not is_province and standard in scope.PROTECTED_REGIONS:
            skipped.append(f"{standard}（不由本地市维护）")
            continue

        parent = str(row.get(cols.get("parent", ""), "")).strip() if cols.get("parent") else ""
        if not is_province and parent and parent not in (allowed or set()):
            skipped.append(f"{standard}（上级「{parent}」不在本地市范围内）")
            continue

        level = str(row.get(cols.get("level", ""), "")).strip() if cols.get("level") else ""
        if level and level not in ("省", "市", "区县"):
            level = ""
        if not level:
            level = "市" if parent in ("", scope.PROVINCE_REGION) else "区县"

        sort_raw = str(row.get(cols.get("sort", ""), "")).strip() if cols.get("sort") else ""
        try:
            sort_order = int(float(sort_raw))
        except (TypeError, ValueError):
            sort_order = None

        aliases = import_templates.split_aliases(
            str(row.get(cols.get("aliases", ""), "")) if cols.get("aliases") else ""
        )
        short = str(row.get(cols.get("short", ""), "")).strip() if cols.get("short") else ""

        item = db.query(Region).filter(Region.standard_name == standard).first()
        if item is None:
            if sort_order is None:
                sort_order = (db.query(func.max(Region.sort_order)).scalar() or 0) + 1
            db.add(
                Region(
                    standard_name=standard,
                    short_name=short,
                    parent=parent,
                    level=level,
                    aliases_json=json.dumps(aliases, ensure_ascii=False),
                    sort_order=sort_order,
                )
            )
            created += 1
            if not is_province:
                # 新建之后要立刻纳入作用域，否则同一份文件里它的下级会被判成越权
                allowed = (allowed or set()) | {standard}
            continue

        item.short_name = short or item.short_name
        if parent:
            item.parent = parent
        item.level = level
        item.aliases_json = json.dumps(aliases, ensure_ascii=False)
        if sort_order is not None:
            item.sort_order = sort_order
        updated += 1

    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped, "columns": header}


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


def _read_table(file: UploadFile) -> tuple["object", list[str]]:
    """把上传的 xlsx / csv 读成 DataFrame，返回 (df, 表头)。"""
    import pandas as pd

    suffix = Path(file.filename or "upload.xlsx").suffix.lower() or ".xlsx"
    if suffix not in (".xlsx", ".xlsm", ".csv"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 或 .csv 文件")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(file.file.read())
        temp_path = handle.name
    try:
        df = pd.read_excel(temp_path, dtype=str).fillna("")
    except Exception as exc:  # noqa: BLE001 - 解析失败就当作用户填错
        raise HTTPException(status_code=400, detail=f"读取文件失败：{exc}") from exc
    finally:
        Path(temp_path).unlink(missing_ok=True)
    return df, [str(c).strip() for c in df.columns]


def _map_columns(header: list[str], spec: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """把「这列其实是哪个字段」猜出来。列名里带关键字的算命中，顺序无所谓。"""
    mapping: dict[str, str] = {}
    for key, keywords in spec.items():
        hit = next((c for c in header if any(k in c for k in keywords)), "")
        if hit:
            mapping[key] = hit
    return mapping


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


def _require_region_manager(caller_role: str | None, action: str = "修改这类配置") -> None:
    """归属地字典 / 钉钉群的写操作：省级和地市管理员才能动。"""
    if caller_role is None:
        return
    if not scope.can_manage_region(caller_role):
        raise HTTPException(status_code=403, detail=f"普通人员不能{action}")


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
async def import_staff(
    file: UploadFile = File(...),
    mobile: str = Query(""),
    db: Session = Depends(get_db),
):
    """按「人员信息导入模板」批量导入/更新人员。

    认这些列（顺序无所谓）：姓名、手机号、归属地、角色、岗位、接收告警。
    手机号已存在的按新内容覆盖更新。
    """
    caller = _resolve_caller(db, mobile)
    _require_region_manager(_caller_role(caller), action="导入文件")

    df, header = _read_table(file)
    cols = _map_columns(header, {
        "name": ("姓名", "名字"),
        "mobile": ("手机", "电话"),
        "region": ("归属", "区域", "地区"),
        "role": ("角色", "身份"),
        "position": ("岗位", "职位"),
        "alert": ("接收告警", "接收提醒", "告警"),
    })
    if not cols.get("name") or not cols.get("mobile"):
        raise HTTPException(
            status_code=400,
            detail="没找到「姓名」或「手机号」列，请用「人员信息」页面下载的模板填写",
        )

    # 角色列可能写中文，也可能写 province_admin 这种英文
    role_words = {"省级管理员": scope.ROLE_PROVINCE, "地市管理员": scope.ROLE_CITY, "普通人员": scope.ROLE_USER}

    normalizer = RegionNormalizer.from_db(db)
    caller_role = _caller_role(caller)
    created = 0
    updated = 0
    unknown_regions: set[str] = set()
    skipped: list[str] = []

    for _, row in df.iterrows():
        name = str(row.get(cols["name"], "")).strip()
        mobile_value = str(row.get(cols["mobile"], "")).strip()
        if not name or not mobile_value:
            continue
        if name == import_templates.EXAMPLE_STAFF_NAME:
            # 模板自带的示例行，不用用户手动删
            continue

        region_raw = str(row.get(cols.get("region", ""), "")).strip() if cols.get("region") else ""
        region_name = ""
        if region_raw:
            outcome = normalizer.normalize(region_raw)
            if outcome.ok:
                region_name = outcome.standard
            else:
                unknown_regions.add(region_raw)
                continue

        role_raw = str(row.get(cols.get("role", ""), "")).strip() if cols.get("role") else ""
        role = role_words.get(role_raw) or scope.normalize_role(role_raw)
        alert_raw = str(row.get(cols.get("alert", ""), "")) if cols.get("alert") else ""

        kwargs = {
            "name": name,
            "region_name": region_name,
            "role": role,
            "position": str(row.get(cols.get("position", ""), "")).strip() if cols.get("position") else "",
            "receive_alert": import_templates.truthy(alert_raw, default=True),
        }

        try:
            # 作用域和角色越权在导入时同样要拦，不能绕过接口直接刷库
            _guard_staff_write(
                db,
                caller_role,
                _caller_region(caller),
                kwargs["region_name"],
                kwargs["role"],
            )
        except HTTPException as exc:
            skipped.append(f"{name}（{exc.detail}）")
            continue

        existing = db.query(Staff).filter(Staff.mobile == mobile_value).first()
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(Staff(mobile=mobile_value, **kwargs))
            created += 1

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "unknown_regions": sorted(unknown_regions),
        "skipped": skipped,
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
