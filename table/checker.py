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

from model import NUMERIC, Table, aggregate, dec_str
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
        if not src or src.startswith("#"):
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
