"""表模型 → Excel（.xlsx），用 XlsxWriter。

确定性（TL-12 ②）：文档属性的创建时间写死（有 meta.date 就用它，否则 2000-01-01），
XlsxWriter 的 zip 内时间戳本身是固定值；同一个表模型两次写出逐字节相同。
公式列写成 Excel 公式并带算好的缓存值：Excel 打开可以重算，别的软件和预览直接看到值。
"""
from __future__ import annotations

import datetime as _dt
import io
import unicodedata
from decimal import Decimal

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name, xl_rowcol_to_cell

import formula as F
from model import NUMERIC, Table, dec_str
from render import display, formula_text, header, totals_row

EPOCH = _dt.datetime(2000, 1, 1)
EXCEL_FN = {"sum": "SUM", "avg": "AVERAGE", "min": "MIN", "max": "MAX", "count": "COUNTA"}
NOTES_NAME = {"zh-CN": "说明", "en": "Notes"}


def _num(v):
    """Decimal → 写进 xlsx 的数：整数写整数（缓存值显示 2501 而不是 2501.0）。"""
    return int(v) if v == v.to_integral_value() and abs(v) < 10 ** 15 else float(v)


def _width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _decimals_needed(values, cap=4, scale=1):
    need = 0
    for v in values:
        if isinstance(v, Decimal):
            s = dec_str(v * scale)
            if "." in s:
                need = max(need, len(s.split(".")[1]))
    return min(need, cap)


def _num_format(col, values):
    d = col.decimals
    if col.type == "integer":
        return "#,##0"
    if col.type == "money":
        d = col.shown_decimals
        return "#,##0" + ("." + "0" * d if d else "")
    if col.type == "percent":
        d = d if d is not None else _decimals_needed(values, scale=100)
        return "0" + ("." + "0" * d if d else "") + "%"
    if d is None:
        return None            # 常规
    return "0" + ("." + "0" * d if d else "")


def to_xlsx(t: Table) -> bytes:
    lang = t.lang
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False, "strings_to_formulas": False,
                                   "strings_to_urls": False, "default_date_format": "yyyy-mm-dd"})
    created = _dt.datetime.fromisoformat(t.meta["date"]) if t.meta.get("date") else EPOCH
    props = {"title": t.title, "created": created, "comments": "mengos table · " + t.sha[:16]}
    if t.subtitle:
        props["subject"] = t.subtitle
    if t.meta.get("author"):
        props["author"] = t.meta["author"]
    if t.meta.get("org"):
        props["company"] = t.meta["org"]
    wb.set_properties(props)
    base = {"font_name": "Microsoft YaHei" if lang != "en" else "Calibri", "font_size": 10.5, "valign": "vcenter"}
    f_head = wb.add_format({**base, "bold": True, "bg_color": "#F2F2EF", "bottom": 1, "text_wrap": True})
    cache = {}

    def fmt(kind, num=None, align=None):
        k = (kind, num, align)
        if k not in cache:
            p = dict(base)
            if num:
                p["num_format"] = num
            if align:
                p["align"] = align
            if kind == "total":
                p.update({"bold": True, "top": 1})
            cache[k] = wb.add_format(p)
        return cache[k]

    used = set()
    for sh in t.sheets:
        used.add(sh.name.lower())
        ws = wb.add_worksheet(sh.name)
        ncol, nrow = len(sh.columns), len(sh.rows)
        nums = [_num_format(c, [r[j] for r in sh.rows]) for j, c in enumerate(sh.columns)]
        for j, c in enumerate(sh.columns):
            ws.write_string(0, j, header(c, lang), f_head)
        col_of = {c.key: j for j, c in enumerate(sh.columns)}
        for i, r in enumerate(sh.rows, start=1):
            for j, (c, v) in enumerate(zip(sh.columns, r)):
                f = fmt("cell", "yyyy-mm-dd" if c.type == "date" else nums[j], c.align)
                if c.formula is not None:
                    expr = F.to_excel(c.node, lambda k, _i=i: xl_rowcol_to_cell(_i, col_of[k]))
                    if "/" in expr:
                        expr = f'IFERROR({expr},"")'
                    ws.write_formula(i, j, "=" + expr, f, "" if v is None else _num(v))
                elif v is None:
                    ws.write_blank(i, j, None, f)
                elif c.type in NUMERIC:
                    ws.write_number(i, j, _num(v), f)
                elif c.type == "date":
                    ws.write_datetime(i, j, _dt.datetime.fromisoformat(v), f)
                elif c.type == "bool":
                    ws.write_boolean(i, j, v, f)
                else:
                    ws.write_string(i, j, v, f)
        tr = totals_row(sh, lang)
        if tr is not None:
            tot = {k: (fn, v) for k, fn, v in sh.totals}
            row = nrow + 1
            for j, c in enumerate(sh.columns):
                if c.key in tot:
                    fn, v = tot[c.key]
                    rng = f"{xl_col_to_name(j)}2:{xl_col_to_name(j)}{nrow + 1}" if nrow else None
                    num = "#,##0" if fn == "count" else nums[j]
                    if fn == "avg" and c.type == "integer" and v is not None and v != v.to_integral_value():
                        num = "#,##0." + "0" * max(1, -v.normalize().as_tuple().exponent)
                    f = fmt("total", num, "right")
                    if rng:
                        ws.write_formula(row, j, f"={EXCEL_FN[fn]}({rng})", f, "" if v is None else _num(v))
                    else:
                        ws.write_number(row, j, _num(v) if v is not None else 0, f)
                elif tr[j]:
                    ws.write_string(row, j, tr[j], fmt("total", None, "left"))
                else:
                    ws.write_blank(row, j, None, fmt("total"))
        for j, c in enumerate(sh.columns):
            if c.width is not None:
                w = c.width
            else:
                texts = [header(c, lang)] + [display(c, r[j], lang) for r in sh.rows[:1000]]
                w = max(6, min(60, max(_width(x) for x in texts) + 2))
            ws.set_column(j, j, w)
        ws.freeze_panes(1, sh.freeze_cols)
        if nrow:
            ws.autofilter(0, 0, nrow, ncol - 1)
    _notes(wb, t, used, lang, f_head, fmt("cell", None, "left"))
    wb.close()
    return buf.getvalue()


def _notes(wb, t, used, lang, f_head, f_text):
    lines = []
    zh = lang != "en"
    if t.subtitle:
        lines.append(("副标题" if zh else "Subtitle", t.subtitle))
    for k, label in (("org", "单位" if zh else "Organization"), ("author", "作者" if zh else "Author"),
                     ("date", "日期" if zh else "Date"), ("version", "版本" if zh else "Version")):
        if t.meta.get(k):
            lines.append((label, t.meta[k]))
    for sh in t.sheets:
        if sh.caption:
            lines.append((sh.name, sh.caption))
        for c in sh.columns:
            if c.formula:
                lines.append((sh.name, f"{c.title} = {formula_text(sh, c)}"))
        if sh.note:
            lines.append((sh.name, sh.note))
    for s in t.sources:
        lines.append(("来源" if zh else "Source", s))
    for s in t.assumptions:
        lines.append(("假设" if zh else "Assumption", s))
    if not lines:
        return
    name, k = NOTES_NAME["zh-CN" if zh else "en"], 2
    base = name
    while name.lower() in used:
        name = f"{base}({k})"
        k += 1
    ws = wb.add_worksheet(name)
    ws.write_string(0, 0, "项目" if zh else "Item", f_head)
    ws.write_string(0, 1, t.title, f_head)
    for i, (a, b) in enumerate(lines, start=1):
        ws.write_string(i, 0, a, f_text)
        ws.write_string(i, 1, b, f_text)
    ws.set_column(0, 0, max(8, min(32, max(_width(a) for a, _ in lines) + 2)))
    ws.set_column(1, 1, 80)
