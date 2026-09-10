"""把报表渲染成 PNG 图片，供钉钉以图片形式推送。

钉钉自定义机器人的 markdown 支持 ![](图片地址)，但不支持表格，
所以「以图片形式发送」能把完整的表格排版原样发出去，手机上也不用左右滑动。

渲染要点：
  1. 标题 / 副标题 / 表头 / 数据行 / 页脚全部用 Pillow 画出来；
  2. 列宽按内容自适应，整图宽度有上限，超宽的列按比例压缩并截断；
  3. 默认按 2 倍尺寸渲染，在高分屏上不发虚。
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 中文字体候选，按优先级取第一个存在的
REGULAR_FONTS = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/PingFang.ttc",
]
BOLD_FONTS = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyhbd.ttf",
    *REGULAR_FONTS,
]

BG = "#FFFFFF"
TITLE_COLOR = "#16223A"
SUB_COLOR = "#7A879C"
HEAD_BG = "#2E4BD8"
HEAD_FG = "#FFFFFF"
ROW_ALT_BG = "#F6F8FC"
CELL_FG = "#243044"
LINE_COLOR = "#E4E9F2"
FOOT_COLOR = "#8A94A6"
ACCENT = "#2E4BD8"
HIT_COLOR = "#D93025"

_font_cache: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}
_measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (bold, int(size))
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    for path in (BOLD_FONTS if bold else REGULAR_FONTS):
        if not Path(path).exists():
            continue
        try:
            font = ImageFont.truetype(path, int(size))
        except OSError:
            continue
        _font_cache[key] = font
        return font
    font = ImageFont.load_default(size=int(size))
    _font_cache[key] = font
    return font


def font_available() -> bool:
    """有没有可用的中文字体；没有的话图片里的中文会变成方块。"""
    return any(Path(path).exists() for path in REGULAR_FONTS)


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _width(text: str, font) -> float:
    return _measure.textlength(text, font=font)


def _fit(text: str, font, limit: float) -> str:
    """把文本截断到 limit 宽度以内，超出部分用省略号。"""
    if limit <= 0:
        return ""
    if _width(text, font) <= limit:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _width(text[:mid] + "…", font) <= limit:
            low = mid
        else:
            high = mid - 1
    return text[:low] + "…"


def _is_number(value: str) -> bool:
    if value in ("", "-", "—", "/"):
        return False
    try:
        float(value.replace(",", "").replace("%", ""))
        return True
    except ValueError:
        return False


def _cell_color(row: dict, column: str, highlight: dict | None) -> str:
    """highlight = {field, op, value, color}，命中就标红。"""
    if not highlight:
        return CELL_FG
    if highlight.get("field") not in (None, "", column):
        return CELL_FG
    try:
        threshold = float(highlight.get("value"))
        current = float(_text(row.get(column)).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return CELL_FG
    op = highlight.get("op", ">")
    hit = {
        ">": current > threshold,
        ">=": current >= threshold,
        "<": current < threshold,
        "<=": current <= threshold,
        "=": current == threshold,
    }.get(op, False)
    if not hit:
        return CELL_FG
    return highlight.get("color") or HIT_COLOR


def default_subtitle(count: int, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"共 {count} 条 · 生成于 {now:%Y-%m-%d %H:%M}"


def render_report(
    title: str,
    rows: list[dict],
    columns: list[str],
    *,
    subtitle: str = "",
    highlight: dict | None = None,
    max_rows: int = 30,
    max_columns: int = 12,
    footer: str = "",
    max_width: int = 1000,
    min_width: int = 620,
    scale: int = 2,
) -> tuple[bytes, list[str]]:
    """把一批数据渲染成 PNG，返回 (图片字节, 提示信息)。"""
    warnings: list[str] = []
    scale = max(1, int(scale or 1))

    names = [name for name in (columns or []) if name]
    if not names and rows:
        names = list(rows[0].keys())
    if len(names) > max_columns:
        warnings.append(f"图片最多显示 {max_columns} 列，已省略 {len(names) - max_columns} 列")
        names = names[:max_columns]

    total = len(rows)
    if max_rows and total > max_rows:
        warnings.append(f"共 {total} 行，图片按设置只展示前 {max_rows} 行")
        rows = rows[:max_rows]

    if not font_available():
        warnings.append("服务器上没找到中文字体，图片里的中文可能显示成方块")

    f_title = _load_font(21 * scale, bold=True)
    f_sub = _load_font(12 * scale)
    f_head = _load_font(13 * scale, bold=True)
    f_cell = _load_font(13 * scale)
    f_foot = _load_font(11 * scale)

    pad = 28 * scale
    cell_pad = 12 * scale
    line_h = 34 * scale
    head_h = 38 * scale
    title_h = 30 * scale
    sub_h = 22 * scale
    max_col_w = 300 * scale
    min_col_w = 74 * scale

    body = [[_text(row.get(name)) for name in names] for row in rows]
    right_align: list[bool] = []
    for index in range(len(names)):
        values = [line[index] for line in body]
        right_align.append(bool(values) and all(_is_number(value) for value in values))

    widths: list[int] = []
    for index, name in enumerate(names):
        width = _width(name, f_head)
        for line in body:
            width = max(width, _width(line[index], f_cell))
        widths.append(int(min(max_col_w, width)) + cell_pad * 2)

    img_w_max = max_width * scale
    content_max = img_w_max - pad * 2
    if widths and sum(widths) > content_max:
        ratio = content_max / sum(widths)
        widths = [max(min_col_w, int(width * ratio)) for width in widths]
        if sum(widths) > content_max:
            ratio = content_max / sum(widths)
            widths = [max(40 * scale, int(width * ratio)) for width in widths]
        if sum(widths) > content_max:
            widths = [content_max // len(widths)] * len(widths)

    content_w = sum(widths)
    target_w = min(img_w_max, max(min_width * scale, content_w + pad * 2))
    if widths and content_w + pad * 2 < target_w:
        extra = target_w - pad * 2 - content_w
        add = extra // len(widths)
        widths = [width + add for width in widths]
        widths[-1] += extra - add * len(widths)
    img_w = pad * 2 + sum(widths)

    head_texts = [_fit(name, f_head, widths[i] - cell_pad * 2) for i, name in enumerate(names)]
    row_texts = [
        [_fit(value, f_cell, widths[i] - cell_pad * 2) for i, value in enumerate(line)]
        for line in body
    ]

    ascent_head, descent_head = f_head.getmetrics()
    ascent_cell, descent_cell = f_cell.getmetrics()
    cell_text_h = ascent_cell + descent_cell

    title_block = title_h + (sub_h if subtitle else 0) + 14 * scale
    table_top = pad + title_block
    row_count = max(1, len(rows))
    table_h = head_h + line_h * row_count
    footer_top = table_top + table_h + 12 * scale
    img_h = (footer_top + 20 * scale if footer else table_top + table_h) + pad

    image = Image.new("RGB", (img_w, img_h), BG)
    draw = ImageDraw.Draw(image)
    line_width = max(1, scale // 2)

    y = pad
    draw.rounded_rectangle(
        [pad, y + 3 * scale, pad + 5 * scale, y + title_h - 3 * scale],
        radius=2 * scale,
        fill=ACCENT,
    )
    draw.text(
        (pad + 16 * scale, y),
        _fit(title or "数据通报", f_title, img_w - pad * 2 - 16 * scale),
        font=f_title,
        fill=TITLE_COLOR,
    )
    y += title_h
    if subtitle:
        draw.text(
            (pad + 16 * scale, y),
            _fit(subtitle, f_sub, img_w - pad * 2 - 16 * scale),
            font=f_sub,
            fill=SUB_COLOR,
        )

    table_x = pad
    table_w = sum(widths)
    rows_top = table_top + head_h

    draw.rectangle([table_x, table_top, table_x + table_w, rows_top], fill=HEAD_BG)
    for index in range(row_count):
        if index % 2 == 1:
            row_y = rows_top + index * line_h
            draw.rectangle([table_x, row_y, table_x + table_w, row_y + line_h], fill=ROW_ALT_BG)

    for index in range(row_count + 1):
        line_y = rows_top + index * line_h
        draw.line([table_x, line_y, table_x + table_w, line_y], fill=LINE_COLOR, width=line_width)
    draw.line([table_x, rows_top, table_x + table_w, rows_top], fill=HEAD_BG, width=line_width)
    draw.line(
        [table_x, table_top, table_x + table_w, table_top],
        fill=HEAD_BG,
        width=line_width,
    )
    cursor = table_x
    for width in widths:
        draw.line(
            [cursor, table_top, cursor, rows_top + row_count * line_h],
            fill=LINE_COLOR,
            width=line_width,
        )
        cursor += width
    draw.line(
        [table_x + table_w, table_top, table_x + table_w, rows_top + row_count * line_h],
        fill=LINE_COLOR,
        width=line_width,
    )

    cursor = table_x
    head_text_y = table_top + (head_h - (ascent_head + descent_head)) / 2
    for index, text in enumerate(head_texts):
        draw.text((cursor + cell_pad, head_text_y), text, font=f_head, fill=HEAD_FG)
        cursor += widths[index]

    if row_texts:
        for row_index, line in enumerate(row_texts):
            text_y = rows_top + row_index * line_h + (line_h - cell_text_h) / 2
            cursor = table_x
            for index, value in enumerate(line):
                color = _cell_color(rows[row_index], names[index], highlight)
                if right_align[index]:
                    offset = cursor + widths[index] - cell_pad - _width(value, f_cell)
                else:
                    offset = cursor + cell_pad
                draw.text((offset, text_y), value, font=f_cell, fill=color)
                cursor += widths[index]
    else:
        hint = "（本次没有数据）"
        draw.text(
            (
                table_x + (table_w - _width(hint, f_cell)) / 2,
                rows_top + (line_h - cell_text_h) / 2,
            ),
            hint,
            font=f_cell,
            fill=SUB_COLOR,
        )

    if footer:
        draw.text(
            (table_x + (table_w - _width(footer, f_foot)) / 2, footer_top),
            footer,
            font=f_foot,
            fill=FOOT_COLOR,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), warnings
