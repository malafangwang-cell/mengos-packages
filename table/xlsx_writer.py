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
from model import DATE_FORMATS, NUMERIC, Table, aggregate_decimals, dec_str, hex_of, static_style
from render import display, formula_text, header, rule_text, totals_row

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
    g = "#,##0" if col.grouped else "0"
    if col.type == "date":
        return DATE_FORMATS[col.date_format or "YYYY-MM-DD"][0]
    if col.type == "integer":
        return g
    if col.type == "money":
        d = col.shown_decimals
        return g + ("." + "0" * d if d else "")
    if col.type == "percent":
        d = d if d is not None else _decimals_needed(values, scale=100)
        return g + ("." + "0" * d if d else "") + "%"
    if d is None:
        if col.grouped and col.type in NUMERIC:     # G5：number 列要千分位而没给小数位时，按数据实际的位数
            d = _decimals_needed(values, cap=10)
            return g + ("." + "0" * d if d else "")
        return None            # 常规
    return g + ("." + "0" * d if d else "")


def _style_props(st):
    p = {}
    if st.get("fill") is not None:
        p["bg_color"] = hex_of(st["fill"], "light", "fill")
    if st.get("color") is not None:
        p["font_color"] = hex_of(st["color"], "light", "color")
    for k in ("bold", "italic"):
        if k in st:
            p[k] = st[k]
    return p


def _style_key(st):
    return tuple(sorted(_style_props(st).items())) if st else ()


def _row_decimals(c):
    """公式列逐行舍入的位数（精度口径 b）；不舍入时为 None。Excel 公式外包一层 ROUND(…, 位数)，与产出台逐个相同。"""
    if c.type == "text":
        return None
    if c.type == "integer":
        return 0
    if c.decimals is None:
        return None
    return c.decimals + 2 if c.type == "percent" else c.decimals


def _guard(sh, keys, cell_of):
    """“有空就空”的 Excel 写法：数值、日期列用 COUNT(…)=n，文字列用 LEN(…)>0。"""
    kinds = {c.key: c.kind for c in sh.columns}
    nums = [cell_of(k) for k in keys if kinds[k] in ("num", "date")]
    txt = [cell_of(k) for k in keys if kinds[k] not in ("num", "date")]
    parts = ([f"COUNT({','.join(nums)})={len(nums)}"] if nums else []) + [f"LEN({x})>0" for x in txt]
    return parts[0] if len(parts) == 1 else f"AND({','.join(parts)})" if parts else None


def _formula_excel(sh, c, cell_of, agg_of, guard_needed):
    kinds = {x.key: x.kind for x in sh.columns}
    expr = F.to_excel(c.node, cell_of, kinds, agg_of)
    d = _row_decimals(c)
    if d is not None:
        expr = f"ROUND({expr},{d})"
    if "/" in expr:
        expr = f'IFERROR({expr},"")'
    if guard_needed:
        keys = [x.key for x in sh.columns if x.key in F.row_refs(c.node)]
        g = _guard(sh, keys, cell_of)
        if g:
            expr = f'IF({g},{expr},"")'
    return expr


def _cache(v):
    if v is None:
        return ""
    return v if isinstance(v, str) else _num(v)


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

    def fmt(kind, num=None, align=None, st=None):
        k = (kind, num, align, _style_key(st))
        if k not in cache:
            p = dict(base)
            if num:
                p["num_format"] = num
            if align:
                p["align"] = align
            if kind == "total":
                p.update({"bold": True, "top": 1})
            if kind == "head":
                p.update({"bold": True, "bg_color": "#F2F2EF", "bottom": 1, "text_wrap": True})
            if st:
                p.update(_style_props(st))
            cache[k] = wb.add_format(p)
        return cache[k]

    used = set()
    for sh in t.sheets:
        used.add(sh.name.lower())
        ws = wb.add_worksheet(sh.name)
        ncol, nrow = len(sh.columns), len(sh.rows)
        nums = [_num_format(c, [r[j] for r in sh.rows]) for j, c in enumerate(sh.columns)]
        hs = sh.header_style
        for j, c in enumerate(sh.columns):
            ws.write_string(0, j, header(c, lang), fmt("head", None, None, hs) if hs else f_head)
        col_of = {c.key: j for j, c in enumerate(sh.columns)}
        styled = any(sh.displays) or any(c.style for c in sh.columns)

        def agg_of(name, k, _i=None):
            col = xl_col_to_name(col_of[k])
            last = f"${col}${nrow + 1}" if name == "total" else f"${col}{_i + 1}"
            return f"SUM(${col}$2:{last})"
        guards = {}
        for j, c in enumerate(sh.columns):
            if c.formula is not None:
                ks = [col_of[k] for k in F.row_refs(c.node)]
                guards[j] = any(r[k] is None for r in sh.rows for k in ks)
        for i, r in enumerate(sh.rows, start=1):
            for j, (c, v) in enumerate(zip(sh.columns, r)):
                f = fmt("cell", nums[j], c.align, static_style(sh, i - 1, j) if styled else None)
                if c.formula is not None:
                    expr = _formula_excel(sh, c, lambda k, _i=i: xl_rowcol_to_cell(_i, col_of[k]),
                                          lambda name, k, _i=i: agg_of(name, k, _i), guards[j])
                    ws.write_formula(i, j, "=" + expr, f, _cache(v))
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
        ov = sh.styles() if (sh.row_styles or styled) else {"totals": {}}
        if tr is not None:
            tot = {k: (fn, v) for k, fn, v in sh.totals}
            row = nrow + 1
            for j, c in enumerate(sh.columns):
                tst = ov["totals"].get(j)
                if c.key in tot:
                    fn, v = tot[c.key]
                    rng = f"{xl_col_to_name(j)}2:{xl_col_to_name(j)}{nrow + 1}" if nrow else None
                    num = "#,##0" if fn == "count" else nums[j]
                    if fn == "avg" and c.type == "integer" and v is not None and v != v.to_integral_value():
                        num = "#,##0." + "0" * max(1, -v.normalize().as_tuple().exponent)
                    f = fmt("total", num, "right", tst)
                    if fn == "none":
                        ws.write_blank(row, j, None, f)
                    elif fn == "formula":
                        _total_formula(ws, sh, c, row, j, v, f, tot, col_of)
                    elif rng:
                        agg = f"{EXCEL_FN[fn]}({rng})"
                        d = None if fn == "count" else aggregate_decimals([x for x in sh.values(c.key) if isinstance(x, Decimal)], fn, c)
                        if isinstance(d, int) and not isinstance(d, bool):
                            agg = f"ROUND({agg},{d})"     # 精度口径 b：合计与产出台逐个相同（平均值等按位数舍入）
                        ws.write_formula(row, j, f"={agg}", f, "" if v is None else _num(v))
                    else:
                        ws.write_number(row, j, _num(v) if v is not None else 0, f)
                elif tr[j]:
                    ws.write_string(row, j, tr[j], fmt("total", None, "left", tst))
                else:
                    ws.write_blank(row, j, None, fmt("total", None, None, tst))
        if nrow and sh.rules:
            _rules(wb, ws, sh, col_of, nrow)
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


def _total_formula(ws, sh, c, row, j, v, f, tot, col_of):
    """G3：fn 为 formula 的合计格，写本列公式的合计行版本（引用合计行上各列的合计）。被引用的列没有合计时留空。"""
    keys = F.row_refs(c.node)
    if any(tot.get(k, (None,))[0] in (None, "none", "count") for k in keys):
        ws.write_blank(row, j, None, f)
        return
    cell_of = lambda k: xl_rowcol_to_cell(row, col_of[k])
    need = any(tot[k][1] is None for k in keys)
    ws.write_formula(row, j, "=" + _formula_excel(sh, c, cell_of, None, need), f, _cache(v))


def _ranges(cols, nrow):
    """列号 → Excel 范围（相邻的列并成一段），数据行 2..nrow+1。"""
    out, start = [], None
    for k, j in enumerate(cols):
        if start is None:
            start = j
        if k + 1 == len(cols) or cols[k + 1] != j + 1:
            out.append(f"{xl_col_to_name(start)}2:{xl_col_to_name(j)}{nrow + 1}")
            start = None
    return out


def _rules(wb, ws, sh, col_of, nrow):
    """G1：规则按次序写成条件格式（XlsxWriter 按添加次序定优先级，先加的优先），范围只含数据行。
    C2 退路：不写恒真规则；条件规则压过单元格的静态格式，与 Excel、LibreOffice 的默认相同。"""
    kinds = {c.key: c.kind for c in sh.columns}
    cell_of = lambda k: f"${xl_col_to_name(col_of[k])}2"

    def agg_of(name, k):
        col = xl_col_to_name(col_of[k])
        return f"SUM(${col}$2:${col}${nrow + 1})" if name == "total" else f"SUM(${col}$2:${col}2)"
    for r in sh.rules:
        if r["kind"] == "scale":
            key, a, b = r["scale"]
            rng = _ranges([col_of[key]], nrow)[0]
            ws.conditional_format(rng, {"type": "2_color_scale", "min_type": "min", "max_type": "max",
                                        "min_color": hex_of(a), "max_color": hex_of(b)})
            continue
        cols = list(range(len(sh.columns))) if r["apply"] == "row" else sorted(col_of[k] for k in r["apply"])
        rngs = _ranges(cols, nrow)
        cond = F.to_excel(r["node"], cell_of, kinds, agg_of)
        keys = [c.key for c in sh.columns if c.key in F.row_refs(r["node"])]
        g = _guard(sh, keys, cell_of)
        crit = f"AND({g},{cond})" if g else cond
        opts = {"type": "formula", "criteria": "=" + crit, "format": wb.add_format(_style_props(r["style"]))}
        if len(rngs) > 1:
            opts["multi_range"] = " ".join(rngs)
        ws.conditional_format(rngs[0], opts)


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
        for i, r in enumerate(sh.rules, start=1):
            lines.append((sh.name, f"规则 {i}：{rule_text(sh, r)}" + (f"（{r['label']}）" if r.get("label") else "")))
        if sh.rules:
            lines.append((sh.name, "规则按次序：先命中的先得，逐属性（底色、字色、加粗、斜体各算各的）；规则压过格、行、列上设的静态样式，"
                                   "与 Excel 一致。在 Excel 里手改被规则罩住的格的颜色看不出效果，要到“条件格式 → 管理规则”里改。"
                                   "LibreOffice 在两条规则同时命中同一格时只显示优先的那一条"))
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
