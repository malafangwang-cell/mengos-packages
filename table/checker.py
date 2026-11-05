"""核对：内置核对 + 期望清单。每条 pass / fail / unknown，总判定取最差。

期望清单一行一条（# 开头为注释）。列名用列标题或 key，含空格时加引号（"…" 或 “…”）。
每条都可以加 sheet=表名（或表的 id），写在行首或行尾都行；也可以单独一行写 sheet=表名，管到下一个这样的行；都不写时核对第一张表。
  columns 列A 列B …                 这些列都在
  order 列A 列B …                   这些列按此顺序出现
  rows [min=N] [max=N]              行数（不含表头与合计）
  unique 列A [列B …]                这些列合起来每行不同（主键不重复）
  nonempty 列A [列B …] | *          这些列（* 为全部列）没有空格子
  range 列 [min=X] [max=Y]          数值都在范围内（百分比列写百分数）
  total 列 sum|avg|min|max|count=V [tol=T]   按数据算出的合计等于 V（误差不超过 T）
  sorted 列 [asc|desc]              按这一列排好序（空格子不计）
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from xlsxwriter.utility import xl_rowcol_to_cell

from model import NUMERIC, Table, aggregate, dec_str
from render import display

MAX_LINES = 300
KINDS = ("columns", "order", "rows", "unique", "nonempty", "range", "total", "sorted")
PLACEHOLDER = re.compile(r"待补|待定|待填|TODO|TBD|XXX|？？|\?\?|…{2,}|\.{6,}", re.IGNORECASE)
MAX_WHERE = 20


class ExpectError(Exception):
    def __init__(self, message, line, hint=None):
        super().__init__(message)
        self.message, self.line, self.hint = message, line, hint


def _tokens(s: str, line: int):
    """→ [(文字, 是否加了引号)]：加了引号的永远是列名，不当参数解析。"""
    out, i, n = [], 0, len(s)
    pairs = {'"': '"', "“": "”", "「": "」", "'": "'"}
    while i < n:
        if s[i].isspace():
            i += 1
            continue
        if s[i] in pairs:
            close = pairs[s[i]]
            j = s.find(close, i + 1)
            if j < 0:
                raise ExpectError(f"引号没有闭合：{s[i:i + 20]}", line)
            out.append((s[i + 1:j], True))
            i = j + 1
            continue
        j = i
        while j < n and not s[j].isspace():
            j += 1
        out.append((s[i:j], False))
        i = j
    return out


def _cell(sh, ri, j):
    return f"{sh.name}!{xl_rowcol_to_cell(ri + 1, j)}"


def _dec(s, line, what):
    try:
        d = Decimal(s.replace(",", ""))
    except InvalidOperation:
        raise ExpectError(f"{what} 应当是数：{s}", line) from None
    if not d.is_finite():
        raise ExpectError(f"{what} 应当是有限的数：{s}", line)
    return d


def builtin(t: Table):
    out = []
    for sh in t.sheets:
        if sh.formula_errors:
            where = [_cell(sh, e["row"], [c.key for c in sh.columns].index(e["column"])) for e in sh.formula_errors]
            out.append({"line": 0, "src": f"(内置) {sh.name}：公式没有除以零", "kind": "formula", "verdict": "fail",
                        "where": where[:MAX_WHERE], "actual": len(where), "reason": f"{len(where)} 格除以零，留空"})
        empty = [c for j, c in enumerate(sh.columns) if sh.rows and all(r[j] is None for r in sh.rows)]
        out.append({"line": 0, "src": f"(内置) {sh.name}：没有整列为空", "kind": "empty_column",
                    "verdict": "fail" if empty else "pass",
                    **({"where": [c.title for c in empty], "reason": "这些列一个值都没有"} if empty else {})})
        hits = []
        for ri, r in enumerate(sh.rows):
            for j, (c, v) in enumerate(zip(sh.columns, r)):
                if isinstance(v, str) and PLACEHOLDER.search(v):
                    hits.append(_cell(sh, ri, j))
        out.append({"line": 0, "src": f"(内置) {sh.name}：没有“待补”“TODO”之类占位", "kind": "placeholder",
                    "verdict": "fail" if hits else "pass",
                    **({"where": hits[:MAX_WHERE], "actual": len(hits)} if hits else {})})
    return out


def _parse(src: str, line: int):
    toks = _tokens(src, line)
    if not toks:
        return None
    # sheet= 写在行首也认（模型常这样写）：挪到核对项后面再解析
    lead = []
    while toks and not toks[0][1] and toks[0][0].startswith("sheet="):
        lead.append(toks.pop(0))
    if not toks:
        raise ExpectError("这一行只有 sheet=，缺核对项", line, "可用：" + "、".join(KINDS))  # 由 run_checks 先处理，这里兜底
    toks = toks[:1] + lead + toks[1:]
    kind, quoted = toks[0]
    if quoted or kind not in KINDS:
        raise ExpectError(f"不认识的核对项：{kind}", line, "可用：" + "、".join(KINDS))
    names, params, flags = [], {}, []
    for text, q in toks[1:]:
        if not q and "=" in text and text.split("=", 1)[0] in ("min", "max", "sheet", "tol", "sum", "avg", "count"):
            k, v = text.split("=", 1)
            if k in params:
                raise ExpectError(f"参数 {k} 写了两次", line)
            params[k] = v
        elif not q and kind == "sorted" and text in ("asc", "desc"):
            flags.append(text)
        elif not q and kind == "total" and "=" in text and text.split("=", 1)[0] in ("min", "max"):
            params[text.split("=", 1)[0]] = text.split("=", 1)[1]
        else:
            names.append(text)
    return kind, names, params, flags


def _sheet_of(t, params, line):
    if "sheet" not in params:
        return t.sheets[0], None
    want = params["sheet"]
    for sh in t.sheets:
        if sh.name == want or sh.id == want:
            return sh, None
    return None, f"没有名为“{want}”的表"


def _cols(sh, names):
    found, missing = [], []
    for n in names:
        c = sh.find(n)
        (found if c else missing).append(c or n)
    return found, missing


def run_checks(t: Table, expect):
    checks = builtin(t)
    assumptions = []
    if expect:
        lines = expect.splitlines()
        if len(lines) > MAX_LINES:
            raise ExpectError(f"期望清单最多 {MAX_LINES} 行", len(lines))
        current = None          # 单独一行 sheet=表名：之后各行默认核对这张表，直到下一个这样的行
        for no, raw in enumerate(lines, start=1):
            src = raw.strip()
            if not src or src.startswith("#"):
                continue
            toks = _tokens(src, no)
            if toks and all(not q and x.startswith("sheet=") for x, q in toks):
                if len(toks) > 1:
                    raise ExpectError("一行只能写一个 sheet=", no)
                current = toks[0][0].split("=", 1)[1]
                continue
            p = _parse(src, no)
            if p is None:
                continue
            if current is not None and "sheet" not in p[2]:
                p[2]["sheet"] = current
            checks.append(_one(t, no, src, *p))
    return checks, assumptions


def _one(t, line, src, kind, names, params, flags):
    base = {"line": line, "src": src, "kind": kind}
    sh, err = _sheet_of(t, params, line)
    if sh is None:
        return {**base, "verdict": "fail", "reason": err}
    lang = t.lang
    if kind == "rows":
        if names:
            raise ExpectError("rows 只写 min= / max=", line)
        if "min" not in params and "max" not in params:
            raise ExpectError("rows 至少写 min= 或 max=", line)
        n = len(sh.rows)
        lo = int(_dec(params["min"], line, "min")) if "min" in params else None
        hi = int(_dec(params["max"], line, "max")) if "max" in params else None
        ok = (lo is None or n >= lo) and (hi is None or n <= hi)
        return {**base, "verdict": "pass" if ok else "fail", "actual": n,
                "expected": {k: v for k, v in (("min", lo), ("max", hi)) if v is not None}}
    if kind == "nonempty" and names == ["*"]:
        cols, missing = list(sh.columns), []
    else:
        if not names:
            raise ExpectError(f"{kind} 后面要写列名", line)
        cols, missing = _cols(sh, names)
    if kind == "columns":
        return {**base, "verdict": "fail" if missing else "pass",
                **({"where": missing, "reason": "表里没有这些列"} if missing else {})}
    if missing:
        return {**base, "verdict": "fail", "where": missing, "reason": "表里没有这些列"}
    idx = [sh.columns.index(c) for c in cols]
    if kind == "order":
        ok = idx == sorted(idx)
        return {**base, "verdict": "pass" if ok else "fail",
                **({} if ok else {"actual": [sh.columns[j].title for j in sorted(idx)]})}
    if kind == "unique":
        seen, dup = {}, []
        for ri, r in enumerate(sh.rows):
            k = tuple(display(sh.columns[j], r[j], lang) for j in idx)
            if k in seen:
                dup.append(_cell(sh, ri, idx[0]))
            else:
                seen[k] = ri
        return {**base, "verdict": "fail" if dup else "pass",
                **({"where": dup[:MAX_WHERE], "actual": len(dup), "reason": "这些行与前面的行重复"} if dup else {})}
    if kind == "nonempty":
        empty = [_cell(sh, ri, j) for ri, r in enumerate(sh.rows) for j in idx if r[j] is None]
        return {**base, "verdict": "fail" if empty else "pass",
                **({"where": empty[:MAX_WHERE], "actual": len(empty)} if empty else {})}
    if len(cols) != 1:
        raise ExpectError(f"{kind} 只核对一列", line)
    c, j = cols[0], idx[0]
    vals = [r[j] for r in sh.rows]
    if kind == "range":
        if c.type not in NUMERIC:
            return {**base, "verdict": "fail", "reason": f"“{c.title}”不是数值列"}
        if "min" not in params and "max" not in params:
            raise ExpectError("range 至少写 min= 或 max=", line)
        scale = Decimal(100) if c.type == "percent" else Decimal(1)
        lo = _dec(params["min"], line, "min") / scale if "min" in params else None
        hi = _dec(params["max"], line, "max") / scale if "max" in params else None
        bad = [_cell(sh, ri, j) for ri, v in enumerate(vals)
               if v is not None and ((lo is not None and v < lo) or (hi is not None and v > hi))]
        if not any(v is not None for v in vals):
            return {**base, "verdict": "unknown", "reason": "这一列没有数值"}
        return {**base, "verdict": "fail" if bad else "pass",
                **({"where": bad[:MAX_WHERE], "actual": len(bad), "reason": "这些格子超出范围"} if bad else {})}
    if kind == "total":
        fns = [k for k in ("sum", "avg", "min", "max", "count") if k in params]
        if len(fns) != 1:
            raise ExpectError("total 写一个 sum= / avg= / min= / max= / count=", line, "例如：total 金额 sum=5000")
        fn = fns[0]
        if fn != "count" and c.type not in NUMERIC:
            return {**base, "verdict": "fail", "reason": f"“{c.title}”不是数值列"}
        scale = Decimal(100) if c.type == "percent" and fn != "count" else Decimal(1)
        want = _dec(params[fn], line, fn) / scale
        tol = _dec(params.get("tol", "0"), line, "tol") / scale
        got = aggregate(vals, fn, c) if fn == "count" else _exact(vals, fn)
        if got is None:
            return {**base, "verdict": "unknown", "reason": "这一列没有数值"}
        ok = abs(got - want) <= tol
        show = (lambda d: dec_str(d * scale))
        return {**base, "verdict": "pass" if ok else "fail", "expected": show(want), "actual": show(got)}
    if kind == "sorted":
        desc = "desc" in flags
        seq = [(ri, v) for ri, v in enumerate(vals) if v is not None]
        bad = []
        for (ra, a), (rb, b) in zip(seq, seq[1:]):
            if (a > b and not desc) or (a < b and desc):
                bad.append(_cell(sh, rb, j))
        return {**base, "verdict": "fail" if bad else "pass",
                **({"where": bad[:MAX_WHERE], "reason": "这些格子破坏了顺序"} if bad else {})}
    raise AssertionError(kind)


def _exact(vals, fn):
    nums = [v for v in vals if isinstance(v, Decimal)]
    if not nums:
        return None
    if fn == "sum":
        return sum(nums, Decimal(0))
    if fn == "avg":
        return sum(nums, Decimal(0)) / len(nums)
    return min(nums) if fn == "min" else max(nums)


def overall(checks):
    vs = [c["verdict"] for c in checks]
    return "fail" if "fail" in vs else "unknown" if "unknown" in vs else "pass"
