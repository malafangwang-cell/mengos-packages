"""文档模型 mengos.document/1：校验与规范化。

规范形态是一份结构化文档模型（JSON）。Markdown、Word、网页都由它派生；proj 追问时改的是模型里的某一节。
本模块只做确定性的事：校验、补缺省、查重、图片校验与尺寸。编号、引用与排版在 assemble.py。
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

SCHEMA = "mengos.document/1"
ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
HASH_RE = re.compile(r"[0-9a-f]{64}")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
LANGS = ("zh-CN", "en")
KINDS = ("document", "outline")
NUMBERING = ("decimal", "chapter", "zh", "none")
FIG_NUMBERING = ("global", "chapter")
PRIORITIES = ("must", "should")
ALIGNS = ("left", "center", "right")
MAX_LEVEL = 4

LIMITS = {
    "sections": 2000, "figures": 300, "tables": 500, "requirements": 2000,
    "title_chars": 200, "heading_chars": 200, "caption_chars": 500, "req_chars": 2000, "source_chars": 300,
    "body_chars": 200_000, "total_chars": 3_000_000,
    "image_bytes": 8 * 1024 * 1024, "svg_bytes": 2 * 1024 * 1024, "images_total_bytes": 48 * 1024 * 1024,
    "table_columns": 30, "table_cells": 20_000, "cell_chars": 2000, "meta_chars": 200,
}

TOP_KEYS = ["schema", "kind", "title", "subtitle", "meta", "requirements", "sections", "figures", "tables"]
META_KEYS = ["lang", "author", "org", "date", "version", "numbering", "figure_numbering", "toc", "cover", "trace_table"]
SECTION_KEYS = ["id", "level", "heading", "body", "responds_to"]
FIGURE_KEYS = ["id", "caption", "width", "source"]
TABLE_KEYS = ["id", "caption", "columns", "rows", "align", "note"]
REQ_KEYS = ["id", "text", "source", "priority", "anchor"]


class BadInput(Exception):
    def __init__(self, message: str, where: str | None = None, hint: str | None = None, line: int | None = None):
        super().__init__(message)
        self.where, self.hint, self.line = where, hint, line


@dataclass
class Requirement:
    id: str
    text: str
    source: str
    priority: str
    anchor: dict | None


@dataclass
class Section:
    index: int
    id: str
    level: int
    heading: str
    body: str
    responds_to: list[str]


@dataclass
class Figure:
    index: int
    id: str
    caption: str
    width: float
    kind: str                 # svg | image
    media_type: str
    data: bytes               # SVG 或位图的字节，随文档一起给出
    px: tuple[float, float] | None   # 固有尺寸（像素）；未知为 None
    source: dict              # 规范化后的 source，写回模型


@dataclass
class Table:
    index: int
    id: str
    caption: str
    columns: list[str]
    rows: list[list[str]]
    align: list[str]
    align_given: bool
    note: str


@dataclass
class Doc:
    kind: str
    title: str
    subtitle: str
    meta: dict
    requirements: list[Requirement]
    sections: list[Section]
    figures: list[Figure]
    tables: list[Table]
    warnings: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        """规范模型：全部字段显式写出，键序固定。"""
        return {
            "schema": SCHEMA,
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "meta": {k: self.meta[k] for k in META_KEYS},
            "requirements": [{"id": r.id, "text": r.text, "source": r.source, "priority": r.priority,
                              **({"anchor": r.anchor} if r.anchor is not None else {})} for r in self.requirements],
            "sections": [{"id": s.id, "level": s.level, "heading": s.heading, "body": s.body,
                          "responds_to": s.responds_to} for s in self.sections],
            "figures": [{"id": f.id, "caption": f.caption, "width": f.width, "source": f.source} for f in self.figures],
            "tables": [{"id": t.id, "caption": t.caption, "columns": t.columns, "rows": t.rows,
                        "align": t.align if t.align_given else None, "note": t.note} for t in self.tables],
        }

    def sha256(self) -> str:
        blob = json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 小工具
def _obj(v, where, keys, required=()):
    if not isinstance(v, dict):
        raise BadInput(f"{where} 必须是对象", where)
    extra = [k for k in v if k not in keys]
    if extra:
        raise BadInput(f"{where} 有不认识的字段：{', '.join(sorted(extra))}（可用：{', '.join(keys)}）", where)
    for k in required:
        if k not in v:
            raise BadInput(f"{where} 缺少字段 {k}", f"{where}.{k}")
    return v


def _str(v, where, limit, *, required=False, oneline=False, default=""):
    if v is None:
        if required:
            raise BadInput(f"{where} 不能为空", where)
        return default
    if not isinstance(v, str):
        raise BadInput(f"{where} 必须是字符串", where)
    if required and not v.strip():
        raise BadInput(f"{where} 不能为空", where)
    if len(v) > limit:
        raise BadInput(f"{where} 超过 {limit} 个字符（现有 {len(v)}）", where)
    if oneline and ("\n" in v or "\r" in v):
        raise BadInput(f"{where} 只能是一行", where)
    bad = _CTRL.search(v)
    if bad:
        raise BadInput(f"{where} 含有不可见的控制字符 U+{ord(bad.group(0)):04X}", where, "删掉它；换行用 \\n，缩进用空格")
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        raise BadInput(f"{where} 含有不成对的代理字符", where) from None
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    return v.strip() if oneline else v


_CTRL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")


def _enum(v, where, allowed, default):
    if v is None:
        return default
    if v not in allowed:
        raise BadInput(f"{where} 只能是 {' / '.join(allowed)}（收到 {v!r}）", where)
    return v


def _bool(v, where, default):
    if v is None:
        return default
    if not isinstance(v, bool):
        raise BadInput(f"{where} 必须是 true 或 false", where)
    return v


def _id(v, where):
    if not isinstance(v, str) or not ID_RE.fullmatch(v):
        raise BadInput(f"{where} 不是合法的 id：以字母开头，只含字母、数字、下划线，最多 32 个字符（收到 {v!r}）", where,
                       "例如 s1、bg、tech_plan、f1、t_budget")
    return v


def _list(v, where, limit, *, default=None):
    if v is None:
        return [] if default is None else default
    if not isinstance(v, list):
        raise BadInput(f"{where} 必须是数组", where)
    if len(v) > limit:
        raise BadInput(f"{where} 超过 {limit} 项（现有 {len(v)}）", where)
    return v


# ---------------------------------------------------------------- 图片
MAX_PX = 30000


def _png_size(b: bytes):
    """完整走一遍 PNG 分块（含 CRC），确认首块是 IHDR、有 IDAT、以 IEND 结尾；返回像素尺寸。"""
    if len(b) < 45 or b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    i, size, seen_idat = 8, None, False
    while i + 12 <= len(b):
        n = int.from_bytes(b[i:i + 4], "big")
        kind, data = b[i + 4:i + 8], b[i + 8:i + 8 + n]
        if len(data) != n or i + 12 + n > len(b):
            return None
        if zlib.crc32(kind + data) & 0xFFFFFFFF != int.from_bytes(b[i + 8 + n:i + 12 + n], "big"):
            return None
        if size is None:
            if kind != b"IHDR" or n != 13:
                return None
            size = (int.from_bytes(data[0:4], "big"), int.from_bytes(data[4:8], "big"))
        elif kind == b"IDAT":
            seen_idat = True
        elif kind == b"IEND":
            w, h = size
            return size if seen_idat and 0 < w <= MAX_PX and 0 < h <= MAX_PX else None
        i += 12 + n
    return None


def _jpeg_size(b: bytes):
    """找到帧头（SOF）取尺寸，并确认其后有结束标记（EOI）。"""
    if len(b) < 4 or b[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7 or m == 0xFF:
            i += 1 if m == 0xFF else 2
            continue
        if m == 0xD9:
            return None
        seg = int.from_bytes(b[i + 2:i + 4], "big")
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(b[i + 5:i + 7], "big")
            w = int.from_bytes(b[i + 7:i + 9], "big")
            ok = 0 < w <= MAX_PX and 0 < h <= MAX_PX and b.find(b"\xff\xd9", i + 2 + seg) != -1
            return (w, h) if ok else None
        i += 2 + seg
    return None


SVG_NS = "http://www.w3.org/2000/svg"
XHTML_NS = "http://www.w3.org/1999/xhtml"
# 只收静态图形元素：没有脚本、动画、内嵌网页、外部图片滤镜。
SVG_ALLOWED = {
    "svg", "g", "defs", "symbol", "use", "title", "desc", "metadata", "switch", "a", "view", "style",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "tspan", "textPath", "image",
    "linearGradient", "radialGradient", "stop", "pattern", "clipPath", "mask", "marker", "filter",
    "feBlend", "feColorMatrix", "feComponentTransfer", "feComposite", "feConvolveMatrix", "feDiffuseLighting",
    "feDisplacementMap", "feDistantLight", "feDropShadow", "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR",
    "feGaussianBlur", "feMerge", "feMergeNode", "feMorphology", "feOffset", "fePointLight", "feSpecularLighting",
    "feSpotLight", "feTile", "feTurbulence",
}
_UNITS = {"": 1.0, "px": 1.0, "pt": 4 / 3, "pc": 16.0, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0}
_LEN_RE = re.compile(r"\s*([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)\s*(px|pt|pc|mm|cm|in)?\s*")
_SAFE_HREF = re.compile(r"#[A-Za-z0-9_\-.:]*|data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=\s]*")
_URL_IN_CSS = re.compile(r"url\(\s*['\"]?\s*([^'\")\s]*)", re.I)
_CSS_BAD = ("@import", "expression(", "image-set(", "src(", "-moz-binding", "behavior:", "@namespace")
_PI = re.compile(r"<\?(?!xml[\s?])", re.I)
_DECL_ENC = re.compile(r"\s*<\?xml[^>]*?encoding\s*=\s*[\"']([^\"']+)", re.I)


def _finite_pos(v):
    return v if v is not None and math.isfinite(v) and 0 < v <= 1e7 else None


def _svg_len(s):
    if s is None:
        return None
    m = _LEN_RE.fullmatch(s)
    if not m:
        return None
    return _finite_pos(float(m.group(1)) * _UNITS[m.group(2) or ""])


def _css_unsafe(text: str) -> bool:
    low = text.lower()
    if "\\" in text or any(x in low for x in _CSS_BAD):
        return True
    return any(not u.startswith("#") for u in _URL_IN_CSS.findall(text))


def _check_svg(data: bytes, where: str):
    """SVG 会作为独立文件交付（可能被浏览器直接打开），所以只收纯图形：
    只许静态图形元素；不许脚本、动画、事件属性、外部引用、内嵌网页、实体声明与样式表指令。
    不合格就拒收并说明，不静默删改。"""
    text = data.decode("utf-8", errors="strict") if data else ""
    low = text.lower()
    if "<!doctype" in low or "<!entity" in low:
        raise BadInput(f"{where}：SVG 不能带 DOCTYPE 或实体声明", where)
    if _PI.search(text):
        raise BadInput(f"{where}：SVG 里不能有处理指令（如 xml-stylesheet）", where)
    enc = _DECL_ENC.match(text)
    if enc and enc.group(1).lower().replace("-", "") != "utf8":
        raise BadInput(f"{where}：SVG 以 UTF-8 交付，XML 声明里的 encoding 只能是 UTF-8", where, "去掉 encoding 或改成 UTF-8")
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError) as e:
        raise BadInput(f"{where}：SVG 不是合法的 XML（{e}）", where) from None
    if root.tag != f"{{{SVG_NS}}}svg":
        raise BadInput(f"{where}：根元素必须是 SVG 命名空间里的 <svg>", where, f'写成 <svg xmlns="{SVG_NS}" …>')
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        ns, _, tag = el.tag[1:].partition("}") if el.tag.startswith("{") else ("", "", el.tag)
        if ns == SVG_NS:
            if tag not in SVG_ALLOWED:
                raise BadInput(f"{where}：SVG 里不能有 <{tag}>（只收静态图形：不要脚本、动画、内嵌网页）", where)
        elif ns == XHTML_NS or not ns:
            raise BadInput(f"{where}：SVG 里的元素 <{tag}> 不在 SVG 命名空间", where)
        if ns == SVG_NS and tag == "style":
            if len(el):
                raise BadInput(f"{where}：<style> 里只能是样式文字", where)
            if _css_unsafe("".join(el.itertext())):
                raise BadInput(f"{where}：SVG 的样式不能引用外部资源，也不能用转义写法", where)
        for k, v in el.attrib.items():
            name = k.rsplit("}", 1)[-1].lower()
            if name.startswith("on"):
                raise BadInput(f"{where}：SVG 里不能有事件属性 {name}", where)
            if name == "href" and not _SAFE_HREF.fullmatch(v.strip()):
                raise BadInput(f"{where}：SVG 里的链接只能指向本图内部（#id）或内嵌位图，收到 {v[:60]!r}", where,
                               "把外部图片转成内嵌位图，或去掉链接")
            if _css_unsafe(v):
                raise BadInput(f"{where}：SVG 属性 {name} 引用了外部资源或用了转义写法", where)
    w, h = _svg_len(root.get("width")), _svg_len(root.get("height"))
    vb = root.get("viewBox")
    if vb:
        try:
            parts = [float(x) for x in re.split(r"[\s,]+", vb.strip())]
        except ValueError:
            parts = []
        if len(parts) == 4 and all(math.isfinite(x) for x in parts) and _finite_pos(parts[2]) and _finite_pos(parts[3]):
            if w and not h:
                h = _finite_pos(w * parts[3] / parts[2])
            elif h and not w:
                w = _finite_pos(h * parts[2] / parts[3])
            elif not w and not h:
                w, h = parts[2], parts[3]
    return (w, h) if w and h else None


def _figure(v, where, index, warnings):
    _obj(v, where, FIGURE_KEYS, ("id", "caption", "source"))
    fid = _id(v["id"], f"{where}.id")
    caption = _str(v["caption"], f"{where}.caption", LIMITS["caption_chars"], required=True, oneline=True)
    width = v.get("width", 0.8)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not 0.1 <= width <= 1.0:
        raise BadInput(f"{where}.width 是占版心宽度的比例，取 0.1–1.0", f"{where}.width")
    width = float(width)
    src = v["source"]
    sw = f"{where}.source"
    if not isinstance(src, dict):
        raise BadInput(f"{sw} 必须是对象：{{\"svg\": \"<svg…>\"}} 或 {{\"media_type\", \"base64\"}}", sw)
    if "svg" in src:
        _obj(src, sw, ["svg"])
        svg = _str(src["svg"], f"{sw}.svg", LIMITS["svg_bytes"], required=True)
        data = svg.encode("utf-8")
        if len(data) > LIMITS["svg_bytes"]:
            raise BadInput(f"{sw}.svg 超过 {LIMITS['svg_bytes'] // 1024 // 1024} MB", f"{sw}.svg")
        px = _check_svg(data, f"{sw}.svg")
        if px is None:
            warnings.append({"where": sw, "code": "figure_size", "message": f"图 {fid} 的 SVG 没写宽高或 viewBox，按 4:3 排版"})
        return Figure(index, fid, caption, width, "svg", "image/svg+xml", data, px, {"svg": svg})
    if "base64" in src:
        _obj(src, sw, ["media_type", "base64"], ("media_type", "base64"))
        mt = _enum(src["media_type"], f"{sw}.media_type", ("image/png", "image/jpeg"), None)
        b64 = src["base64"]
        if not isinstance(b64, str):
            raise BadInput(f"{sw}.base64 必须是字符串", f"{sw}.base64")
        if b64.startswith("data:"):
            raise BadInput(f"{sw}.base64 只放编码本身，不带 data: 前缀", f"{sw}.base64")
        try:
            data = base64.b64decode("".join(b64.split()), validate=True)
        except ValueError:
            raise BadInput(f"{sw}.base64 不是合法的 base64", f"{sw}.base64") from None
        if len(data) > LIMITS["image_bytes"]:
            raise BadInput(f"{sw} 图片超过 {LIMITS['image_bytes'] // 1024 // 1024} MB", sw)
        px = _png_size(data) if mt == "image/png" else _jpeg_size(data)
        if px is None:
            raise BadInput(f"{sw}：不是完整的 {mt} 图片（文件头、尺寸或结尾不符）", sw, "重新导出一张 PNG 或 JPEG")
        return Figure(index, fid, caption, width, "image", mt, data, (float(px[0]), float(px[1])),
                      {"media_type": mt, "base64": base64.b64encode(data).decode("ascii")})
    raise BadInput(f"{sw} 要给出 svg，或 media_type 加 base64", sw, "图片随文档一起给出：矢量图写 svg，位图写 PNG 或 JPEG 的 base64")


# ---------------------------------------------------------------- 表格
_NUMERIC = re.compile(r"[¥$€£]?\s?[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s?[%‰]?")


def _cell(v, where):
    if v is None:
        return ""
    if isinstance(v, bool):
        raise BadInput(f"{where} 不能是布尔值，请写成文字", where)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise BadInput(f"{where} 不是有限数", where)
        return repr(v)
    return _str(v, where, LIMITS["cell_chars"])


def _table(v, where, index):
    _obj(v, where, TABLE_KEYS, ("id", "caption", "columns", "rows"))
    tid = _id(v["id"], f"{where}.id")
    caption = _str(v["caption"], f"{where}.caption", LIMITS["caption_chars"], required=True, oneline=True)
    cols = _list(v["columns"], f"{where}.columns", LIMITS["table_columns"])
    if not cols:
        raise BadInput(f"{where}.columns 至少一列", f"{where}.columns")
    columns = [_str(c, f"{where}.columns[{i}]", LIMITS["cell_chars"], oneline=True) for i, c in enumerate(cols)]
    rows_in = _list(v["rows"], f"{where}.rows", LIMITS["table_cells"])
    if len(rows_in) * len(columns) > LIMITS["table_cells"]:
        raise BadInput(f"{where} 超过 {LIMITS['table_cells']} 个单元格", where)
    rows = []
    for r, row in enumerate(rows_in):
        rw = f"{where}.rows[{r}]"
        if not isinstance(row, list):
            raise BadInput(f"{rw} 必须是数组", rw)
        if len(row) != len(columns):
            raise BadInput(f"{rw} 有 {len(row)} 格，表头有 {len(columns)} 列", rw, "每行的格数要与 columns 相同；空格写 null 或 \"\"")
        rows.append([_cell(c, f"{rw}[{i}]") for i, c in enumerate(row)])
    align_given = v.get("align") is not None
    if align_given:
        al = _list(v["align"], f"{where}.align", LIMITS["table_columns"])
        if len(al) != len(columns):
            raise BadInput(f"{where}.align 要与列数相同（{len(columns)}）", f"{where}.align")
        align = [_enum(a, f"{where}.align[{i}]", ALIGNS, None) for i, a in enumerate(al)]
    else:
        align = []
        for i in range(len(columns)):
            vals = [row[i].strip() for row in rows if row[i].strip()]
            align.append("right" if vals and all(_NUMERIC.fullmatch(x) for x in vals) else "left")
    note = _str(v.get("note"), f"{where}.note", LIMITS["caption_chars"])
    return Table(index, tid, caption, columns, rows, align, align_given, note)


# ---------------------------------------------------------------- 要求
def _requirement(v, where):
    _obj(v, where, REQ_KEYS, ("id", "text"))
    rid = _id(v["id"], f"{where}.id")
    text = _str(v["text"], f"{where}.text", LIMITS["req_chars"], required=True)
    source = _str(v.get("source"), f"{where}.source", LIMITS["source_chars"], oneline=True)
    pr = _enum(v.get("priority"), f"{where}.priority", PRIORITIES, "must")
    anchor = v.get("anchor")
    if anchor is not None:
        aw = f"{where}.anchor"
        _obj(anchor, aw, ["object", "page", "bbox"])
        out = {}
        if "object" in anchor:
            if not isinstance(anchor["object"], str) or not HASH_RE.fullmatch(anchor["object"]):
                raise BadInput(f"{aw}.object 必须是 sha256（64 位小写十六进制）", f"{aw}.object")
            out["object"] = anchor["object"]
        if "page" in anchor:
            p = anchor["page"]
            if isinstance(p, bool) or not isinstance(p, int) or p < 1:
                raise BadInput(f"{aw}.page 是从 1 开始的页码", f"{aw}.page")
            out["page"] = p
        if "bbox" in anchor:
            b = anchor["bbox"]
            if (not isinstance(b, list) or len(b) != 4
                    or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in b)):
                raise BadInput(f"{aw}.bbox 是四个数 [x0, y0, x1, y1]", f"{aw}.bbox")
            out["bbox"] = b
        anchor = out
    return Requirement(rid, text, source, pr, anchor)


# ---------------------------------------------------------------- 入口
def normalize(raw) -> Doc:
    """把输入收成规范模型。兼容旧契约 {title, sections:[{heading, body}]}：缺的 id、level 取缺省。"""
    _obj(raw, "doc", TOP_KEYS, ("title", "sections"))
    if raw.get("schema") is not None and raw["schema"] != SCHEMA:
        raise BadInput(f"doc.schema 只能是 {SCHEMA}", "doc.schema")
    warnings: list[dict] = []
    kind = _enum(raw.get("kind"), "doc.kind", KINDS, "document")
    title = _str(raw["title"], "doc.title", LIMITS["title_chars"], required=True, oneline=True)
    subtitle = _str(raw.get("subtitle"), "doc.subtitle", LIMITS["title_chars"], oneline=True)

    m = raw.get("meta") or {}
    _obj(m, "doc.meta", META_KEYS)
    meta = {
        "lang": _enum(m.get("lang"), "doc.meta.lang", LANGS, "zh-CN"),
        "author": _str(m.get("author"), "doc.meta.author", LIMITS["meta_chars"], oneline=True),
        "org": _str(m.get("org"), "doc.meta.org", LIMITS["meta_chars"], oneline=True),
        "date": _str(m.get("date"), "doc.meta.date", 10, oneline=True),
        "version": _str(m.get("version"), "doc.meta.version", 40, oneline=True),
        "numbering": _enum(m.get("numbering"), "doc.meta.numbering", NUMBERING, "decimal"),
        "figure_numbering": _enum(m.get("figure_numbering"), "doc.meta.figure_numbering", FIG_NUMBERING, "global"),
        "toc": _bool(m.get("toc"), "doc.meta.toc", True),
        "cover": _bool(m.get("cover"), "doc.meta.cover", False),
        "trace_table": _bool(m.get("trace_table"), "doc.meta.trace_table", False),
    }
    if meta["date"] and not DATE_RE.fullmatch(meta["date"]):
        raise BadInput("doc.meta.date 写成 YYYY-MM-DD", "doc.meta.date")
    if meta["figure_numbering"] == "chapter" and meta["numbering"] == "none":
        raise BadInput("figure_numbering=chapter 需要章节编号", "doc.meta.figure_numbering",
                       "改用 global，或把 numbering 设为 decimal / chapter / zh")

    reqs = [_requirement(r, f"doc.requirements[{i}]")
            for i, r in enumerate(_list(raw.get("requirements"), "doc.requirements", LIMITS["requirements"]))]
    _unique([r.id for r in reqs], "doc.requirements", "要求")

    secs_in = _list(raw["sections"], "doc.sections", LIMITS["sections"])
    if not secs_in:
        raise BadInput("doc.sections 至少一节", "doc.sections")
    explicit = {s["id"] for s in secs_in if isinstance(s, dict) and isinstance(s.get("id"), str)}
    sections, total, prev = [], 0, 0
    for i, s in enumerate(secs_in):
        w = f"doc.sections[{i}]"
        _obj(s, w, SECTION_KEYS, ("heading",))
        if s.get("id") is None:
            sid = f"s{i + 1}"
            if sid in explicit:
                raise BadInput(f"第 {i + 1} 节没写 id，缺省 id {sid} 与另一节的 id 重复", f"{w}.id", "每一节都写 id，或都不写")
        else:
            sid = _id(s["id"], f"{w}.id")
        lv = s.get("level", 1)
        if isinstance(lv, bool) or not isinstance(lv, int) or not 1 <= lv <= MAX_LEVEL:
            raise BadInput(f"{w}.level 取 1–{MAX_LEVEL}（收到 {lv!r}）", f"{w}.level")
        if lv > prev + 1:
            raise BadInput(f"第 1 节（{sid}）必须是 level 1（收到 {lv}）" if i == 0 else
                           f"第 {i + 1} 节（{sid}）level {lv} 跳级：上一节是 level {prev}", f"{w}.level",
                           "第一节必须是 level 1；每一节最多比上一节深一级")
        prev = lv
        heading = _str(s["heading"], f"{w}.heading", LIMITS["heading_chars"], required=True, oneline=True)
        body = _str(s.get("body"), f"{w}.body", LIMITS["body_chars"])
        total += len(body)
        rt = _list(s.get("responds_to"), f"{w}.responds_to", LIMITS["requirements"])
        responds = [_id(x, f"{w}.responds_to[{j}]") for j, x in enumerate(rt)]
        if len(set(responds)) != len(responds):
            raise BadInput(f"{w}.responds_to 有重复的要求 id", f"{w}.responds_to")
        sections.append(Section(i, sid, lv, heading, body, responds))
    if total > LIMITS["total_chars"]:
        raise BadInput(f"正文合计超过 {LIMITS['total_chars']} 个字符", "doc.sections")
    _unique([s.id for s in sections], "doc.sections", "节")

    figs = [_figure(f, f"doc.figures[{i}]", i, warnings)
            for i, f in enumerate(_list(raw.get("figures"), "doc.figures", LIMITS["figures"]))]
    _unique([f.id for f in figs], "doc.figures", "图")
    if sum(len(f.data or b"") for f in figs) > LIMITS["images_total_bytes"]:
        raise BadInput(f"图片合计超过 {LIMITS['images_total_bytes'] // 1024 // 1024} MB", "doc.figures")
    tabs = [_table(t, f"doc.tables[{i}]", i)
            for i, t in enumerate(_list(raw.get("tables"), "doc.tables", LIMITS["tables"]))]
    _unique([t.id for t in tabs], "doc.tables", "表")

    return Doc(kind, title, subtitle, meta, reqs, sections, figs, tabs, warnings)


def _unique(ids, where, what):
    seen = set()
    for i, x in enumerate(ids):
        if x in seen:
            raise BadInput(f"{what}的 id {x} 重复", f"{where}[{i}].id")
        seen.add(x)
