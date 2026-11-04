"""核对：内置的结构核对 + 期望清单。每条 pass / fail / unknown，总判定取最差。

期望清单一行一条（# 开头为注释）。标题可以用引号括起来（"…" 或 “…”），也可以写 id:节id。
  has 标题 [level=N]                      有这一节
  order 标题A 标题B …                     这些节按此顺序出现
  length 标题|total [min=N] [max=N] [unit=words|chars]   篇幅（含子节）；words 为字数，口径接近 Word
  contains 标题|total 短语                这一节（含子节）里出现这个短语
  figures [min=N] [max=N]                 图的数量
  tables [min=N] [max=N]                  表的数量
  pages [min=N] [max=N]                   页数：排版前无法确定，恒为 unknown
  covered [要求id …]                      必须项（或所列要求）都有非空章节响应
"""
from __future__ import annotations

import re
import unicodedata

from assemble import Assembled

LEAD_NUM = re.compile(r"^\s*(?:第[一二三四五六七八九十百千零〇两\d]+[章节部分篇]|[一二三四五六七八九十百]+[、．.]"
                      r"|[（(][一二三四五六七八九十\d]{1,3}[）)]|\d{1,3}(?:[.．]\d{1,3})*[.．、]?)\s*")

MAX_LINES = 300
KINDS = ("has", "order", "length", "contains", "figures", "tables", "pages", "covered")


class ExpectError(Exception):
    def __init__(self, message, line, hint=None):
        super().__init__(message)
        self.message, self.line, self.hint = message, line, hint


def _tokens(s: str, line: int):
    """→ [(文字, 是否加了引号)]：加了引号的永远是标题或短语，不当参数解析。"""
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


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def _opts(args, line, allowed):
    opts, rest = {}, []
    for a, quoted in args:
        m = None if quoted else re.fullmatch(r"([a-z]+)=(.*)", a)
        if m:
            if m.group(1) not in allowed:
                raise ExpectError(f"不认识的参数 {m.group(1)}=（可用：{', '.join(allowed) or '无'}）", line)
            if m.group(1) in opts:
                raise ExpectError(f"参数 {m.group(1)}= 写了两次", line)
            opts[m.group(1)] = m.group(2)
        else:
            rest.append(a)
    return opts, rest


def _int(v, name, line):
    if v is None:
        return None
    if not re.fullmatch(r"\d+", v):
        raise ExpectError(f"{name}= 要写非负整数（收到 {v}）", line)
    return int(v)


class _Ctx:
    def __init__(self, a: Assembled):
        self.a = a

    def find_all(self, target: str):
        """标题或 id:… → 所有匹配的节（按文中顺序）。"""
        a = self.a
        if target.startswith("id:"):
            o = a.by_id.get(target[3:])
            return [o] if o else []
        want = _norm(target)
        stripped = _norm(LEAD_NUM.sub("", target, count=1))
        return [o for o in a.sections
                if _norm(o.sec.heading) in (want, stripped) or _norm(o.display) == want]

    def find(self, target: str, line: int, c: dict | None = None):
        """第一个匹配的节；同名不止一节时在核对项里注明。"""
        hits = self.find_all(target)
        if len(hits) > 1 and c is not None:
            c["note"] = f"“{target}”有 {len(hits)} 节同名，按第一节（{hits[0].display}）核对；可改写 id:节id"
        return hits[0] if hits else None

    def scope_text(self, o) -> str:
        a = self.a
        if o is None:
            return "\n".join(x.sec.heading + "\n" + x.text for x in a.sections)
        i = a.sections.index(o)
        parts = [o.sec.heading + "\n" + o.text]
        for d in a.sections[i + 1:]:
            if d.sec.level <= o.sec.level:
                break
            parts.append(d.sec.heading + "\n" + d.text)
        return "\n".join(parts)


def _range(actual, lo, hi):
    return (lo is None or actual >= lo) and (hi is None or actual <= hi)


def _bounds(lo, hi, unit=""):
    if lo is not None and hi is not None:
        return f"{lo}–{hi}{unit}"
    if lo is not None:
        return f"≥ {lo}{unit}"
    return f"≤ {hi}{unit}"


def _expect_line(ctx: _Ctx, kind, args, line, src):
    a = ctx.a
    c = {"line": line, "src": src, "kind": kind}
    if kind == "has":
        opts, rest = _opts(args, line, ("level",))
        if len(rest) != 1:
            raise ExpectError("has 后面写一个标题（含空格时加引号）", line)
        lv = _int(opts.get("level"), "level", line)
        if lv is not None and not 1 <= lv <= 4:
            raise ExpectError("level 取 1–4", line)
        hits = ctx.find_all(rest[0])
        c["expected"] = rest[0] + (f"（level {lv}）" if lv else "")
        if not hits:
            return dict(c, verdict="fail", reason="没有这一节")
        good = [o for o in hits if not lv or o.sec.level == lv]
        o = (good or hits)[0]
        c["where"] = [o.sec.id]
        c["actual"] = o.display
        if not good:
            return dict(c, verdict="fail", reason=f"层级是 {o.sec.level}")
        return dict(c, verdict="pass")
    if kind == "order":
        opts, args = _opts(args, line, ())
        if len(args) < 2:
            raise ExpectError("order 后面至少写两个标题", line)
        found = [(t, ctx.find(t, line, c)) for t in args]
        missing = [t for t, o in found if o is None]
        c["expected"] = " → ".join(args)
        if missing:
            return dict(c, verdict="fail", reason="没有这些节：" + "、".join(missing))
        idx = [a.sections.index(o) for _, o in found]
        c["where"] = [o.sec.id for _, o in found]
        c["actual"] = " → ".join(o.display for _, o in sorted(found, key=lambda x: a.sections.index(x[1])))
        if idx != sorted(idx):
            return dict(c, verdict="fail", reason="顺序不符")
        return dict(c, verdict="pass")
    if kind == "length":
        opts, rest = _opts(args, line, ("min", "max", "unit"))
        if len(rest) != 1:
            raise ExpectError("length 后面写一个标题或 total，再写 min= / max=", line)
        lo, hi = _int(opts.get("min"), "min", line), _int(opts.get("max"), "max", line)
        if lo is None and hi is None:
            raise ExpectError("length 至少写 min= 或 max= 之一", line)
        unit = opts.get("unit", "words")
        if unit not in ("words", "chars"):
            raise ExpectError("unit 只能是 words（字数）或 chars（字符数，不计空白）", line)
        uname = " 字" if unit == "words" else " 字符"
        c["expected"] = _bounds(lo, hi, uname)
        if rest[0] == "total":
            actual = a.stats[unit]
        else:
            o = ctx.find(rest[0], line, c)
            if o is None:
                return dict(c, verdict="fail", reason=f"没有这一节：{rest[0]}")
            c["where"] = [o.sec.id]
            actual = o.words_total if unit == "words" else o.chars_total
        c["actual"] = actual
        return dict(c, verdict="pass" if _range(actual, lo, hi) else "fail")
    if kind == "contains":
        opts, args = _opts(args, line, ())
        if len(args) != 2:
            raise ExpectError("contains 后面写范围（标题或 total）和短语，含空格时加引号", line)
        scope, phrase = args
        if not _norm(phrase):
            raise ExpectError("contains 的短语不能为空", line)
        o = None
        if scope != "total":
            o = ctx.find(scope, line, c)
            if o is None:
                return dict(c, expected=phrase, verdict="fail", reason=f"没有这一节：{scope}")
            c["where"] = [o.sec.id]
        text = ctx.scope_text(o)
        c["expected"] = phrase
        hit = _norm(phrase) in _norm(text)
        return dict(c, verdict="pass" if hit else "fail", **({} if hit else {"reason": "没有出现"}))
    if kind in ("figures", "tables"):
        opts, rest = _opts(args, line, ("min", "max"))
        if rest:
            raise ExpectError(f"{kind} 只接 min= / max=", line)
        lo, hi = _int(opts.get("min"), "min", line), _int(opts.get("max"), "max", line)
        if lo is None and hi is None:
            raise ExpectError(f"{kind} 至少写 min= 或 max= 之一", line)
        actual = a.stats[kind]
        return dict(c, expected=_bounds(lo, hi), actual=actual, verdict="pass" if _range(actual, lo, hi) else "fail")
    if kind == "pages":
        opts, rest = _opts(args, line, ("min", "max"))
        if rest:
            raise ExpectError("pages 只接 min= / max=", line)
        lo, hi = _int(opts.get("min"), "min", line), _int(opts.get("max"), "max", line)
        return dict(c, expected=_bounds(lo, hi, " 页") if (lo is not None or hi is not None) else "页数",
                    verdict="unknown", reason="页数取决于排版与字体，导出前无法确定；在 Word 里打开后查看")
    if kind == "covered":
        opts, args = _opts(args, line, ())
        trace = {t["req"]: t for t in a.trace}
        ids = args or [t["req"] for t in a.trace if t["priority"] == "must"]
        unknown = [r for r in ids if r not in trace]
        if unknown:
            return dict(c, expected="、".join(ids), verdict="fail", reason="没有这些要求：" + "、".join(unknown))
        if not trace:
            return dict(c, expected="必须项都有响应", verdict="unknown",
                        reason="文档里没有列出要求，无法核对响应；把任务书或招标文件的要求列进 requirements")
        if not ids:
            return dict(c, expected="必须项都有响应", actual="0 条必须项", verdict="pass",
                        reason=f"要求都是建议项（{len(trace)} 条），没有必须项")
        miss = [r for r in ids if not trace[r]["covered"]]
        c["expected"] = "、".join(ids) if args else f"全部 {len(ids)} 条必须项"
        c["actual"] = f"{len(ids) - len(miss)}/{len(ids)} 有响应"
        return dict(c, verdict="fail" if miss else "pass", **({"reason": "未响应：" + "、".join(miss)} if miss else {}))
    raise ExpectError(f"不认识的核对项 {kind}", line, "可用：" + "、".join(KINDS))


BUILTIN = [
    ("refs", "引用都能解析", ("ref_unknown", "ref_bad"), None),
    ("placement", "图表都已放置且只放一次", ("figure_orphan", "table_orphan", "figure_double", "table_double"), None),
    ("empty", "没有空节", ("empty_section",), "document"),
    ("placeholder", "没有待补的占位", ("placeholder",), "document"),
    ("numbering", "标题里没有手写编号与自动编号重复", ("heading_numbered",), None),
    ("images", "图片都能显示", ("body_image",), None),
]


def run_checks(a: Assembled, expect: str | None):
    checks, assumptions = [], []
    by_code: dict[str, list[dict]] = {}
    for w in a.warnings:
        by_code.setdefault(w["code"], []).append(w)
    for kind, label, codes, only in BUILTIN:
        if only and a.doc.kind != only:
            continue
        hits = [w for c in codes for w in by_code.get(c, [])]
        c = {"line": 0, "src": f"（内置）{label}", "kind": kind, "actual": len(hits)}
        if hits:
            c.update(verdict="fail", where=sorted({h["where"] for h in hits}),
                     reason="；".join(h["message"] for h in hits[:5]) + (f"；另有 {len(hits) - 5} 处" if len(hits) > 5 else ""))
        else:
            c["verdict"] = "pass"
        checks.append(c)
    if a.doc.requirements:
        must = [t for t in a.trace if t["priority"] == "must"]
        miss = [t["req"] for t in must if not t["covered"]]
        bad = by_code.get("trace_unknown_req", [])
        c = {"line": 0, "src": "（内置）必须项都有章节响应", "kind": "requirements",
             "actual": f"{len(must) - len(miss)}/{len(must)} 有响应"}
        if miss or bad:
            reasons = (["未响应：" + "、".join(miss)] if miss else []) + [b["message"] for b in bad[:3]]
            c.update(verdict="fail", reason="；".join(reasons))
        else:
            c["verdict"] = "pass"
        should = [t["req"] for t in a.trace if t["priority"] == "should" and not t["covered"]]
        if should:
            c["note"] = "建议项未响应：" + "、".join(should)
        checks.append(c)
        assumptions.append("要求与章节的对应关系由作者在 responds_to 里声明；本核对只确认每条必须项都有非空章节声明响应，"
                           "不判断内容是否满足要求")

    if expect:
        lines = expect.lstrip("\ufeff").split("\n")
        if len(lines) > MAX_LINES:
            raise ExpectError(f"期望清单超过 {MAX_LINES} 行", MAX_LINES + 1)
        ctx = _Ctx(a)
        for n, raw in enumerate(lines, start=1):
            s = raw.strip()
            if not s or s.startswith("#"):
                continue
            toks = _tokens(s, n)
            kind, args = toks[0][0], toks[1:]
            if kind not in KINDS:
                raise ExpectError(f"不认识的核对项 {kind}", n, "可用：" + "、".join(KINDS))
            checks.append(_expect_line(ctx, kind, args, n, s))
        if any(c["kind"] == "length" and c.get("expected", "").endswith("字") for c in checks):
            assumptions.append("字数按接近 Word 的口径计算：每个汉字或全角标点算 1，每个西文词或数字串算 1；与 Word 的统计可能有小的出入")
    return checks, assumptions


def overall(checks) -> str:
    vs = {c["verdict"] for c in checks}
    if "fail" in vs:
        return "fail"
    if "unknown" in vs:
        return "unknown"
    return "pass"
