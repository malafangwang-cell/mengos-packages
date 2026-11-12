"""派生视图：显示文字、产出台数据（view）、Markdown、CSV。全部由表模型确定性地派生。"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

from model import DATE_FORMATS, NUMERIC, Table, dec_str, hex_of, quantize

FN_LABEL = {"zh-CN": {"sum": "合计", "avg": "平均", "min": "最小", "max": "最大", "count": "计数", "formula": "按公式", "none": "留空"},
            "en": {"sum": "Total", "avg": "Average", "min": "Min", "max": "Max", "count": "Count", "formula": "By formula", "none": "Blank"}}


def dumps(obj) -> bytes:
    """文件里的 JSON：键序固定、非 ASCII 原样、两格缩进、末尾换行。"""
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def _group(int_part: str) -> str:
    neg = int_part.startswith("-")
    s = int_part[1:] if neg else int_part
    out = []
    while len(s) > 3:
        out.insert(0, s[-3:])
        s = s[:-3]
    out.insert(0, s)
    return ("-" if neg else "") + ",".join(out)


def fmt_num(v: Decimal, decimals, thousands: bool) -> str:
    q = quantize(v, decimals)
    s = format(q, "f") if decimals is not None else dec_str(q)
    if s in ("-0", ) or (s.startswith("-") and Decimal(s) == 0):
        s = s[1:]
    if thousands:
        ip, _, fp = s.partition(".")
        s = _group(ip) + ("." + fp if fp else "")
    return s


def display(col, v, lang="zh-CN", is_count=False) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return ("是" if v else "否") if lang != "en" else ("Yes" if v else "No")
    if isinstance(v, str):
        if col.type == "date" and col.date_format:
            y, m, d = (int(x) for x in v.split("-"))
            return DATE_FORMATS[col.date_format][1].format(y=y, m=m, d=d)
        return v
    if is_count:
        return fmt_num(v, 0, True)
    t = col.type
    if t == "integer":
        return fmt_num(v, 0, col.grouped)
    if t == "money":
        return fmt_num(v, col.shown_decimals, col.grouped)
    if t == "percent":
        return fmt_num(v * 100, col.decimals, col.grouped) + "%"
    return fmt_num(v, col.decimals, col.grouped)


def header(col, lang="zh-CN") -> str:
    if not col.unit:
        return col.title
    return f"{col.title}（{col.unit}）" if lang != "en" else f"{col.title} ({col.unit})"


def sort_key(col, v):
    """产出台排序用：数值给数，日期与文字给串，空值给 null。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, Decimal):
        return float(v)
    return v


def totals_row(sh, lang):
    """→ [显示文字]，或 None（没有合计）。第一列没有合计时放标签。"""
    if not sh.totals:
        return None
    by = {k: (fn, v) for k, fn, v in sh.totals}
    labels = FN_LABEL["en" if lang == "en" else "zh-CN"]
    out = []
    for c in sh.columns:
        if c.key in by:
            fn, v = by[c.key]
            if fn == "avg" and c.type == "integer" and v is not None:
                out.append(fmt_num(v, None, c.grouped))      # 整数列的平均值照实显示小数，不按整数取整
            else:
                out.append(display(c, v, lang, fn == "count"))
        else:
            out.append("")
    first = sh.columns[0].key
    if first not in by:
        fns = []
        for _, fn, _ in sh.totals:
            lab = labels["sum"] if fn in ("formula", "none") else labels[fn]   # 按公式、留空不单列标签
            if lab not in fns:
                fns.append(lab)
        out[0] = " / ".join(fns)
    return out


def totals_fn(sh):
    """合计行每一格的算法（G3）：sum / avg / min / max / count / formula / none，没有合计的格为 None。"""
    by = {k: fn for k, fn, _ in sh.totals}
    return [by.get(c.key) for c in sh.columns]


def formula_text(sh, col) -> str:
    """公式里的列 key 换成列标题，给人看。"""
    return expr_text(sh, col.formula, col)


def expr_text(sh, src, col=None) -> str:
    import formula as F
    s = ""
    for kind, val in F.tokenize(src):
        if kind == "id":
            c = sh.find(val)
            s += c.title if c is not None and c is not col else val
        elif kind == "op" and val in ("+", "-", "*", "/"):
            s += f" {({'*': '×', '/': '÷'}).get(val, val)} "
        elif kind == "cmp":
            s += f" {({'>=': '≥', '<=': '≤', '<>': '≠', '!=': '≠', '==': '='}).get(val, val)} "
        elif val == ",":
            s += ", "
        else:
            s += val
    return s


STYLE_WORDS = {"fill": "底", "color": "字"}


def style_text(st) -> str:
    parts = [f"{st[k]}{STYLE_WORDS[k]}" for k in ("fill", "color") if k in st]
    parts += [w for k, w in (("bold", "加粗"), ("italic", "斜体")) if st.get(k)]
    parts += [w for k, w in (("bold", "不加粗"), ("italic", "不斜体")) if st.get(k) is False]
    return "、".join(parts) or "无样式"


def rule_text(sh, r) -> str:
    """规则写成一句给人看的话（产出台说明区与 Excel 说明表共用）。"""
    title = {c.key: c.title for c in sh.columns}
    if r["kind"] == "scale":
        key, a, b = r["scale"]
        return f"{title[key]}：色阶，最小值{a} → 最大值{b}"
    where = "整行" if r["apply"] == "row" else "、".join(title[k] for k in r["apply"])
    return f"{expr_text(sh, r['src'])} → {where}{style_text(r['style'])}"


def view_style(st) -> dict:
    o = {}
    for k in ("fill", "color"):
        if k in st:
            o[k] = hex_of(st[k], "light", k)
            o[k + "_dark"] = hex_of(st[k], "dark", k)
    for k in ("bold", "italic"):
        if k in st:
            o[k] = st[k]
    return o


def _view_styles(sh, s):
    ov = sh.styles()
    table, index = [], {}

    def idx(st):
        v = view_style(st)
        key = json.dumps(v, sort_keys=True)
        if key not in index:
            index[key] = len(table)
            table.append(v)
        return index[key]
    cells = [[ri, j, idx(st)] for (ri, j), st in sorted(ov["cells"].items())]
    tots = [[j, idx(st)] for j, st in sorted(ov["totals"].items())] if sh.totals else []
    head = idx(ov["header"]) if ov["header"] else None
    if cells:
        s["cell_styles"] = cells
    if tots:
        s["totals_styles"] = tots
    if head is not None:
        s["header_style"] = head
    if table:
        s["styles"] = table
    if sh.rules:
        s["rules"] = [{"n": i + 1, "text": rule_text(sh, r), **({"label": r["label"]} if r.get("label") else {})}
                      for i, r in enumerate(sh.rules)]


def to_view(t: Table) -> dict:
    lang = t.lang
    sheets = []
    for sh in t.sheets:
        cols = [{"key": c.key, "title": c.title, "header": header(c, lang), "type": c.type, "align": c.align,
                 **({"unit": c.unit} if c.unit else {}), **({"formula": c.formula, "formula_display": formula_text(sh, c)} if c.formula else {})} for c in sh.columns]
        s = {"name": sh.name, "columns": cols,
             "rows": [[display(c, v, lang) for c, v in zip(sh.columns, r)] for r in sh.rows],
             "keys": [[sort_key(c, v) for c, v in zip(sh.columns, r)] for r in sh.rows]}
        tr = totals_row(sh, lang)
        if tr is not None:
            s["totals"] = tr
            fns = totals_fn(sh)
            if any(f not in (None, "sum") for f in fns) or any(fn != "sum" for _, fn, _ in sh.totals):
                s["totals_fn"] = fns
        _view_styles(sh, s)
        if sh.caption:
            s["caption"] = sh.caption
        if sh.note:
            s["note"] = sh.note
        if sh.freeze_cols:
            s["freeze_cols"] = sh.freeze_cols
        sheets.append(s)
    v = {"schema": "mengos.table.view/1", "title": t.title, "lang": lang, "sheets": sheets, "stats": t.stats(),
         "table_sha256": t.sha}
    if t.subtitle:
        v["subtitle"] = t.subtitle
    if t.meta:
        v["meta"] = dict(t.meta)
    if t.sources:
        v["sources"] = list(t.sources)
    if t.assumptions:
        v["assumptions"] = list(t.assumptions)
    return v


def _md_cell(s: str) -> str:
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def to_markdown(t: Table) -> str:
    lang = t.lang
    out = [f"# {_md_cell(t.title)}", ""]
    if t.subtitle:
        out += [t.subtitle, ""]
    meta = [t.meta.get(k) for k in ("org", "author", "date", "version") if t.meta.get(k)]
    if meta:
        out += [" · ".join(meta), ""]
    many = len(t.sheets) > 1
    for sh in t.sheets:
        if many:
            out += [f"## {_md_cell(sh.name)}", ""]
        if sh.caption:
            out += [f"**{_md_cell(sh.caption)}**", ""]
        out.append("| " + " | ".join(_md_cell(header(c, lang)) for c in sh.columns) + " |")
        out.append("|" + "|".join({"left": " --- ", "center": " :-: ", "right": " --: "}[c.align] for c in sh.columns) + "|")
        for r in sh.rows:
            out.append("| " + " | ".join(_md_cell(display(c, v, lang)) for c, v in zip(sh.columns, r)) + " |")
        tr = totals_row(sh, lang)
        if tr is not None:
            out.append("| " + " | ".join(f"**{_md_cell(x)}**" if x else "" for x in tr) + " |")
        out.append("")
        formulas = [c for c in sh.columns if c.formula]
        if formulas:
            label = "公式" if lang != "en" else "Formulas"
            out += [f"{label}：" + "；".join(f"{c.title} = {formula_text(sh, c)}" for c in formulas), ""]
        if sh.note:
            out += [sh.note, ""]
    if t.sources:
        out += ["来源：" if lang != "en" else "Sources:", ""] + [f"- {s}" for s in t.sources] + [""]
    if t.assumptions:
        out += ["假设：" if lang != "en" else "Assumptions:", ""] + [f"- {s}" for s in t.assumptions] + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def csv_value(col, v) -> str:
    """CSV 里放原值（不加千分位、不带百分号），便于程序读取；百分比列写百分数。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        # 以 = + - @ 开头的文字在表格软件里会被当成公式执行，前面加一个单引号（CSV 注入防护）
        return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
    if col.type == "percent":
        return dec_str(v * 100)
    if col.decimals is not None or col.type == "money":
        return fmt_num(v, col.shown_decimals, False)
    return dec_str(v)


def to_csv(sh, lang) -> bytes:
    """UTF-8 带 BOM（Excel 直接打开不乱码），CRLF 换行（RFC 4180）。不含合计行。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow([header(c, lang) + ("（%）" if lang != "en" else " (%)") if c.type == "percent" and not c.unit else header(c, lang)
                for c in sh.columns])
    for r in sh.rows:
        w.writerow([csv_value(c, v) for c, v in zip(sh.columns, r)])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
