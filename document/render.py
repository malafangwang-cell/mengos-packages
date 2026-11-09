"""派生视图：Markdown（给模型看、也可下载）、产出台数据（view.json）、单文件网页。

全部由组装结果确定性地生成；同一文档模型，输出逐字节相同。
"""
from __future__ import annotations

import base64
import html
import json
import re

from assemble import MD, Assembled, SecOut, md_escape

ROLE_FIG = "document.figure"
EXT = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg"}


def _meta_line(a: Assembled) -> str:
    m, zh = a.doc.meta, a.doc.meta["lang"] == "zh-CN"
    labels = (("author", "作者"), ("org", "单位"), ("date", "日期"), ("version", "版本")) if zh else \
        (("author", "Author"), ("org", "Organization"), ("date", "Date"), ("version", "Version"))
    parts = [f"{lab}：{m[k]}" if zh else f"{lab}: {m[k]}" for k, lab in labels if m[k]]
    return ("　" if zh else " · ").join(parts)


ROLE_FIG_ORIG = "document.figure_original"


def figure_filename(name: str, fig) -> str:
    """Markdown 里图的文件名：位图指向原图产出文件 figures/<id>.<ext>（同一字节、同一对象，不另存一份）；SVG 仍随 Markdown 附一个文件。"""
    return fig.orig_path if fig.orig_path else f"{name}.f-{fig.id}{EXT[fig.media_type]}"


# ---------------------------------------------------------------- Markdown
NESTED_ATX = re.compile(r"^((?:[ \t]*>)*[ \t]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+)*[ \t]*)(#{1,6})(?=[ \t]|$)")


def sub_depth(section_depth: int, k: int, kmin: int) -> int:
    """正文小标题的层级：最浅的一级紧接本节标题的下一级，其余按相对层级顺延；夹在 [本节下一级, 6]。"""
    return max(section_depth + 1, min(6, section_depth + 1 + k - kmin))


def _relevel_md(text: str, base_depth: int, kmin: int) -> str:
    """正文里的小标题挂到本节之下（含列表、引用块里的 # 标题）。"""
    if not kmin:
        return text
    tokens = MD.parse(text)
    lines = text.split("\n")
    edits = []
    for i, t in enumerate(tokens):
        if t.type != "heading_open" or not t.map:
            continue
        depth = sub_depth(base_depth, int(t.tag[1]), kmin)
        if t.level == 0:
            content = " ".join(tokens[i + 1].content.split("\n")).strip()
            edits.append((t.map[0], t.map[1], "#" * depth + " " + content))
        else:
            line = lines[t.map[0]]
            m = NESTED_ATX.match(line)
            if m:
                edits.append((t.map[0], t.map[0] + 1, m.group(1) + "#" * depth + line[m.end():]))
    for start, end, new in reversed(edits):
        lines[start:end] = [new]
    return "\n".join(lines)


def _close_fence(text: str) -> str:
    """没有闭合的代码块会一直延续到文件末尾、吞掉后面各节；在本段末尾替它闭合。"""
    tokens = MD.parse(text)
    lines = text.split("\n")
    for t in tokens:
        if t.type == "fence" and t.level == 0 and t.map:
            end = t.map[1] - 1
            last = lines[end].strip() if end > t.map[0] else ""
            if not (last and set(last) == {t.markup[0]} and len(last) >= len(t.markup)):
                return text.rstrip("\n") + "\n" + t.markup
    return text


def _md_plain(s: str) -> str:
    """纯文字写进 Markdown：转义行内记号与行首的块记号，换行写成硬换行。"""
    out = []
    for ln in s.split("\n"):
        e = md_escape(ln)
        e = re.sub(r"^(\s*)([-+=])", r"\1\\\2", e)
        e = re.sub(r"^(\s*\d+)([.)])", r"\1\\\2", e)
        out.append(e)
    return "\\\n".join(out)


def _md_table_cell(s: str) -> str:
    return md_escape(s).replace("\n", "<br>")


def _md_table(columns, rows, align) -> list[str]:
    sep = {"left": ":--", "center": ":-:", "right": "--:"}
    out = ["| " + " | ".join(_md_table_cell(c) or " " for c in columns) + " |",
           "|" + "|".join(sep[x] for x in align) + "|"]
    out += ["| " + " | ".join(_md_table_cell(c) for c in r) + " |" for r in rows]
    return out


def to_markdown(a: Assembled, name: str):
    """返回 (Markdown 文本, [(文件名, 字节, media_type)])：SVG 以同名前缀的文件交付；位图引用 figures/ 下的原图文件。"""
    d, W, zh = a.doc, a.words, a.doc.meta["lang"] == "zh-CN"
    figs, tabs = a.figures, a.tables
    out = [f"# {md_escape(d.title)}", ""]
    if d.subtitle:
        out += [f"**{md_escape(d.subtitle)}**", ""]
    ml = _meta_line(a)
    if ml:
        out += [_md_plain(ml), ""]
    if d.meta["toc"]:
        out += [f"**{W['toc']}**", ""]
        for o in a.sections:
            out.append("  " * (o.sec.level - 1) + f"- [{md_escape(o.display)}](#{o.anchor})")
        if d.meta["trace_table"] and d.requirements:
            out.append(f"- [{md_escape(W['trace'])}](#sec-_trace)")
        out.append("")
    files = []
    for o in a.sections:
        out += [f'<a id="{o.anchor}"></a>', "", "#" * (o.sec.level + 1) + " " + md_escape(o.display), ""]
        for sg in o.segs:
            if sg.kind == "md":
                body = _close_fence(_relevel_md(sg.text, o.sec.level + 1, o.sub_kmin)).strip("\n")
                if body.strip():
                    out += [body, ""]
            elif sg.kind == "fig":
                f = figs[sg.ref]
                cap = a.fig_caption(f)
                out += [f'<a id="fig-{f.id}"></a>', ""]
                fn = figure_filename(name, f)
                if not f.orig_path:                      # SVG：附图文件；位图：引用原图产出文件，不在这里再出一份
                    files.append((fn, f.data, f.media_type))
                out += [f"![{md_escape(cap)}]({fn})", "", f"*{md_escape(cap)}*", ""]
            else:
                t = tabs[sg.ref]
                out += [f'<a id="tab-{t.id}"></a>', "", f"**{md_escape(a.tab_caption(t))}**", ""]
                out += _md_table(t.columns, t.rows, t.align) + [""]
                if t.note:
                    out += [W["note"] + _md_plain(t.note), ""]
    if d.meta["trace_table"] and d.requirements:
        cols, rows = trace_rows(a)
        out += ['<a id="sec-_trace"></a>', "", "## " + md_escape(W["trace"]), ""]
        out += _md_table(cols, rows, ["left"] * len(cols)) + [""]
    text = "\n".join(out).rstrip("\n") + "\n"
    return text, files


def trace_rows(a: Assembled):
    W = a.words
    by_req = {t["req"]: t for t in a.trace}
    rows = []
    for r in a.doc.requirements:
        t = by_req[r.id]
        secs = "；".join(a.by_id[s].display for s in t["sections"]) if a.doc.meta["lang"] == "zh-CN" else \
            "; ".join(a.by_id[s].display for s in t["sections"])
        status = W["covered"] if t["covered"] else W["uncovered"]
        rows.append([r.id, r.text, r.source, W[r.priority], secs, status])
    return W["trace_cols"], rows


# ---------------------------------------------------------------- HTML 片段
def _render_md_html(a: Assembled, o: SecOut, text: str) -> str:
    tokens = MD.parse(text, o.env())
    base = o.sec.level + 1
    for t in tokens:
        if t.type in ("heading_open", "heading_close") and o.sub_kmin:
            t.tag = f"h{sub_depth(base, int(t.tag[1]), o.sub_kmin)}"
            if t.type == "heading_open":
                t.attrSet("class", "sub")
        elif t.type == "table_open":
            t.attrSet("class", "md-table")
        elif t.type == "inline":
            for c in t.children or []:
                if c.type == "link_open":
                    href = c.attrGet("href") or ""
                    if not href.startswith("#"):
                        c.attrSet("rel", "noopener noreferrer")
                        c.attrSet("target", "_blank")
                elif c.type == "image":
                    c.type, c.tag, c.nesting = "html_inline", "", 0
                    alt = inline_alt(c)
                    c.content = f'<span class="omitted">〔{html.escape(a.words["img_omitted"])}：{html.escape(alt)}〕</span>'
                    c.children = None
    return MD.renderer.render(tokens, MD.options, {})


def inline_alt(tok) -> str:
    return "".join(ch.content for ch in (tok.children or []) if ch.type in ("text", "code_inline")) or tok.content


def data_uri(f) -> str:
    return f"data:{f.view_type};base64," + base64.b64encode(f.view_data).decode("ascii")


def figure_html(a: Assembled, f) -> str:
    cap = html.escape(a.fig_caption(f))
    inner = f'<img src="{data_uri(f)}" alt="{cap}" style="width:{round(f.width * 100)}%">'
    return f'<figure class="fig" id="fig-{f.id}">{inner}<figcaption>{cap}</figcaption></figure>\n'


def _cell_html(s: str) -> str:
    return html.escape(s).replace("\n", "<br>")


def table_html(columns, rows, align, caption: str | None, tid: str | None, note: str = "", note_label: str = "") -> str:
    idattr = f' id="tab-{tid}"' if tid else ""
    out = [f'<div class="tbl"{idattr}>']
    if caption:
        out.append(f'<p class="cap">{html.escape(caption)}</p>')
    out.append("<table><thead><tr>" + "".join(
        f'<th style="text-align:{al}">{_cell_html(c)}</th>' for c, al in zip(columns, align)) + "</tr></thead><tbody>")
    for r in rows:
        out.append("<tr>" + "".join(f'<td style="text-align:{al}">{_cell_html(c)}</td>' for c, al in zip(r, align)) + "</tr>")
    out.append("</tbody></table>")
    if note:
        out.append(f'<p class="note">{html.escape(note_label + note)}</p>')
    out.append("</div>\n")
    return "".join(out)


def section_body_html(a: Assembled, o: SecOut) -> str:
    parts = []
    figs, tabs = a.figures, a.tables
    for sg in o.segs:
        if sg.kind == "md":
            if sg.text.strip():
                parts.append(_render_md_html(a, o, sg.text))
        elif sg.kind == "fig":
            parts.append(figure_html(a, figs[sg.ref]))
        else:
            t = tabs[sg.ref]
            parts.append(table_html(t.columns, t.rows, t.align, a.tab_caption(t), t.id, t.note, a.words["note"]))
    return "".join(parts)


def heading_html(o: SecOut) -> str:
    lv = min(6, o.sec.level + 1)
    if not o.number:
        return f'<h{lv} class="h">{html.escape(o.sec.heading)}</h{lv}>\n'
    sep = o.display[len(o.number):len(o.display) - len(o.sec.heading)]
    return (f'<h{lv} class="h"><span class="num">{html.escape(o.number)}</span>{html.escape(sep)}'
            f'{html.escape(o.sec.heading)}</h{lv}>\n')


# ---------------------------------------------------------------- 产出台数据
def to_view(a: Assembled) -> dict:
    d = a.doc
    sections = []
    for o in a.sections:
        sections.append({
            "id": o.sec.id, "anchor": o.anchor, "level": o.sec.level, "number": o.number, "heading": o.sec.heading,
            "display": o.display, "parent": o.parent, "html": section_body_html(a, o),
            "words": o.words, "chars": o.chars, "words_total": o.words_total, "chars_total": o.chars_total,
            "responds_to": o.sec.responds_to, "empty": not o.text.strip(),
        })
    trace_by = {t["req"]: t for t in a.trace}
    view = {
        "schema": "mengos.document.view/1",
        "doc_sha256": a.sha,
        "kind": d.kind,
        "title": d.title, "subtitle": d.subtitle,
        "meta": {k: d.meta[k] for k in ("lang", "author", "org", "date", "version", "numbering", "toc", "cover", "trace_table")},
        "toc": [{"id": o.sec.id, "anchor": o.anchor, "level": o.sec.level, "display": o.display} for o in a.sections],
        "sections": sections,
        "figures": [{"id": f.id, "label": f"{a.words['fig']} {a.fig_label[f.id]}", "caption": f.caption,
                     "section": a.fig_section[f.id], "kind": f.kind}
                    for f in d.figures if f.id in a.fig_label],
        "tables": [{"id": t.id, "label": f"{a.words['tab']} {a.tab_label[t.id]}", "caption": t.caption,
                    "section": a.tab_section[t.id], "rows": len(t.rows)}
                   for t in d.tables if t.id in a.tab_label],
        "requirements": [{"id": r.id, "text": r.text, "source": r.source, "priority": r.priority,
                          "anchor": r.anchor, "sections": trace_by[r.id]["sections"], "covered": trace_by[r.id]["covered"]}
                         for r in d.requirements],
        "warnings": a.warnings,
        "stats": a.stats,
    }
    if d.meta["trace_table"] and d.requirements:
        cols, rows = trace_rows(a)
        view["appendix"] = [{"id": "_trace", "anchor": "sec-_trace", "heading": a.words["trace"],
                             "html": table_html(cols, rows, ["left"] * len(cols), None, None)}]
    return view


def dumps(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1, allow_nan=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------- 单文件网页
CSS = """
:root{--ink:#1d1d1f;--muted:#6b6b70;--line:#d9d9de;--accent:#1f5fbf;--bg:#fff;--soft:#f5f5f7}
@media (prefers-color-scheme:dark){:root{--ink:#e8e8ea;--muted:#a0a0a8;--line:#3a3a40;--accent:#7fb0ff;--bg:#16161a;--soft:#202026}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.8 "Noto Serif SC","Source Han Serif SC","Songti SC",SimSun,Georgia,serif}
main{max-width:820px;margin:0 auto;padding:40px 20px 80px}
h1,h2,h3,h4,h5,h6,.cap,figcaption,nav{font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif}
header.cover{margin:24px 0 36px;padding-bottom:20px;border-bottom:1px solid var(--line)}
header.cover h1{font-size:30px;line-height:1.35;margin:0 0 8px}
header.cover .sub{font-size:19px;color:var(--muted);margin:0 0 10px}
header.cover .meta{font-size:14px;color:var(--muted)}
nav.toc{background:var(--soft);border-radius:8px;padding:14px 18px;margin:0 0 32px;font-size:15px}
nav.toc b{display:block;margin-bottom:6px}
nav.toc a{color:inherit;text-decoration:none;display:block;padding:1px 0}
nav.toc a:hover{color:var(--accent)}
nav.toc .l2{padding-left:1.5em}nav.toc .l3{padding-left:3em}nav.toc .l4{padding-left:4.5em}
h2.h{font-size:23px;margin:36px 0 12px}h3.h{font-size:19px;margin:28px 0 10px}h4.h,h5.h{font-size:17px;margin:22px 0 8px}
h3.sub,h4.sub,h5.sub,h6.sub{font-size:16px;margin:18px 0 6px}
.num{color:var(--accent);margin-right:.15em}
p{margin:0 0 12px}
a{color:var(--accent)}
figure.fig{margin:20px 0;text-align:center;break-inside:avoid}
figure.fig img{max-width:100%;height:auto;background:#fff}
figure.missing .ph{border:1px dashed var(--line);padding:40px 12px;color:var(--muted);font-size:14px}
figcaption,.cap{font-size:14px;color:var(--muted);margin:6px 0}
.tbl{margin:18px 0;overflow-x:auto}.tbl .cap{text-align:center}
table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.6}
th,td{border:1px solid var(--line);padding:5px 8px;vertical-align:top}
th{background:var(--soft)}
.note{font-size:13px;color:var(--muted)}
pre{background:var(--soft);padding:10px 12px;border-radius:6px;overflow-x:auto;font-size:13px;line-height:1.5}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.92em}
blockquote{margin:12px 0;padding:2px 14px;border-left:3px solid var(--line);color:var(--muted)}
.omitted{color:var(--muted);font-size:14px}
@page{size:A4;margin:25mm 22mm}
@media print{body{font-size:11.5pt;background:#fff;color:#000}main{max-width:none;padding:0}nav.toc{background:none;border:1px solid #ccc}
h2.h,h3.h,h4.h{break-after:avoid}a{color:inherit;text-decoration:none}}
"""


def to_html(a: Assembled) -> str:
    d, W = a.doc, a.words
    lang = "zh-CN" if d.meta["lang"] == "zh-CN" else "en"
    out = [f'<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
           f'<meta name="generator" content="mengos document">\n'
           f'<title>{html.escape(d.title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n<main>\n<header class="cover">\n'
           f'<h1>{html.escape(d.title)}</h1>\n']
    if d.subtitle:
        out.append(f'<p class="sub">{html.escape(d.subtitle)}</p>\n')
    ml = _meta_line(a)
    if ml:
        out.append(f'<p class="meta">{html.escape(ml)}</p>\n')
    out.append("</header>\n")
    if d.meta["toc"]:
        out.append(f'<nav class="toc"><b>{html.escape(W["toc"])}</b>\n')
        for o in a.sections:
            out.append(f'<a class="l{o.sec.level}" href="#{o.anchor}">{html.escape(o.display)}</a>\n')
        if d.meta["trace_table"] and d.requirements:
            out.append(f'<a class="l1" href="#sec-_trace">{html.escape(W["trace"])}</a>\n')
        out.append("</nav>\n")
    for o in a.sections:
        out.append(f'<section id="{o.anchor}" data-level="{o.sec.level}">\n{heading_html(o)}{section_body_html(a, o)}</section>\n')
    if d.meta["trace_table"] and d.requirements:
        cols, rows = trace_rows(a)
        out.append(f'<section id="sec-_trace" data-level="1">\n<h2 class="h">{html.escape(W["trace"])}</h2>\n'
                   f'{table_html(cols, rows, ["left"] * len(cols), None, None)}</section>\n')
    out.append("</main>\n</body>\n</html>\n")
    return "".join(out)
