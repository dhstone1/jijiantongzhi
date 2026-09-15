"""角色与作用域。

三级角色：

  province_admin  省级管理员  全省范围，所有权限，负责配置地市管理员 / 普通人员的角色和归属地
  city_admin      地市管理员  只能查看和修改本地市（含下属区县）的规则、记录、人员、归属地、钉钉群
  user            普通人员    只能查看本地市的东西

作用域 = 自己归属地 + 全部下级归属地。层级靠 Region.parent 串起来
（河北省 → 邢台市 → 18 个区县），所以「邢台市管理员能看到襄都区的东西」不用额外配置，
往字典里加一个地市，它的管理员立刻就管到下属区县。
"""
from __future__ import annotations

from ..models import Region

ROLE_PROVINCE = "province_admin"
ROLE_CITY = "city_admin"
ROLE_USER = "user"

# 省级管理员挂在这个归属地上
PROVINCE_REGION = "河北省"

# 省级维护的顶层归属地，地市管理员不能改名 / 删除
PROTECTED_REGIONS = {PROVINCE_REGION, "邢台市"}

ROLE_LABELS = {
    ROLE_PROVINCE: "省级管理员",
    ROLE_CITY: "地市管理员",
    ROLE_USER: "普通人员",
}

# 菜单权限。省级管理员拿全部，所以不需要单列
MENU_DASHBOARD = "dashboard"
MENU_RULES = "rules"
MENU_LOGS = "logs"
MENU_BOTS = "bots"
MENU_REGIONS = "regions"
MENU_STAFF = "staff"
MENU_DATASOURCES = "datasources"
MENU_SETTINGS = "settings"

ALL_MENUS = [
    MENU_DASHBOARD,
    MENU_RULES,
    MENU_LOGS,
    MENU_DATASOURCES,
    MENU_BOTS,
    MENU_REGIONS,
    MENU_STAFF,
    MENU_SETTINGS,
]

# 地市管理员：本地的规则、记录、人员、归属地、钉钉群都能管；
# 数据源和系统设置是全省级的，不给他
CITY_MENUS = [MENU_DASHBOARD, MENU_RULES, MENU_LOGS, MENU_BOTS, MENU_REGIONS, MENU_STAFF]
# 普通人员：只看本地规则和记录
USER_MENUS = [MENU_DASHBOARD, MENU_RULES, MENU_LOGS]

ROLE_MENUS = {
    ROLE_PROVINCE: ALL_MENUS,
    ROLE_CITY: CITY_MENUS,
    ROLE_USER: USER_MENUS,
}


def normalize_role(role: str | None) -> str:
    """老库里 role 只有 admin / user，admin 按省级管理员算。"""
    value = (role or "").strip().lower()
    if value in ("admin", ROLE_PROVINCE, "province", "provinceadmin", "省级管理员"):
        return ROLE_PROVINCE
    if value in (ROLE_CITY, "city", "cityadmin", "地市管理员", "市级管理员"):
        return ROLE_CITY
    return ROLE_USER


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get(normalize_role(role), "普通人员")


def menus_of(role: str | None) -> list[str]:
    return list(ROLE_MENUS.get(normalize_role(role), USER_MENUS))


def is_province(role: str | None) -> bool:
    return normalize_role(role) == ROLE_PROVINCE


def is_city(role: str | None) -> bool:
    return normalize_role(role) == ROLE_CITY


def can_manage_region(role: str | None) -> bool:
    """能不能进「归属地字典 / 人员信息 / 钉钉群」这几个本地管理页面。"""
    return normalize_role(role) in (ROLE_PROVINCE, ROLE_CITY)


# ---------------------------------------------------------------- 归属地作用域

def children_map(regions: list[Region]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for item in regions:
        mapping.setdefault((item.parent or "").strip(), []).append(item.standard_name)
    return mapping


def scope_from(regions: list[Region], region_name: str) -> set[str]:
    """自己 + 全部下级的标准名。归属地为空则返回空集合（调用方按「不限」处理）。"""
    name = (region_name or "").strip()
    if not name:
        return set()

    by_parent = children_map(regions)
    result = {name}
    stack = [name]
    while stack:
        current = stack.pop()
        for child in by_parent.get(current, []):
            if child not in result:
                result.add(child)
                stack.append(child)
    return result


def active_regions(db) -> list[Region]:
    return (
        db.query(Region)
        .filter(Region.is_active.is_(True))
        .order_by(Region.sort_order, Region.id)
        .all()
    )


def caller_scope(db, role: str | None, region_name: str) -> set[str] | None:
    """返回调用者的可见归属地集合；None 表示不限（省级管理员）。"""
    if is_province(role):
        return None
    scope = scope_from(active_regions(db), region_name)
    return scope or {region_name or ""}


def region_filter_value(db, region_name: str) -> list[str] | str:
    """取数时的归属地过滤值。

    传「邢台市」就会展开成「邢台市 + 18 个区县」，所以地市级的规则能把
    下属区县的明细一起取出来；传区县就还是那一个区县。
    """
    name = (region_name or "").strip()
    if not name:
        return ""
    names = scope_from(active_regions(db), name)
    return sorted(names) if names else name


def can_see_region(scope: set[str] | None, region_name: str) -> bool:
    """这条数据（规则 / 人员 / 群）在调用者作用域内吗。归属地为空的只有省级能看。"""
    if scope is None:
        return True
    return bool(region_name) and region_name in scope
