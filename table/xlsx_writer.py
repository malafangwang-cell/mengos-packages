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
from model import DATE_FORMATS, NUMERIC, SUBTOTAL_CODE, Table, aggregate_decimals, dec_str, hex_of, static_style
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
            if kind in ("group", "subtotal"):
                p.update({"bold": True})
            if kind == "head":
                p.update({"bold": True, "bg_color": "#F2F2EF", "bottom": 1, "text_wrap": True})
            if st:
                p.update(_style_props(st))
            cache[k] = wb.add_format(p)
        return cache[k]

    used = set()
    plans = {id(sh): _plan(sh) for sh in t.sheets}
    for sh in t.sheets:
        used.add(sh.name.lower())
        ws = wb.add_worksheet(sh.name)
        ncol, nrow = len(sh.columns), len(sh.rows)
        plan = plans[id(sh)]
        if plan["lines"] is not None:
            _write_layout_sheet(wb, ws, t, sh, plans, fmt, f_head, lang)
            continue
        nums = [_num_format(c, [r[j] for r in sh.rows]) for j, c in enumerate(sh.columns)]
        hs = sh.header_style
        for j, c in enumerate(sh.columns):
            ws.write_string(0, j, header(c, lang), fmt("head", None, None, hs) if hs else f_head)
        col_of = {c.key: j for j, c in enumerate(sh.columns)}
        styled = any(sh.displays) or any(c.style for c in sh.columns)

        def agg_of(name, k, _i=None, _key=None):
            if name in ("xagg", "sumif", "countif"):
                return _xsheet(t, plans, k, _key)
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
                                          lambda name, k, key=None, _i=i: agg_of(name, k, _i, key), guards[j])
                    ws.write_formula(i, j, "=" + expr, f, _cache(v))
                elif (i - 1, j) in sh.exprs:
                    ws.write_formula(i, j, "=" + _expr_excel(t, sh, plans, i - 1, j), f, _cache(v))
                elif (i - 1) in sh.derive_src and c.key in sh.derive_src[i - 1]:
                    _write_derived(ws, t, plans, sh, i - 1, j, i, f, v)
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


def _plan(sh):
    """每张表的数据行在 Excel 里的行号（0 起，表头是 0）。有分组、合并时另给显示次序 lines：[(行号, 条目)]。"""
    if not sh.has_layout():
        return {"pos": {ri: ri + 1 for ri in range(len(sh.rows))}, "lines": None, "last": len(sh.rows)}
    pos, lines = {}, []
    for k, e in enumerate(sh.layout, start=1):
        if e["kind"] == "data":
            pos[e["ri"]] = k
        lines.append((k, e))
    return {"pos": pos, "lines": lines, "last": len(lines)}


def _segments(rows):
    """Excel 行号（0 起）→ 连续的段 [(起, 止)]。"""
    out = []
    for r in sorted(rows):
        if out and r == out[-1][1] + 1:
            out[-1][1] = r
        else:
            out.append([r, r])
    return [tuple(x) for x in out]


def _qname(name):
    return "'" + name.replace("'", "''") + "'"


def _col_ranges(sheet_prefix, j, segs, absolute=True):
    col = xl_col_to_name(j)
    d = "$" if absolute else ""
    return [f"{sheet_prefix}{d}{col}{d}{a + 1}" if a == b else f"{sheet_prefix}{d}{col}{d}{a + 1}:{d}{col}{d}{b + 1}" for a, b in segs]


def _xsheet(t, plans, node, key):
    """跨表汇总（G10）的 Excel 写法：等值匹配的 SUMPRODUCT（不用 SUMIF：它把 * ? ~ 当通配符、把 > = 开头的文字当比较式）。"""
    tag = node[0]
    ref = node[2] if tag == "xagg" else node[1]
    o = next(x for x in t.sheets if x.id == ref[0])
    pos = plans[id(o)]["pos"]
    segs = _segments(pos.values())
    pre = _qname(o.name) + "!"
    jc = next(k for k, c in enumerate(o.columns) if c.key == ref[1])
    if not segs:
        return "0"
    cond = _col_ranges(pre, jc, segs)
    if tag == "xagg":
        return f"SUM({','.join(cond)})"
    if tag == "countif":
        return "+".join(f"SUMPRODUCT(--({r}={key}))" for r in cond)
    js = next(k for k, c in enumerate(o.columns) if c.key == node[3][1])
    sums = _col_ranges(pre, js, segs)
    return "+".join(f"SUMPRODUCT(--({r}={key}),{q})" for r, q in zip(cond, sums))


def _expr_excel(t, sh, plans, ri, j):
    """格公式（G17）：每格写它自己的公式。本表别行的格写 G2，别表的格写 '01立柱'!G2；引用的格有空时外包 IF(COUNT…)。"""
    src, node = sh.exprs[(ri, j)]
    pos = plans[id(sh)]["pos"]
    col_of = {c.key: k for k, c in enumerate(sh.columns)}

    def cell_of(x):
        if isinstance(x, tuple):
            o = t.book[x[1]]
            ref = xl_rowcol_to_cell(plans[id(o)]["pos"][x[2]], x[3])
            return ref if o is sh else _qname(o.name) + "!" + ref
        return xl_rowcol_to_cell(pos[ri], col_of[x])
    kinds = {c.key: c.kind for c in sh.columns}

    class K(dict):
        def __missing__(self, k):
            return t.book[k[1]].columns[k[3]].kind
    expr = F.to_excel(node, cell_of, K(kinds))
    cells = [x for x in F.cell_refs(node)] + [k for k in F.row_refs(node)]
    vals = [t.book[x[1]].rows[x[2]][x[3]] if isinstance(x, tuple) else sh.rows[ri][col_of[x]] for x in cells]
    if any(v is None for v in vals):
        expr = f'IF(COUNT({",".join(cell_of(x) for x in cells)})={len(cells)},{expr},"")'
    return expr


def _write_derived(ws, t, plans, sh, ri, j, row, f, v):
    """派生表的数（G10）：引用各来源格的求和公式，分部改了跟着变。"""
    srcs = sh.derive_src[ri][sh.columns[j].key]
    refs = []
    for o, sri, sj in srcs:
        if isinstance(o.rows[sri][sj], Decimal):
            refs.append(_qname(o.name) + "!" + xl_rowcol_to_cell(plans[id(o)]["pos"][sri], sj))
    if refs:
        ws.write_formula(row, j, "=" + "+".join(refs), f, _cache(v))
    else:
        ws.write_blank(row, j, None, f)


def _write_layout_sheet(wb, ws, t, sh, plans, fmt, f_head, lang):
    """有分组、小计、合并的表（G7、G9）：按显示次序写。组员设分级显示 1 级，合并掉的明细 2 级并折叠；
    小计、合计写 SUBTOTAL(…, 看得见的数据行)：合并掉的明细不算，合并行算，小计行本身被 SUBTOTAL 跳过。"""
    from render import layout_cells, layout_label_col
    plan = plans[id(sh)]
    pos, lines = plan["pos"], plan["lines"]
    nums = [_num_format(c, [r[j] for r in sh.rows]) for j, c in enumerate(sh.columns)]
    hs = sh.header_style
    for j, c in enumerate(sh.columns):
        ws.write_string(0, j, header(c, lang), fmt("head", None, None, hs) if hs else f_head)
    col_of = {c.key: j for j, c in enumerate(sh.columns)}
    styled = any(sh.displays) or any(c.style for c in sh.columns)
    data_segs = _segments(pos.values())
    guards = {}
    for j, c in enumerate(sh.columns):
        if c.formula is not None:
            ks = [col_of[k] for k in F.row_refs(c.node)]
            guards[j] = any(r[k] is None for r in sh.rows for k in ks)
    ws.outline_settings(True, False, True, False)
    eff_rows = {}
    for r, e in lines:
        if e["kind"] == "merged" or (e["kind"] == "data" and "detail" not in e):
            eff_rows.setdefault(e.get("group"), []).append(r)
    label_j = layout_label_col(sh)
    sub_fn = {x["column"]: x["fn"] for x in sh.subtotals}
    for r, e in lines:
        kind = e["kind"]
        if kind == "data":
            ri = e["ri"]
            level = 2 if "detail" in e else 1 if (e.get("group") is not None and not e.get("head")) else 0
            ws.set_row(r, None, None, {"level": level, "hidden": "detail" in e})
            for j, c in enumerate(sh.columns):
                v = sh.rows[ri][j]
                f = fmt("cell", nums[j], c.align, static_style(sh, ri, j) if styled else None)

                def agg_of(name, k, key=None, _r=r):
                    if name in ("xagg", "sumif", "countif"):
                        return _xsheet(t, plans, k, key)
                    segs = data_segs if name == "total" else [(a, min(b, _r)) for a, b in data_segs if a <= _r]
                    return "SUM(" + ",".join(_col_ranges("", col_of[k], segs)) + ")"     # cumsum：本行及以上的数据行
                if c.formula is not None:
                    expr = _formula_excel(sh, c, lambda k, _r=r: xl_rowcol_to_cell(_r, col_of[k]), agg_of, guards[j])
                    ws.write_formula(r, j, "=" + expr, f, _cache(v))
                elif (ri, j) in sh.exprs:
                    ws.write_formula(r, j, "=" + _expr_excel(t, sh, plans, ri, j), f, _cache(v))
                elif ri in sh.derive_src and c.key in sh.derive_src[ri]:
                    _write_derived(ws, t, plans, sh, ri, j, r, f, v)
                else:
                    _write_value(ws, r, j, c, v, f)
            continue
        kst = sh.row_styles.get(kind) if kind in ("subtotal", "group") else None
        if kind == "group":
            ws.set_row(r, None, None, {"level": 0})
            cells = layout_cells(sh, e, lang)
            for j, c in enumerate(sh.columns):
                f = fmt("group", None, "left" if j == label_j else c.align, kst)
                if cells[j]:
                    ws.write_string(r, j, cells[j], f)
                else:
                    ws.write_blank(r, j, None, f)
            continue
        if kind == "merged":
            m = sh.merged[e["mi"]]
            ws.set_row(r, None, None, {"level": 1 if e.get("group") is not None else 0, "collapsed": True})
            detail_rows = [pos[ri] for ri in m["members"]]
            for j, c in enumerate(sh.columns):
                v = e["values"][j]
                f = fmt("cell", nums[j], c.align, None)
                how = sh.merge_rows["agg"].get(c.key)
                if how == "formula":
                    expr = _formula_excel(sh, c, lambda k, _r=r: xl_rowcol_to_cell(_r, col_of[k]), None, any(
                        e["values"][col_of[k]] is None for k in F.row_refs(c.node)))
                    ws.write_formula(r, j, "=" + expr, f, _cache(v))
                elif how == "sum":
                    ws.write_formula(r, j, "=SUM(" + ",".join(xl_rowcol_to_cell(x, j) for x in detail_rows) + ")", f, _cache(v))
                else:
                    _write_value(ws, r, j, c, v, f)
            continue
        # 小计
        ws.set_row(r, None, None, {"level": 0})
        cells = layout_cells(sh, e, lang)
        segs = _segments(eff_rows.get(e.get("group"), []))
        for j, c in enumerate(sh.columns):
            fn = sub_fn.get(c.key)
            v = e["values"][j]
            num = "#,##0" if fn == "count" else nums[j]
            f = fmt("subtotal", num, "right" if fn else ("left" if j == label_j else c.align), kst)
            if fn == "formula":
                keys = F.row_refs(c.node)
                if any(sub_fn.get(k) in (None, "count") for k in keys):
                    ws.write_blank(r, j, None, f)
                else:
                    expr = _formula_excel(sh, c, lambda k, _r=r: xl_rowcol_to_cell(_r, col_of[k]), None,
                                          any(e["values"][col_of[k]] is None for k in keys))
                    ws.write_formula(r, j, "=" + expr, f, _cache(v))
            elif fn and segs:
                ws.write_formula(r, j, "=" + _subtotal(fn, j, segs, c, sh, e), f, _cache(v))
            elif cells[j] and not fn:
                ws.write_string(r, j, cells[j], f)
            else:
                ws.write_blank(r, j, None, f)
    last = plan["last"]
    tr = totals_row(sh, lang)
    ov = sh.styles() if (sh.row_styles or styled) else {"totals": {}}
    if tr is not None:
        tot = {k: (fn, v) for k, fn, v in sh.totals}
        row = last + 1
        segs = _segments([r for rows in eff_rows.values() for r in rows])
        for j, c in enumerate(sh.columns):
            tst = ov["totals"].get(j)
            if c.key in tot:
                fn, v = tot[c.key]
                num = "#,##0" if fn == "count" else nums[j]
                f = fmt("total", num, "right", tst)
                if fn == "none":
                    ws.write_blank(row, j, None, f)
                elif fn == "formula":
                    _total_formula(ws, sh, c, row, j, v, f, tot, col_of)
                elif segs:
                    ws.write_formula(row, j, "=" + _subtotal(fn, j, segs, c, sh, None), f, "" if v is None else _num(v))
                else:
                    ws.write_number(row, j, _num(v) if v is not None else 0, f)
            elif tr[j]:
                ws.write_string(row, j, tr[j], fmt("total", None, "left", tst))
            else:
                ws.write_blank(row, j, None, fmt("total", None, None, tst))
    if sh.rows and sh.rules:
        _rules(wb, ws, sh, col_of, len(sh.rows), _segments(pos.values()))
    for j, c in enumerate(sh.columns):
        if c.width is not None:
            w = c.width
        else:
            texts = [header(c, lang)] + [display(c, r[j], lang) for r in sh.rows[:1000]]
            w = max(6, min(60, max(_width(x) for x in texts) + 2))
        ws.set_column(j, j, w)
    ws.freeze_panes(1, sh.freeze_cols)
    ws.autofilter(0, 0, last, len(sh.columns) - 1)


def _subtotal(fn, j, segs, c, sh, e):
    """SUBTOTAL(代码, 看得见的数据行)；平均值等按合计的位数外包 ROUND（精度口径 b）。"""
    expr = f"SUBTOTAL({SUBTOTAL_CODE[fn]},{','.join(_col_ranges('', j, segs, absolute=False))})"
    if fn != "count":
        rows = sh.eff_rows() if e is None else [x["values"] if x["kind"] == "merged" else sh.rows[x["ri"]] for x in e["rows"]]
        d = aggregate_decimals([r[j] for r in rows if isinstance(r[j], Decimal)], fn, c)
        if isinstance(d, int) and not isinstance(d, bool):
            expr = f"ROUND({expr},{d})"
    return expr


def _write_value(ws, r, j, c, v, f):
    if v is None:
        ws.write_blank(r, j, None, f)
    elif isinstance(v, Decimal):
        ws.write_number(r, j, _num(v), f)
    elif c.type == "date":
        ws.write_datetime(r, j, _dt.datetime.fromisoformat(v), f)
    elif isinstance(v, bool):
        ws.write_boolean(r, j, v, f)
    else:
        ws.write_string(r, j, v, f)


def _total_formula(ws, sh, c, row, j, v, f, tot, col_of):
    """G3：fn 为 formula 的合计格，写本列公式的合计行版本（引用合计行上各列的合计）。被引用的列没有合计时留空。"""
    keys = F.row_refs(c.node)
    if any(tot.get(k, (None,))[0] in (None, "none", "count") for k in keys):
        ws.write_blank(row, j, None, f)
        return
    cell_of = lambda k: xl_rowcol_to_cell(row, col_of[k])
    need = any(tot[k][1] is None for k in keys)
    ws.write_formula(row, j, "=" + _formula_excel(sh, c, cell_of, None, need), f, _cache(v))


def _ranges(cols, nrow, segs=None):
    """列号 → Excel 范围（相邻的列并成一段），数据行 2..nrow+1；有分组时按数据行所在的段。"""
    segs = segs or [(1, nrow)]
    out, start = [], None
    for k, j in enumerate(cols):
        if start is None:
            start = j
        if k + 1 == len(cols) or cols[k + 1] != j + 1:
            for a, b in segs:
                out.append(f"{xl_col_to_name(start)}{a + 1}:{xl_col_to_name(j)}{b + 1}")
            start = None
    return out


def _rules(wb, ws, sh, col_of, nrow, segs=None):
    """G1：规则按次序写成条件格式（XlsxWriter 按添加次序定优先级，先加的优先），范围只含数据行。
    C2 退路：不写恒真规则；条件规则压过单元格的静态格式，与 Excel、LibreOffice 的默认相同。"""
    kinds = {c.key: c.kind for c in sh.columns}
    top = (segs[0][0] + 1) if segs else 2
    cell_of = lambda k: f"${xl_col_to_name(col_of[k])}{top}"

    def agg_of(name, k, key=None):
        col = xl_col_to_name(col_of[k])
        if segs:
            rngs = ",".join(f"${col}${a + 1}:${col}${b + 1}" for a, b in segs)
            return f"SUM({rngs})" if name == "total" else f"SUM(${col}${top}:${col}{top})"
        return f"SUM(${col}$2:${col}${nrow + 1})" if name == "total" else f"SUM(${col}$2:${col}2)"
    for r in sh.rules:
        if r["kind"] == "scale":
            key, a, b = r["scale"]
            rngs = _ranges([col_of[key]], nrow, segs)
            opts = {"type": "2_color_scale", "min_type": "min", "max_type": "max", "min_color": hex_of(a), "max_color": hex_of(b)}
            if len(rngs) > 1:
                opts["multi_range"] = " ".join(rngs)
            ws.conditional_format(rngs[0], opts)
            continue
        cols = list(range(len(sh.columns))) if r["apply"] == "row" else sorted(col_of[k] for k in r["apply"])
        rngs = _ranges(cols, nrow, segs)
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
