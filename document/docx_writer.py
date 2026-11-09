"""Word 导出：A4，章节、图、表编号与 Markdown 一致；目录、页码、书签与内部链接；文件逐字节确定。

排版约定（中文）：正文宋体小四、1.5 倍行距、首行缩进 2 字；标题黑体；图题在图下，表题在表上。
目录是 Word 的目录域，预先填好条目；在 Word 里打开时会提示更新域，更新后带页码。
"""
from __future__ import annotations

import datetime as dt
import io
import re
import struct
import zipfile
import zlib

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.shape import CT_Inline
from docx.shared import Emu, Mm, Pt, RGBColor
from docx.table import _Cell
from lxml import etree

from assemble import EAST_ASIAN, MD, Assembled, SecOut, inline_text
from render import inline_alt, trace_rows

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff\ud800-\udfff]")   # XML 1.0 不允许的字符（实体解码后可能出现）
SVG_EXT_URI = "{96DAC541-7B7A-43D3-8B79-37D633B846F1}"
ASVG_NS = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

PROFILES = {
    "zh-CN": {"body": ("Times New Roman", "宋体"), "head": ("Arial", "黑体"), "size": 12, "line": 1.5,
              "indent": 24, "after": 0, "heads": [16, 15, 14, 12], "title": 22, "subtitle": 16, "small": 10.5,
              "margins": (25.4, 31.8), "lang": ("en-US", "zh-CN")},
    "en": {"body": ("Times New Roman", "宋体"), "head": ("Arial", "黑体"), "size": 11, "line": 1.15,
           "indent": 0, "after": 6, "heads": [16, 14, 12, 11], "title": 24, "subtitle": 15, "small": 9.5,
           "margins": (25.4, 25.4), "lang": ("en-US", "zh-CN")},
}
BULLETS = ["•", "◦", "▪", "▫"]
LINK_BLUE = "1F5FBF"

PPR_ORDER = ["w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr", "w:widowControl", "w:numPr",
             "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
             "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
             "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
             "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle",
             "w:rPr", "w:sectPr", "w:pPrChange"]
RPR_ORDER = ["w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps", "w:strike", "w:dstrike",
             "w:outline", "w:shadow", "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden",
             "w:color", "w:spacing", "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
             "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout",
             "w:specVanish", "w:oMath"]


def _put(parent, el, order):
    """按 schema 规定的子元素顺序插入（Word 对顺序很严格）。"""
    tag = el.tag
    names = [qn(x) for x in order]
    idx = names.index(tag)
    later = set(names[idx + 1:])
    for old in parent.findall(tag):
        parent.remove(old)
    for i, child in enumerate(parent):
        if child.tag in later:
            parent.insert(i, el)
            return el
    parent.append(el)
    return el


def _el(tag, **attrs):
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(qn(k), str(v))
    return e


def _fonts(rpr, latin, east):
    f = _el("w:rFonts", **{"w:ascii": latin, "w:hAnsi": latin, "w:eastAsia": east, "w:cs": latin})
    _put(rpr, f, RPR_ORDER)


def _style_fonts(style, latin, east, size=None, bold=None, color="000000", lang=None):
    rpr = style.element.get_or_add_rPr()
    _fonts(rpr, latin, east)
    if bold is not None:
        style.font.bold = bold
    if size is not None:
        style.font.size = Pt(size)
    style.font.color.rgb = RGBColor.from_string(color)
    style.font.italic = False
    if lang:
        _put(rpr, _el("w:lang", **{"w:val": lang[0], "w:eastAsia": lang[1]}), RPR_ORDER)


def _png_box(w: int, h: int) -> bytes:
    """SVG 的后备位图：浅灰框。新版 Word 显示 SVG 本身，旧版本显示这个框。"""
    edge, fill = b"\xb0\xb0\xb0", b"\xf2\xf2\xf2"
    rows = []
    for y in range(h):
        if y in (0, h - 1):
            rows.append(b"\x00" + edge * w)
        else:
            rows.append(b"\x00" + edge + fill * (w - 2) + edge)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


class _Writer:
    def __init__(self, a: Assembled):
        self.a = a
        self.lang = a.doc.meta["lang"]
        self.P = PROFILES[self.lang]
        self.doc = Document()
        self.bm_id = 0
        self.svg_n = 0
        self.img_n = 0
        self.last_spacer = None
        self.bookmarks = {o.anchor for o in a.sections} | {f"fig-{f}" for f in a.fig_label} | \
            {f"tab-{t}" for t in a.tab_label} | \
            ({"sec-_trace"} if a.doc.meta["trace_table"] and a.doc.requirements else set())
        self._setup()

    # ------------------------------------------------------------ 版式与样式
    def _setup(self):
        d, P = self.doc, self.P
        sec = d.sections[0]
        sec.page_width, sec.page_height = Mm(210), Mm(297)
        tb, lr = P["margins"]
        sec.top_margin = sec.bottom_margin = Mm(tb)
        sec.left_margin = sec.right_margin = Mm(lr)
        sec.header_distance = sec.footer_distance = Mm(15)
        self.text_width = sec.page_width - sec.left_margin - sec.right_margin

        st = d.styles
        normal = st["Normal"]
        _style_fonts(normal, *P["body"], size=P["size"], lang=P["lang"])
        pf = normal.paragraph_format
        pf.line_spacing = P["line"]
        pf.space_before, pf.space_after = Pt(0), Pt(P["after"])
        pf.first_line_indent = Pt(P["indent"]) if P["indent"] else None
        pf.widow_control = True

        for lv in range(1, 5):
            h = st[f"Heading {lv}"]
            _style_fonts(h, *P["head"], size=P["heads"][lv - 1], bold=True)
            hf = h.paragraph_format
            hf.first_line_indent = Pt(0)
            hf.space_before, hf.space_after = Pt(18 if lv == 1 else 12), Pt(6)
            hf.line_spacing = 1.25
            hf.keep_with_next = True
        t = st["Title"]
        _style_fonts(t, *P["head"], size=P["title"], bold=True)
        t.element.get_or_add_pPr()
        for b in t.element.pPr.findall(qn("w:pBdr")):
            t.element.pPr.remove(b)
        t.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        t.paragraph_format.first_line_indent = Pt(0)
        t.paragraph_format.space_after = Pt(12)
        sub = st["Subtitle"]
        _style_fonts(sub, *P["body"], size=P["subtitle"], bold=False)
        sub.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.paragraph_format.first_line_indent = Pt(0)
        cap = st["Caption"]
        _style_fonts(cap, *P["head"], size=P["small"], bold=False)
        cap.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.first_line_indent = Pt(0)
        cap.paragraph_format.space_before, cap.paragraph_format.space_after = Pt(3), Pt(9)
        cap.paragraph_format.keep_with_next = False
        th = st["TOC Heading"]
        _style_fonts(th, *P["head"], size=P["heads"][0], bold=True)
        th.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        th.paragraph_format.first_line_indent = Pt(0)

        self.s_sub = st.add_style("mengos Subheading", WD_STYLE_TYPE.PARAGRAPH)
        self.s_sub.base_style = normal
        _style_fonts(self.s_sub, *P["head"], size=P["size"], bold=True)
        f = self.s_sub.paragraph_format
        f.first_line_indent, f.space_before, f.space_after, f.keep_with_next = Pt(0), Pt(6), Pt(3), True

        self.s_plain = st.add_style("mengos Plain", WD_STYLE_TYPE.PARAGRAPH)
        self.s_plain.base_style = normal
        self.s_plain.paragraph_format.first_line_indent = Pt(0)

        self.s_cell = st.add_style("mengos Table Text", WD_STYLE_TYPE.PARAGRAPH)
        self.s_cell.base_style = normal
        _style_fonts(self.s_cell, *P["body"], size=P["small"])
        cf = self.s_cell.paragraph_format
        cf.first_line_indent, cf.line_spacing, cf.space_after = Pt(0), 1.2, Pt(0)

        self.s_code = st.add_style("mengos Code", WD_STYLE_TYPE.PARAGRAPH)
        self.s_code.base_style = normal
        _style_fonts(self.s_code, "Consolas", P["body"][1], size=P["small"] - 0.5)
        kf = self.s_code.paragraph_format
        kf.first_line_indent, kf.line_spacing, kf.space_before, kf.space_after = Pt(0), 1.0, Pt(3), Pt(6)

        self.s_toc = []
        for lv in range(1, 5):
            s = st.add_style(f"toc {lv}", WD_STYLE_TYPE.PARAGRAPH)
            s.base_style = normal
            s.paragraph_format.first_line_indent = Pt(0)
            s.paragraph_format.left_indent = Pt((lv - 1) * 21)
            s.paragraph_format.space_after = Pt(0)
            self.s_toc.append(s)

        footer = sec.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.paragraph_format.first_line_indent = Pt(0)
        self._field(footer._p, "PAGE", "1")
        if self.a.doc.meta["cover"]:
            sec.different_first_page_header_footer = True

    # ------------------------------------------------------------ 低层
    def _bookmark(self, p, name, inner):
        self.bm_id += 1
        bid = self.bm_id
        p._p.append(_el("w:bookmarkStart", **{"w:id": bid, "w:name": name}))
        inner()
        p._p.append(_el("w:bookmarkEnd", **{"w:id": bid}))

    @staticmethod
    def _bm(anchor: str) -> str:
        return anchor.replace("-", "_", 1)

    def _run(self, text, *, bold=False, italic=False, strike=False, code=False, color=None, underline=False):
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        if code:
            rpr.append(_el("w:rFonts", **{"w:ascii": "Consolas", "w:hAnsi": "Consolas", "w:cs": "Consolas"}))
        if bold:
            rpr.append(OxmlElement("w:b"))
        if italic:
            rpr.append(OxmlElement("w:i"))
        if strike:
            rpr.append(OxmlElement("w:strike"))
        if color:
            rpr.append(_el("w:color", **{"w:val": color}))
        if underline:
            rpr.append(_el("w:u", **{"w:val": "single"}))
        if len(rpr):
            r.append(rpr)
        parts = _XML_BAD.sub("", text).split("\n")
        for k, part in enumerate(parts):
            if k:
                r.append(OxmlElement("w:br"))
            segs = part.split("\t")
            for j, s in enumerate(segs):
                if j:
                    r.append(OxmlElement("w:tab"))
                if s:
                    t = OxmlElement("w:t")
                    t.set(qn("xml:space"), "preserve")
                    t.text = s
                    r.append(t)
        return r

    def _field(self, parent, instr, placeholder="", dirty=False):
        b = OxmlElement("w:r")
        fb = _el("w:fldChar", **{"w:fldCharType": "begin"})
        if dirty:
            fb.set(qn("w:dirty"), "true")
        b.append(fb)
        parent.append(b)
        r = OxmlElement("w:r")
        it = OxmlElement("w:instrText")
        it.set(qn("xml:space"), "preserve")
        it.text = f" {instr} "
        r.append(it)
        parent.append(r)
        s = OxmlElement("w:r")
        s.append(_el("w:fldChar", **{"w:fldCharType": "separate"}))
        parent.append(s)
        if placeholder:
            parent.append(self._run(placeholder))
        e = OxmlElement("w:r")
        e.append(_el("w:fldChar", **{"w:fldCharType": "end"}))
        parent.append(e)

    def _para(self, style=None, align=None, indent=None, first=None, keep=False):
        p = self.doc.add_paragraph(style=style)
        pf = p.paragraph_format
        if align is not None:
            pf.alignment = align
        if indent is not None:
            pf.left_indent = Pt(indent)
        if first is not None:
            pf.first_line_indent = Pt(first)
        if keep:
            pf.keep_with_next = True
        return p

    def _border(self, p, sides=("top", "left", "bottom", "right"), val="single", color="B0B0B0", sz=6, space=4):
        ppr = p._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        for side in sides:
            bdr.append(_el(f"w:{side}", **{"w:val": val, "w:sz": sz, "w:space": space, "w:color": color}))
        _put(ppr, bdr, PPR_ORDER)

    def _shade(self, p, fill="F2F2F2"):
        _put(p._p.get_or_add_pPr(), _el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": fill}), PPR_ORDER)

    # ------------------------------------------------------------ 行内
    def _inline(self, p, children, base=None):
        base = dict(base or {})
        target = p._p
        state = {"bold": 0, "italic": 0, "strike": 0}
        link_style = None
        kids = list(children or [])
        last = ""
        for i, c in enumerate(kids):
            ty = c.type
            fmt = dict(bold=bool(state["bold"]) or base.get("bold", False), italic=bool(state["italic"]),
                       strike=bool(state["strike"]))
            if link_style:
                fmt.update(link_style)
            if ty == "text":
                if c.content:
                    target.append(self._run(c.content, **fmt))
                    last = c.content
            elif ty == "code_inline":
                target.append(self._run(c.content, code=True, **fmt))
                last = c.content
            elif ty == "softbreak":
                nxt = next((k.content for k in kids[i + 1:] if k.type in ("text", "code_inline") and k.content), "")
                if not (last and nxt and EAST_ASIAN.match(last[-1]) and EAST_ASIAN.match(nxt[0])):
                    target.append(self._run(" ", **fmt))
            elif ty == "hardbreak":
                r = OxmlElement("w:r")
                r.append(OxmlElement("w:br"))
                target.append(r)
            elif ty in ("strong_open", "strong_close"):
                state["bold"] += 1 if ty.endswith("open") else -1
            elif ty in ("em_open", "em_close"):
                state["italic"] += 1 if ty.endswith("open") else -1
            elif ty in ("s_open", "s_close"):
                state["strike"] += 1 if ty.endswith("open") else -1
            elif ty == "link_open":
                href = c.attrGet("href") or ""
                h = None
                if href.startswith("#"):
                    if href[1:] in self.bookmarks:
                        h = _el("w:hyperlink", **{"w:anchor": self._bm(href[1:]), "w:history": 1})
                        link_style = {}
                elif re.match(r"(?i)(https?|mailto):", href):
                    rid = self.doc.part.relate_to(href, RT.HYPERLINK, is_external=True)
                    h = _el("w:hyperlink", **{"r:id": rid, "w:history": 1})
                    link_style = {"color": LINK_BLUE, "underline": True}
                if h is not None:
                    p._p.append(h)
                    target = h
            elif ty == "link_close":
                target, link_style = p._p, None
            elif ty == "image":
                alt = inline_alt(c)
                target.append(self._run(f"〔{self.a.words['img_omitted']}：{alt}〕", **fmt))

    # ------------------------------------------------------------ 块
    def _blocks(self, o: SecOut, text: str):
        tokens = MD.parse(text, o.env())
        lists, items, quote = [], [], 0
        i = 0
        while i < len(tokens):
            t = tokens[i]
            ty = t.type
            if items and items[-1][0] and ty in ("fence", "code_block", "heading_open", "bullet_list_open",
                                                   "ordered_list_open", "table_open", "hr", "blockquote_open"):
                self._list_para(lists, items, quote, None)
            if ty == "paragraph_open":
                inline = tokens[i + 1]
                if lists:
                    self._list_para(lists, items, quote, inline.children)
                else:
                    p = self._para(indent=12 * quote if quote else None, first=0 if quote else None)
                    if quote:
                        self._border(p, sides=("left",), color="B0B0B0", sz=12, space=8)
                    self._inline(p, inline.children)
                i += 3
                continue
            if ty == "heading_open":
                p = self._para(style=self.s_sub)
                self._inline(p, tokens[i + 1].children)
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
                items.append([True, prefix])
            elif ty == "list_item_close":
                if items[-1][0]:
                    self._list_para(lists, items, quote, None)
                items.pop()
            elif ty == "blockquote_open":
                quote += 1
            elif ty == "blockquote_close":
                quote -= 1
            elif ty in ("fence", "code_block"):
                p = self._para(style=self.s_code, indent=self._list_indent(lists) + 12 * quote)
                self._shade(p)
                p._p.append(self._run(t.content.rstrip("\n"), code=True))
            elif ty == "hr":
                p = self._para(style=self.s_plain)
                self._border(p, sides=("bottom",), color="A0A0A0", sz=6, space=1)
            elif ty == "table_open":
                j = i
                while tokens[j].type != "table_close":
                    j += 1
                self._md_table(tokens[i:j + 1])
                i = j + 1
                continue
            i += 1

    def _list_indent(self, lists):
        return 21 * len(lists)

    def _list_para(self, lists, items, quote, children):
        first, prefix = items[-1]
        indent = self._list_indent(lists) + 12 * quote
        p = self._para(style=self.s_plain, indent=indent, first=-21 if first else 0)
        p.paragraph_format.space_after = Pt(2)
        if first:
            p._p.append(self._run(prefix + "\t"))
            items[-1][0] = False
        if children:
            self._inline(p, children)
        return p

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
                style = t.attrGet("style") or ""
                m = re.search(r"text-align:(left|center|right)", style)
                if t.type == "th_open":
                    aligns.append(m.group(1) if m else "left")
                cur.append(tokens[i + 1].children)
                i += 3
                continue
            i += 1
        head = header[0] if header else []
        self._table(head, rows, aligns or ["left"] * len(head), inline=True)

    def _table(self, columns, rows, align, inline=False):
        n = len(columns)
        tbl = self.doc.add_table(rows=1 + len(rows), cols=n)
        tbl.style = self.doc.styles["Table Grid"]
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        widths = self._widths(columns, rows, inline)
        for k, col in enumerate(tbl.columns):
            col.width = Emu(widths[k])
        # 逐行取单元格要一次遍历：按行号取行、取 row.cells 都会重建整张表，行数一多就成平方级
        grid = [[_Cell(tc, tbl) for tc in tr.tc_lst] for tr in tbl._tbl.tr_lst]
        for cells in grid:
            for k, cell in enumerate(cells):
                cell.width = Emu(widths[k])
        al = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT}
        tbl._tbl.tr_lst[0].get_or_add_trPr().append(_el("w:tblHeader"))
        for k, cell in enumerate(grid[0]):
            p = cell.paragraphs[0]
            p.style = self.s_cell
            p.alignment = al[align[k]] if k < len(align) else al["left"]
            if inline:
                self._inline(p, columns[k], base={"bold": True})
            else:
                p._p.append(self._run(columns[k], bold=True))
            cell._tc.get_or_add_tcPr().append(_el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": "F2F2F2"}))
        for r, row in enumerate(rows):
            for k, cell in enumerate(grid[r + 1]):
                p = cell.paragraphs[0]
                p.style = self.s_cell
                p.alignment = al[align[k]] if k < len(align) else al["left"]
                if k < len(row):
                    if inline:
                        self._inline(p, row[k])
                    else:
                        p._p.append(self._run(row[k]))
        self._spacer(6)
        return tbl

    def _spacer(self, pt):
        """表格后必须跟一个段落；用固定行高的空段落，最后一张表后用 1 pt，避免多出空白页。"""
        sp = self._para(style=self.s_plain)
        sp.paragraph_format.space_before = sp.paragraph_format.space_after = Pt(0)
        sp.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        sp.paragraph_format.line_spacing = Pt(pt)
        rpr = OxmlElement("w:rPr")
        rpr.append(_el("w:sz", **{"w:val": 2}))
        _put(sp._p.get_or_add_pPr(), rpr, PPR_ORDER)
        self.last_spacer = sp
        return sp

    def _widths(self, columns, rows, inline):
        """按内容定列宽：先算每列不换行所需的宽度（汉字计 2 个单位、其余 1 个，封顶 40），
        够放就按比例撑满版心；不够放时，短列取所需宽度，剩余宽度按需求比例分给长列。"""
        def w(cell):
            s = inline_text(cell) if inline else cell
            return max((sum(2 if EAST_ASIAN.match(ch) else 1 for ch in ln) for ln in s.split("\n")), default=0)
        unit, pad = Pt(self.P["small"]) / 2, Pt(11)
        n = len(columns)
        need = [max(2, min(40, max([w(columns[k])] + [w(r[k]) for r in rows if k < len(r)]))) * unit + pad
                for k in range(n)]
        total = int(self.text_width)
        if sum(need) <= total:
            return [int(x * total / sum(need)) for x in need]
        out, budget, rest = [0] * n, total, sorted(range(n), key=lambda k: need[k])
        while rest and need[rest[0]] <= budget / len(rest):
            k = rest.pop(0)
            out[k] = int(need[k])
            budget -= need[k]
        demand = sum(need[k] for k in rest)
        for k in rest:
            out[k] = int(budget * need[k] / demand)
        return out

    def _picture(self, run, data, ext, media, cx, cy, name):
        """嵌入位图。尺寸用已校验过的像素尺寸，不依赖按文件头猜格式（有些合法 JPEG 不带 JFIF/Exif 头）。"""
        self.img_n += 1
        part = Part(PackURI(f"/word/media/mengos_img{self.img_n}.{ext}"), media, data, self.doc.part.package)
        rid = self.doc.part.relate_to(part, RT.IMAGE)
        inline = CT_Inline.new_pic_inline(self.doc.part.next_id, rid, name, Emu(cx), Emu(cy))
        run._r.add_drawing(inline)
        return inline

    def _figure(self, f):
        a = self.a
        width = int(self.text_width * f.width)
        if f.px:
            w_px, h_px = f.px
        else:
            w_px, h_px = 4.0, 3.0
        height = int(width * h_px / w_px)
        max_h = int(Mm(200))
        if height > max_h:
            width, height = int(width * max_h / height), max_h
        width, height = max(width, int(Pt(4))), max(height, int(Pt(4)))      # 极端长宽比也不画成零
        p = self._para(style=self.s_plain, align=WD_ALIGN_PARAGRAPH.CENTER, keep=True)
        p.paragraph_format.space_before = Pt(6)
        run = p.add_run()
        if f.kind == "svg":
            scale = 300 / max(w_px, h_px)
            box = _png_box(max(8, min(600, round(w_px * scale))), max(8, min(600, round(h_px * scale))))
            inline = self._picture(run, box, "png", "image/png", width, height, f"{f.id}.png")
            self.svg_n += 1
            part = Part(PackURI(f"/word/media/mengos_svg{self.svg_n}.svg"), "image/svg+xml", f.data,
                        self.doc.part.package)
            rid = self.doc.part.relate_to(part, RT.IMAGE)
            blip = inline.find(".//{%s}blip" % A_NS)
            ext_lst = etree.SubElement(blip, "{%s}extLst" % A_NS)
            ext = etree.SubElement(ext_lst, "{%s}ext" % A_NS, uri=SVG_EXT_URI)
            svg = etree.SubElement(ext, "{%s}svgBlip" % ASVG_NS, nsmap={"asvg": ASVG_NS})
            svg.set("{%s}embed" % R_NS, rid)
        else:
            self._picture(run, f.view_data, "jpeg", f.view_type, width, height, f"{f.id}.jpeg")
        cap = self._para(style=self.doc.styles["Caption"])
        self._bookmark(cap, f"fig_{f.id}", lambda: cap._p.append(self._run(a.fig_caption(f))))

    # ------------------------------------------------------------ 组装
    def _heading(self, o: SecOut):
        p = self.doc.add_paragraph(style=self.doc.styles[f"Heading {o.sec.level}"])
        self._bookmark(p, self._bm(o.anchor), lambda: p._p.append(self._run(o.display)))

    def _front(self):
        d, a = self.a.doc, self.a
        m = d.meta
        zh = self.lang == "zh-CN"
        if m["cover"]:
            sp = self._para(style=self.s_plain)
            sp.paragraph_format.space_before = Pt(150)
        t = self.doc.add_paragraph(style=self.doc.styles["Title"])
        t._p.append(self._run(d.title))
        if d.subtitle:
            s = self.doc.add_paragraph(style=self.doc.styles["Subtitle"])
            s._p.append(self._run(d.subtitle))
        lines = []
        for k, lab in ((("org", "单位"), ("author", "作者"), ("date", "日期"), ("version", "版本")) if zh else
                       (("org", "Organization"), ("author", "Author"), ("date", "Date"), ("version", "Version"))):
            if m[k]:
                lines.append(f"{lab}：{m[k]}" if zh else f"{lab}: {m[k]}")
        if lines:
            if m["cover"]:
                gap = self._para(style=self.s_plain)
                gap.paragraph_format.space_before = Pt(120)
                for ln in lines:
                    p = self._para(style=self.s_plain, align=WD_ALIGN_PARAGRAPH.CENTER)
                    p._p.append(self._run(ln))
            else:
                p = self._para(style=self.s_plain, align=WD_ALIGN_PARAGRAPH.CENTER)
                p.paragraph_format.space_after = Pt(18)
                p._p.append(self._run(("　" if zh else "  ·  ").join(lines), color="595959"))
        if m["cover"]:
            self._page_break()
        if m["toc"]:
            self._toc()
            if m["cover"]:
                self._page_break()

    def _page_break(self):
        p = self._para(style=self.s_plain)
        p.add_run().add_break(WD_BREAK.PAGE)

    def _toc(self):
        a = self.a
        h = self.doc.add_paragraph(style=self.doc.styles["TOC Heading"])
        h._p.append(self._run(a.words["toc"]))
        entries = [(o.sec.level, o.display, o.anchor) for o in a.sections]
        if a.doc.meta["trace_table"] and a.doc.requirements:
            entries.append((1, a.words["trace"], "sec-_trace"))
        for k, (lv, text, anchor) in enumerate(entries):
            p = self.doc.add_paragraph(style=self.s_toc[lv - 1])
            if k == 0:
                b = OxmlElement("w:r")
                b.append(_el("w:fldChar", **{"w:fldCharType": "begin", "w:dirty": "true"}))
                p._p.append(b)
                r = OxmlElement("w:r")
                it = OxmlElement("w:instrText")
                it.set(qn("xml:space"), "preserve")
                it.text = ' TOC \\o "1-4" \\h \\z \\u '
                r.append(it)
                p._p.append(r)
                s = OxmlElement("w:r")
                s.append(_el("w:fldChar", **{"w:fldCharType": "separate"}))
                p._p.append(s)
            hl = _el("w:hyperlink", **{"w:anchor": self._bm(anchor), "w:history": 1})
            hl.append(self._run(text))
            p._p.append(hl)
            if k == len(entries) - 1:
                e = OxmlElement("w:r")
                e.append(_el("w:fldChar", **{"w:fldCharType": "end"}))
                p._p.append(e)
        gap = self._para(style=self.s_plain)
        gap.paragraph_format.space_after = Pt(12)

    def build(self) -> bytes:
        a = self.a
        self._front()
        figs, tabs = a.figures, a.tables
        for o in a.sections:
            self._heading(o)
            for sg in o.segs:
                if sg.kind == "md":
                    if sg.text.strip():
                        self._blocks(o, sg.text)
                elif sg.kind == "fig":
                    self._figure(figs[sg.ref])
                else:
                    t = tabs[sg.ref]
                    cap = self._para(style=self.doc.styles["Caption"], keep=True)
                    cap.paragraph_format.space_before = Pt(9)
                    cap.paragraph_format.space_after = Pt(3)
                    self._bookmark(cap, f"tab_{t.id}", lambda: cap._p.append(self._run(a.tab_caption(t))))
                    self._table(t.columns, t.rows, t.align)
                    if t.note:
                        n = self._para(style=self.s_cell)
                        n._p.append(self._run(a.words["note"] + t.note))
        if a.doc.meta["trace_table"] and a.doc.requirements:
            p = self.doc.add_paragraph(style=self.doc.styles["Heading 1"])
            self._bookmark(p, "sec__trace", lambda: p._p.append(self._run(a.words["trace"])))
            cols, rows = trace_rows(a)
            self._table(cols, rows, ["left"] * len(cols))
        body = self.doc.element.body
        last = [el for el in body if el.tag != qn("w:sectPr")][-1]
        if self.last_spacer is not None and last is self.last_spacer._p:
            self.last_spacer.paragraph_format.line_spacing = Pt(1)
        self._core()
        buf = io.BytesIO()
        self.doc.save(buf)
        return _normalize_zip(buf.getvalue())

    def _core(self):
        d = self.a.doc
        cp = self.doc.core_properties
        cp.title = d.title
        cp.subject = d.subtitle
        cp.author = d.meta["author"]
        cp.last_modified_by = "mengos"
        cp.comments = ""
        cp.keywords = ""
        cp.category = ""
        cp.revision = 1
        cp.language = d.meta["lang"]
        when = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
        if d.meta["date"]:
            y, mo, da = (int(x) for x in d.meta["date"].split("-"))
            try:
                when = dt.datetime(y, mo, da, tzinfo=dt.timezone.utc)
            except ValueError:
                pass
        cp.created = cp.modified = when
        cp.last_printed = when
        pkg = self.doc.part.package
        for rid, rel in list(pkg.rels.items()):
            if rel.reltype.endswith("/thumbnail"):
                del pkg.rels[rid]


def _normalize_zip(data: bytes) -> bytes:
    """固定 zip 内的时间戳与属性，保证同一文档两次导出逐字节相同。"""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            zi = zipfile.ZipInfo(info.filename, FIXED_ZIP_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            zi.create_system = 0
            z.writestr(zi, src.read(info.filename), compresslevel=6)
    return out.getvalue()


def to_docx(a: Assembled) -> bytes:
    return _Writer(a).build()
