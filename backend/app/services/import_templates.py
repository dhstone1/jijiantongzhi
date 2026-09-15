"""导入模板：给「归属地字典」和「人员信息」各生成一份能直接填的 xlsx。

每份模板两个工作表：
  1. 填数据的表 —— 表头就是导入时认的列名，下面给一行示例；
  2. 说明 —— 每列怎么填，外加当前能用的归属地清单（按调用者的作用域给），
     免得用户填完发现导不进去。
"""
from __future__ import annotations

from io import BytesIO

REGION_COLUMNS = ["标准名", "简称", "上级归属地", "级别", "别名", "排序"]
STAFF_COLUMNS = ["姓名", "手机号", "归属地", "角色", "岗位", "接收告警"]

# 模板里的示例行。用一眼就是假的名字，导入时按这两个名字跳过，
# 用户忘了删也不会变成脏数据。
EXAMPLE_REGION_NAME = "示例区"
EXAMPLE_REGION_SHORT = "示例"
EXAMPLE_STAFF_NAME = "示例人员"
EXAMPLE_STAFF_MOBILE = "13000000000"

REGION_HEADERS = ["字段", "说明"]
REGION_NOTES = [
    ["标准名", "必填。归属地的规范写法，例如「襄都区」「邢台市」"],
    ["简称", "选填。报表里常见的简写，例如「襄都」"],
    ["上级归属地", "选填。填「河北省」表示这是个地市；填地市名表示这是个区县；留空表示顶层"],
    ["级别", "选填。省 / 市 / 区县，留空按上级自动推断"],
    ["别名", "选填。同一个归属地的其他写法，多个用逗号分隔，例如「桥东区,桥东」"],
    ["排序", "选填。数字，越小越靠前；留空按现有顺序往后排"],
    ["", ""],
    ["注意", f"第 2 行是示例（{EXAMPLE_REGION_NAME}），导入时会自动跳过，不用手动删"],
]

STAFF_HEADERS = ["字段", "说明"]
STAFF_NOTES = [
    ["姓名", "必填"],
    ["手机号", "必填。既是登录凭据，也是钉钉 @ 人的号码；重复的手机号会被覆盖更新"],
    ["归属地", "选填。必须能在归属地字典里匹配到，匹配不上的会在导入结果里列出来"],
    ["角色", "选填。省级管理员 / 地市管理员 / 普通人员，留空按普通人员"],
    ["岗位", "选填"],
    ["接收告警", "选填。是 / 否，留空按「是」"],
    ["", ""],
    ["注意", f"第 2 行是示例（{EXAMPLE_STAFF_NAME}），导入时会自动跳过，不用手动删"],
]

def region_sample(parent: str) -> list:
    return [EXAMPLE_REGION_NAME, EXAMPLE_REGION_SHORT, parent, "区县", "示例新区,示例区", "99"]


def staff_sample(region: str = "") -> list:
    return [EXAMPLE_STAFF_NAME, EXAMPLE_STAFF_MOBILE, region, "普通人员", "网络运营", "是"]


def _write(sheets: list[tuple[str, list[list], list[int]]]) -> bytes:
    """sheets = [(表名, 行, 列宽), ...]"""
    import pandas as pd
    from openpyxl.utils import get_column_letter

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, rows, widths in sheets:
            # 第一行当表头，别让它变成一行数据（不然用户打开会觉得表头是数据）
            header = [str(cell) for cell in rows[0]]
            body = [
                [*row, *[""] * (len(header) - len(row))][: len(header)]
                for row in rows[1:]
            ]
            pd.DataFrame(body, columns=header).to_excel(writer, index=False, sheet_name=name)
            sheet = writer.sheets[name]
            for index, width in enumerate(widths, start=1):
                sheet.column_dimensions[get_column_letter(index)].width = width
    return buffer.getvalue()


def _widths(rows: list[list], minimum: int = 10, maximum: int = 46) -> list[int]:
    columns = max((len(row) for row in rows), default=1)
    result = []
    for index in range(columns):
        width = minimum
        for row in rows:
            text = str(row[index]) if index < len(row) else ""
            # 中文按两个字符宽度估
            width = max(width, sum(2 if ord(ch) > 127 else 1 for ch in text) + 3)
        result.append(min(width, maximum))
    return result


def build_regions_template(scope_options: list[str], parent: str = "") -> bytes:
    """scope_options 是「上级归属地」能填的值；parent 决定示例行怎么填。"""
    data = [REGION_COLUMNS, region_sample(parent)]
    notes = [REGION_HEADERS, *REGION_NOTES]
    options = [["上级归属地可选值", "说明"], *[[name, ""] for name in scope_options]]
    return _write(
        [
            ("归属地", data, _widths(data)),
            ("说明", notes, _widths(notes, maximum=70)),
            ("可选值", options, _widths(options, maximum=40)),
        ]
    )


def build_staff_template(scope_options: list[str], region: str = "") -> bytes:
    data = [STAFF_COLUMNS, staff_sample(region)]
    notes = [STAFF_HEADERS, *STAFF_NOTES]
    options = [["归属地可选值", "说明"], *[[name, ""] for name in scope_options]]
    return _write(
        [
            ("人员", data, _widths(data)),
            ("说明", notes, _widths(notes, maximum=70)),
            ("可选值", options, _widths(options, maximum=40)),
        ]
    )


def split_aliases(text: str) -> list[str]:
    """别名列支持中英文逗号、顿号、分号、竖线混着写。"""
    import re

    parts = re.split(r"[,，、;；|/]+", str(text or ""))
    return [part.strip() for part in parts if part.strip()]


def truthy(text: str, default: bool = True) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return default
    return value in ("是", "y", "yes", "true", "1", "开", "启用", "√")
