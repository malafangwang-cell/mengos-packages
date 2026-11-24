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

2.2.0（执行令 table 包 2.2.0 G11）：
  · unique 报出全部重复的行（每组重复的每一行、每个键格），不只报后一行；
  · 内置核对：有整行为空的行时判 pass，附一句提示（空行不算错）；
  · sheet=* 管整本工作簿：nonempty、range 逐表核；unique 把各表合起来查重（如图纸号不重号）；
  · 跨表两类，只读不写，表按 id 指定：
      match 列 sheet=目标表 key=键列[,键列] against=表[,表] [where=列:值]
          against 里符合 where 的每一行，在目标表里找同键的行比这一列；找不到或不等都报；
      sum_equal 列 sheet=目标表 from=表[,表] [by=键列[,键列]] [where=列:值]
          目标表这一列按键相加，等于来源表里符合 where 的行按键相加；不写 by 时比整列合计；
  · 每条问题写明 表、行、规则、现值、应值（problems）。核对不改表。
  · optional 列… [sheet=表|*]：这些列按规定可以整列为空（如分解单的“颜色1”），内置的“没有整列为空”不再报它们。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from xlsxwriter.utility import xl_rowcol_to_cell

import formula as F
from model import NUMERIC, LocateFail, Table, aggregate, cell_label, dec_str, locate, quantize, squash
from render import display

MAX_LINES = 300
KINDS = ("columns", "order", "rows", "unique", "nonempty", "range", "total", "sorted", "match", "sum_equal", "optional")
PARAMS = ("min", "max", "sheet", "tol", "sum", "avg", "count", "key", "against", "from", "by", "where")
MAX_PROBLEMS = 200
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


def builtin(t: Table, optional=None):
    optional = optional or {}
    out = []
    for sh in t.sheets:
        skip = optional.get("*", set()) | optional.get(sh.name, set()) | (optional.get(sh.id, set()) if sh.id else set())
        if sh.formula_errors:
            where = [_cell(sh, e["row"], [c.key for c in sh.columns].index(e["column"])) for e in sh.formula_errors]
            out.append({"line": 0, "src": f"(内置) {sh.name}：公式没有除以零", "kind": "formula", "verdict": "fail",
                        "where": where[:MAX_WHERE], "actual": len(where), "reason": f"{len(where)} 格除以零，留空"})
        empty = [c for j, c in enumerate(sh.columns) if sh.rows and all(r[j] is None for r in sh.rows)
                 and c.key not in skip and c.title not in skip and c.numbering is None]   # 编号列由工具编，可以整列为空
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
        blank = [ri for ri, r in enumerate(sh.rows) if all(v is None for c, v in zip(sh.columns, r) if c.formula is None and c.numbering is None)]
        if blank:      # 2.2.0：空行不算错，只提示（T2-03）；只在有空行时出这一条，原有各条的次序不变
            out.append({"line": 0, "src": f"(内置) {sh.name}：有没有整行为空的行", "kind": "empty_row", "verdict": "pass",
                        "where": [f"{sh.name} 第 {ri + 1} 行" for ri in blank[:MAX_WHERE]], "actual": len(blank),
                        "reason": f"有 {len(blank)} 行整行为空（还没填）；空行不计入合计，不算错"})
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
        if not q and "=" in text and text.split("=", 1)[0] in PARAMS:
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
    return _find_sheet(t, want)


def _find_sheet(t, want):
    for sh in t.sheets:
        if sh.name == want or sh.id == want:
            return sh, None
    return None, f"没有名为“{want}”的表"


def _norm_text(v):
    import unicodedata
    return unicodedata.normalize("NFKC", str(v)).strip()


def _where_filter(sh, spec, line):
    """where=列:值（文字按 NFKC 去首尾空白比）。"""
    if spec is None:
        return lambda r: True
    if ":" not in spec:
        raise ExpectError("where 写成 列:值，例如 where=产品角色:五金", line)
    name, want = spec.split(":", 1)
    c = sh.find(name)
    if c is None:
        return None
    j = sh.columns.index(c)
    return lambda r: r[j] is not None and _norm_text(display(c, r[j])) == _norm_text(want)


def _key_of(sh, cols, r):
    return tuple(None if r[sh.columns.index(c)] is None else _norm_text(display(c, r[sh.columns.index(c)])) for c in cols)


def _prob(sh, ri, rule, actual, expected, col=None):
    o = {"sheet": sh.name, "row": ri + 1, "rule": rule}
    if col is not None:
        o["cell"] = _cell(sh, ri, sh.columns.index(col))
    o["actual"] = actual
    if expected is not None:
        o["expected"] = expected
    return o


def _cols(sh, names):
    found, missing = [], []
    for n in names:
        c = sh.find(n)
        (found if c else missing).append(c or n)
    return found, missing


def _optional(t, expect):
    """先扫一遍期望清单里的 optional 行：哪些列可以整列为空。"""
    out = {}
    current = None
    for no, raw in enumerate((expect or "").splitlines(), start=1):
        src = raw.strip()
        if not src or src.startswith("#") or src.startswith("cell ") or src.startswith("text "):
            continue
        toks = _tokens(src, no)
        if toks and all(not q and x.startswith("sheet=") for x, q in toks):
            current = toks[0][0].split("=", 1)[1] if len(toks) == 1 else current
            continue
        p = _parse(src, no)
        if p is None or p[0] != "optional":
            continue
        kind, names, params, _ = p
        if not names:
            raise ExpectError("optional 后面要写列名", no)
        sheet = params.get("sheet", current)
        if sheet is None:
            sheet = t.sheets[0].id or t.sheets[0].name
        out.setdefault(sheet, set()).update(names)
        for sh in t.sheets:
            for n in names:
                c = sh.find(n)
                if c is not None and (sheet == "*" or sheet in (sh.name, sh.id)):
                    out.setdefault(sh.name, set()).add(c.key)
    return out


def run_checks(t: Table, expect):
    checks = builtin(t, _optional(t, expect) if expect and len(expect.splitlines()) <= MAX_LINES else None)
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
            src, hint = split_hint(src)     # r20（补一 D3）：行尾“# 提示：……”是作者写的提示，不是核对项的一部分
            if src.startswith("cell ") or src.startswith("text "):
                checks.append(_cell_check(t, no, src, hint))
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
            c = _one(t, no, src, *p)
            if hint is not None:
                c["hint"] = hint
            checks.append(c)
    return checks, assumptions


def _one(t, line, src, kind, names, params, flags):
    base = {"line": line, "src": src, "kind": kind}
    if kind == "optional":
        return {**base, "verdict": "pass", "reason": "这些列按规定可以整列为空：" + "、".join(names)}
    if params.get("sheet") == "*":
        return _whole_book(t, line, src, kind, names, params, flags, base)
    if kind in ("match", "sum_equal"):
        return _cross(t, line, src, kind, names, params, base)
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
        return _unique(base, [(sh, ri, r) for ri, r in enumerate(sh.rows)], [(sh, idx)], lang)
    if kind == "nonempty":
        empty = [(ri, j) for ri, r in enumerate(sh.rows) for j in idx if r[j] is None]
        return {**base, "verdict": "fail" if empty else "pass",
                **({"where": [_cell(sh, ri, j) for ri, j in empty][:MAX_WHERE], "actual": len(empty),
                    "problems": [_prob(sh, ri, f"nonempty {sh.columns[j].title}", None, "不为空", sh.columns[j])
                                 for ri, j in empty][:MAX_PROBLEMS]} if empty else {})}
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


def _unique(base, rows, idx_of, lang, skip_empty=False):
    """rows：[(表, 行号, 行)]；idx_of：[(表, 键列序号)]。报出每组重复的每一行、每个键格（2.2.0 G11）。"""
    idx = {id(sh): ix for sh, ix in idx_of}
    groups, order = {}, []
    for sh, ri, r in rows:
        k = tuple(_norm_text(display(sh.columns[j], r[j], lang)) for j in idx[id(sh)])
        if skip_empty and all(x == "" for x in k):
            continue                 # 整本查重时，键全空的行不算重复（如还没编图纸号的标准件）
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append((sh, ri))
    dups = [groups[k] for k in order if len(groups[k]) > 1]
    if not dups:
        return {**base, "verdict": "pass"}
    where, probs = [], []
    for g in dups:
        names = "、".join(f"{s.name} 第 {ri + 1} 行" for s, ri in g)
        for s, ri in g:
            where += [_cell(s, ri, j) for j in idx[id(s)]]
            probs.append(_prob(s, ri, base["src"], f"与{names}重复", "不重复"))
    return {**base, "verdict": "fail", "where": where[:MAX_WHERE], "actual": sum(len(g) for g in dups),
            "reason": f"{len(dups)} 组重复，共 {sum(len(g) for g in dups)} 行", "problems": probs[:MAX_PROBLEMS]}


def _whole_book(t, line, src, kind, names, params, flags, base):
    """sheet=* ：nonempty、range 逐表核（有这几列的表）；unique 把各表合起来查重。"""
    if kind not in ("nonempty", "range", "unique"):
        raise ExpectError(f"sheet=* 只用于 nonempty、range、unique", line)
    if not names:
        raise ExpectError(f"{kind} 后面要写列名", line)
    targets = [(sh, [sh.find(n) for n in names]) for sh in t.sheets]
    targets = [(sh, cs) for sh, cs in targets if all(c is not None for c in cs)]
    if not targets:
        return {**base, "verdict": "fail", "where": names, "reason": "没有哪张表有这些列"}
    if kind == "unique":
        rows = [(sh, ri, r) for sh, _ in targets for ri, r in enumerate(sh.rows)]
        return _unique(base, rows, [(sh, [sh.columns.index(c) for c in cs]) for sh, cs in targets], t.lang, skip_empty=True)
    results = []
    for sh, cs in targets:
        p = dict(params)
        p["sheet"] = sh.id or sh.name
        results.append(_one(t, line, src, kind, [c.key for c in cs], p, flags))
    verdict = "fail" if any(r["verdict"] == "fail" for r in results) else "unknown" if any(r["verdict"] == "unknown" for r in results) else "pass"
    out = {**base, "verdict": verdict, "actual": {r_sh.name: r["verdict"] for (r_sh, _), r in zip(targets, results)}}
    where = [w for r in results for w in r.get("where", [])]
    probs = [p for r in results for p in r.get("problems", [])]
    if where:
        out["where"] = where[:MAX_WHERE]
    if probs:
        out["problems"] = probs[:MAX_PROBLEMS]
    return out


def _cross(t, line, src, kind, names, params, base):
    """跨表两类（G11）：match 按键比一列；sum_equal 比按键之和。表按 id（或表名）指定。"""
    if len(names) != 1:
        raise ExpectError(f"{kind} 核对一列：{kind} 列 sheet=目标表 …", line)
    if "sheet" not in params:
        raise ExpectError(f"{kind} 要写 sheet=目标表", line)
    tgt, err = _find_sheet(t, params["sheet"])
    if tgt is None:
        return {**base, "verdict": "fail", "reason": err}
    src_key = "against" if kind == "match" else "from"
    if src_key not in params:
        raise ExpectError(f"{kind} 要写 {src_key}=表[,表]", line)
    others = []
    for x in params[src_key].split(","):
        o, err = _find_sheet(t, x.strip())
        if o is None:
            return {**base, "verdict": "fail", "reason": err}
        others.append(o)
    col_name = names[0]
    tc = tgt.find(col_name)
    if tc is None:
        return {**base, "verdict": "fail", "where": [col_name], "reason": f"“{tgt.name}”里没有这一列"}
    keys = [x.strip() for x in params.get("key" if kind == "match" else "by", "").split(",") if x.strip()]
    if kind == "match" and not keys:
        raise ExpectError("match 要写 key=键列", line)
    probs = []
    tkeys = [tgt.find(k) for k in keys]
    if any(c is None for c in tkeys):
        return {**base, "verdict": "fail", "where": keys, "reason": f"“{tgt.name}”里没有这些键列"}
    tj = tgt.columns.index(tc)
    show = lambda c, v: None if v is None else display(c, v)
    if kind == "match":
        index = {}
        for ri, r in enumerate(tgt.rows):
            index.setdefault(_key_of(tgt, tkeys, r), []).append(ri)
        for o in others:
            oc, okeys = o.find(col_name), [o.find(k) for k in keys]
            flt = _where_filter(o, params.get("where"), line)
            if oc is None or any(c is None for c in okeys) or flt is None:
                return {**base, "verdict": "fail", "reason": f"“{o.name}”里没有“{col_name}”、键列或 where 的列"}
            oj = o.columns.index(oc)
            for ri, r in enumerate(o.rows):
                if not flt(r):
                    continue
                k = _key_of(o, okeys, r)
                hits = index.get(k, [])
                label = "、".join(x or "" for x in k)
                if not hits:
                    probs.append(_prob(tgt, -1, base["src"], f"“{tgt.name}”里没有“{label}”", f"{show(oc, r[oj])}（{o.name} 第 {ri + 1} 行）"))
                    probs[-1].pop("row")
                    continue
                for h in hits:
                    if tgt.rows[h][tj] != r[oj]:
                        probs.append(_prob(tgt, h, base["src"], show(tc, tgt.rows[h][tj]), f"{show(oc, r[oj])}（{o.name} 第 {ri + 1} 行）", tc))
    else:
        bkeys = tkeys

        def sums(sh, col, ks, flt):
            out = {}
            j = sh.columns.index(col)
            for ri, r in enumerate(sh.rows):
                if flt is not None and not flt(r):
                    continue
                k = _key_of(sh, ks, r)
                v = r[j]
                acc = out.setdefault(k, [Decimal(0), []])
                if isinstance(v, Decimal):
                    acc[0] += v
                acc[1].append(ri)
            return out
        if tc.type not in NUMERIC:
            return {**base, "verdict": "fail", "reason": f"“{tc.title}”不是数值列"}
        got = sums(tgt, tc, bkeys, None)
        want = {}
        for o in others:
            oc, oks = o.find(col_name), [o.find(k) for k in keys]
            flt = _where_filter(o, params.get("where"), line)
            if oc is None or any(c is None for c in oks) or flt is None:
                return {**base, "verdict": "fail", "reason": f"“{o.name}”里没有“{col_name}”、键列或 where 的列"}
            for k, (v, _) in sums(o, oc, oks, flt).items():
                want[k] = want.get(k, Decimal(0)) + v
        for k in list(dict.fromkeys(list(got) + list(want))):
            a = got.get(k, [Decimal(0), []])
            w = want.get(k, Decimal(0))
            if a[0] != w:
                label = "、".join(x or "" for x in k) or "整列合计"
                p = _prob(tgt, a[1][0] if a[1] else -1, base["src"], f"{label}：{dec_str(a[0])}", f"{dec_str(w)}（{'、'.join(o.name for o in others)}之和）",
                          tc if a[1] else None)
                if not a[1]:
                    p.pop("row")
                probs.append(p)
    return {**base, "verdict": "fail" if probs else "pass",
            **({"actual": len(probs), "where": [p.get("cell", p["sheet"]) for p in probs][:MAX_WHERE],
                "problems": probs[:MAX_PROBLEMS], "reason": f"{len(probs)} 处对不上"} if probs else {})}


def summary(checks):
    """回执的一句话：全部通过，或几条不通过（T9-10：没有问题时写明全部通过，不生成空的问题表）。"""
    mine = [c for c in checks if c["line"] > 0]
    bad = [c for c in checks if c["verdict"] == "fail"]
    if not bad:
        return f"全部通过（期望清单 {len(mine)} 条）" if mine else "全部通过"
    n = sum(len(c.get("problems", [])) or 1 for c in bad)
    return f"{len(bad)} 条核对不通过，共 {n} 处问题"


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


# ═══ r17n（架构线 2026-11-23，；稿 docs/arch-package-checks 7319614c 的“甲”）：两类按格核对的核对项 ═══
#   cell <表/行/列> = <算式> [tol=<误差>]      一格的值等于由别的格算出的值
#   text <表/行/列> = "<模板>"                  一格的文字里含有模板；模板里的 {表/行/列} 代入那一格的值
# 格写成 表/行/列：表写表的 id 或表名（表名写前几个字也认）；行写行的 $id，或这一行前三列里某一格的文字（只有一行含这段文字时也认）；
#   列写列的 key 或标题。与稿不同的两处（按 r17 读数定）：行不只认 $id（各次真跑里行 id 各不相同，项名是规范定死的）；
#   text 判“含有”而不是逐字相等（规格串前半段的截面、厚度各有写法，要核的是其中那个数）。
_CELL_ADDR = re.compile(r"[^\s=+\-*/(),{}\"]+/[^\s=+\-*/(),{}\"]+/[^\s=+\-*(),{}\"]+")


def _squash_text(v):
    return squash(v)


def _locate_msg(lf, parts):
    """locate 找不到时的说明（进模型的话，沿用 r17n–r18f 的写法；r19 加逐字同名一句）。"""
    if lf.kind == "form":
        return f"“{lf.addr}”不是 表/行/列 的写法"
    if lf.kind == "sheet":
        return f"没有“{parts[0]}”这张表"
    if lf.kind == "col":
        return f"表 {parts[0]} 没有“{parts[2]}”这一列"
    if lf.kind == "dup":
        return f"表 {parts[0]} 里{'名为' if lf.exact else '含'}“{parts[1]}”的行有 {lf.n} 行"
    return f"表 {parts[0]} 里没有名为“{parts[1]}”的行：新增一行、名字写“{parts[1]}”，已有这一项而名字不同的把名字改成它（行的名字写在这一行的前三列里）"


def _locate(t, addr):
    """表/行/列 → (值, None, 位置) 或 (None, 说明, 位置或 None)。r19：认法是 model.locate（与格公式同一段代码，A1）；
    说到表里的格一律用 cell_label 的“表名/行名/列名”（A6）。"""
    parts = addr.split("/")
    try:
        sh, ri, j = locate(t, addr)
    except LocateFail as lf:
        return None, _locate_msg(lf, parts), None
    v = sh.rows[ri][j] if j < len(sh.rows[ri]) else None
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None, f"{cell_label(t, sh, ri, j)} 还是空的", (sh, ri, j)
    return v, None, (sh, ri, j)


def _num_text_c(v):
    d = v if isinstance(v, Decimal) else Decimal(str(v))
    s = format(d.normalize(), "f")
    return s


def _pos(t, sh, ri, j):
    """一格的位置（给引擎做 C3 的写入归属用，不进模型的话）：入参里的表序号、行序号、行 $id、列 key，以及说法。"""
    src = sh.src[ri] if sh.src is not None and ri < len(sh.src) else ri
    rid = sh.row_ids[ri] if ri < len(sh.row_ids) else None
    c = sh.columns[j]
    return {"sheet": sh._index, "sheet_id": sh.id, "row": src, "rid": rid, "col": c.key, "title": c.title, "label": cell_label(t, sh, ri, j)}


def _expr_closure(t, sh, ri, j, acc, seen=None):
    """一格若是格公式：它一路读到的格（不含它自己）；读到的格又是格公式的，接着往下追。"""
    seen = set() if seen is None else seen
    if (sh._index, ri, j) in seen:
        return
    seen.add((sh._index, ri, j))
    node = sh.expr_nodes.get((ri, j))
    if node is None:
        return
    for l in F.cell_refs(node):
        acc.add((l[1], l[2], l[3]))
        _expr_closure(t, t.book[l[1]], l[2], l[3], acc, seen)
    for key in F.row_refs(node):
        jj = next(i for i, c in enumerate(sh.columns) if c.key == key)
        acc.add((sh._index, ri, jj))
        _expr_closure(t, sh, ri, jj, acc, seen)


def _eval_expr(t, expr, reads=None, nodes=None):
    """算式里的格换成值，再按四则与函数求值。返回 (Decimal, None) 或 (None, 说明)。
    r19（功能清单 A1）：与格公式同一个解析器与求值器（formula.py），格按 model.locate 找；函数表同格公式（含 sqrt）。
    reads 给一个集合时收进算式读到的格 {(表序号, 行序号, 列序号)}。"""
    def resolve(name):
        raise F.FormulaError(f"“{name}”不是 表/行/列 的写法")

    def resolve_path(addr):
        try:
            sh, ri, j = locate(t, addr)
        except LocateFail as lf:
            raise F.RefError(lf.kind, addr, lf) from None
        return ("cell", sh._index, ri, j)

    class Ext:
        def cell(self, loc):
            return t.book[loc[1]].rows[loc[2]][loc[3]]

        def pcell(self, loc, addr):
            v = t.book[loc[1]].rows[loc[2]][loc[3]]
            if v is None or (isinstance(v, str) and not v.strip()):
                raise F.RefError("empty", addr, None, loc)
            if isinstance(v, Decimal):
                return v
            try:
                return Decimal(str(v).replace(",", "").strip())
            except InvalidOperation:
                raise F.RefError("notnum", addr, v, loc) from None
    try:
        node = F.parse(expr, resolve, None, None, resolve_path)
        F.kind_of(node, {})
    except F.RefError as err:
        return None, _locate_msg(err.detail, err.addr.split("/"))
    except (F.FormulaError, KeyError):
        return None, "算式写法认不出"
    if reads is not None:
        for l in F.cell_refs(node):
            reads.add((l[1], l[2], l[3]))
    if nodes is not None:
        nodes.append(node)
    try:
        v = F.evaluate(node, {}, None, 0, Ext())
    except F.DivZero:
        return None, "算式里除数为零"
    except F.RefError as err:
        if err.kind == "empty":
            o = t.book[err.loc[1]]
            return None, f"{cell_label(t, o, err.loc[2], err.loc[3])} 还是空的"
        return None, f"“{err.addr}”这一格不是数（现为“{err.detail}”）"
    except (F.FormulaError, ArithmeticError, TypeError):
        return None, "算式写法认不出"
    if not isinstance(v, Decimal):
        return None, "算式写法认不出"
    return quantize(v, None), None


# r20（功能清单补一 D3）：核对项行尾可带一句作者写的提示，写成“# 提示：……”（# 前至少一个空格；“10#角钢”这类文字里的 # 不算）。
# 提示是规范包的内容，表格工具不解释：核对项未过时原样接在那句话的末尾，通过时不出现。
HINT_RE = re.compile(r"\s+#\s*提示[:：]\s*(.+?)\s*$")
HINT_JOIN = "。提示："
SELF_CHECK_FAIL = "{me} 现为 {val}，核对项‘{src}’不过；这一格是算出来的，不要直接改它，重新读它用到的读出量：{inputs}"          # 进模型的话：<原话>。提示：<作者的提示>
# r21（立法者 2026-11-24 批，逐字）：自检类核对项（算式里含被核的那一格）未过、被核的格是读出的（不是格公式）——不叫它改这一格，
#   叫它把这一格和算式里一起被核的格重新读一遍；话尾照旧接“。提示：<作者的提示>”。一起被核的格按算式里出现的次序，不含它自己。
SELF_CHECK_READ_FAIL = "{me} 现为 {val}，核对项‘{src}’不过；重新读这一格和它一起被核的格：{peers}"
SELF_CHECK_READ_FAIL_ALONE = "{me} 现为 {val}，核对项‘{src}’不过；重新读这一格"     # 算式里没有别的格时（如 floor(这一格)）


def split_hint(src):
    """核对项一行 → (去掉提示的核对项原文, 提示或 None)。"""
    m = HINT_RE.search(src)
    if m is None:
        return src, None
    return src[:m.start()].rstrip(), m.group(1)


def _canon(node):
    """格公式的语法树去掉“怎么指的格”（表名/行名/列名、@行id.列 都换成格的位置），用来判断两个算式是不是同一个式子。"""
    if isinstance(node, tuple):
        if node and node[0] in ("pref", "cref") and isinstance(node[1], tuple):
            return ("loc",) + tuple(node[1][1:])
        return tuple(_canon(x) for x in node)
    if isinstance(node, list):
        return tuple(_canon(x) for x in node)
    return node


def _inputs(t, at):
    """被核的格若是格公式：沿格公式一路追到底，读出量（不是格公式的格）{(表序号, 行序号, 列序号)}，按位置排好。"""
    acc = set()
    _expr_closure(t, at[0], at[1], at[2], acc)
    return [k for k in sorted(acc) if (k[1], k[2]) not in t.book[k[0]].expr_nodes]


def _with_hint(c, hint):
    if hint is None:
        return c
    c = {**c, "hint": hint}
    if c.get("verdict") == "fail" and c.get("message"):
        c["message"] = c["message"] + HINT_JOIN + hint
    return c


def _mentions(expr, addr):
    """算式（或文字模板）里是不是写着 addr 这个 表/行/列（比较时去掉空白、NFKC）。只在被核的格找不到、没法按位置比时用。"""
    a = _squash_text(addr)
    return bool(a) and any(_squash_text(m) == a for m in re.findall(r"[^\s()+\-*,{}=<>]+/[^\s()+\-*,{}=<>]+/[^\s()+\-*,{}=<>]+", expr))


def _self_read_text(t, me, val, src, peers):
    if not peers:
        return SELF_CHECK_READ_FAIL_ALONE.format(me=me, val=val, src=src)
    names = "、".join(cell_label(t, t.book[k[0]], k[1], k[2]) for k in peers)
    return SELF_CHECK_READ_FAIL.format(me=me, val=val, src=src, peers=names)


def _self_read_msg(t, at, me, val, src, node):
    """r21：自检类核对项、读出格未过时的话。一起被核的格 = 核对项算式里直接写到的格，按出现次序、去重、不含被核的格自己。"""
    me_loc = (at[0]._index, at[1], at[2])
    peers = []
    for l in F.cell_refs(node):
        k = (l[1], l[2], l[3])
        if k != me_loc and k not in peers:
            peers.append(k)
    return _self_read_text(t, me, val, src, peers)


def _cell_check(t, line, src, hint=None):
    return _with_hint(_cell_check0(t, line, src), hint)


def _cell_check0(t, line, src):
    kind = src[:4]
    base = {"line": line, "src": src, "kind": kind}
    body = src[5:].strip()
    if "=" not in body:
        raise ExpectError(f"{kind} 核对项写成 {kind} 表/行/列 = …", line)
    left, right = (x.strip() for x in body.split("=", 1))
    cur, why, at = _locate(t, left)
    reads = set()
    # r19：被核的那一格与读到的格（位置），给引擎判 C3“牵涉到的写入”与导出时“核到”用；不进模型的话（failed 只取 message）
    def cells():
        out = {}
        if at is not None:
            out["target"] = _pos(t, *at)
            _expr_closure(t, at[0], at[1], at[2], reads)
        out["reads"] = [_pos(t, t.book[k[0]], k[1], k[2]) for k in sorted(reads) if at is None or k != (at[0]._index, at[1], at[2])]
        return out
    me = cell_label(t, *at) if at is not None else left
    if kind == "cell":
        tol = Decimal(0)
        m = re.search(r"\s+tol=([0-9.]+)\s*$", right)
        if m:
            tol = Decimal(m.group(1))
            right = right[:m.start()].strip()
        nodes = []
        want, why2 = _eval_expr(t, right, reads, nodes)
        # r20（补一 D3、D4）：两种特别的核对项，判法照旧，只在回执里记一笔、改未过时的话——
        #   restates：被核的格是格公式，且核对项的算式就是这个格公式（对它恒真，只防把算出来的格改成直接写的数）；
        #   self：核对项的算式读到被核的那一格自己（如 floor(这一格)），是在查这一格像不像话，不是给它一个新值。
        node0 = at[0].expr_nodes.get((at[1], at[2])) if at is not None else None
        if node0 is not None and nodes and _canon(node0) == _canon(nodes[0]):
            base["restates"] = True
        if at is not None and nodes and any((l[1], l[2], l[3]) == (at[0]._index, at[1], at[2]) for l in F.cell_refs(nodes[0])):
            base["self"] = True
        elif at is None and _mentions(right, left):
            base["self"] = True          # r21：被核的格找不到时按写法判（算式里写着同一个 表/行/列）
        if node0 is not None:
            base["inputs"] = [_pos(t, t.book[k[0]], k[1], k[2]) for k in _inputs(t, at)]
        if why2 is not None:
            return {**base, "verdict": "fail", "message": f"{me} 核不了：{why2}", "cells": cells()}
        # r21：自检类核对项未过时一律不说“把这一格改成它”（它给的不是这一格的新值）
        fix = "" if base.get("self") else "，把这一格改成它"
        if why is not None:
            return {**base, "verdict": "fail", "message": f"{why}；按规范它应等于 {right}{fix}", "cells": cells()}
        try:
            got = cur if isinstance(cur, Decimal) else Decimal(str(cur).replace(",", ""))
        except Exception:
            return {**base, "verdict": "fail", "message": f"{me} 现为“{cur}”，不是数；按规范它应等于 {right}{fix}", "cells": cells()}
        if abs(quantize(got, None) - want) <= tol:
            return {**base, "verdict": "pass", "cells": cells()}
        if base.get("self") and base.get("inputs"):
            # r20（补一 D3，进模型的话，草案）：自检类核对项未过、被核的格是算出来的——不叫它改这一格，点出它用到的读出量
            names = "、".join(x["label"] for x in base["inputs"])
            return {**base, "verdict": "fail", "message": SELF_CHECK_FAIL.format(me=me, val=_num_text_c(got), src=src, inputs=names), "cells": cells()}
        if base.get("self"):
            # r21：被核的格是读出的（或算式里读不到读出量）——点出算式里和它一起被核的格
            return {**base, "verdict": "fail", "message": _self_read_msg(t, at, me, _num_text_c(got), src, nodes[0]), "cells": cells()}
        return {**base, "verdict": "fail", "message": f"{me} 现为 {_num_text_c(got)}；按规范它应等于 {right}，把这一格改成它", "cells": cells()}
    tpl = right.strip()
    if len(tpl) >= 2 and tpl[0] == tpl[-1] == '"':
        tpl = tpl[1:-1]
    problems = []

    def fill(m):
        if m.group(1).startswith("="):          # {=算式}：代入算式的值（r17q）
            v, w = _eval_expr(t, m.group(1)[1:], reads)
            if w is not None:
                problems.append(w)
                return ""
            return _num_text_c(v)
        v, w, at2 = _locate(t, m.group(1))
        if at2 is not None:
            reads.add((at2[0]._index, at2[1], at2[2]))
        if w is not None:
            problems.append(w)
            return ""
        try:
            return _num_text_c(v if isinstance(v, Decimal) else Decimal(str(v)))
        except Exception:
            return str(v)
    want = re.sub(r"\{([^{}]+)\}", fill, tpl)
    if (at is not None and (at[0]._index, at[1], at[2]) in reads) or (at is None and _mentions(tpl, left)):
        base["self"] = True              # r21：模板里读到被核的那一格自己，也是自检类
    if problems:
        return {**base, "verdict": "fail", "message": f"{me} 核不了：{problems[0]}", "cells": cells()}
    tfix = "" if base.get("self") else "，把这一格改成含它的写法"
    if why is not None:
        return {**base, "verdict": "fail", "message": f"{why}；按规范这一格里应有“{want}”{tfix}", "cells": cells()}
    if _squash_text(want) in _squash_text(cur):
        return {**base, "verdict": "pass", "cells": cells()}
    if base.get("self"):
        peers = [k for k in sorted(reads) if k != (at[0]._index, at[1], at[2])]
        return {**base, "verdict": "fail", "message": _self_read_text(t, me, f"“{cur}”", src, peers), "cells": cells()}
    return {**base, "verdict": "fail", "message": f"{me} 现为“{cur}”；按规范这一格里应有“{want}”（按 {'、'.join(x.lstrip('=') for x in re.findall(r'[{]([^{}]+)[}]', tpl)) or '规范'}），把这一格改成含它的写法", "cells": cells()}


def failed_items(checks):
    """逐条未过的按格核对项，给下一轮照着改。r17y：同一行（表/行）的几条并成一句，句与句之间用“；”——
    下一轮一次只看得到前几条，一行的数量、规格、图纸号分成三条会占掉三个位置。"""
    groups, order = {}, []
    for c in checks:
        if c.get("kind") not in ("cell", "text") or c["verdict"] != "fail" or not c.get("message"):
            continue
        left = c["src"][5:].split("=", 1)[0].strip()
        key = "/".join(left.split("/")[:2])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c["message"])
    return ["；".join(groups[k]) for k in order]
