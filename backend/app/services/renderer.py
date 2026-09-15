"""消息模板渲染。

模板语法（保持极简，运营人员 5 分钟能学会）：

  {{字段名}}          取第一行的这个字段的值
  {{表格}}            把全部数据渲染成对齐文本块
  {{列表}}            每行一条数据
  {{#each}} ... {{/each}}   自定义循环，内部可用 {{字段名}}
  {{行数}} {{总数}}   数据行数（英文 count / rows 也可以）
  {{日期}} {{时间}}   渲染时刻（英文 date / time 也可以）

表格有三种呈现方式，规则里用「表格样式」选：

  code   包在代码块里的对齐文本，钉钉里按等宽显示，列一定对齐（默认）
  plain  按显示宽度对齐的纯文本，纯文本消息只能用这种
  md     GFM 表格语法 | a | b |，客户端不认时看到的是一行竖线
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

PLACEHOLDER = re.compile(r"\{\{\s*([^#/{}][^{}]*?)\s*\}\}")
EACH_BLOCK = re.compile(r"\{\{#each\}\}(.*?)\{\{/each\}\}", re.S)

BUILTIN_KEYS = {"行数", "日期", "时间", "表格", "列表"}

# {{表格}} 的呈现方式（规则 query.table_style）
TABLE_STYLES = ("code", "plain", "md")

# 运营人员偶尔会写成英文，这里做一层等价映射，避免模板报「字段不存在」
KEY_ALIASES = {
    "count": "行数",
    "rows": "行数",
    "rowcount": "行数",
    "total": "行数",
    "总数": "行数",
    "table": "表格",
    "list": "列表",
    "date": "日期",
    "time": "时间",
}


def display_width(text: str) -> int:
    """中文按 2 个宽度计算，用于对齐。"""
    width = 0
    for ch in str(text):
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def pad(text: str, width: int, align: str = "left") -> str:
    text = "" if text is None else str(text)
    space = max(0, width - display_width(text))
    if align == "right":
        return " " * space + text
    return text + " " * space


def _value(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def tidy_blank_lines(text: str) -> str:
    """占位符被压空后会留下多余空行，这里合并掉。"""
    lines = [line.rstrip() for line in text.splitlines()]
    kept: list[str] = []
    for line in lines:
        if not line and kept and not kept[-1]:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def render_template(
    template: str,
    rows: list[dict],
    columns: list[str] | None = None,
    highlight: dict | None = None,
    now: datetime | None = None,
    suppress_table: bool = False,
    table_style: str = "code",
) -> tuple[str, list[str]]:
    """渲染模板，返回 (文本, 告警列表)。

    suppress_table=True 时 {{表格}} / {{列表}} 渲染成空，用于「图片里已经有表格了，
    文字部分就不要再重复发一遍数据」的场景。
    table_style 决定 {{表格}} 长什么样，取值见 TABLE_STYLES。
    """
    now = now or datetime.now()
    warnings: list[str] = []
    columns = columns or (list(rows[0].keys()) if rows else [])
    first = rows[0] if rows else {}

    def build_context(row: dict | None) -> dict:
        data = row or {}
        return {
            "行数": str(len(rows)),
            "日期": now.strftime("%Y-%m-%d"),
            "时间": now.strftime("%H:%M"),
            "表格": "" if suppress_table else render_table(rows, columns, highlight, table_style),
            "列表": "" if suppress_table else render_list(rows, columns),
            "__row__": data,
        }

    context = build_context(first)

    def replace_in(text: str) -> str:
        def repl(match: re.Match) -> str:
            key = match.group(1).strip()
            if key in context:
                return context[key]
            alias = KEY_ALIASES.get(key.lower())
            if alias and alias in context:
                return context[alias]
            if key in (first or {}):
                return _value(first, key)
            warnings.append(f"模板里的 {{{{ {key} }}}} 在数据里找不到，已原样保留")
            return match.group(0)

        return PLACEHOLDER.sub(repl, text)

    # 先处理 each 块
    row_context = build_context(first)

    def each_repl(match: re.Match) -> str:
        body = match.group(1)
        parts = []
        for index, row in enumerate(rows, start=1):
            local = dict(context)
            local.update({k: _value(row, k) for k in row})
            local["序号"] = str(index)
            local["__row__"] = row
            text = body
            for key, value in local.items():
                if key.startswith("__"):
                    continue
                text = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", str(value), text)
            parts.append(text)
        return "".join(parts)

    rendered = EACH_BLOCK.sub(each_repl, template)
    rendered = replace_in(rendered)

    _ = row_context
    if suppress_table:
        rendered = tidy_blank_lines(rendered)
    return rendered.strip(), sorted(set(warnings))


def _highlight_cell(
    value: str,
    column: str,
    row: dict,
    highlight: dict | None,
    allow_html: bool = True,
) -> str:
    if not highlight:
        return value
    if highlight.get("field") not in (None, "", column):
        return value
    try:
        threshold = float(highlight.get("value"))
        current = float(str(row.get(column, "")).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return value
    op = highlight.get("op", ">")
    hit = {
        ">": current > threshold,
        ">=": current >= threshold,
        "<": current < threshold,
        "<=": current <= threshold,
        "=": current == threshold,
    }.get(op, False)
    if not hit:
        return value
    if not allow_html:
        # 代码块里 HTML 标签不会渲染，只会原样显示成源码，所以不加
        return value
    color = highlight.get("color") or "#FF0000"
    return f'<font color="{color}">{value}</font>'


def render_aligned_table(
    rows: list[dict],
    columns: list[str],
    highlight: dict | None = None,
    allow_html: bool = True,
) -> str:
    if not rows or not columns:
        return "（无数据）"

    header = [str(c) for c in columns]
    body = [[_value(row, c) for c in columns] for row in rows]

    widths = []
    for index, name in enumerate(header):
        width = display_width(name)
        for line in body:
            width = max(width, display_width(line[index]))
        widths.append(min(width, 24))

    lines = ["  ".join(pad(name, widths[i]) for i, name in enumerate(header))]
    lines.append("  ".join("-" * widths[i] for i in range(len(header))))
    for row, values in zip(rows, body):
        cells = []
        for index, value in enumerate(values):
            if display_width(value) > widths[index]:
                value = value[: widths[index] - 1] + "…"
            cells.append(
                _highlight_cell(
                    pad(value, widths[index]), columns[index], row, highlight, allow_html
                )
            )
        lines.append("  ".join(cells))
    return "\n".join(lines)


def _escape_cell(text: str) -> str:
    """Markdown 表格里的竖线和换行会撑破单元格，先转义掉。"""
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def render_markdown_table(
    rows: list[dict],
    columns: list[str],
    highlight: dict | None = None,
) -> str:
    """GFM 表格语法，能不能渲染成表格取决于钉钉客户端。"""
    if not rows or not columns:
        return "（无数据）"

    header = [_escape_cell(str(column)) or " " for column in columns]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        cells = []
        for column in columns:
            text = _escape_cell(_value(row, column)) or " "
            cells.append(_highlight_cell(text, column, row, highlight))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_table(
    rows: list[dict],
    columns: list[str],
    highlight: dict | None = None,
    style: str = "code",
) -> str:
    """按 table_style 渲染数据表格，取值见 TABLE_STYLES。"""
    style = str(style or "code").lower()
    if style not in TABLE_STYLES:
        style = "code"
    if style == "md":
        return render_markdown_table(rows, columns, highlight)
    if style == "plain":
        return render_aligned_table(rows, columns, highlight)
    # code：钉钉里等宽显示，列一定对齐；代码块内 HTML 不生效，标红要去掉
    body = render_aligned_table(rows, columns, highlight, allow_html=False)
    return f"```\n{body}\n```"


def resolve_table_style(msg_type: str, query_cfg: dict | None) -> str:
    """纯文本消息不做 markdown 渲染，代码块和表格语法都会原样显示，只能退化成对齐文本。"""
    if str(msg_type or "markdown").lower() == "text":
        return "plain"
    style = str((query_cfg or {}).get("table_style") or "code").lower()
    return style if style in TABLE_STYLES else "code"


def render_list(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "（无数据）"
    lines = []
    for index, row in enumerate(rows, start=1):
        parts = [f"**{column}** {_value(row, column)}" for column in columns]
        lines.append(f"{index}. " + " ｜ ".join(parts))
    return "\n".join(lines)


def default_template(title: str, columns: list[str], time_field: str = "") -> str:
    """根据所选字段生成一份模板初稿。"""
    time_line = f"> 统计时间：{{{{{time_field}}}}}\n" if time_field else ""
    return (
        f"#### {title}\n"
        f"{time_line}"
        f"\n{{{{表格}}}}\n"
        f"\n共 {{{{行数}}}} 条"
    )


def columns_from_rows(rows: list[dict]) -> list[str]:
    return list(rows[0].keys()) if rows else []
