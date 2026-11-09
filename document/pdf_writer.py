"""PDF 导出：纯 Python 从已装配的文档模型直接排版（reportlab），与 Word、网页同源；逐字节确定。

排版约定：A4，页边距上下 25 mm、左右 22 mm（同网页打印样式）；正文衬线（Noto Serif SC）、标题无衬线（Noto Sans SC），
字号行距照 Word 版的 zh-CN / en 两套；图题在图下，表题在表上；目录带页码与内部链接（两遍排版）；按标题层级写 PDF 书签；
位图用文档模型的嵌入副本（长边 ≤1600 px 的 JPEG），SVG 转矢量，转不了的原位画占位框并列入提醒。
字体随包带（fonts/，SIL OFL 1.1），嵌入时子集化；不读系统字体、不写当前时间（reportlab invariant 模式）。
"""
from __future__ import annotations

import io
import re
from contextlib import contextmanager
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from assemble import EAST_ASIAN, MD, Assembled, SecOut, inline_text
from render import inline_alt, trace_rows

FONT_DIR = Path(__file__).resolve().parent / "fonts"
SERIF, SERIF_B = "NotoSerifSC-Regular", "NotoSerifSC-Bold"
SANS, SANS_B = "NotoSansSC-Regular", "NotoSansSC-Bold"
_FONT_FILES = {SERIF: "NotoSerifSC-Regular.ttf", SERIF_B: "NotoSerifSC-Bold.ttf",
               SANS: "NotoSansSC-Regular.ttf", SANS_B: "NotoSansSC-Bold.ttf"}

# 与 Word 版同一套字号行距（docx_writer.PROFILES）；页边距按网页打印样式。
PROFILES = {
    "zh-CN": {"size": 12, "line": 1.5, "indent": 24, "after": 0, "heads": [16, 15, 14, 12], "title": 22, "subtitle": 16, "small": 10.5},
    "en": {"size": 11, "line": 1.15, "indent": 0, "after": 6, "heads": [16, 14, 12, 11], "title": 24, "subtitle": 15, "small": 9.5},
}
MARGIN_TB, MARGIN_LR = 25 * mm, 22 * mm
TEXT_W = A4[0] - 2 * MARGIN_LR
MAX_FIG_H = 200 * mm
LINK = "#1F5FBF"
GRID = colors.HexColor("#B0B0B0")
BULLETS = ["•", "◦", "▪", "▫"]
_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿\ud800-\udfff]")
MAX_PASSES = 4


# ---------------------------------------------------------------- 字体
def _register_fonts():
    for name, fn in _FONT_FILES.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / fn)))
    pdfmetrics.registerFontFamily(SERIF, normal=SERIF, bold=SERIF_B, italic=SERIF, boldItalic=SERIF_B)
    pdfmetrics.registerFontFamily(SANS, normal=SANS, bold=SANS_B, italic=SANS, boldItalic=SANS_B)
    from reportlab.graphics import shapes
    shapes.STATE_DEFAULTS["fontName"] = SANS        # 矢量图起始字体默认是 Helvetica（未嵌入）


@contextmanager
def _svg_fonts():
    """SVG 里的字体名一律映射到随包字体，不查系统字体（svglib 默认会调 fc-match 并读系统目录，结果随机器而变）。"""
    from svglib import fonts as sf
    fm = sf.get_global_font_map()
    old = fm.find_font

    def find(font_name, weight="normal", style="normal"):
        name = (font_name or "").lower()
        serif = ("serif" in name and "sans" not in name) or any(k in name for k in ("times", "song", "宋", "georgia"))
        bold = str(weight).lower() in ("bold", "bolder", "600", "700", "800", "900")
        return ((SERIF_B if bold else SERIF) if serif else (SANS_B if bold else SANS)), True

    fm.find_font = find
    try:
        yield
    finally:
        fm.find_font = old


# ---------------------------------------------------------------- 流式元素
class _Anchor(Flowable):
    """零高度的书签落点：内部链接（[[sec:]]、[[fig:]]、[[tab:]]、目录）跳到这里。"""

    def __init__(self, name):
        super().__init__()
        self.name = name

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        self.canv.bookmarkHorizontal(self.name, 0, 0)


class _Heading(Paragraph):
    """标题段落：书签落点写在段落自己里（<a name>），随标题一起换页，不会被孤立在上一页末尾。"""

    def __init__(self, text, style, level, anchor, title):
        super().__init__(f'<a name="{anchor}"/>{text}', style)
        self.level, self.anchor, self.title = level, anchor, title


class _TocLine(Flowable):
    """目录一行：标题（可点）、页码靠右、细点线。"""

    def __init__(self, text, level, anchor, page, style):
        super().__init__()
        self.level, self.anchor, self.page, self.style, self.text = level, anchor, page, style, text
        self.indent = (level - 1) * 14

    def wrap(self, aw, ah):
        self.aw = aw
        self.p = Paragraph(escape(self.text), self.style)
        _, self.ph = self.p.wrap(aw - self.indent - 34, ah)
        self.h = self.ph + 5
        return aw, self.h

    def draw(self):
        c = self.canv
        self.p.drawOn(c, self.indent, 3)
        base = 3 + self.ph - getattr(self.p.blPara, "ascent", self.style.fontSize)
        c.setFont(SANS, self.style.fontSize - 1)
        c.setFillColor(colors.HexColor("#444444"))
        c.drawRightString(self.aw, base, str(self.page))
        c.setStrokeColor(colors.HexColor("#CCCCCC"))
        c.setDash(1, 2)
        c.line(self.indent, 1.5, self.aw, 1.5)
        c.setDash()
        c.linkRect("", self.anchor, (0, 0, self.aw, self.h), relative=1, thickness=0)


class _Doc(BaseDocTemplate):
    def __init__(self, buf, meta, cover):
        super().__init__(buf, pagesize=A4, leftMargin=MARGIN_LR, rightMargin=MARGIN_LR, topMargin=MARGIN_TB,
                         bottomMargin=MARGIN_TB, title=meta["title"], author=meta["author"], subject=meta["subject"],
                         creator="mengos document", invariant=1,
                         initialFontName=SANS, initialFontSize=10)      # 画布起始字体也用随包字体，页面资源里不留未嵌入的 Helvetica
        self.cover = cover
        self.pages: dict[str, int] = {}
        self._last_level = 0
        frame = Frame(MARGIN_LR, MARGIN_TB, TEXT_W, A4[1] - 2 * MARGIN_TB, id="body",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._footer)])

    def _footer(self, canv, doc):
        if self.cover and doc.page == 1:
            return
        canv.saveState()
        canv.setFont(SANS, 9)
        canv.setFillColor(colors.HexColor("#555555"))
        canv.drawCentredString(A4[0] / 2, 14 * mm, str(doc.page))
        canv.restoreState()

    def afterFlowable(self, fl):
        if isinstance(fl, _Heading):
            self.pages[fl.anchor] = self.page
            level = min(fl.level, self._last_level + 1)          # PDF 书签层级不能跳级
            self._last_level = level
            self.canv.addOutlineEntry(fl.title, fl.anchor, level - 1, closed=0)


# ---------------------------------------------------------------- 排版
class _Builder:
    def __init__(self, a: Assembled):
        self.a = a
        self.zh = a.doc.meta["lang"] == "zh-CN"
        self.P = PROFILES["zh-CN" if self.zh else "en"]
        self.warnings: list[dict] = []
        self.texts: list[str] = []          # 排进版面的全部文字，用来查缺字
        self.svg_failed: set[str] = set()
        self._styles()

    # -------------------------------------------------------- 样式
    def _styles(self):
        P = self.P
        size, lead = P["size"], round(P["size"] * P["line"], 2)
        wrap = "CJK"
        mk = lambda name, **kw: ParagraphStyle(name, wordWrap=wrap, **kw)
        self.body = mk("body", fontName=SERIF, fontSize=size, leading=lead, firstLineIndent=P["indent"],
                       spaceAfter=P["after"], alignment=TA_LEFT)
        self.plain = mk("plain", parent=self.body, firstLineIndent=0)
        self.heads = [mk(f"h{i}", fontName=SANS_B, fontSize=P["heads"][i - 1], leading=P["heads"][i - 1] * 1.3,
                         spaceBefore=18 if i == 1 else 12, spaceAfter=6, keepWithNext=1) for i in range(1, 5)]
        self.sub = mk("sub", fontName=SANS_B, fontSize=size, leading=lead, spaceBefore=6, spaceAfter=3, keepWithNext=1)
        self.title = mk("title", fontName=SANS_B, fontSize=P["title"], leading=P["title"] * 1.3, alignment=TA_CENTER,
                        spaceAfter=12)
        self.subtitle = mk("subtitle", fontName=SERIF, fontSize=P["subtitle"], leading=P["subtitle"] * 1.4,
                           alignment=TA_CENTER, spaceAfter=10)
        self.meta_line = mk("meta", fontName=SERIF, fontSize=P["small"] + 1, leading=(P["small"] + 1) * 1.5,
                            alignment=TA_CENTER, textColor=colors.HexColor("#595959"))
        self.caption = mk("caption", fontName=SANS, fontSize=P["small"], leading=P["small"] * 1.4, alignment=TA_CENTER,
                          spaceBefore=3, spaceAfter=9)
        self.tcaption = mk("tcaption", parent=self.caption, spaceBefore=9, spaceAfter=3, keepWithNext=1)
        self.cell = mk("cell", fontName=SERIF, fontSize=P["small"], leading=P["small"] * 1.35)
        self.cell_head = mk("cellh", parent=self.cell, fontName=SANS_B)
        self.note = mk("note", parent=self.cell, textColor=colors.HexColor("#444444"), spaceBefore=2, spaceAfter=6)
        self.code = mk("code", fontName=SANS, fontSize=size - 1.5, leading=(size - 1.5) * 1.35, firstLineIndent=0,
                       backColor=colors.HexColor("#F2F2F2"), borderPadding=4, spaceBefore=4, spaceAfter=8)
        self.toc_head = mk("tochead", fontName=SANS_B, fontSize=P["heads"][0], leading=P["heads"][0] * 1.3,
                           alignment=TA_CENTER, spaceAfter=10)
        self.toc = mk("toc", fontName=SERIF, fontSize=P["size"] - 1, leading=(P["size"] - 1) * 1.35)
        self.placeholder = mk("ph", fontName=SANS, fontSize=P["small"], leading=P["small"] * 1.4, alignment=TA_CENTER,
                              textColor=colors.HexColor("#666666"))

    # -------------------------------------------------------- 文字 → reportlab 迷你标记
    def _t(self, s: str) -> str:
        s = _BAD.sub("", s)
        self.texts.append(s)
        return escape(s).replace("\n", "<br/>")

    def _inline(self, children, base_bold=False) -> str:
        out, state = [], {"b": 0, "i": 0, "s": 0}
        open_tags: list[str] = []
        kids = list(children or [])
        last = ""
        link_open = False
        for i, c in enumerate(kids):
            ty = c.type
            if ty == "text":
                if c.content:
                    out.append(self._t(c.content))
                    last = c.content
            elif ty == "code_inline":
                out.append(f'<font name="{SANS}" backColor="#F2F2F2">{self._t(c.content)}</font>')
                last = c.content
            elif ty == "softbreak":
                nxt = next((k.content for k in kids[i + 1:] if k.type in ("text", "code_inline") and k.content), "")
                if not (last and nxt and EAST_ASIAN.match(last[-1]) and EAST_ASIAN.match(nxt[0])):
                    out.append(" ")
            elif ty == "hardbreak":
                out.append("<br/>")
            elif ty == "strong_open":
                out.append("<b>")
            elif ty == "strong_close":
                out.append("</b>")
            elif ty == "em_open":
                out.append("<i>")
            elif ty == "em_close":
                out.append("</i>")
            elif ty == "s_open":
                out.append("<strike>")
            elif ty == "s_close":
                out.append("</strike>")
            elif ty == "link_open":
                href = c.attrGet("href") or ""
                if href.startswith("#") and re.fullmatch(r"#[A-Za-z0-9_\-]+", href):
                    out.append(f'<a href="{href}" color="{LINK}">')
                    link_open = True
                elif re.match(r"(?i)(https?|mailto):", href):
                    out.append(f'<a href="{escape(href, {chr(34): "&quot;"})}" color="{LINK}">')
                    link_open = True
            elif ty == "link_close":
                if link_open:
                    out.append("</a>")
                    link_open = False
            elif ty == "image":
                out.append(self._t(f"〔{self.a.words['img_omitted']}：{inline_alt(c)}〕"))
        if link_open:
            out.append("</a>")
        s = "".join(out)
        return f"<b>{s}</b>" if base_bold else s

    # -------------------------------------------------------- Markdown 块
    def _blocks(self, o: SecOut, text: str) -> list:
        tokens = MD.parse(text, o.env())
        story, lists, quote = [], [], 0
        pending = []          # 列表项：[是否尚未写出项目符号, 符号]
        i = 0

        def indent():
            return 21 * len(lists) + 14 * quote

        def para(markup, first_item=None, style=None):
            st = ParagraphStyle("li", parent=style or self.plain, leftIndent=indent(),
                                textColor=colors.HexColor("#555555") if quote else (style or self.plain).textColor,
                                spaceAfter=2 if lists else (style or self.plain).spaceAfter)
            if first_item:
                st.bulletIndent = indent() - 21
                st.bulletFontName = SERIF
                return Paragraph(markup, st, bulletText=first_item)
            return Paragraph(markup, st)

        def flush_item():
            if pending and pending[-1][0]:
                story.append(para("", pending[-1][1]))
                pending[-1][0] = False

        while i < len(tokens):
            t = tokens[i]
            ty = t.type
            if pending and pending[-1][0] and ty in ("fence", "code_block", "heading_open", "bullet_list_open",
                                                      "ordered_list_open", "table_open", "hr", "blockquote_open"):
                flush_item()
            if ty == "paragraph_open":
                markup = self._inline(tokens[i + 1].children)
                if lists:
                    first = None
                    if pending and pending[-1][0]:
                        first, pending[-1][0] = pending[-1][1], False
                    story.append(para(markup, first))
                elif quote:
                    story.append(para(markup, style=self.plain))
                else:
                    story.append(Paragraph(markup, self.body))
                i += 3
                continue
            if ty == "heading_open":
                story.append(Paragraph(self._inline(tokens[i + 1].children), self.sub))
                i += 3
                continue
            if ty in ("bullet_list_open", "ordered_list_open"):
                st = t.attrGet("start")
                start = int(st) if ty == "ordered_list_open" and st is not None else 1
                lists.append({"ordered": ty == "ordered_list_open", "n": start - 1})
            elif ty in ("bullet_list_close", "ordered_list_close"):
                lists.pop()
            elif ty == "list_item_open":
                lists[-1]["n"] += 1
                L = lists[-1]
                prefix = f"{L['n']}{t.markup or '.'}" if L["ordered"] else BULLETS[(len(lists) - 1) % len(BULLETS)]
                pending.append([True, prefix])
            elif ty == "list_item_close":
                flush_item()
                pending.pop()
            elif ty == "blockquote_open":
                quote += 1
            elif ty == "blockquote_close":
                quote -= 1
            elif ty in ("fence", "code_block"):
                code = _BAD.sub("", t.content.rstrip("\n"))
                self.texts.append(code)
                esc = escape(code)
                esc = re.sub(r"(?m)^( +)", lambda m: "&nbsp;" * len(m.group(1)), esc)
                esc = re.sub(r"  +", lambda m: " " + "&nbsp;" * (len(m.group(0)) - 1), esc).replace("\t", "&nbsp;" * 4)
                st = ParagraphStyle("codeb", parent=self.code, leftIndent=indent() + 4, rightIndent=4)
                story.append(Paragraph(esc.replace("\n", "<br/>"), st))
            elif ty == "hr":
                story.append(Table([[""]], colWidths=[TEXT_W], rowHeights=[6],
                                   style=[("FONTNAME", (0, 0), (-1, -1), SERIF),
                                          ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.HexColor("#A0A0A0"))]))
            elif ty == "table_open":
                j = i
                while tokens[j].type != "table_close":
                    j += 1
                story.append(self._md_table(tokens[i:j + 1]))
                story.append(Spacer(1, 6))
                i = j + 1
                continue
            i += 1
        return story

    def _md_table(self, tokens):
        header, rows, cur, aligns = [], [], None, []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t.type == "tr_open":
                cur = []
            elif t.type == "tr_close":
                if header:
                    rows.append(cur)
                else:
                    header.append(cur)
            elif t.type in ("th_open", "td_open"):
                m = re.search(r"text-align:(left|center|right)", t.attrGet("style") or "")
                if t.type == "th_open":
                    aligns.append(m.group(1) if m else "left")
                cur.append(tokens[i + 1].children)
                i += 3
                continue
            i += 1
        head = header[0] if header else []
        return self._table(head, rows, aligns or ["left"] * len(head), inline=True)

    # -------------------------------------------------------- 表
    def _widths(self, columns, rows, inline):
        """按内容定列宽：与 Word 版同一算法（汉字计 2 个单位、其余 1 个，封顶 40）。"""
        def w(cell):
            s = inline_text(cell) if inline else cell
            return max((sum(2 if EAST_ASIAN.match(ch) else 1 for ch in ln) for ln in s.split("\n")), default=0)
        unit, pad = self.P["small"] / 2, 11
        n = len(columns)
        need = [max(2, min(40, max([w(columns[k])] + [w(r[k]) for r in rows if k < len(r)]))) * unit + pad
                for k in range(n)]
        total = TEXT_W
        if sum(need) <= total:
            return [x * total / sum(need) for x in need]
        out, budget, rest = [0.0] * n, total, sorted(range(n), key=lambda k: need[k])
        while rest and need[rest[0]] <= budget / len(rest):
            k = rest.pop(0)
            out[k] = need[k]
            budget -= need[k]
        demand = sum(need[k] for k in rest)
        for k in rest:
            out[k] = budget * need[k] / demand
        return out

    def _table(self, columns, rows, align, inline=False):
        n = len(columns)
        al = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}

        def cell(c, k, head):
            st = ParagraphStyle("c", parent=self.cell_head if head else self.cell, alignment=al.get(align[k] if k < len(align) else "left", TA_LEFT))
            return Paragraph(self._inline(c) if inline else self._t(c), st)

        data = [[cell(c, k, True) for k, c in enumerate(columns)]]
        for r in rows:
            data.append([cell(r[k] if k < len(r) else ([] if inline else ""), k, False) for k in range(n)])
        t = Table(data, colWidths=self._widths(columns, rows, inline), repeatRows=1, splitInRow=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), SERIF),          # 表格默认字体是 Helvetica（未嵌入），一律换成随包字体
            ("GRID", (0, 0), (-1, -1), 0.5, GRID),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return t

    # -------------------------------------------------------- 图
    def _figure(self, f) -> list:
        a = self.a
        cap = a.fig_caption(f)
        w_px, h_px = f.px if f.px else (4.0, 3.0)
        width = f.width * TEXT_W
        height = width * h_px / w_px
        if height > MAX_FIG_H:
            width, height = width * MAX_FIG_H / height, MAX_FIG_H
        width, height = max(width, 4), max(height, 4)
        pic = None
        if f.kind == "svg":
            pic = self._svg(f, width, height)
            if pic is None:
                self.svg_failed.add(f.id)
                self.warnings.append({"where": f"doc.figures[{f.index}]", "code": "pdf_figure_unsupported",
                                      "message": f"图 {f.id} 的 SVG 无法在 PDF 中绘制，已在原位放占位框（Word 与网页不受影响）"})
                pic = Table([[Paragraph(self._t("此图无法在 PDF 中绘制" if self.zh else "This figure cannot be drawn in the PDF"),
                                        self.placeholder)]], colWidths=[width], rowHeights=[height])
                pic.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), SERIF), ("BOX", (0, 0), (-1, -1), 0.8, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        else:
            pic = Image(io.BytesIO(f.view_data), width=width, height=height)
        pic.hAlign = "CENTER"
        cp = Paragraph(self._t(cap), self.caption)
        return [KeepTogether([_Anchor(f"fig-{f.id}"), Spacer(1, 6), pic, cp])]

    def _svg(self, f, width, height):
        try:
            from svglib.svglib import svg2rlg
            with _svg_fonts():
                dr = svg2rlg(io.BytesIO(f.data))
            if dr is None or not dr.width or not dr.height:
                return None
            sx, sy = width / dr.width, height / dr.height
            s = min(sx, sy)
            dr.scale(s, s)
            dr.width, dr.height = dr.width * s, dr.height * s
            self._collect_svg_text(dr)
            return dr
        except Exception:     # noqa: BLE001 —— 任何转换失败都落到占位框，由提醒告知
            return None

    def _collect_svg_text(self, node):
        for ch in getattr(node, "contents", []) or []:
            if hasattr(ch, "text") and isinstance(ch.text, str):
                self.texts.append(ch.text)
            self._collect_svg_text(ch)

    # -------------------------------------------------------- 封面、目录
    def _front(self, pages) -> list:
        a, d = self.a, self.a.doc
        m = d.meta
        out = []
        if m["cover"]:
            out.append(Spacer(1, 150))
        out.append(Paragraph(self._t(d.title), self.title))
        if d.subtitle:
            out.append(Paragraph(self._t(d.subtitle), self.subtitle))
        labels = (("org", "单位"), ("author", "作者"), ("date", "日期"), ("version", "版本")) if self.zh else \
            (("org", "Organization"), ("author", "Author"), ("date", "Date"), ("version", "Version"))
        lines = [(f"{lab}：{m[k]}" if self.zh else f"{lab}: {m[k]}") for k, lab in labels if m[k]]
        if lines:
            if m["cover"]:
                out.append(Spacer(1, 120))
                out += [Paragraph(self._t(ln), ParagraphStyle("cv", parent=self.meta_line, textColor=colors.black,
                                                              fontSize=self.P["size"], leading=self.P["size"] * 1.8))
                        for ln in lines]
            else:
                out.append(Paragraph(self._t(("　" if self.zh else "  ·  ").join(lines)), self.meta_line))
                out.append(Spacer(1, 12))
        if m["cover"]:
            out.append(PageBreak())
        if m["toc"]:
            out.append(Paragraph(self._t(a.words["toc"]), self.toc_head))
            entries = [(o.sec.level, o.display, o.anchor) for o in a.sections]
            if m["trace_table"] and d.requirements:
                entries.append((1, a.words["trace"], "sec-_trace"))
            for lv, text, anchor in entries:
                self.texts.append(text)
                out.append(_TocLine(text, lv, anchor, pages.get(anchor, 0), self.toc))
            out.append(Spacer(1, 12))
            if m["cover"]:
                out.append(PageBreak())
        return out

    # -------------------------------------------------------- 全文
    def story(self, pages) -> list:
        a = self.a
        s = self._front(pages)
        figs, tabs = a.figures, a.tables
        for o in a.sections:
            s.append(_Heading(self._t(o.display), self.heads[o.sec.level - 1], o.sec.level, o.anchor, o.display))
            for sg in o.segs:
                if sg.kind == "md":
                    if sg.text.strip():
                        s += self._blocks(o, sg.text)
                elif sg.kind == "fig":
                    s += self._figure(figs[sg.ref])
                else:
                    t = tabs[sg.ref]
                    s.append(Paragraph(f'<a name="tab-{t.id}"/>' + self._t(a.tab_caption(t)), self.tcaption))
                    s.append(self._table(t.columns, t.rows, t.align))
                    if t.note:
                        s.append(Paragraph(self._t(a.words["note"] + t.note), self.note))
                    else:
                        s.append(Spacer(1, 6))
        if a.doc.meta["trace_table"] and a.doc.requirements:
            s.append(_Heading(self._t(a.words["trace"]), self.heads[0], 1, "sec-_trace", a.words["trace"]))
            cols, rows = trace_rows(a)
            s.append(self._table(cols, rows, ["left"] * len(cols)))
        return s


def _missing_glyphs(texts) -> list[str]:
    cmaps = [pdfmetrics.getFont(n).face.charToGlyph for n in (SERIF, SANS)]
    seen: dict[str, int] = {}
    for t in texts:
        for ch in t:
            if ch.isspace() or ord(ch) < 0x20:
                continue
            if not all(ord(ch) in cm for cm in cmaps):
                seen[ch] = seen.get(ch, 0) + 1
    return sorted(seen)


def to_pdf(a: Assembled) -> tuple[bytes, list[dict]]:
    """→ (PDF 字节, 提醒列表)。两遍排版：第一遍量出各标题所在页，第二遍把页码填进目录；页数变了就再排一遍。"""
    _register_fonts()
    d = a.doc
    meta = {"title": d.title, "author": d.meta["author"] or d.meta["org"] or "", "subject": d.subtitle or ""}
    pages: dict[str, int] = {}
    warnings: list[dict] = []
    for _ in range(MAX_PASSES):
        b = _Builder(a)
        buf = io.BytesIO()
        doc = _Doc(buf, meta, d.meta["cover"])
        doc.build(b.story(pages))
        warnings = b.warnings
        if doc.pages == pages:
            break
        pages = dict(doc.pages)
    missing = _missing_glyphs(b.texts)
    if missing:
        shown = "".join(missing[:20])
        warnings.append({"where": "doc", "code": "pdf_glyph_missing",
                         "message": f"PDF 随包字体没有这些字符（共 {len(missing)} 个，前 {min(20, len(missing))} 个：{shown}），"
                                    "它们在 PDF 里会显示为空框"})
    return buf.getvalue(), warnings
