"""组装：编号、放置图表、解析交叉引用、统计、要求追溯。

正文是 Markdown。工具在正文里只认三种记号：
  · 单独一行 [[fig:id]] / [[tab:id]]：把图、表放在这里；
  · 行内 [[sec:id]] / [[fig:id]] / [[tab:id]]：引用，换成“第 2.1 节”“图 3”“表 1”并链接过去；
  · 其余文字原样保留。代码块与行内代码里的记号不处理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

from model import Doc, Figure, Section, Table

PLACE_RE = re.compile(r"^ {0,3}\[\[(fig|tab):([A-Za-z][A-Za-z0-9_]{0,31})\]\]\s*$")
REF_RE = re.compile(r"\[\[([a-z]+):([^\]\n]{1,64})\]\]")
ID_FULL = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
# 标题手写编号：只认不会与正文数字混淆的写法（第一章、一、（一）、1、、1.背景）；
# “1.1 预算”“3 背景”这类纯数字开头，只有与本节自己的编号对得上才算（避免“24 小时运维”“1.5 倍冗余”误报）。
NUMBERED_HEADING = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百千零〇两\d]+[章节部分篇]"
    r"|[一二三四五六七八九十百]+[、．.]"
    r"|[（(][一二三四五六七八九十\d]{1,3}[）)]"
    r"|\d{1,3}、"
    r"|\d{1,3}[.．](?![\d\s]))")
LEADING_NUMBER = re.compile(r"^\s*(\d{1,3}(?:[.．]\d{1,3}){0,3})[.．]?\s")
PLACEHOLDERS = re.compile(
    r"(?<![A-Za-z])(?:TODO|TBD|FIXME|XXX)(?![A-Za-z])|×××|待补充|待补|待定|待填写|待完善|此处填写|请填写|请补充|占位符"
    r"|(?i:lorem ipsum)")
EAST_ASIAN = re.compile(
    "[⺀-⿿　-〿぀-ヿ㄀-ㄯ㈀-㋿㐀-䶿一-鿿"
    "豈-﫿︰-﹏＀-￯\U00020000-\U0002fa1f]")
LATIN_WORD = re.compile(r"[A-Za-z0-9À-ɏ]+(?:['’.\-][A-Za-z0-9À-ɏ]+)*")

WORDS = {
    "zh-CN": {"fig": "图", "tab": "表", "toc": "目录", "trace": "附：要求响应对照表", "note": "注：",
              "trace_cols": ["编号", "要求", "来源", "类别", "响应章节", "状态"], "must": "必须", "should": "建议",
              "covered": "已响应", "uncovered": "未响应", "img_omitted": "图片未显示"},
    "en": {"fig": "Figure", "tab": "Table", "toc": "Contents", "trace": "Appendix: Requirement Response Matrix",
           "note": "Note: ", "trace_cols": ["ID", "Requirement", "Source", "Priority", "Responding sections", "Status"],
           "must": "must", "should": "should", "covered": "covered", "uncovered": "not covered",
           "img_omitted": "image not shown"},
}


def md_parser() -> MarkdownIt:
    return MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable(
        ["table", "strikethrough"])


MD = md_parser()


def zh_num(n: int) -> str:
    d = "零一二三四五六七八九"
    if n < 10:
        return d[n]
    if n < 20:
        return "十" + (d[n % 10] if n % 10 else "")
    if n < 100:
        return d[n // 10] + "十" + (d[n % 10] if n % 10 else "")
    if n < 10000:
        unit, size = ("百", 100) if n < 1000 else ("千", 1000)
        h, r = d[n // size] + unit, n % size
        if r == 0:
            return h
        rest = zh_num(r)
        if rest.startswith("十"):
            rest = "一" + rest
        return h + ("零" if r < size // 10 else "") + rest
    return str(n)


def hand_numbered(heading: str, path: tuple) -> bool:
    if NUMBERED_HEADING.match(heading):
        return True
    m = LEADING_NUMBER.match(heading)
    if not m:
        return False
    nums = tuple(int(x) for x in re.split(r"[.．]", m.group(1)))
    if len(nums) == 1:
        return nums[0] == path[-1]
    return nums[0] == path[0]


def count_words(text: str) -> int:
    """字数，口径接近 Word 的“字数”：每个汉字或全角标点算 1，每个西文词或数字串算 1。"""
    return len(EAST_ASIAN.findall(text)) + len(LATIN_WORD.findall(text))


def count_chars(text: str) -> int:
    """字符数（不计空白）。"""
    return sum(1 for c in text if not c.isspace())


def md_escape(s: str) -> str:
    return re.sub(r"([\\`*_\[\]<>#!|&~])", r"\\\1", s)


# ---------------------------------------------------------------- 结果结构
@dataclass
class Seg:
    kind: str                 # md | fig | tab
    text: str = ""            # md：引用已解析的 Markdown
    line: int = 1             # 在本节正文里的起始行（1 起）
    ref: str = ""             # fig / tab 的 id


@dataclass
class SecOut:
    sec: Section
    number: str               # “1.2”“第一章”“（一）”；不编号时为空
    display: str              # 带编号的标题
    ref_text: str             # 被引用时的写法
    anchor: str
    parent: str | None
    chapter: int              # 所属一级节的序号（1 起）
    segs: list[Seg] = field(default_factory=list)
    sub_kmin: int = 0         # 正文里小标题的最浅层级（0 = 没有）
    text: str = ""            # 本节可见文字（不含子节）
    words: int = 0
    chars: int = 0
    words_total: int = 0
    chars_total: int = 0
    leaf: bool = True
    refs: dict = field(default_factory=dict)   # 本节正文里的链接引用定义，切段后各段共用

    def env(self) -> dict:
        return {"references": dict(self.refs)}


@dataclass
class Assembled:
    doc: Doc
    sha: str
    words: dict
    sections: list[SecOut]
    by_id: dict
    fig_label: dict           # id → “1”“2-1”
    tab_label: dict
    fig_section: dict         # id → 所在节 id
    tab_section: dict
    trace: list[dict]
    warnings: list[dict]
    stats: dict

    def fig_caption(self, f: Figure) -> str:
        return f"{self.words['fig']} {self.fig_label[f.id]}　{f.caption}" if self.doc.meta["lang"] == "zh-CN" \
            else f"{self.words['fig']} {self.fig_label[f.id]}. {f.caption}"

    def tab_caption(self, t: Table) -> str:
        return f"{self.words['tab']} {self.tab_label[t.id]}　{t.caption}" if self.doc.meta["lang"] == "zh-CN" \
            else f"{self.words['tab']} {self.tab_label[t.id]}. {t.caption}"

    @property
    def figures(self) -> dict:
        return {f.id: f for f in self.doc.figures}

    @property
    def tables(self) -> dict:
        return {t.id: t for t in self.doc.tables}


# ---------------------------------------------------------------- 正文切分与引用
# 哪些行是代码、哪些行是段落，一律以解析器的结果为准（缩进代码、列表与引用块里的代码都算），
# 不另写一套行扫描。行内代码只在同一段落（同一 inline token 的行范围）里配对。
def _regions(text: str):
    """→ (代码行集合, 不可放置的行集合, {(起行, 止行): [各个引用是否在链接文字里]})"""
    tokens = MD.parse(text)
    code, blocked, paras = set(), set(), {}
    for t in tokens:
        if t.type in ("code_block", "fence") and t.map:
            code.update(range(t.map[0], t.map[1]))
        elif t.type == "table_open" and t.map:
            blocked.update(range(t.map[0], t.map[1]))
        elif t.type == "inline" and t.map:
            flags, depth = [], 0
            for c in t.children or []:
                if c.type == "link_open":
                    depth += 1
                elif c.type == "link_close":
                    depth -= 1
                elif c.type == "text":
                    flags += [depth > 0] * len(REF_RE.findall(c.content))
            paras.setdefault((t.map[0], t.map[1]), []).extend(flags)
    return code, blocked | code, paras


def split_body(body: str):
    """按放置行切开正文；代码与表格里的行不算放置。返回 [(kind, payload, line)]。"""
    _, blocked, _ = _regions(body)
    out, buf, buf_line = [], [], 1
    for i, line in enumerate(body.split("\n"), start=1):
        p = PLACE_RE.match(line) if (i - 1) not in blocked else None
        if p:
            if buf:
                out.append(("md", "\n".join(buf), buf_line))
            out.append((p.group(1), p.group(2), i))
            buf, buf_line = [], i + 1
            continue
        if not buf:
            buf_line = i
        buf.append(line)
    if buf:
        out.append(("md", "\n".join(buf), buf_line))
    return out


def _code_spans(text: str):
    """→ [(可替换?, 片段)]：行内代码不可替换。"""
    out, i, start, n = [], 0, 0, len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] != "`":
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run = j - i
        k, close = j, -1
        while k < n:
            if text[k] == "`":
                m = k
                while m < n and text[m] == "`":
                    m += 1
                if m - k == run:
                    close = k
                    break
                k = m
            else:
                k += 1
        if close < 0:
            i = j
            continue
        if i > start:
            out.append((True, text[start:i]))
        out.append((False, text[i:close + run]))
        i = start = close + run
    if start < n:
        out.append((True, text[start:]))
    return out


def _walk_refs(text: str, fn=None):
    """逐段落找引用记号（跳过代码），fn(match, in_link) 给出替换文字；返回 (新文本, [(kind, id, 原文)])。"""
    code, _, paras = _regions(text)
    lines = text.split("\n")
    found = []
    for (s, e), flags in sorted(paras.items()):
        if any(i in code for i in range(s, e)):
            continue
        chunk = "\n".join(lines[s:e])
        parts = _code_spans(chunk)
        n = sum(len(REF_RE.findall(p)) for ok, p in parts if ok)
        it = iter(flags if len(flags) == n else [False] * n)

        def sub(m):
            found.append((m.group(1), m.group(2), m.group(0)))
            inside = next(it)
            return fn(m, inside) if fn else m.group(0)

        new = "".join(REF_RE.sub(sub, p) if ok else p for ok, p in parts)
        lines[s:e] = new.split("\n")
    return "\n".join(lines), found


def scan_refs(text: str):
    """正文里的引用记号（不含代码）：[(kind, id, 原文)]。"""
    return _walk_refs(text)[1]


def replace_refs(text: str, fn) -> str:
    return _walk_refs(text, fn)[0]


# ---------------------------------------------------------------- Markdown → 文字
def inline_text(children) -> str:
    out = []
    for t in children or []:
        if t.type in ("text", "code_inline"):
            out.append(t.content)
        elif t.type in ("softbreak", "hardbreak"):
            out.append("\n")
        elif t.type == "image":
            out.append(t.content)
    return "".join(out)


def md_text(text: str, env: dict | None = None) -> tuple[str, list]:
    """一段 Markdown 的可见文字，以及解析出的 token。"""
    tokens = MD.parse(text, env if env is not None else {})
    parts = []
    for t in tokens:
        if t.type == "inline":
            parts.append(inline_text(t.children))
        elif t.type in ("code_block", "fence"):
            parts.append(t.content)
    return "\n".join(parts), tokens


# ---------------------------------------------------------------- 编号
def _section_numbers(doc: Doc):
    style, lang = doc.meta["numbering"], doc.meta["lang"]
    counters = [0] * 4
    out = []
    for s in doc.sections:
        L = s.level
        counters[L - 1] += 1
        for i in range(L, 4):
            counters[i] = 0
        path = counters[:L]
        dec = ".".join(str(x) for x in path)
        if style == "decimal":
            num, disp = dec, f"{dec} {s.heading}"
        elif style == "chapter":
            if L == 1:
                num = f"第{zh_num(path[0])}章" if lang == "zh-CN" else f"Chapter {path[0]}"
                disp = f"{num}　{s.heading}" if lang == "zh-CN" else f"{num} {s.heading}"
            else:
                num, disp = dec, f"{dec} {s.heading}"
        elif style == "zh":
            n = path[-1]
            num = [f"{zh_num(n)}、", f"（{zh_num(n)}）", f"{n}．", f"（{n}）"][L - 1]
            disp = num + s.heading
        else:
            num, disp = "", s.heading
        if lang == "zh-CN":
            if style == "decimal" or (style == "chapter" and L > 1):
                ref = f"第 {dec} 节"
            elif style == "chapter":
                ref = num
            else:
                ref = f"“{s.heading}”一节"
        else:
            if style == "decimal" or (style == "chapter" and L > 1):
                ref = f"Section {dec}"
            elif style == "chapter":
                ref = num
            else:
                ref = f"“{s.heading}”"
        out.append((num, disp, ref, path[0], tuple(path)))
    return out


# ---------------------------------------------------------------- 组装
def assemble(doc: Doc) -> Assembled:
    W = WORDS[doc.meta["lang"]]
    warnings = list(doc.warnings)
    nums = _section_numbers(doc)
    figs, tabs = {f.id: f for f in doc.figures}, {t.id: t for t in doc.tables}
    sec_ids = {s.id for s in doc.sections}

    outs: list[SecOut] = []
    stack: list[SecOut] = []
    paths = {}
    for s, (num, disp, ref, chap, path) in zip(doc.sections, nums):
        paths[s.id] = path
        while stack and stack[-1].sec.level >= s.level:
            stack.pop()
        o = SecOut(s, num, disp, ref, f"sec-{s.id}", stack[-1].sec.id if stack else None, chap)
        if stack:
            stack[-1].leaf = False
        stack.append(o)
        outs.append(o)
    by_id = {o.sec.id: o for o in outs}

    # 第一遍：放置与引用
    placed = {"fig": {}, "tab": {}}          # id → (节序, 段序)
    first_ref = {"fig": {}, "tab": {}}       # id → 节序
    raw_segs = []
    for k, o in enumerate(outs):
        segs = split_body(o.sec.body)
        kept = []
        for kind, payload, line in segs:
            if kind == "md":
                for rk, rid, _ in scan_refs(payload):
                    if rk in first_ref and rid in (figs if rk == "fig" else tabs):
                        first_ref[rk].setdefault(rid, k)
                kept.append(Seg("md", payload, line))
                continue
            pool = figs if kind == "fig" else tabs
            what = W[kind]
            if payload not in pool:
                warnings.append({"where": f"sections[{o.sec.index}]", "code": "ref_unknown", "line": line,
                                 "message": f"第 {o.sec.index + 1} 节（{o.sec.id}）第 {line} 行放置的{what} {payload} 不存在"})
                kept.append(Seg("md", f"〔{what} {payload} 不存在〕", line))
                continue
            if payload in placed[kind]:
                prev = outs[placed[kind][payload][0]].sec
                warnings.append({"where": f"sections[{o.sec.index}]", "code": f"{'figure' if kind == 'fig' else 'table'}_double",
                                 "line": line,
                                 "message": f"{what} {payload} 已在第 {prev.index + 1} 节（{prev.id}）放置过；第 {o.sec.index + 1} 节第 {line} 行的再次放置未采用，"
                                            f"再次提到请用行内引用"})
                continue
            placed[kind][payload] = (k, len(kept))
            kept.append(Seg(kind, ref=payload, line=line))
        raw_segs.append(kept)

    for kind, pool, code in (("fig", doc.figures, "figure"), ("tab", doc.tables, "table")):
        for item in pool:
            if item.id in placed[kind]:
                continue
            if item.id in first_ref[kind]:
                k = first_ref[kind][item.id]
                raw_segs[k].append(Seg(kind, ref=item.id, line=0))
                placed[kind][item.id] = (k, len(raw_segs[k]) - 1)
                warnings.append({"where": f"sections[{outs[k].sec.index}]", "code": f"{code}_auto_placed",
                                 "message": f"{W[kind]} {item.id} 没有指定位置，放在第一次引用它的第 {outs[k].sec.index + 1} 节（{outs[k].sec.id}）末尾"})
            else:
                warnings.append({"where": f"{'figures' if kind == 'fig' else 'tables'}[{item.index}]", "code": f"{code}_orphan",
                                 "message": f"{W[kind]} {item.id} 既没有放置也没有被引用，不会出现在文档里"})

    # 图表编号：按出现顺序
    fig_label, tab_label, fig_sec, tab_sec = {}, {}, {}, {}
    per_chapter = {"fig": {}, "tab": {}}
    seq = {"fig": 0, "tab": 0}
    for k, segs in enumerate(raw_segs):
        for sg in segs:
            if sg.kind not in ("fig", "tab"):
                continue
            seq[sg.kind] += 1
            chap = outs[k].chapter
            per_chapter[sg.kind][chap] = per_chapter[sg.kind].get(chap, 0) + 1
            label = (f"{chap}-{per_chapter[sg.kind][chap]}" if doc.meta["figure_numbering"] == "chapter"
                     else str(seq[sg.kind]))
            (fig_label if sg.kind == "fig" else tab_label)[sg.ref] = label
            (fig_sec if sg.kind == "fig" else tab_sec)[sg.ref] = outs[k].sec.id

    # 第二遍：解析行内引用
    def resolver(where, sec_no):
        def fn(m, in_link=False):
            kind, rid = m.group(1), m.group(2)
            if kind not in ("sec", "fig", "tab"):
                warnings.append({"where": where, "code": "ref_bad",
                                 "message": f"第 {sec_no} 节里的 {m.group(0)} 不是可用的引用（只认 sec、fig、tab）"})
                return f"〔无效引用 {md_escape(kind)}:{md_escape(rid)}〕"
            if not ID_FULL.fullmatch(rid):
                warnings.append({"where": where, "code": "ref_bad",
                                 "message": f"第 {sec_no} 节里的 {m.group(0)}：id 只含字母、数字、下划线"})
                return f"〔无效引用 {md_escape(kind)}:{md_escape(rid)}〕"
            if kind == "sec":
                if rid not in by_id:
                    warnings.append({"where": where, "code": "ref_unknown", "message": f"第 {sec_no} 节引用的节 {rid} 不存在"})
                    return f"〔节 {rid} 不存在〕"
                label = md_escape(by_id[rid].ref_text)
                return label if in_link else f"[{label}](#sec-{rid})"
            labels = fig_label if kind == "fig" else tab_label
            pool = figs if kind == "fig" else tabs
            if rid not in pool:
                warnings.append({"where": where, "code": "ref_unknown",
                                 "message": f"第 {sec_no} 节引用的{W[kind]} {rid} 不存在"})
                return f"〔{W[kind]} {rid} 不存在〕"
            label = f"{W[kind]} {labels[rid]}"
            return label if in_link else f"[{label}](#{kind}-{rid})"
        return fn

    for k, o in enumerate(outs):
        fn = resolver(f"sections[{o.sec.index}]", o.sec.index + 1)
        for sg in raw_segs[k]:
            if sg.kind == "md":
                sg.text = replace_refs(sg.text, fn)
        o.segs = raw_segs[k]
        env: dict = {}
        MD.parse(o.sec.body, env)
        o.refs = env.get("references", {})

    # 文字、统计、正文里的小标题与图片
    for o in outs:
        texts, kmin = [], 0
        for sg in o.segs:
            if sg.kind == "md":
                t, tokens = md_text(sg.text, o.env())
                texts.append(t)
                for tk in tokens:
                    if tk.type == "heading_open":
                        lv = int(tk.tag[1])
                        kmin = lv if not kmin else min(kmin, lv)
                    if tk.type == "inline":
                        for c in tk.children or []:
                            if c.type == "image":
                                ln = sg.line + (tk.map[0] if tk.map else 0)
                                warnings.append({"where": f"sections[{o.sec.index}]", "code": "body_image", "line": ln,
                                                 "message": f"第 {o.sec.index + 1} 节第 {ln} 行用了正文图片语法，导出时不显示；"
                                                            f"图请放进 figures 并用 [[fig:id]] 放置"})
            elif sg.kind == "fig":
                f = figs[sg.ref]
                texts.append(f"{W['fig']} {fig_label[f.id]} {f.caption}")
            else:
                t = tabs[sg.ref]
                cells = [" ".join(t.columns)] + [" ".join(r) for r in t.rows]
                texts.append(f"{W['tab']} {tab_label[t.id]} {t.caption}\n" + "\n".join(cells) + ("\n" + t.note if t.note else ""))
        o.sub_kmin = kmin
        o.text = "\n".join(texts)
        o.words, o.chars = count_words(o.text), count_chars(o.text)

    for i, o in enumerate(outs):
        o.words_total, o.chars_total = o.words, o.chars
        for d in outs[i + 1:]:
            if d.sec.level <= o.sec.level:
                break
            o.words_total += d.words
            o.chars_total += d.chars

    # 结构提醒
    for o in outs:
        s = o.sec
        if doc.kind == "document" and o.leaf and not o.text.strip():
            warnings.append({"where": f"sections[{s.index}]", "code": "empty_section",
                             "message": f"第 {s.index + 1} 节（{s.id}“{s.heading}”）没有正文"})
        if doc.meta["numbering"] != "none" and hand_numbered(s.heading, paths[s.id]):
            warnings.append({"where": f"sections[{s.index}].heading", "code": "heading_numbered",
                             "message": f"第 {s.index + 1} 节标题“{s.heading}”已带编号，会与自动编号重复",
                             "hint": "去掉标题里的编号，或把 meta.numbering 设为 none"})
    if doc.kind == "document":
        _placeholders(doc, outs, warnings)

    # 要求追溯
    responders: dict[str, list[str]] = {r.id: [] for r in doc.requirements}
    for o in outs:
        for rid in o.sec.responds_to:
            if rid in responders:
                responders[rid].append(o.sec.id)
            else:
                warnings.append({"where": f"sections[{o.sec.index}].responds_to", "code": "trace_unknown_req",
                                 "message": f"第 {o.sec.index + 1} 节声明响应的要求 {rid} 不在 requirements 里"})
    trace = []
    for r in doc.requirements:
        secs = responders[r.id]
        live = [x for x in secs if doc.kind == "outline" or by_id[x].text.strip() or not by_id[x].leaf]
        covered = bool(live)
        trace.append({"req": r.id, "priority": r.priority, "sections": secs, "covered": covered})
        if not covered:
            warnings.append({"where": f"requirements", "code": "req_uncovered" if r.priority == "must" else "req_uncovered_should",
                             "message": f"要求 {r.id}（{'必须' if r.priority == 'must' else '建议'}）没有章节响应"
                                        + ("（声明响应的章节没有正文）" if secs else "")})

    words_all = sum(o.words for o in outs)
    chars_all = sum(o.chars for o in outs)
    must = [t for t in trace if t["priority"] == "must"]
    stats = {
        "sections": len(outs), "chapters": sum(1 for o in outs if o.sec.level == 1),
        "words": words_all, "chars": chars_all,
        "figures": len(fig_label), "tables": len(tab_label),
        "requirements": len(trace), "must": len(must), "must_covered": sum(1 for t in must if t["covered"]),
        "warnings": len(warnings),
    }
    return Assembled(doc, doc.sha256(), W, outs, by_id, fig_label, tab_label, fig_sec, tab_sec, trace, warnings, stats)


def _placeholders(doc, outs, warnings, cap=50):
    hits = 0

    def hit(where, text, label):
        nonlocal hits
        for m in PLACEHOLDERS.finditer(text):
            if hits >= cap:
                return
            a = max(0, m.start() - 12)
            snippet = text[a:m.end() + 12].replace("\n", " ")
            warnings.append({"where": where, "code": "placeholder",
                             "message": f"{label}有待补的占位“{m.group(0)}”：…{snippet}…"})
            hits += 1

    hit("title", doc.title + " " + doc.subtitle, "标题")
    for o in outs:
        hit(f"sections[{o.sec.index}]", o.sec.heading + "\n" + o.text, f"第 {o.sec.index + 1} 节（{o.sec.id}）")
