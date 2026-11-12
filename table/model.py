"""表模型（mengos.table/1）：把调用方写的表规范成唯一的规范对象。

规范对象是唯一真源：产出台、Markdown、Excel、CSV 都由它确定性地派生（WP-W6 §6）。
数值一律用 Decimal 计算、以十进制字符串存，两次运行逐字节相同（TL-12 ②）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

import formula as F

SCHEMA = "mengos.table/1"
TYPES = ("text", "integer", "number", "money", "percent", "date", "bool")
NUMERIC = ("integer", "number", "money", "percent")
FNS = ("sum", "avg", "min", "max", "count", "formula", "none")
# 2.1.0 G1：样式值只有四种属性；颜色取命名色板（Excel 色值、产出台浅色与深色主题各一套）。名字不能读成数（不进 08 PD-1e 证件账）。
STYLE_KEYS = ("fill", "color", "bold", "italic")
PALETTE = {   # 名字: (Excel 与浅色主题, 深色主题底色, 深色主题字色)
    "红": ("#FF0000", "#8E1B1B", "#FF7B72"), "橙": ("#FFC000", "#8A5A00", "#FFB547"),
    "黄": ("#FFFF00", "#6B6400", "#F2E35A"), "绿": ("#00B050", "#1B6B3A", "#5FD38D"),
    "蓝": ("#0070C0", "#1D4F86", "#6CB4F5"), "深蓝": ("#1F3864", "#22385F", "#9DB7E8"),
    "灰": ("#808080", "#4A4A47", "#A8A8A3"), "浅灰": ("#D9D9D9", "#33332F", "#C8C8C3"),
    "白": ("#FFFFFF", "#191918", "#ECECE8"), "黑": ("#000000", "#0B0B0A", "#ECECE8"),
    "浅红": ("#FFC7CE", "#5A2A2E", "#FFB3BC"), "浅黄": ("#FFF2CC", "#4A4220", "#F5E3A1"),
}
COLOR_ALIAS = {"red": "红", "orange": "橙", "yellow": "黄", "green": "绿", "blue": "蓝", "navy": "深蓝", "darkblue": "深蓝",
               "gray": "灰", "grey": "灰", "lightgray": "浅灰", "lightgrey": "浅灰", "white": "白", "black": "黑",
               "lightred": "浅红", "pink": "浅红", "lightyellow": "浅黄"}
COLOR_NAMES = tuple(PALETTE) + tuple(COLOR_ALIAS)
DISPLAY_KEY = "$style"        # 行里的保留键：本行、本格的显示设置（17 TL-30 v0.2.98 “显示设置跟着行走”）
ROW_KINDS = ("total", "subtotal", "group")   # row_styles 只按行种类写：合计行、小计行、包生成的组头（2.2.0 G7）
ID_KEY = "$id"                # 行里的保留键：稳定的行 id（2.2.0 G17），格公式按它引用别的行
EXPR_KEY = "$expr"            # 格里的保留的式（08 PD-1e v0.2.98、17 TL-30b）
NUMBERINGS = ("seq", "outline")
MAX_LEVEL = 4
SUBTOTAL_CODE = {"sum": 9, "avg": 1, "min": 5, "max": 4, "count": 3}
DATE_FORMATS = {"YYYY-MM-DD": ("yyyy-mm-dd", "{y:04d}-{m:02d}-{d:02d}"), "YYYY/MM/DD": ("yyyy/mm/dd", "{y:04d}/{m:02d}/{d:02d}"),
                "YYYY年M月D日": ('yyyy"年"m"月"d"日"', "{y:04d}年{m}月{d}日"), "M月D日": ('m"月"d"日"', "{m}月{d}日"),
                "YYYY.MM.DD": ("yyyy.mm.dd", "{y:04d}.{m:02d}.{d:02d}")}
MAX_RULES = 50
MAX_FLOAT_WARN = 20           # G4：每列最多点名这么多格，其余合成一句
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
SHEET_BAD = re.compile(r"[\[\]:*?/\\]")
MAX_SHEETS = 20
MAX_COLS = 200
MAX_ROWS = 100_000
MAX_CELLS = 1_000_000
MAX_TEXT = 32_767          # Excel 单元格上限
MAX_TITLE = 200
DEFAULT_DECIMALS = {"money": 2}
BLANKS = {"", "-", "—", "–", "/", "N/A", "n/a", "NA"}
TRUE = {"true", "yes", "y", "是", "对", "有", "√", "✓"}
FALSE = {"false", "no", "n", "否", "错", "无", "×", "✗"}
CURRENCY = re.compile(r"[¥￥$€£元]|RMB|CNY|USD", re.IGNORECASE)
NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
THOUSANDS_RE = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
DATE_RES = (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
            re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$"), re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})$"))
META_KEYS = ("lang", "author", "org", "date", "version")


class BadInput(Exception):
    def __init__(self, message, where=None, hint=None, line=None):
        super().__init__(message)
        self.where, self.hint, self.line = where, hint, line


# ---------------------------------------------------------------- 数值
def dec_str(d: Decimal) -> str:
    """Decimal → 不带指数的十进制字符串；-0 记为 0。"""
    if d == 0:
        return "0"
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def quantize(d: Decimal, decimals):
    if d is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        if decimals is None:
            q = d.quantize(Decimal("1e-10"), rounding=ROUND_HALF_UP) if d.adjusted() < 40 else d
            return Decimal(dec_str(q))
        return d.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _num_from(v, ctype, where, stored=False):
    """单元格 → Decimal | None。stored=True：值取自表模型（.table.json），百分比列已经存成小数，不再除以 100。"""
    if v is None:
        return None
    if isinstance(v, bool):
        raise BadInput(f"这一列是数值，不能写 {str(v).lower()}", where)
    if isinstance(v, int):
        d = Decimal(v)
    elif isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise BadInput("数值不能是 NaN 或无穷大", where)
        d = Decimal(repr(v))
    elif isinstance(v, str):
        s = unicodedata.normalize("NFKC", v).strip()
        if s in BLANKS:
            return None
        pct = s.endswith("%")
        if pct:
            s = s[:-1].strip()
        if ctype == "money":
            s = CURRENCY.sub("", s).strip()
        s = s.replace(" ", "")
        if THOUSANDS_RE.match(s):
            s = s.replace(",", "")
        if not NUM_RE.match(s):
            raise BadInput(f"“{v[:40]}” 不是数值", where, "数值列只写数字；单位写在列的 unit 里，空格子写 null")
        d = Decimal(s)
        if pct and ctype != "percent":
            d = d / 100
    else:
        raise BadInput("单元格只能是字符串、数字、true/false 或 null", where)
    if not d.is_finite() or abs(d.adjusted()) > 30:
        raise BadInput("数值超出范围（绝对值在 1e-30 到 1e30 之间）", where)
    if ctype == "percent" and not stored:
        d = d / 100            # 百分比列写的是百分数：12.5 与 "12.5%" 都是 12.5%，存为 0.125
    if ctype == "integer":
        if d != d.to_integral_value():
            raise BadInput(f"整数列不能有小数：{v}", where, "要小数就把这一列的 type 改成 number")
        d = d.to_integral_value()
    return Decimal(dec_str(d))


def _date_from(v, where):
    if v is None:
        return None
    if not isinstance(v, str):
        raise BadInput("日期写成字符串 YYYY-MM-DD", where)
    s = unicodedata.normalize("NFKC", v).strip()
    if s in BLANKS:
        return None
    for r in DATE_RES:
        m = r.match(s)
        if m:
            try:
                return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                break
    raise BadInput(f"“{v[:40]}” 不是日期", where, "日期写成 YYYY-MM-DD，例如 2026-10-24")


def _bool_from(v, where):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = unicodedata.normalize("NFKC", v).strip().lower()
        if s in BLANKS:
            return None
        if s in TRUE:
            return True
        if s in FALSE:
            return False
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    raise BadInput(f"“{str(v)[:40]}” 不是是/否", where, "是否列写 true / false（也认“是”“否”）")


def _text_from(v, where, lang):
    if v is None:
        return None
    if isinstance(v, bool):
        return ("是" if v else "否") if lang != "en" else ("Yes" if v else "No")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return dec_str(Decimal(repr(v)))
    if not isinstance(v, str):
        raise BadInput("单元格只能是字符串、数字、true/false 或 null", where)
    if len(v) > MAX_TEXT:
        raise BadInput(f"单元格文字超过 {MAX_TEXT} 个字符（Excel 的上限）", where)
    return v if v.strip() else None


def _looks(v):
    """类型推断用：单元格看起来像什么。"""
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "integer" if v == int(v) and abs(v) < 1e15 else "number"
    if isinstance(v, str):
        s = unicodedata.normalize("NFKC", v).strip()
        if s in BLANKS:
            return None
        if DATE_RES[0].match(s):
            return "date"
        t = s.replace(" ", "")
        if THOUSANDS_RE.match(t):
            t = t.replace(",", "")
        if NUM_RE.match(t) and "e" not in t.lower():
            return "number" if "." in t else "integer"
    return "text"


def infer_type(values):
    kinds = {k for k in (_looks(v) for v in values if v is not None) if k is not None}
    if not kinds:
        return "text"
    if kinds == {"bool"}:
        return "bool"
    if kinds == {"date"}:
        return "date"
    if kinds <= {"integer"}:
        return "integer"
    if kinds <= {"integer", "number"}:
        return "number"
    return "text"


# ---------------------------------------------------------------- 结构
class Column:
    __slots__ = ("key", "title", "type", "unit", "decimals", "formula", "node", "align", "width", "inferred",
                 "style", "date_format", "thousands", "numbering", "identifier")

    def to_json(self):
        o = {"key": self.key, "title": self.title, "type": self.type}
        if self.unit:
            o["unit"] = self.unit
        if self.decimals is not None:
            o["decimals"] = self.decimals
        if self.formula is not None:
            o["formula"] = self.formula
        if self.width is not None:
            o["width"] = self.width
        o["align"] = self.align
        if self.style:
            o["style"] = dict(self.style)
        if self.date_format is not None:
            o["date_format"] = self.date_format
        if self.thousands is not None:
            o["thousands"] = self.thousands
        if self.numbering is not None:
            o["numbering"] = self.numbering
        if self.identifier:
            o["identifier"] = True
        return o

    @property
    def grouped(self):
        """数值显示带不带千分位：integer、money 缺省带，number、percent 缺省不带（G5 可改）。"""
        return self.thousands if self.thousands is not None else self.type in ("integer", "money")

    @property
    def kind(self):
        return "num" if self.type in NUMERIC else self.type if self.type in ("date", "bool") else "text"

    @property
    def shown_decimals(self):
        return self.decimals if self.decimals is not None else DEFAULT_DECIMALS.get(self.type)


class Sheet:
    __slots__ = ("id", "name", "caption", "note", "columns", "rows", "totals", "freeze_cols", "formula_errors",
                 "header_style", "rules", "row_styles", "displays", "raw", "_styles",
                 "row_ids", "exprs", "outline_from", "levels", "group", "subtotals", "merge_rows", "derive",
                 "layout", "merged", "derive_src", "_spec", "_where", "_index")

    def col(self, key):
        return next(c for c in self.columns if c.key == key)

    def find(self, name):
        """按 key 或列标题找列；找不到返回 None。"""
        n = _norm(name)
        for c in self.columns:
            if c.key == name:
                return c
        for c in self.columns:
            if _norm(c.title) == n:
                return c
        for c in self.columns:
            if c.unit and _norm(f"{c.title}({c.unit})") == n:
                return c
        return None

    def values(self, key):
        i = next(j for j, c in enumerate(self.columns) if c.key == key)
        return [r[i] for r in self.rows]

    def to_json(self):
        o = {"name": self.name}
        if self.id:
            o["id"] = self.id
        if self.caption:
            o["caption"] = self.caption
        o["columns"] = [c.to_json() for c in self.columns]
        o["rows"] = [self._row_json(ri, r, d) for ri, (r, d) in enumerate(zip(self.rows, self.displays))]
        if self.totals:
            o["totals"] = [{"column": k, "fn": fn, "value": None if v is None else dec_str(v)} for k, fn, v in self.totals]
        if self.freeze_cols:
            o["freeze_cols"] = self.freeze_cols
        if self.note:
            o["note"] = self.note
        if self.header_style:
            o["header_style"] = dict(self.header_style)
        if self.rules:
            o["rules"] = [_rule_json(r) for r in self.rules]
        if self.row_styles:
            o["row_styles"] = [{"kind": k, "style": dict(v)} for k, v in self.row_styles.items()]
        if self.outline_from:
            o["outline_from"] = {"column": self.outline_from[0], "levels": dict(self.outline_from[1])}
        if self.group:
            o["group"] = dict(self.group)
        if self.subtotals:
            o["subtotals"] = [dict(x) for x in self.subtotals]
        if self.merge_rows:
            o["merge_rows"] = json.loads(json.dumps(self.merge_rows))
        if self.derive:
            o["derive"] = json.loads(json.dumps(self.derive))
        return o

    def _row_json(self, ri, r, d):
        cells = [({EXPR_KEY: self.exprs[(ri, j)][0]} if (ri, j) in self.exprs else _cell_json(c, v))
                 for j, (c, v) in enumerate(zip(self.columns, r))]
        rid = self.row_ids[ri] if self.row_ids else None
        if not d and rid is None:
            return cells
        o = {c.key: v for c, v in zip(self.columns, cells)}
        if rid is not None:
            o[ID_KEY] = rid
        if d:
            o[DISPLAY_KEY] = _display_json(d)
        return o

    def eff_rows(self):
        """看得见的数据行（合计、小计按它算）：合并掉的明细不算，合并行算。没有合并时就是全部数据行。"""
        if not self.merged:
            return self.rows
        return [e["values"] if e["kind"] == "merged" else self.rows[e["ri"]]
                for e in self.layout if e["kind"] == "merged" or (e["kind"] == "data" and "detail" not in e)]

    def eff_values(self, key):
        j = next(k for k, c in enumerate(self.columns) if c.key == key)
        return [r[j] for r in self.eff_rows()]

    def has_layout(self):
        return bool(self.layout) and any(e["kind"] != "data" for e in self.layout)

    def styles(self):
        """每格的最终样式（G1 叠加，见 _overlay）。只算一次。"""
        if self._styles is None:
            self._styles = _overlay(self)
        return self._styles


def _display_json(d):
    o = {}
    if d.get("row"):
        o["row"] = dict(d["row"])
    if d.get("cells"):
        o["cells"] = {k: dict(v) for k, v in d["cells"].items()}
    return o


def _rule_json(r):
    o = {}
    if r.get("label"):
        o["label"] = r["label"]
    if r["kind"] == "scale":
        key, a, b = r["scale"]
        o["scale"] = {"column": key, "from": a, "to": b}
        return o
    o["when"] = r["src"]
    o["apply_to"] = "row" if r["apply"] == "row" else list(r["apply"])
    o["style"] = dict(r["style"])
    return o


def _cell_json(col, v):
    if v is None or isinstance(v, (str, bool)):
        return v
    return dec_str(v)


class Table:
    __slots__ = ("title", "subtitle", "meta", "sheets", "sources", "assumptions", "warnings", "_json", "_sha", "book")

    def to_json(self):
        if self._json is None:
            o = {"schema": SCHEMA, "title": self.title}
            if self.subtitle:
                o["subtitle"] = self.subtitle
            if self.meta:
                o["meta"] = dict(self.meta)
            o["sheets"] = [s.to_json() for s in self.sheets]
            if self.sources:
                o["sources"] = list(self.sources)
            if self.assumptions:
                o["assumptions"] = list(self.assumptions)
            self._json = o
        return self._json

    @property
    def sha(self):
        if self._sha is None:
            self._sha = hashlib.sha256(dumps(self.to_json())).hexdigest()
        return self._sha

    @property
    def lang(self):
        return self.meta.get("lang", "zh-CN")

    def stats(self):
        rows = sum(len(s.rows) for s in self.sheets)
        cols = sum(len(s.columns) for s in self.sheets)
        cells = sum(len(s.rows) * len(s.columns) for s in self.sheets)
        empty = sum(1 for s in self.sheets for r in s.rows for v in r if v is None)
        formulas = sum(1 for s in self.sheets for c in s.columns if c.formula is not None)
        return {"sheets": len(self.sheets), "rows": rows, "columns": cols, "cells": cells,
                "empty_cells": empty, "formula_columns": formulas, "warnings": len(self.warnings)}


def dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _norm(s) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s))).lower()


def _str(v, where, maxlen, required=False):
    if v is None:
        if required:
            raise BadInput("必填", where)
        return None
    if not isinstance(v, str):
        raise BadInput("应当是字符串", where)
    v = v.strip()
    if required and not v:
        raise BadInput("不能为空", where)
    if len(v) > maxlen:
        raise BadInput(f"超过 {maxlen} 个字符", where)
    return v or None


def _allowed(obj, keys, where):
    if not isinstance(obj, dict):
        raise BadInput("应当是 JSON 对象", where)
    extra = sorted(set(obj) - set(keys))
    if extra:
        raise BadInput(f"不认识的字段：{', '.join(extra)}（可用：{', '.join(keys)}）", f"{where}.{extra[0]}" if where else extra[0])


# ---------------------------------------------------------------- 规范化
SHEET_STYLE_KEYS = ("header_style", "rules", "row_styles")
STRUCT_KEYS = ("outline_from", "group", "subtotals", "merge_rows")     # 2.2.0 G7–G9：单表写法也可用
SHEET_ONLY_KEYS = ("derive",)                                           # 2.2.0 G10：只在 sheets 写法里
TABLE_KEYS = ("schema", "title", "subtitle", "meta", "sheets", "sources", "assumptions",
              "columns", "rows", "totals", "caption", "note", "freeze_cols", "name", "lang") + SHEET_STYLE_KEYS + STRUCT_KEYS + ("sheet_order",)
SHEET_KEYS = ("id", "name", "caption", "note", "columns", "rows", "totals", "freeze_cols") + SHEET_STYLE_KEYS + STRUCT_KEYS + SHEET_ONLY_KEYS
COL_KEYS = ("key", "title", "type", "unit", "decimals", "formula", "width", "align", "style", "date_format", "thousands", "numbering", "identifier")
ID_TITLE = re.compile(r"(编号|序号|代号|代码|编码|号码|图号|料号|ID)$", re.IGNORECASE)
ID_LOOK = re.compile(r"^(0\d+(\.\d+)?|\d+\.\d*0|\d+(\.\d+){2,})$")     # 前导零、小数点后有末尾零、两个以上小数点


def normalize(raw, build=False) -> Table:
    """build=True 只给 table.build：被引用列须写 type、无行的表给警告（2.0.0）。核对与导出收的是表对象，照 1.x 口径。"""
    if not isinstance(raw, dict):
        raise BadInput("table 应当是 JSON 对象：{title, sheets:[…]}，或单张表 {title, columns, rows}", "table")
    _allowed(raw, TABLE_KEYS, "table")
    if raw.get("schema") not in (None, SCHEMA):
        raise BadInput(f"schema 只能是 {SCHEMA}", "table.schema")
    t = Table()
    t._json = t._sha = None
    t.warnings = []
    t.title = _str(raw.get("title"), "table.title", MAX_TITLE, True)
    t.subtitle = _str(raw.get("subtitle"), "table.subtitle", MAX_TITLE)
    t.meta = _meta(raw.get("meta"))
    if "lang" in raw:           # 顶层 lang 是 meta.lang 的简写；两处都写时须一致
        lang = _meta({"lang": raw["lang"]}).get("lang")
        if lang is not None:
            if t.meta.get("lang", lang) != lang:
                raise BadInput("lang 与 meta.lang 不一致", "table.lang")
            t.meta["lang"] = lang
    single = [k for k in ("columns", "rows", "totals", "caption", "note", "freeze_cols", "name") + SHEET_STYLE_KEYS + STRUCT_KEYS if k in raw]
    if "sheets" in raw and single:
        raise BadInput(f"sheets 与单张表的写法二选一：有 sheets 时 {single[0]} 写进各张表里", f"table.{single[0]}")
    if "sheets" in raw:
        sheets = raw["sheets"]
        if not isinstance(sheets, list) or not sheets:
            raise BadInput("sheets 是至少一张表的数组", "table.sheets")
        if len(sheets) > MAX_SHEETS:
            raise BadInput(f"最多 {MAX_SHEETS} 张表", "table.sheets")
        where = [f"table.sheets[{i}]" for i in range(len(sheets))]
    else:
        if "columns" not in raw:
            raise BadInput("缺少 columns：单张表写 {title, columns, rows}，多张表写 sheets", "table.columns")
        if "sheet_order" in raw:
            raise BadInput("sheet_order 只用于几张表（sheets）的写法", "table.sheet_order")
        sheets = [{k: raw[k] for k in ("columns", "rows", "totals", "caption", "note", "freeze_cols") + SHEET_STYLE_KEYS + STRUCT_KEYS if k in raw}]
        sheets[0]["name"] = raw.get("name") if raw.get("name") is not None else t.title
        where = ["table"]
    from_model = raw.get("schema") == SCHEMA
    t.sheets = []
    total_cells = 0
    used = set()
    more_src, more_asm = [], []
    for i, (s, w) in enumerate(zip(sheets, where)):
        if isinstance(s, dict) and ("sources" in s or "assumptions" in s):
            # 写在某张表里的来源与前提并入整张表（它们本来就是整份表格的说明）
            s = dict(s)
            more_src += _strlist(s.pop("sources", None), f"{w}.sources", 100, 1000)
            more_asm += _strlist(s.pop("assumptions", None), f"{w}.assumptions", 100, 1000)
        sh = _sheet(s, w, i, t, used, from_model, build)
        total_cells += len(sh.rows) * len(sh.columns)
        if total_cells > MAX_CELLS:
            raise BadInput(f"单元格合计超过 {MAX_CELLS:,} 个", w)
        sh._index = i
        t.sheets.append(sh)
    ids = [s.id for s in t.sheets if s.id]
    if len(ids) != len(set(ids)):
        raise BadInput("各张表的 id 不能重复", "table.sheets")
    t.book = list(t.sheets)                   # 解析次序：格的定位 ("cell", 序号, 行, 列) 按它找表，不受 sheet_order 影响
    _exprs(t)                                 # 2.2.0 G17：格公式整本一起算（引用别的格、别的表）
    for sh in _finish_order(t):               # 2.2.0 G10：跨表汇总、派生表按依赖次序算
        _sheet_finish(sh, t, build)
    for sh in t.sheets:
        total_cells += len(sh.rows) * len(sh.columns) if sh.derive else 0
        if total_cells > MAX_CELLS:
            raise BadInput(f"单元格合计超过 {MAX_CELLS:,} 个", sh._where)
    if "sheet_order" in raw:
        t.sheets = _sheet_order(raw["sheet_order"], t.sheets)
    t.sources = _merge(_strlist(raw.get("sources"), "table.sources", 100, 1000), more_src, "table.sources")
    t.assumptions = _merge(_strlist(raw.get("assumptions"), "table.assumptions", 100, 1000), more_asm, "table.assumptions")
    return t


def _merge(a, b, where):
    out = list(a)
    for x in b:
        if x not in out:
            out.append(x)
    if len(out) > 100:
        raise BadInput("最多 100 条", where)
    return out


def _strlist(v, where, maxn, maxlen):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > maxn:
        raise BadInput(f"应当是字符串数组（最多 {maxn} 条）", where)
    return [x for x in (_str(x, f"{where}[{i}]", maxlen) for i, x in enumerate(v)) if x]


def _meta(m):
    if m is None:
        return {}
    _allowed(m, META_KEYS, "table.meta")
    out = {}
    for k in META_KEYS:
        if k not in m:
            continue
        v = _str(m[k], f"table.meta.{k}", 200)
        if v is None:
            continue
        if k == "lang" and v not in ("zh-CN", "en"):
            raise BadInput("lang 只能是 zh-CN 或 en", "table.meta.lang")
        if k == "date":
            v = _date_from(v, "table.meta.date")
        out[k] = v
    return out


def _sheet_name(name, i, used, t, where):
    n = name if isinstance(name, str) and name.strip() else f"表{i + 1}"
    fixed = SHEET_BAD.sub("_", n.strip()).strip("'")[:31] or f"表{i + 1}"
    base, k = fixed, 2
    while fixed.lower() in used or fixed.lower() == "history":
        suffix = f"({k})"
        fixed = base[:31 - len(suffix)] + suffix
        k += 1
    if fixed != n.strip():
        t.warnings.append({"where": f"{where}.name", "code": "sheet_name",
                           "message": f"表名改成了“{fixed}”（Excel 表名最多 31 个字符，不能有 [ ] : * ? / \\，不能重复）"})
    used.add(fixed.lower())
    return fixed


def _sheet(s, where, i, t, used, from_model, build=False) -> Sheet:
    _allowed(s, SHEET_KEYS, where)
    sh = Sheet()
    sh.formula_errors = []
    sh.raw = {}
    sh._styles = None
    sh._spec, sh._where = s, where
    sh.row_ids, sh.exprs = [], {}
    sh.outline_from = sh.levels = sh.group = sh.merge_rows = sh.derive = None
    sh.subtotals, sh.layout, sh.merged, sh.derive_src = [], [], [], {}
    sid = s.get("id")
    if sid is not None and (not isinstance(sid, str) or not KEY_RE.match(sid)):
        raise BadInput("id 由字母、数字、下划线组成，字母或下划线开头，最多 32 个字符", f"{where}.id")
    sh.id = sid
    sh.name = _sheet_name(s.get("name"), i, used, t, where)
    sh.caption = _str(s.get("caption"), f"{where}.caption", 500)
    sh.note = _str(s.get("note"), f"{where}.note", 2000)
    fc = s.get("freeze_cols", 0)
    if isinstance(fc, bool) or not isinstance(fc, int) or not 0 <= fc <= 10:
        raise BadInput("freeze_cols 是 0–10 的整数：左边冻结几列", f"{where}.freeze_cols")
    cols = s.get("columns")
    if not isinstance(cols, list) or not cols:
        raise BadInput("columns 是至少一列的数组", f"{where}.columns")
    if len(cols) > MAX_COLS:
        raise BadInput(f"一张表最多 {MAX_COLS} 列", f"{where}.columns")
    rows = s.get("rows", [])
    if s.get("derive") is not None:
        if rows and not from_model:
            raise BadInput("派生表的行由工具从各分部生成，rows 不用写", f"{where}.rows")
        rows = []
    if not isinstance(rows, list):
        raise BadInput("rows 是行的数组：每行是一个数组（按列的顺序）或一个对象（列名 → 值）", f"{where}.rows")
    if len(rows) > MAX_ROWS:
        raise BadInput(f"一张表最多 {MAX_ROWS:,} 行", f"{where}.rows")
    sh.columns = [_column(c, f"{where}.columns[{j}]", j) for j, c in enumerate(cols)]
    keys = [c.key for c in sh.columns]
    if len(set(keys)) != len(keys):
        dup = next(k for k in keys if keys.count(k) > 1)
        raise BadInput(f"列的 key 重复：{dup}", f"{where}.columns")
    titles = [_norm(c.title) for c in sh.columns]
    if len(set(titles)) != len(titles):
        dup = next(c.title for c in sh.columns if titles.count(_norm(c.title)) > 1)
        raise BadInput(f"列标题重复：{dup}", f"{where}.columns", "同一张表里列标题不能相同，可以加上区分的字，或用 unit 写单位")
    if build:
        _declared_types(s, sh, where)
    plain = [j for j, c in enumerate(sh.columns) if c.formula is None]
    sh.displays = []
    raw_rows = [_row(r, f"{where}.rows[{ri}]", sh, plain, t, from_model, ri) for ri, r in enumerate(rows)]
    # 没写 type 的列按内容推断（公式列恒为数值；编号列 outline 为文字、seq 为整数；派生表的列取来源表同名列的类型）
    for j, c in enumerate(sh.columns):
        if c.type is None and c.numbering is not None:
            c.type = "text" if c.numbering == "outline" else "integer"
            c.inferred = True
        if c.type is None and any(_is_expr(r[j]) for r in raw_rows):
            raise BadInput(f"“{c.title}”有格公式（{EXPR_KEY}），这一列要写 type（integer、number 或 money）", f"{where}.columns[{j}].type")
        if c.type is None and s.get("derive") is not None and c.formula is None:
            c.type = None                     # 留到生成行以后再定（_derive_rows）
            continue
        if c.type is None:
            c.type = "number" if c.formula is not None else infer_type([r[j] for r in raw_rows])
            c.inferred = True
        if c.formula is not None and c.type not in NUMERIC + ("text",):
            raise BadInput("公式列的 type 只能是数值类（integer、number、money、percent），或 text（结果是文字的 if）",
                           f"{where}.columns[{j}].type")
        if c.decimals is not None and c.type not in NUMERIC:
            raise BadInput("decimals 只用于数值列", f"{where}.columns[{j}].decimals")
        if c.thousands is not None and c.type not in NUMERIC:
            raise BadInput("thousands 只用于数值列", f"{where}.columns[{j}].thousands")
        if c.date_format is not None and c.type != "date":
            raise BadInput("date_format 只用于日期列", f"{where}.columns[{j}].date_format")
        if c.numbering == "outline" and c.type != "text":
            raise BadInput("层级编号（numbering outline）存为文字，type 写 text 或不写", f"{where}.columns[{j}].type")
        if c.numbering == "seq" and c.type not in ("integer", "text"):
            raise BadInput("序号（numbering seq）的 type 写 integer 或 text", f"{where}.columns[{j}].type")
        if c.numbering is not None and c.formula is not None:
            raise BadInput("编号列由工具生成，不能再写 formula", f"{where}.columns[{j}].numbering")
        if c.type is not None:
            c.align = c.align or ("right" if c.type in NUMERIC else "center" if c.type == "bool" else "left")
    sh.rows = [[_cell_or_expr(sh, ri, j, v, f"{where}.rows[{ri}][{j}]", t.lang, from_model) for j, v in enumerate(r)]
               for ri, r in enumerate(raw_rows)]
    ids = [x for x in sh.row_ids if x is not None]
    if len(ids) != len(set(ids)):
        dup = next(x for x in ids if ids.count(x) > 1)
        raise BadInput(f"行 id 重复：{dup}", f"{where}.rows", "同一张表里每行的 $id 不能相同")
    sh.freeze_cols = fc
    sh.outline_from = _outline_from(s.get("outline_from"), sh, f"{where}.outline_from")
    sh.group = _group_spec(s.get("group"), sh, f"{where}.group")
    if sh.group and sh.group["by"] != "outline":
        _reorder_by_group(sh)                 # 按一列分组：同组的行排在一起（在算格公式与列公式之前，cumsum 按这个次序）
    return sh


def _sheet_finish(sh, t, build):
    """列公式、合并、分组、编号、合计、样式与规则。跨表汇总与派生表要等被引用的表先算完（_finish_order）。"""
    s, where = sh._spec, sh._where
    if s.get("derive") is not None:
        _derive_rows(sh, s["derive"], t, f"{where}.derive")
    _formulas(sh, where, t)
    if build:
        _number_warnings(sh, t, where)
    sh.levels = _levels(sh)
    sh.merge_rows = _merge_spec(s.get("merge_rows"), sh, f"{where}.merge_rows")
    sh.subtotals = _subtotal_spec(s.get("subtotals"), sh, f"{where}.subtotals")
    _layout(sh, t, where)
    _numbering(sh, t, where)
    sh.totals = _totals(s.get("totals"), sh, f"{where}.totals", t)
    sh.header_style = _style(s.get("header_style"), f"{where}.header_style")
    sh.row_styles = _row_styles(s.get("row_styles"), f"{where}.row_styles")
    sh.rules = _rules(s.get("rules"), sh, f"{where}.rules", t)
    if build and not sh.rows:
        t.warnings.append({"where": f"{where}.rows", "code": "no_rows",
                           "message": f"“{sh.name}”还没有行，只交出表头" + ("，合计留空" if sh.totals else "")})


def _declared_types(s, sh, where):
    """2.0.0：被公式或合计引用的列必须显式写 type。

    不写 type 的列按行内容推断；行数变了（零行、分批追加）推断结果会跟着变，被引用的列因此可能时而能算、时而报错。
    要求显式写 type，被引用列的类型就不随行数据变化。不被引用的列仍按内容推断。
    公式写错、引用了不存在的列、合计列名不对，这里不报，留给后面的公式与合计校验报原来的错。
    """
    need = {}
    for c in sh.columns:
        if c.formula is None:
            continue
        found = []

        def collect(name, _found=found):
            cc = sh.find(name)
            if cc is not None:
                _found.append(cc)
            return name
        try:
            F.parse(c.formula, collect)
        except F.FormulaError:
            continue
        for cc in found:
            need.setdefault(sh.columns.index(cc), f"公式列“{c.title}”的公式“{c.formula}”")
    spec = s.get("totals")
    for it in spec if isinstance(spec, list) else []:
        name = it if isinstance(it, str) else it.get("column") if isinstance(it, dict) else None
        cc = sh.find(name) if isinstance(name, str) else None
        fn = it.get("fn", "sum") if isinstance(it, dict) else "sum"
        if cc is not None and fn != "none":          # none 只是留空，不读这一列的值
            need.setdefault(sh.columns.index(cc), f"合计（{fn}）")
    for j in sorted(need):
        c = sh.columns[j]
        if c.type is None:
            raise BadInput(f"“{c.title}”被{need[j]}引用，须显式写 type", f"{where}.columns[{j}].type",
                           "被公式或合计引用的列要写 type：数值列写 integer、number、money 或 percent；只做 count 合计的列也可以写 text 等其他类型")


def _column(c, where, j) -> Column:
    col = Column()
    col.inferred = False
    if isinstance(c, str):
        c = {"title": c}
    _allowed(c, COL_KEYS, where)
    col.title = _str(c.get("title"), f"{where}.title", 200, True)
    key = c.get("key")
    if key is not None and (not isinstance(key, str) or not KEY_RE.match(key)):
        raise BadInput("key 由字母、数字、下划线组成，字母或下划线开头，最多 32 个字符；公式里用它引用这一列", f"{where}.key")
    col.key = key or f"c{j + 1}"
    ty = c.get("type")
    if ty is not None and ty not in TYPES:
        raise BadInput(f"type 只能是 {' / '.join(TYPES)}", f"{where}.type")
    col.type = ty
    col.unit = _str(c.get("unit"), f"{where}.unit", 40)
    d = c.get("decimals")
    if d is not None and (isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 10):
        raise BadInput("decimals 是 0–10 的整数：显示几位小数", f"{where}.decimals")
    col.decimals = d
    f = c.get("formula")
    if f is not None and (not isinstance(f, str) or not f.strip()):
        raise BadInput("formula 是公式字符串，例如 \"单价 * 数量\"", f"{where}.formula")
    col.formula = f.strip() if f is not None else None
    col.node = None
    w = c.get("width")
    if w is not None and (isinstance(w, bool) or not isinstance(w, int) or not 4 <= w <= 100):
        raise BadInput("width 是 4–100 的整数：列宽（字符数）", f"{where}.width")
    col.width = w
    a = c.get("align")
    if a is not None and a not in ("left", "center", "right"):
        raise BadInput("align 只能是 left、center、right", f"{where}.align")
    col.align = a
    col.style = _style(c.get("style"), f"{where}.style")
    df = c.get("date_format")
    if df is not None and df not in DATE_FORMATS:
        raise BadInput(f"date_format 只能是 {' / '.join(DATE_FORMATS)}", f"{where}.date_format")
    col.date_format = df
    th = c.get("thousands")
    if th is not None and not isinstance(th, bool):
        raise BadInput("thousands 是 true 或 false：数字要不要千分位", f"{where}.thousands")
    col.thousands = th
    nb = c.get("numbering")
    if nb is not None and nb not in NUMBERINGS:
        raise BadInput("numbering 只能是 seq（数据行依次编 1、2…）或 outline（按 outline_from 的层级编 1、1.1…）", f"{where}.numbering")
    col.numbering = nb
    idf = c.get("identifier")
    if idf is not None and not isinstance(idf, bool):
        raise BadInput("identifier 是 true 或 false：这一列是标识符（编号、代码），不是数", f"{where}.identifier")
    col.identifier = bool(idf)
    return col


def _row(r, where, sh, plain, t, from_model, ri):
    n = len(sh.columns)
    if isinstance(r, dict) and DISPLAY_KEY in r:
        sh.displays.append(_display(r[DISPLAY_KEY], sh, f"{where}.{DISPLAY_KEY}"))
        r = {k: v for k, v in r.items() if k != DISPLAY_KEY}
    else:
        sh.displays.append(None)
    rid = None
    if isinstance(r, dict) and ID_KEY in r:
        rid = r[ID_KEY]
        if not isinstance(rid, str) or not KEY_RE.match(rid):
            raise BadInput(f"{ID_KEY} 是行 id：字母、数字、下划线，字母或下划线开头，最多 32 个字符", f"{where}.{ID_KEY}")
        r = {k: v for k, v in r.items() if k != ID_KEY}
    sh.row_ids.append(rid)
    if isinstance(r, dict):
        out = [None] * n
        for k, v in r.items():
            c = sh.find(k) if isinstance(k, str) else None
            if c is None:
                raise BadInput(f"这一行有表里没有的列：{k}", where, "对象写法的键要与列的 key 或标题相同")
            j = sh.columns.index(c)
            if _is_expr(v) and (c.formula is not None or c.numbering is not None):
                raise BadInput(f"“{c.title}”是{'公式列' if c.formula else '编号列'}，格里不能写 {EXPR_KEY}", f"{where}.{k}",
                               "列公式整列同算；只有个别格算法不同时，把这一列当输入列（不写 formula），在格里写式")
            if c.formula is not None or c.numbering is not None:
                if v is not None and not from_model:
                    _formula_given(t, where, c)
                continue
            out[j] = v
        return out
    if not isinstance(r, list):
        raise BadInput("每行是一个数组（按列的顺序）或一个对象（列名 → 值）", where)
    if len(r) == n:
        out = list(r)
        for j, c in enumerate(sh.columns):
            if _is_expr(out[j]) and (c.formula is not None or c.numbering is not None):
                raise BadInput(f"“{c.title}”是{'公式列' if c.formula else '编号列'}，格里不能写 {EXPR_KEY}", f"{where}[{j}]",
                               "列公式整列同算；只有个别格算法不同时，把这一列当输入列（不写 formula），在格里写式")
            if c.formula is not None or c.numbering is not None:
                if out[j] is not None and not from_model:
                    _formula_given(t, where, c)
                out[j] = None
        return out
    if len(r) == len(plain) and len(plain) < n:
        out = [None] * n
        for j, v in zip(plain, r):
            c = sh.columns[j]
            if c.numbering is not None:           # 编号列给了值：不用，由工具编号
                if _is_expr(v):
                    raise BadInput(f"“{c.title}”是编号列，格里不能写 {EXPR_KEY}", f"{where}[{j}]")
                if v is not None and not from_model:
                    _formula_given(t, where, c)
                continue
            out[j] = v
        return out
    inputs = [j for j in plain if sh.columns[j].numbering is None]
    if len(inputs) < len(plain) and len(r) == len(inputs):     # 2.2.0：编号列由工具编，行里可以不写
        out = [None] * n
        for j, v in zip(inputs, r):
            out[j] = v
        return out
    want = f"列数 {n}" if len(plain) == n else f"列数 {n}，或等于非公式列数 {len(plain)}"
    if len(inputs) < len(plain):
        want += f"，或等于输入列数 {len(inputs)}（不含公式列与编号列）"
    raise BadInput(f"第 {ri + 1} 行有 {len(r)} 格，表有 {n} 列：数组行的格数须等于{want}（实际 {len(r)}）", where,
                   "空格子写 null；分批追加行请用对象行（列的 key 或标题 → 值）；改了列要把已有的数组行按新列重写")


def _formula_given(t, where, c):
    code = "formula_value_ignored"
    if not any(w["code"] == code and w.get("column") == c.key for w in t.warnings):
        what = "公式列，行里给的值不用，按公式算" if c.formula is not None else "编号列，行里给的值不用，由工具编号"
        t.warnings.append({"where": where, "code": code, "column": c.key, "message": f"“{c.title}”是{what}"})


# ---------------------------------------------------------------- 格公式（G17）
class _Expr:
    """格里的保留的式（{"$expr": 式}）。值在整本表解析完以后统一算（_exprs）。"""
    __slots__ = ("src", "where")

    def __init__(self, src, where):
        self.src, self.where = src, where


def _is_expr(v):
    return isinstance(v, dict) and EXPR_KEY in v


def _cell_or_expr(sh, ri, j, v, where, lang, stored=False):
    col = sh.columns[j]
    if isinstance(v, dict):
        if EXPR_KEY not in v:
            raise BadInput(f"单元格只能是字符串、数字、true/false、null，或格公式 {{\"{EXPR_KEY}\": 式}}", where)
        _allowed(v, (EXPR_KEY,), where)
        src = v[EXPR_KEY]
        if not isinstance(src, str) or not src.strip() or len(src) > F.MAX_LEN:
            raise BadInput(f"{EXPR_KEY} 是式的字符串（1–{F.MAX_LEN} 个字符），例如 \"6*28\"、\"@r1.数量*2\"", where)
        if col.type not in ("integer", "number", "money"):
            raise BadInput(f"“{col.title}”是{col.type}列，格公式只用于 integer、number、money 列", where)
        sh.exprs[(ri, j)] = (src.strip(), None)
        return _Expr(src.strip(), where)
    return _cell(col, v, where, lang, stored)


def _expr_kinds(t):
    class K(dict):
        def __missing__(self, k):
            if isinstance(k, tuple) and k and k[0] == "cell":
                return t.book[k[1]].columns[k[3]].kind
            if isinstance(k, tuple) and len(k) == 2:
                sh = next(x for x in t.sheets if x.id == k[0])
                return sh.col(k[1]).kind
            raise KeyError(k)
    return K


def _cell_resolver(t, sh):
    """@行id.列 与 @表id/行id.列 → ("cell", 表序号, 行序号, 列序号)。只能引用输入列的格（不引用公式列与编号列）。"""
    def resolve_ref(sid, rid, col):
        target = sh if sid is None else next((x for x in t.sheets if x.id == sid), None)
        if target is None:
            raise F.FormulaError(f"@{sid}/{rid}.{col}：没有 id 为 {sid} 的表")
        if rid not in target.row_ids:
            raise F.FormulaError(f"@{(sid + '/') if sid else ''}{rid}.{col}：“{target.name}”里没有 id 为 {rid} 的行（被引用的行要写 {ID_KEY}）")
        c = target.find(col)
        if c is None:
            raise F.FormulaError(f"@{(sid + '/') if sid else ''}{rid}.{col}：“{target.name}”里没有“{col}”这一列")
        if c.formula is not None or c.numbering is not None:
            raise F.FormulaError(f"@{(sid + '/') if sid else ''}{rid}.{col}：“{c.title}”是{'公式列' if c.formula else '编号列'}；格公式只引用输入列的格")
        return ("cell", target._index, target.row_ids.index(rid), target.columns.index(c))
    return resolve_ref


def _exprs(t):
    """整本表的格公式一起算：引用别的格时先算那一格；成环回 BAD_INPUT。照 G4 再用双精度算一遍，不同就告警。"""
    pending = [(sh, ri, j) for sh in t.sheets for (ri, j) in sh.exprs]
    if not pending:
        return
    K = _expr_kinds(t)
    nodes = {}
    for sh, ri, j in pending:
        e = sh.rows[ri][j]

        def resolve(name, _sh=sh):
            c = _sh.find(name)
            if c is None:
                raise F.FormulaError(f"式里的“{name}”不是这张表的列；引用别的行写 @行id.列，别的表写 @表id/行id.列")
            if c.formula is not None or c.numbering is not None:
                raise F.FormulaError(f"“{c.title}”是{'公式列' if c.formula else '编号列'}；格公式只引用输入列")
            return c.key
        try:
            node = F.parse(e.src, resolve, _cell_resolver(t, sh))
            k = F.kind_of(node, K({c.key: c.kind for c in sh.columns}))
        except F.FormulaError as err:
            raise BadInput(f"格公式“{e.src}”：{err}", e.where) from None
        if k != "num":
            raise BadInput(f"格公式“{e.src}”的结果要是数（{'条件' if k == 'bool' else '文字'}不行）", e.where)
        nodes[("cell", sh._index, ri, j)] = (node, e)
    state, val = {}, {}

    class Ext:
        def cell(self, loc):
            return get(loc)

    def get(loc):
        if loc not in nodes:
            return t.book[loc[1]].rows[loc[2]][loc[3]]
        if loc in val:
            return val[loc]
        node, e = nodes[loc]
        if state.get(loc) == 1:
            raise BadInput(f"格公式成环：“{e.src}”引用回到了自己", e.where)
        state[loc] = 1
        sh = t.book[loc[1]]
        used = F.row_refs(node)               # 只取式里用到的本行的列（不碰自己这一格）
        row = {c.key: get(("cell", loc[1], loc[2], jj)) for jj, c in enumerate(sh.columns) if c.key in used}
        try:
            v = F.evaluate(node, row, None, loc[2], Ext())
        except F.DivZero:
            v = None
            t.warnings.append({"where": e.where, "code": "div_zero", "message": f"格公式“{e.src}”除以零，这一格留空"})
        except F.FormulaError as err:
            raise BadInput(f"格公式“{e.src}”：{err}", e.where) from None
        col = sh.columns[loc[3]]
        if v is not None:
            v = quantize(v, None)
            if col.type == "integer" and v != v.to_integral_value():
                raise BadInput(f"格公式“{e.src}”算出 {dec_str(v)}，“{col.title}”是整数列", e.where,
                               "要取整就在式里写 roundup、rounddown、ceiling、floor 或 round；要小数就把这一列的 type 改成 number")
            v = Decimal(dec_str(v))
        val[loc] = v
        state[loc] = 2
        fv, hit = F.float_eval(node, row, None, loc[2], Ext())
        if hit and v is not None and isinstance(fv, float) and Decimal(dec_str(quantize(Decimal(repr(fv)), None))) != v:
            t.warnings.append({"where": e.where, "code": "excel_float",
                               "message": f"格公式“{e.src}”（{sh.name}!{col_name(loc[3])}{loc[2] + 2}）在 Excel 里重算可能得 {dec_str(Decimal(repr(fv)))}；"
                                          f"产出台按十进制算得 {dec_str(v)}。导出的公式已先归整到 15 位有效数字，仍请在 Excel 里核对这一格"})
        return v
    for loc in nodes:
        get(loc)
    for loc, (node, e) in nodes.items():       # 先全部算完再写回：算的时候别的格读的是 val
        sh = t.book[loc[1]]
        sh.rows[loc[2]][loc[3]] = val[loc]
        sh.exprs[(loc[2], loc[3])] = (e.src, node)


# ---------------------------------------------------------------- 跨表：次序、派生表、表序（G10）
def _sheet_deps(sh, t):
    deps = set()
    for c in sh.columns:
        if c.formula is None:
            continue
        try:
            node = F.parse(c.formula, lambda n: n, None, lambda sid, col: (sid, col))
        except F.FormulaError:
            continue
        deps |= F.sheet_refs(node)
    d = sh._spec.get("derive")
    if isinstance(d, dict) and isinstance(d.get("from"), list):
        deps |= {x for x in d["from"] if isinstance(x, str)}
    return deps


def _finish_order(t):
    by_id = {sh.id: sh for sh in t.sheets if sh.id}
    order, state = [], {}

    def visit(sh, path):
        if state.get(id(sh)) == 2:
            return
        if state.get(id(sh)) == 1:
            names = "、".join(x.name for x in path[path.index(sh):] + [sh])
            raise BadInput(f"表之间的引用成环：{names}", sh._where)
        state[id(sh)] = 1
        for sid in sorted(_sheet_deps(sh, t)):
            if sid == sh.id:
                continue
            other = by_id.get(sid)
            if other is None:
                raise BadInput(f"“{sh.name}”引用了不存在的表 id：{sid}", sh._where, "跨表引用按表的 id；被引用的表删了要先改引用它的公式")
            visit(other, path + [sh])
        state[id(sh)] = 2
        order.append(sh)
    for sh in t.sheets:
        visit(sh, [])
    return order


def _sheet_order(v, sheets):
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise BadInput("sheet_order 是表 id 的数组，按此次序排表；没列进去的表排在后面", "table.sheet_order")
    ids = [s.id for s in sheets]
    bad = [x for x in v if x not in ids]
    if bad:
        raise BadInput(f"sheet_order 里的“{bad[0]}”不是哪张表的 id", "table.sheet_order")
    if len(set(v)) != len(v):
        raise BadInput("sheet_order 里有重复的 id", "table.sheet_order")
    pos = {x: i for i, x in enumerate(v)}
    return sorted(sheets, key=lambda s: (0, pos[s.id]) if s.id in pos else (1, sheets.index(s)))


def norm_key(v):
    """合并与派生的键：NFKC 后去掉首尾空白，逐字比（G9）。"""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return ("n", v)
    return ("s", unicodedata.normalize("NFKC", str(v)).strip())


NEAR = str.maketrans({"x": "×", "X": "×", "*": "×", "＊": "×"})


def near_key(k):
    return tuple(None if x is None else (x[0], x[1].casefold().translate(NEAR)) if x[0] == "s" else x for x in k)


def _near_warnings(t, keys, where, what):
    """写法相近（不分大小写，x、X、*、＊ 当作 ×）而原文不同的键：不合并，告警点名两种写法。"""
    seen = {}
    told = set()
    for k in keys:
        nk = near_key(k)
        if nk in seen and seen[nk] != k and (seen[nk], k) not in told:
            told.add((seen[nk], k))
            a = "、".join("" if x is None else str(x[1]) for x in seen[nk])
            b = "、".join("" if x is None else str(x[1]) for x in k)
            t.warnings.append({"where": where, "code": "merge_key_near",
                               "message": f"{what}的键“{a}”与“{b}”写法相近而不同，没有合并；要合并请先统一写法"})
        seen.setdefault(nk, k)


def _derive_rows(sh, d, t, where):
    """派生表（T9-08 的“标准件”）：从几张表里取符合条件的行，按键合并，agg 只收 sum。"""
    _allowed(d, ("from", "where", "by", "agg"), where)
    src_ids = d.get("from")
    if not isinstance(src_ids, list) or not src_ids or not all(isinstance(x, str) for x in src_ids):
        raise BadInput("derive.from 是来源表 id 的数组", f"{where}.from")
    srcs = []
    for x in src_ids:
        o = next((s for s in t.sheets if s.id == x), None)
        if o is None or o is sh:
            raise BadInput(f"derive.from 里的“{x}”不是别的表的 id", f"{where}.from")
        srcs.append(o)
    by = d.get("by")
    if not isinstance(by, list) or not by or not all(isinstance(x, str) for x in by):
        raise BadInput("derive.by 是键列的数组，例如 [\"产品名称\", \"规格\"]", f"{where}.by")
    agg = d.get("agg", {})
    if not isinstance(agg, dict) or any(v != "sum" for v in agg.values()):
        raise BadInput("derive.agg 写 {列: \"sum\"}：派生表从各分部取值相加，只收 sum", f"{where}.agg")
    for c in sh.columns:
        if c.formula is None and all(o.find(c.key) is None and o.find(c.title) is None for o in srcs):
            raise BadInput(f"派生表的列“{c.title}”在来源表里都没有", f"{where}", "派生表的列要与来源表的列同名（标题或 key）")
    for name in list(by) + list(agg):
        if sh.find(name) is None:
            raise BadInput(f"“{name}”不是派生表的列", f"{where}.by" if name in by else f"{where}.agg")
    cond = d.get("where")
    groups, order, members = {}, [], {}
    for o in srcs:
        node = None
        if cond is not None:
            if not isinstance(cond, str) or not cond.strip():
                raise BadInput("derive.where 是条件式，例如 \"产品角色 = \\\"五金\\\"\"", f"{where}.where")
            try:
                node = F.parse(cond, _resolver(o, None, "条件"))
                if F.kind_of(node, _kinds(o)) != "bool":
                    raise F.FormulaError("不是条件")
            except F.FormulaError as e:
                raise BadInput(f"derive.where“{cond}”在“{o.name}”里：{e}", f"{where}.where") from None
        cols_o = {c.key: [r[k] for r in o.rows] for k, c in enumerate(o.columns)}
        for ri, r in enumerate(o.rows):
            if node is not None and F.evaluate(node, _env(o, r), cols_o, ri) is not True:
                continue
            key = tuple(norm_key(_src_val(o, r, sh.find(b))) for b in by)
            if all(x is None for x in key):
                continue
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((o, ri))
    _near_warnings(t, order, where, "派生表")
    for c in sh.columns:                                   # 没写 type 的列取来源表同名列的类型
        if c.type is None:
            for o in srcs:
                oc = o.find(c.key) or o.find(c.title)
                if oc is not None:
                    c.type = oc.type
                    break
            c.type = c.type or "text"
            c.inferred = True
            c.align = c.align or ("right" if c.type in NUMERIC else "center" if c.type == "bool" else "left")
    agg_keys = {sh.find(a).key for a in agg}
    sh.rows, sh.displays, sh.row_ids = [], [], []
    for gi, key in enumerate(order):
        mem = groups[key]
        row = []
        for c in sh.columns:
            if c.formula is not None:
                row.append(None)
                continue
            vals = [_src_val(o, o.rows[ri], c) for o, ri in mem]
            if c.key in agg_keys:
                nums = [v for v in vals if isinstance(v, Decimal)]
                row.append(sum(nums, Decimal(0)) if nums else None)
            elif all(v == vals[0] for v in vals):
                row.append(vals[0])
            else:
                row.append(None)
        sh.rows.append(row)
        sh.displays.append(None)
        sh.row_ids.append(None)
        sh.derive_src[gi] = {c.key: [(o, ri, o.columns.index(o.find(c.key) or o.find(c.title))) for o, ri in mem]
                             for c in sh.columns if c.key in agg_keys}
    sh.derive = {"from": list(src_ids), "by": [sh.find(b).key for b in by], "agg": {sh.find(a).key: "sum" for a in agg},
                 **({"where": cond.strip()} if cond else {})}


def _src_val(o, r, c):
    """派生表的列在来源表里对应的值（按 key 或标题找）。"""
    if c is None:
        return None
    oc = o.find(c.key) or o.find(c.title)
    if oc is None:
        return None
    return r[o.columns.index(oc)]


# ---------------------------------------------------------------- 层级、分组、合并、编号（G7–G9）
def _outline_from(v, sh, where):
    """层级来源：{column: 一列文字, levels: {文字: 1–4}}。不收整数层级列（写在行里的数要证件）。"""
    if v is None:
        return None
    _allowed(v, ("column", "levels"), where)
    c = sh.find(v.get("column")) if isinstance(v.get("column"), str) else None
    if c is None:
        raise BadInput(f"outline_from.column“{v.get('column')}”不是这张表的列", f"{where}.column")
    if c.type != "text":
        raise BadInput(f"层级来源“{c.title}”要是一列文字（如“产品角色”：主件、焊接子件），不收整数层级列", f"{where}.column",
                       "写在行里的 1、2 是数据，每一格都要证件；用一列文字按 levels 映射成层级")
    lv = v.get("levels")
    if not isinstance(lv, dict) or not lv:
        raise BadInput("outline_from.levels 是 {文字: 层级}，例如 {\"主件\": 1, \"焊接子件\": 2}", f"{where}.levels")
    out = {}
    for k, n in lv.items():
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_LEVEL:
            raise BadInput(f"层级是 1–{MAX_LEVEL} 的整数", f"{where}.levels")
        out[unicodedata.normalize("NFKC", k).strip()] = n
    return (c.key, out)


def _levels(sh):
    if not sh.outline_from:
        return None
    key, lv = sh.outline_from
    j = next(k for k, c in enumerate(sh.columns) if c.key == key)
    return [lv.get(unicodedata.normalize("NFKC", r[j]).strip()) if isinstance(r[j], str) else None for r in sh.rows]


def _group_spec(v, sh, where):
    if v is None:
        return None
    _allowed(v, ("by", "rest_label", "label_column"), where)
    by = v.get("by")
    out = {}
    if by == "outline":
        if not sh.outline_from:
            raise BadInput("group.by 为 outline 时要先写 outline_from（层级来源）", f"{where}.by")
        out["by"] = "outline"
    else:
        c = sh.find(by) if isinstance(by, str) else None
        if c is None:
            raise BadInput(f"group.by 写一列的名字（按这一列的值分组），或写 \"outline\"（按层级分组）", f"{where}.by")
        if c.formula is not None or c.numbering is not None:
            raise BadInput(f"“{c.title}”是{'公式列' if c.formula else '编号列'}；按输入列的值分组", f"{where}.by")
        out["by"] = c.key
    if v.get("rest_label") is not None:
        if out["by"] != "outline":
            raise BadInput("rest_label 只用于按层级分组：层级为空的连续几行另成一组，组头显示这个名字", f"{where}.rest_label")
        out["rest_label"] = _str(v.get("rest_label"), f"{where}.rest_label", 100, True)
    if v.get("label_column") is not None:
        c = sh.find(v["label_column"]) if isinstance(v["label_column"], str) else None
        if c is None:
            raise BadInput("label_column 写一列的名字：组头、小计的标签写在这一列", f"{where}.label_column")
        out["label_column"] = c.key
    return out


def _reorder_by_group(sh):
    """按一列分组：组的次序按该值首次出现的先后，组内保持原行序（行跟着它的样式与 id 一起挪）。"""
    j = next(k for k, c in enumerate(sh.columns) if c.key == sh.group["by"])
    first, order = {}, []
    for ri, r in enumerate(sh.rows):
        k = norm_key(r[j]) if not isinstance(r[j], _Expr) else ("e", ri)
        if k not in first:
            first[k] = len(first)
        order.append((first[k], ri))
    perm = [ri for _, ri in sorted(order)]
    if perm == list(range(len(sh.rows))):
        return
    new_index = {old: new for new, old in enumerate(perm)}
    sh.rows = [sh.rows[i] for i in perm]
    sh.displays = [sh.displays[i] for i in perm]
    sh.row_ids = [sh.row_ids[i] for i in perm]
    sh.exprs = {(new_index[ri], j2): v for (ri, j2), v in sh.exprs.items()}


def _subtotal_spec(v, sh, where):
    if v is None:
        return []
    if not sh.group:
        raise BadInput("subtotals 要配 group：先分组，每组末尾出一行小计", where)
    if not isinstance(v, list) or len(v) > MAX_COLS:
        raise BadInput("subtotals 是 [{column, fn}]，fn 同合计（sum、avg、min、max、count、formula）", where)
    out, seen = [], set()
    for i, it in enumerate(v):
        w = f"{where}[{i}]"
        if isinstance(it, str):
            it = {"column": it, "fn": "sum"}
        _allowed(it, ("column", "fn"), w)
        c = sh.find(it.get("column")) if isinstance(it.get("column"), str) else None
        if c is None:
            raise BadInput(f"小计的列“{it.get('column')}”不在表里", f"{w}.column")
        fn = it.get("fn", "sum")
        if fn not in FNS or fn == "none":
            raise BadInput("小计的 fn 只能是 sum、avg、min、max、count、formula", f"{w}.fn")
        if fn not in ("count",) and c.type not in NUMERIC:
            raise BadInput(f"“{c.title}”不是数值列，只能 count", f"{w}.fn")
        if fn == "formula" and (c.formula is None or F.uses(c.node, ("agg", "xagg", "sumif", "countif"))):
            raise BadInput(f"“{c.title}”不能按公式小计（不是公式列，或公式看整列、看别的表）", f"{w}.fn")
        if c.key in seen:
            raise BadInput(f"“{c.title}”的小计写了两次", w)
        seen.add(c.key)
        out.append({"column": c.key, "fn": fn})
    return out


def _merge_spec(v, sh, where):
    if v is None:
        return None
    _allowed(v, ("by", "scope", "agg", "join"), where)
    by = v.get("by")
    if not isinstance(by, list) or not by or not all(isinstance(x, str) for x in by):
        raise BadInput("merge_rows.by 是键列的数组，例如 [\"名称\", \"规格\"]", f"{where}.by")
    keys = []
    for x in by:
        c = sh.find(x)
        if c is None:
            raise BadInput(f"merge_rows.by 里的“{x}”不是这张表的列", f"{where}.by")
        keys.append(c.key)
    scope = v.get("scope", "sheet")
    if scope not in ("sheet", "group"):
        raise BadInput("merge_rows.scope 是 sheet（整张表里合并）或 group（只在组内合并）", f"{where}.scope")
    if scope == "group" and not sh.group:
        raise BadInput("scope 为 group 时要先写 group", f"{where}.scope")
    agg = v.get("agg", {})
    if not isinstance(agg, dict):
        raise BadInput("merge_rows.agg 是 {列: \"sum\" | \"formula\"}", f"{where}.agg")
    ag = {}
    for name, how in agg.items():
        c = sh.find(name)
        if c is None:
            raise BadInput(f"merge_rows.agg 里的“{name}”不是这张表的列", f"{where}.agg")
        if how not in ("sum", "formula"):
            raise BadInput("agg 只能是 sum（各行相加）或 formula（合并后按本列公式重算）", f"{where}.agg")
        if how == "formula" and c.formula is None:
            raise BadInput(f"“{c.title}”不是公式列，不能按公式重算；输入列写 sum", f"{where}.agg")
        if how == "formula" and F.uses(c.node, ("agg", "xagg", "sumif", "countif")):
            raise BadInput(f"“{c.title}”的公式看整列或别的表，合并行上不能重算", f"{where}.agg")
        if how == "sum" and c.type not in NUMERIC:
            raise BadInput(f"“{c.title}”不是数值列，不能相加", f"{where}.agg")
        if how == "formula" and any(j == sh.columns.index(c) for (_, j) in sh.exprs):
            raise BadInput(f"“{c.title}”里有格公式，只能 sum", f"{where}.agg")
        ag[c.key] = how
    for j, c in enumerate(sh.columns):            # 格公式所在的列只能 sum
        if c.key in ag and ag[c.key] != "sum" and any(jj == j for (_, jj) in sh.exprs):
            raise BadInput(f"“{c.title}”里有格公式，合并口径只能 sum", f"{where}.agg")
        if c.formula is not None and c.key not in ag and F.uses(c.node, F.DISCONTINUOUS):
            raise BadInput(f"“{c.title}”的公式含取整函数，合并口径要写明：sum（各行取整后相加）或 formula（合并后再取整）",
                           f"{where}.agg", "例如 agg: {\"下料数量\": \"formula\"}")
    join = v.get("join", [])
    if not isinstance(join, list) or not all(isinstance(x, str) for x in join):
        raise BadInput("merge_rows.join 是文字列的数组：这些列用“；”连起来", f"{where}.join")
    jk = []
    for x in join:
        c = sh.find(x)
        if c is None or c.type not in ("text",):
            raise BadInput(f"merge_rows.join 里的“{x}”要是这张表的文字列", f"{where}.join")
        jk.append(c.key)
    return {"by": keys, "scope": scope, "agg": ag, "join": jk}


def _merged_values(sh, members, t, where):
    m = sh.merge_rows
    vals = [None] * len(sh.columns)
    for j, c in enumerate(sh.columns):
        col = [sh.rows[ri][j] for ri in members]
        if c.key in m["by"]:
            vals[j] = col[0]
        elif c.key in m["join"]:
            seen = []
            for x in col:
                if x is not None and x not in seen:
                    seen.append(x)
            vals[j] = "；".join(seen) if seen else None
        elif m["agg"].get(c.key) == "sum":
            nums = [x for x in col if isinstance(x, Decimal)]
            vals[j] = sum(nums, Decimal(0)) if nums else None
        elif m["agg"].get(c.key) == "formula":
            vals[j] = None             # 下面按公式重算
        elif all(x == col[0] for x in col):
            vals[j] = col[0]
        elif c.formula is not None:
            raise BadInput(f"合并的几行“{c.title}”各不相同，要在 merge_rows.agg 里写明口径（sum 或 formula）", f"{where}.agg")
        else:
            vals[j] = None             # 各行不同又没写口径：留空，不猜（数值列要相加就在 agg 里写 sum）
            if c.type in NUMERIC and not any(w.get("column") == c.key and w["code"] == "merge_blank" for w in t.warnings):
                t.warnings.append({"where": f"{where}.agg", "code": "merge_blank", "column": c.key,
                                   "message": f"合并的几行“{c.title}”各不相同，合并行上留空；要相加就在 merge_rows.agg 里写 \"{c.title}\": \"sum\""})
    for j, c in enumerate(sh.columns):           # 合并后按本列公式重算（左边的列先算好）
        if m["agg"].get(c.key) == "formula":
            try:
                v = F.evaluate(c.node, {cc.key: vals[k] for k, cc in enumerate(sh.columns)})
            except F.DivZero:
                v = None
            if v is not None and c.type == "integer":
                v = v.quantize(Decimal(1), rounding=ROUND_HALF_UP)
            vals[j] = None if v is None or c.type == "text" else quantize(v, c.decimals if c.type != "percent" or c.decimals is None else c.decimals + 2)
    return vals


def _layout(sh, t, where):
    """显示的次序：组头（包生成的，或就是那一行数据）、组员、合并行（明细折叠在它上面）、小计行。只有分组或合并时才有。"""
    sh.layout, sh.merged = [], []
    if not sh.group and not sh.merge_rows:
        return
    n = len(sh.rows)
    # 1 分组
    groups = []        # {label, head (数据行号或 None), members: [行号]}
    if not sh.group:
        groups = [{"label": None, "head": None, "members": list(range(n)), "gen": False}]
    elif sh.group["by"] == "outline":
        cur = None
        for ri in range(n):
            lv = sh.levels[ri]
            if lv == 1:                      # 层级 1 的行开一组，它自己就是组头（仍是数据行）
                cur = {"label": None, "head": ri, "members": [], "gen": False}
                groups.append(cur)
            elif lv is None and sh.group.get("rest_label"):
                if cur is None or not cur.get("rest"):   # 层级为空的连续几行另成一组，组头由包生成
                    cur = {"label": sh.group["rest_label"], "head": None, "members": [], "gen": True, "rest": True}
                    groups.append(cur)
                cur["members"].append(ri)
            else:
                if cur is None or (cur.get("rest") and lv is not None):   # 第一个层级 1 之前的行：不成组头
                    cur = {"label": None, "head": None, "members": [], "gen": False, "loose": True}
                    groups.append(cur)
                cur["members"].append(ri)
    else:
        j = next(k for k, c in enumerate(sh.columns) if c.key == sh.group["by"])
        last = object()
        for ri in range(n):
            k = norm_key(sh.rows[ri][j])
            if k != last:
                from render import display as _disp
                label = _disp(sh.columns[j], sh.rows[ri][j], t.lang) or "（空）"
                groups.append({"label": label, "head": None, "members": [], "gen": True})
                last = k
            groups[-1]["members"].append(ri)
    # 2 合并
    detail_of, place = {}, {}
    if sh.merge_rows:
        m = sh.merge_rows
        idx = [next(k for k, c in enumerate(sh.columns) if c.key == b) for b in m["by"]]
        scopes = [[g["head"]] * (g["head"] is not None) + g["members"] for g in groups] if m["scope"] == "group" \
            else [[ri for g in groups for ri in ([g["head"]] * (g["head"] is not None) + g["members"])]]
        all_keys = []
        for sc in scopes:
            buckets, order = {}, []
            for ri in sc:
                key = tuple(norm_key(sh.rows[ri][j]) for j in idx)
                if all(x is None for x in key):
                    continue
                if key not in buckets:
                    buckets[key] = []
                    order.append(key)
                buckets[key].append(ri)
            all_keys += order
            for key in order:
                mem = buckets[key]
                if len(mem) < 2:
                    continue
                mi = len(sh.merged)
                sh.merged.append({"members": mem, "values": _merged_values(sh, mem, t, where)})
                for ri in mem:
                    detail_of[ri] = mi
                place[mem[-1]] = mi
        _near_warnings(t, all_keys, f"{where}.merge_rows", "合并")
    # 3 排出显示次序
    sub = {x["column"]: x["fn"] for x in sh.subtotals}
    for gi, g in enumerate(groups):
        gid = gi if sh.group else None
        if g["gen"]:
            sh.layout.append({"kind": "group", "group": gid, "label": g["label"]})
        rows_g = ([g["head"]] if g["head"] is not None else []) + g["members"]
        for ri in rows_g:
            e = {"kind": "data", "ri": ri, "group": gid}
            if ri == g["head"]:
                e["head"] = True
            if ri in detail_of:
                e["detail"] = detail_of[ri]
            sh.layout.append(e)
            if ri in place:
                sh.layout.append({"kind": "merged", "mi": place[ri], "group": gid, "values": sh.merged[place[ri]]["values"]})
        if sub and sh.group and not g.get("loose"):
            eff = [e for e in sh.layout if e.get("group") == gid and
                   (e["kind"] == "merged" or (e["kind"] == "data" and "detail" not in e))]
            sh.layout.append({"kind": "subtotal", "group": gid, "label": g["label"] or _head_label(sh, g, t),
                              "values": _subtotal_values(sh, eff, sub, t), "rows": eff})


def _head_label(sh, g, t):
    if g["head"] is None:
        return None
    from render import display as _disp
    lc = _label_col(sh)
    j = next(k for k, c in enumerate(sh.columns) if c.key == lc)
    return _disp(sh.columns[j], sh.rows[g["head"]][j], t.lang) or None


def _label_col(sh):
    """组头、小计的标签写在哪一列：group.label_column；缺省取第一列不是编号的文字列，再不行取第一列。"""
    if sh.group and sh.group.get("label_column"):
        return sh.group["label_column"]
    skip = {sh.outline_from[0]} if sh.outline_from else set()
    for c in sh.columns:
        if c.type == "text" and c.numbering is None and c.formula is None and c.key not in skip:
            return c.key
    return sh.columns[0].key


def _subtotal_values(sh, eff, sub, t):
    vals = [None] * len(sh.columns)
    rows = [e["values"] if e["kind"] == "merged" else sh.rows[e["ri"]] for e in eff]
    for j, c in enumerate(sh.columns):
        fn = sub.get(c.key)
        if fn and fn != "formula":
            vals[j] = aggregate([r[j] for r in rows], fn, c)
    for j, c in enumerate(sh.columns):
        if sub.get(c.key) == "formula":
            env = {k: vals[kk] if sub.get(k) not in (None, "count") else None
                   for kk, k in enumerate(cc.key for cc in sh.columns) if k in F.row_refs(c.node)}
            try:
                v = F.evaluate(c.node, env)
            except F.DivZero:
                v = None
            vals[j] = None if v is None else quantize(v, c.decimals if c.type != "percent" or c.decimals is None else c.decimals + 2)
    return vals


def _numbering(sh, t, where):
    """编号列（G8）：seq 给看得见的数据行依次编 1…n（生成的组头、小计不编，合并掉的明细不编，合并行编）；
    outline 按层级编 1、1.1、1.2、2…，层级为空的行不编号。编号存为文字（outline）或整数（seq），每次都重算。"""
    cols = [(j, c) for j, c in enumerate(sh.columns) if c.numbering]
    if not cols:
        return
    for j, c in cols:
        if c.numbering == "outline" and not sh.outline_from:
            raise BadInput(f"“{c.title}”按层级编号（numbering outline），要先写 outline_from", f"{where}.columns[{j}].numbering")
    seq = [e for e in sh.layout if e["kind"] == "merged" or (e["kind"] == "data" and "detail" not in e)] if sh.layout \
        else [{"kind": "data", "ri": ri} for ri in range(len(sh.rows))]
    for j, c in cols:
        for ri in range(len(sh.rows)):
            sh.rows[ri][j] = None
        counters = [0] * (MAX_LEVEL + 1)
        k = 0
        for e in seq:
            target = sh.merged[e["mi"]]["values"] if e["kind"] == "merged" else sh.rows[e["ri"]]
            if c.numbering == "seq":
                k += 1
                target[j] = Decimal(k) if c.type == "integer" else str(k)
                continue
            lv = _level_of(sh, e)
            if lv is None:
                target[j] = None
                continue
            counters[lv] += 1
            for d in range(lv + 1, MAX_LEVEL + 1):
                counters[d] = 0
            parts = counters[1:lv + 1]
            target[j] = ".".join(str(x) for x in parts) if all(parts) else None


def _level_of(sh, e):
    if e["kind"] == "merged":
        key, lv = sh.outline_from
        j = next(k for k, c in enumerate(sh.columns) if c.key == key)
        v = sh.merged[e["mi"]]["values"][j]
        return lv.get(unicodedata.normalize("NFKC", v).strip()) if isinstance(v, str) else None
    return sh.levels[e["ri"]]


# ---------------------------------------------------------------- 样式（G1）
def _style(v, where):
    """样式值 {fill?, color?, bold?, italic?} → 规范写法（颜色用色板里的中文名）；缺席或空对象 → None。"""
    if v is None:
        return None
    if not isinstance(v, dict):
        raise BadInput("样式是对象：{fill 底色, color 字色, bold 加粗, italic 斜体}", where)
    _allowed(v, STYLE_KEYS, where)
    out = {}
    for k in STYLE_KEYS:
        if k not in v:
            continue
        x = v[k]
        if k in ("fill", "color"):
            out[k] = _color(x, f"{where}.{k}")
        else:
            if not isinstance(x, bool):
                raise BadInput(f"{k} 是 true 或 false", f"{where}.{k}")
            out[k] = x
    return out or None


def _color(x, where):
    if isinstance(x, str):
        n = unicodedata.normalize("NFKC", x).strip()
        if n in PALETTE:
            return n
        a = COLOR_ALIAS.get(n.lower().replace(" ", "").replace("_", ""))
        if a:
            return a
    raise BadInput(f"颜色取色板里的名字：{'、'.join(PALETTE)}", where, "也认英文名 red、orange、yellow、green、blue、navy、gray、lightgray、white、black、lightred、lightyellow")


def _display(v, sh, where):
    """行里的保留键 $style：{row: 样式（整行）, cells: {列名: 样式}}。跟着这一行走，不按行号寻址（17 TL-30 v0.2.98）。"""
    if not isinstance(v, dict):
        raise BadInput(f"{DISPLAY_KEY} 是对象：{{row: 整行的样式, cells: {{列名: 这一格的样式}}}}", where)
    _allowed(v, ("row", "cells"), where)
    out = {}
    row = _style(v.get("row"), f"{where}.row")
    if row:
        out["row"] = row
    cells = v.get("cells")
    if cells is not None:
        if not isinstance(cells, dict):
            raise BadInput("cells 是对象：列的 key 或标题 → 样式", f"{where}.cells")
        cs = {}
        for k, st in cells.items():
            c = sh.find(k) if isinstance(k, str) else None
            if c is None:
                raise BadInput(f"cells 里的“{k}”不是这张表的列", f"{where}.cells")
            if c.key in cs:
                raise BadInput(f"cells 里“{c.title}”写了两次", f"{where}.cells")
            st = _style(st, f"{where}.cells.{k}")
            if st:
                cs[c.key] = st
        if cs:
            out["cells"] = {c.key: cs[c.key] for c in sh.columns if c.key in cs}
    return out or None


def _row_styles(v, where):
    if v is None:
        return {}
    if not isinstance(v, list) or len(v) > len(ROW_KINDS):
        raise BadInput(f"row_styles 是数组：[{{kind, style}}]，kind 为 {' / '.join(ROW_KINDS)}", where)
    out = {}
    for i, it in enumerate(v):
        w = f"{where}[{i}]"
        _allowed(it, ("kind", "style"), w)
        k = it.get("kind")
        if k not in ROW_KINDS:
            raise BadInput(f"kind 只能是 {' / '.join(ROW_KINDS)}（total 合计行）；某一行、某一格的样式写在那一行的 {DISPLAY_KEY} 里",
                           f"{w}.kind")
        if k in out:
            raise BadInput(f"row_styles 里 {k} 写了两次", w)
        st = _style(it.get("style"), f"{w}.style")
        if st:
            out[k] = st
    return out


def _rules(v, sh, where, t):
    """条件规则（有序，先命中先得，逐属性）。条件直接写条件式（与公式同一种写法）；色阶单列。不标 by-id：给了就整组替换。"""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > MAX_RULES:
        raise BadInput(f"rules 是规则的数组（最多 {MAX_RULES} 条）：[{{when, apply_to, style}}] 或 [{{scale: {{column, from, to}}}}]", where)
    kinds = _kinds(sh)
    out = []
    for i, it in enumerate(v):
        w = f"{where}[{i}]"
        if not isinstance(it, dict):
            raise BadInput("每条规则是对象：{when 条件, apply_to 着色范围, style 样式}，或色阶 {scale: {column, from, to}}", w)
        label = _str(it.get("label"), f"{w}.label", 200)
        if "scale" in it:
            _allowed(it, ("scale", "label"), w)
            sc = it["scale"]
            _allowed(sc, ("column", "from", "to"), f"{w}.scale")
            c = sh.find(sc.get("column")) if isinstance(sc.get("column"), str) else None
            if c is None:
                raise BadInput(f"色阶的列“{sc.get('column')}”不在表里", f"{w}.scale.column")
            if c.type not in NUMERIC:
                raise BadInput(f"“{c.title}”不是数值列，不能做色阶", f"{w}.scale.column")
            a = _color(sc.get("from", "白"), f"{w}.scale.from")
            b = _color(sc.get("to", "绿"), f"{w}.scale.to")
            out.append({"kind": "scale", "scale": (c.key, a, b), "label": label, "where": w})
            continue
        _allowed(it, ("when", "apply_to", "style", "label"), w)
        src = it.get("when")
        if not isinstance(src, str) or not src.strip():
            raise BadInput("when 是条件式，例如 \"金额 > 10000\"、\"实际 > 预算\"、\"到货日期 > \\\"2026-11-20\\\"\"", f"{w}.when")
        try:
            node = F.parse(src, _resolver(sh, None, "条件"))
            k = F.kind_of(node, kinds)
        except F.FormulaError as e:
            raise BadInput(f"条件“{src}”：{e}", f"{w}.when") from None
        if k != "bool":
            raise BadInput(f"条件“{src}”不是条件：要写比较（> >= < <= = <>），或用 and、or、not 组合", f"{w}.when")
        ap = it.get("apply_to")
        if ap is None:
            keys = [c.key for c in sh.columns if c.key in F.row_refs(node)]
            if not keys:
                raise BadInput("这条规则没有引用列，写 apply_to 说明给哪些列着色", f"{w}.apply_to")
            apply = keys
        elif ap == "row":
            apply = "row"
        elif isinstance(ap, list) and ap and all(isinstance(x, str) for x in ap):
            apply = []
            for x in ap:
                c = sh.find(x)
                if c is None:
                    raise BadInput(f"apply_to 里的“{x}”不是这张表的列", f"{w}.apply_to")
                if c.key not in apply:
                    apply.append(c.key)
            apply = [c.key for c in sh.columns if c.key in apply]
        else:
            raise BadInput("apply_to 写 \"row\"（整行着色），或列名的数组；不写时给条件里引用的列着色", f"{w}.apply_to")
        st = _style(it.get("style"), f"{w}.style")
        if not st:
            raise BadInput("规则要有 style：{fill 底色, color 字色, bold, italic}", f"{w}.style")
        r = {"kind": "when", "src": src.strip(), "node": node, "apply": apply, "style": st, "label": label, "where": w}
        r["hits"] = _rule_hits(sh, r, t)
        out.append(r)
    return out


def _rule_hits(sh, r, t):
    """规则命中的数据行（不管合计行）。条件里的比较照双精度再算一遍，结果不同就告警（G4）。"""
    cols = {c.key: [row[k] for row in sh.rows] for k, c in enumerate(sh.columns)}
    hits, flt = [], []
    for ri, row in enumerate(sh.rows):
        env = _env(sh, row)
        try:
            v = F.evaluate(r["node"], env, cols, ri)
        except F.DivZero:
            v = None
        hits.append(v is True)
        fv, hit = F.float_eval(r["node"], env, cols, ri)
        if hit and (fv is True) != (v is True):
            flt.append(ri)
    for ri in flt[:MAX_FLOAT_WARN]:
        t.warnings.append({"where": f"{r['where']}.when", "code": "excel_float",
                           "message": f"规则“{r['src']}”在第 {ri + 1} 行：产出台判{'命中' if hits[ri] else '不命中'}，"
                                      f"Excel 里按双精度比较可能{'不命中' if hits[ri] else '命中'}（数在比较的边界上）；"
                                      "导出的条件已先归整到 15 位有效数字，仍请在 Excel 里核对这一行"})
    return hits


def scale_t(sh, key):
    """色阶：每行在最小到最大之间的位置 0–1（空格子为 None）。最小等于最大时都取 0。"""
    j = next(k for k, c in enumerate(sh.columns) if c.key == key)
    vals = [r[j] for r in sh.rows]
    nums = [v for v in vals if isinstance(v, Decimal)]
    if not nums:
        return [None] * len(vals)
    lo, hi = min(nums), max(nums)
    return [None if not isinstance(v, Decimal) else (Decimal(0) if hi == lo else (v - lo) / (hi - lo)) for v in vals]


def _overlay(sh):
    """G1 叠加（C2 退路口径，与 Excel 相同）：一格的每个属性分别决定——
       条件规则（按次序，先命中先得）> 格（$style.cells）> 行（$style.row）> 列默认（columns[].style）。
       规则只管数据行；合计行取 row_styles 的 total > 列默认；表头取 header_style。
    返回 {"cells": {(行, 列): 样式}, "totals": {列: 样式}, "header": 样式 | None}。色阶的底色写成 ("scale", 起色, 止色, t)。"""
    cells = {}
    scales = {}
    if not (sh.rules or any(sh.displays) or any(c.style for c in sh.columns)):
        totals = {j: dict(sh.row_styles["total"]) for j in range(len(sh.columns))} if sh.row_styles.get("total") else {}
        return {"cells": cells, "totals": totals, "header": sh.header_style}
    for r in sh.rules:
        if r["kind"] == "scale":
            scales[id(r)] = scale_t(sh, r["scale"][0])
    for ri in range(len(sh.rows)):
        d = sh.displays[ri] or {}
        for j, c in enumerate(sh.columns):
            st = dict(c.style or {})
            st.update(d.get("row") or {})
            st.update((d.get("cells") or {}).get(c.key) or {})
            ruled = {}
            for r in sh.rules:
                if r["kind"] == "scale":
                    if r["scale"][0] == c.key and scales[id(r)][ri] is not None and "fill" not in ruled:
                        ruled["fill"] = ("scale", r["scale"][1], r["scale"][2], scales[id(r)][ri])
                    continue
                if r["hits"][ri] and (r["apply"] == "row" or c.key in r["apply"]):
                    for k, v in r["style"].items():
                        ruled.setdefault(k, v)
            st.update(ruled)
            if st:
                cells[(ri, j)] = st
    totals = {}
    for j, c in enumerate(sh.columns):
        st = dict(c.style or {})
        st.update(sh.row_styles.get("total") or {})
        if st:
            totals[j] = st
    return {"cells": cells, "totals": totals, "header": sh.header_style}


def static_style(sh, ri, j):
    """静态的三层（列默认 < 行 < 格），Excel 里写成单元格格式；条件规则另写成条件格式压在上面。"""
    c = sh.columns[j]
    d = sh.displays[ri] or {}
    st = dict(c.style or {})
    st.update(d.get("row") or {})
    st.update((d.get("cells") or {}).get(c.key) or {})
    return st


def hex_of(v, theme="light", attr="fill"):
    """样式里的颜色 → #RRGGBB。theme: light（也是 Excel 的色值）或 dark。"""
    if isinstance(v, tuple):
        _, a, b, tt = v
        return _mix(hex_of(a, theme, attr), hex_of(b, theme, attr), float(tt))
    x = PALETTE[v]
    if theme == "light":
        return x[0]
    return x[1] if attr == "fill" else x[2]


def _mix(a, b, tt):
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * tt):02X}" for x, y in zip(ca, cb))


def _cell(col, v, where, lang, stored=False):
    if col.formula is not None:
        return None
    if col.type in NUMERIC:
        return _num_from(v, col.type, where, stored)
    if col.type == "date":
        return _date_from(v, where)
    if col.type == "bool":
        return _bool_from(v, where)
    return _text_from(v, where, lang)


def _env(sh, row):
    """一行 → 公式求值用的环境：数值列给 Decimal，日期给 ISO 串，文字给串，是否给 bool。"""
    return {c.key: row[k] for k, c in enumerate(sh.columns)}


def _kinds(sh):
    return {c.key: c.kind for c in sh.columns}


def col_name(j: int) -> str:
    s = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


def _resolver(sh, j, what="公式"):
    def resolve(name):
        cc = sh.find(name)
        if cc is None:
            raise F.FormulaError(f"{what}里的“{name}”不是这张表的列（用列的 key 或标题）")
        k = sh.columns.index(cc)
        if j is not None:
            if cc.formula is not None and k >= j:
                raise F.FormulaError(f"公式只能引用它左边的公式列（“{cc.title}”在右边）" if k != j else "公式不能引用自己")
            if k == j:
                raise F.FormulaError("公式不能引用自己")
        if cc.numbering is not None:
            raise F.FormulaError(f"“{cc.title}”是编号列，不能参与计算")
        return cc.key
    return resolve


class _Book:
    """跨表汇总的取值（G10）：别的表已经算完（_finish_order 保证次序）。"""

    def __init__(self, t, sh):
        self.t, self.sh, self.n = t, sh, None

    def sheet(self, sid):
        return next(x for x in self.t.sheets if x.id == sid)

    def column(self, ref):
        o = self.sheet(ref[0])
        j = next(k for k, c in enumerate(o.columns) if c.key == ref[1])
        return [r[j] for r in o.rows]

    def matched(self, n):
        self.n = n if self.n is None else min(self.n, n)

    def cell(self, loc):
        raise F.FormulaError("列公式不能引用某一格")


def _qresolver(t, sh):
    def resolve_q(sid, col):
        o = next((x for x in t.sheets if x.id == sid), None)
        if o is None:
            raise F.FormulaError(f"{sid}.{col}：没有 id 为 {sid} 的表（跨表引用写 表id.列）")
        if o is sh:
            raise F.FormulaError(f"{sid}.{col}：本表的列直接写列名")
        c = o.find(col)
        if c is None:
            raise F.FormulaError(f"{sid}.{col}：“{o.name}”里没有“{col}”这一列")
        return (o.id, c.key)
    return resolve_q


def _xkinds(t, sh):
    K = _expr_kinds(t)
    return K({c.key: c.kind for c in sh.columns})


def _formulas(sh, where, t):
    kinds = _xkinds(t, sh)
    cols = {}
    for j, c in enumerate(sh.columns):
        if c.formula is None:
            cols[c.key] = [r[j] for r in sh.rows]
    for j, c in enumerate(sh.columns):
        if c.formula is None:
            continue
        w = f"{where}.columns[{j}].formula"
        try:
            c.node = F.parse(c.formula, _resolver(sh, j), None, _qresolver(t, sh))
            k = F.kind_of(c.node, kinds)
        except F.FormulaError as e:
            raise BadInput(f"公式“{c.formula}”：{e}", w) from None
        if k == "bool":
            raise BadInput(f"公式“{c.formula}”：结果是条件（真或假），要用 if(条件, 甲, 乙) 写成数或文字", w)
        if c.type == "text" and k not in ("text", "empty"):
            raise BadInput(f"公式“{c.formula}”：type 为 text 的公式列，结果只能是双引号里的文字或空", w)
        if c.type != "text" and k == "text":
            raise BadInput(f"公式“{c.formula}”：结果是文字，这一列的 type 要写 text", f"{where}.columns[{j}].type")
        kinds[c.key] = c.kind
        divz = 0
        raw = []
        check_float = F.uses(c.node, F.DISCONTINUOUS + ("cmp",))
        flt = []
        book = _Book(t, sh)
        nomatch = []
        for ri, row in enumerate(sh.rows):
            env = _env(sh, row)
            book.n = None
            try:
                v = F.evaluate(c.node, env, cols, ri, book)
                if book.n == 0:
                    nomatch.append(ri)
            except F.DivZero:
                v = None
                divz += 1
                sh.formula_errors.append({"row": ri, "column": c.key})
            except F.FormulaError as e:
                raise BadInput(f"公式“{c.formula}”：{e}", w) from None
            raw.append(v)
            if c.type == "text":
                row[j] = v
            else:
                if v is not None and c.type == "integer":
                    v = v.quantize(Decimal(1), rounding=ROUND_HALF_UP)
                row[j] = None if v is None else quantize(v, c.decimals if c.type != "percent" or c.decimals is None else c.decimals + 2)
            if check_float:
                fv, hit = F.float_eval(c.node, env, cols, ri, book)
                if hit and _float_differs(c, row[j], fv):
                    flt.append((ri, fv))
        sh.raw[c.key] = raw
        cols[c.key] = [r[j] for r in sh.rows]
        if divz:
            t.warnings.append({"where": w, "code": "div_zero", "column": c.key,
                               "message": f"“{c.title}”有 {divz} 行除以零，这些格子留空"})
        if nomatch:
            names = "、".join(f"第 {ri + 1} 行" for ri in nomatch[:10])
            t.warnings.append({"where": w, "code": "ref_no_match", "column": c.key,
                               "message": f"“{c.title}”的跨表汇总在{names}{'等' if len(nomatch) > 10 else ''}一行也对不上（结果为 0）；"
                                          "请核对两张表的写法是否一致"})
        _float_warnings(t, sh, w, j, c, flt)


def _number_warnings(sh, t, where):
    """17 TL-30 v0.2.99 与 2.2.0 令 §二 补：只提示，不改写、不拒收。
    formula_no_column：公式的结果不依赖任何一列（如 168、数量*0+168）；
    numeric_as_text：列显式写了 type text，而整列的值都能读成数（编号列、identifier、像标识符的值、标题像编号的列除外）。"""
    for j, c in enumerate(sh.columns):
        if c.formula is not None and c.node is not None and not F.live_refs(c.node):
            t.warnings.append({"where": f"{where}.columns[{j}].formula", "code": "formula_no_column", "column": c.key,
                               "message": f"“{c.title}”的公式“{c.formula}”不依赖任何一列，每行都是同一个数；"
                                          "公式不把数据原样带进表：数要写在输入格里（照常标出处），或引用一列"})
        if (c.type == "text" and not c.inferred and c.formula is None and c.numbering is None and not c.identifier
                and not ID_TITLE.search(c.title)):
            vals = [r[j] for r in sh.rows if isinstance(r[j], str)]
            norm = [unicodedata.normalize("NFKC", v).strip().replace(",", "") for v in vals]
            if norm and all(NUM_RE.match(v) for v in norm) and not any(ID_LOOK.match(v) for v in norm):
                t.warnings.append({"where": f"{where}.columns[{j}].type", "code": "numeric_as_text", "column": c.key,
                                   "message": f"“{c.title}”写成了文字列，可它的值都是数；表格里的数默认就是数字，可以计算。"
                                              "这一列若是编号、代码一类的标识符，写 \"identifier\": true"})


def _float_value(c, fv):
    """双精度结果按本列的口径写成 Decimal（与 Excel 公式外包的 ROUND 一致），便于与产出台的值比。"""
    if fv is None or isinstance(fv, (str, bool)):
        return fv
    if fv != fv or fv in (float("inf"), float("-inf")):
        return None
    d = Decimal(repr(fv))
    if c.type == "integer":
        d = d.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return quantize(d, c.decimals if c.type != "percent" or c.decimals is None else c.decimals + 2)


def _float_differs(c, v, fv):
    if c.type == "text":
        return v != fv
    return _float_value(c, fv) != v


def _float_warnings(t, sh, w, j, c, flt):
    """G4 ②：不连续的函数（取整、比较、if）照双精度再算一遍，与产出台不同就告警，点名到格。只告警，不改结果。"""
    for ri, fv in flt[:MAX_FLOAT_WARN]:
        got = _float_value(c, fv)
        shown = "空" if got is None else got if isinstance(got, str) else dec_str(got)
        mine = sh.rows[ri][j]
        mine = "空" if mine is None else mine if isinstance(mine, str) else dec_str(mine)
        t.warnings.append({"where": f"{w}", "code": "excel_float", "column": c.key,
                           "message": f"“{c.title}”第 {ri + 1} 行（{sh.name}!{col_name(j)}{ri + 2}）在 Excel 里重算可能得 {shown}；"
                                      f"产出台按十进制算得 {mine}。双精度浮点在取整或比较的边界上差一个尾数；"
                                      "导出的公式已先归整到 15 位有效数字，仍请在 Excel 里核对这一格"})
    if len(flt) > MAX_FLOAT_WARN:
        t.warnings.append({"where": w, "code": "excel_float", "column": c.key,
                           "message": f"“{c.title}”另有 {len(flt) - MAX_FLOAT_WARN} 格同样可能与 Excel 重算不同，未逐一列出"})


def _totals(spec, sh, where, t=None):
    if spec is None:
        return []
    if not isinstance(spec, list) or len(spec) > MAX_COLS:
        raise BadInput("totals 是合计的数组：[{column, fn}]，fn 为 sum / avg / min / max / count / formula / none；只写列名时按 sum", where)
    items, seen = [], set()
    for i, it in enumerate(spec):
        w = f"{where}[{i}]"
        if isinstance(it, str):
            it = {"column": it, "fn": "sum"}
        _allowed(it, ("column", "fn", "value"), w)
        name = it.get("column")
        c = sh.find(name) if isinstance(name, str) else None
        if c is None:
            raise BadInput(f"合计的列“{name}”不在表里", f"{w}.column")
        fn = it.get("fn", "sum")
        if fn not in FNS:
            raise BadInput("fn 只能是 sum、avg、min、max、count、formula（合计行按本列公式重算）、none（留空）", f"{w}.fn")
        if fn not in ("count", "none") and c.type not in NUMERIC:
            raise BadInput(f"“{c.title}”不是数值列，只能 count", f"{w}.fn")
        if fn == "formula":
            if c.formula is None:
                raise BadInput(f"“{c.title}”不是公式列，不能按公式合计", f"{w}.fn", "fn 为 formula 只用于公式列：合计行把各列的合计代入本列公式")
            if F.uses(c.node, ("agg",)):
                raise BadInput(f"“{c.title}”的公式用了 total 或 cumsum，不能按公式合计", f"{w}.fn")
        if c.key in seen:
            raise BadInput(f"“{c.title}”的合计写了两次", w)
        seen.add(c.key)
        items.append((c, fn, w))
    order = {c.key: k for k, c in enumerate(sh.columns)}
    items.sort(key=lambda x: order[x[0].key])
    vals = {}
    for c, fn, w in items:
        if fn not in ("formula", "none"):
            vals[c.key] = aggregate(sh.eff_values(c.key), fn, c)
            if t is not None:
                _total_warnings(t, sh, c, fn, vals[c.key], w)
    by_fn = {c.key: fn for c, fn, _ in items}
    for c, fn, w in items:
        if fn == "none":
            vals[c.key] = None
        elif fn == "formula":
            env = {k: vals.get(k) if by_fn.get(k) not in (None, "none", "count") else None for k in F.row_refs(c.node)}
            try:
                v = F.evaluate(c.node, env)
            except F.DivZero:
                v = None
            if v is not None and c.type == "integer":
                v = v.quantize(Decimal(1), rounding=ROUND_HALF_UP)
            vals[c.key] = None if v is None else quantize(v, c.decimals if c.type != "percent" or c.decimals is None else c.decimals + 2)
    return [(c.key, fn, vals[c.key]) for c, fn, _ in items]


def _total_warnings(t, sh, c, fn, v, w):
    """G3 ratio_total：比率类公式列配了 sum、avg；G4（精度口径 b）rounded_sum：逐行舍入后相加与先加后舍入不同。只告警，不改结果。"""
    if c.formula is not None and fn in ("sum", "avg") and (c.type == "percent" or F.divides_by_column(c.node)):
        t.warnings.append({"where": w, "code": "ratio_total", "column": c.key,
                           "message": f"“{c.title}”是比率类的公式列，合计用了{'求和' if fn == 'sum' else '平均'}；"
                                      "比率的合计通常要按公式重算（fn 写 formula，例如 实际合计 ÷ 预算合计）"})
    raw = sh.raw.get(c.key) if not sh.merged else None
    if fn == "sum" and raw is not None and v is not None and (c.decimals is not None or c.type == "integer"):
        exact = aggregate(raw, "sum", c)
        d = c.decimals if c.type != "percent" or c.decimals is None else c.decimals + 2
        exact = quantize(exact, 0 if c.type == "integer" else d)
        if exact != v:
            col = next(x for x in sh.columns if x.key == c.key)
            from render import display
            t.warnings.append({"where": w, "code": "rounded_sum", "column": c.key,
                               "message": f"“{c.title}”各行先按显示位数舍入再相加，合计为 {display(col, v)}；"
                                          f"各行不舍入、相加后再舍入为 {display(col, exact)}。产出台与 Excel 都按逐行舍入（精度口径 b），两边一致"})


def aggregate(vals, fn, col):
    if fn == "count":
        return Decimal(sum(1 for v in vals if v is not None))
    nums = [v for v in vals if isinstance(v, Decimal)]
    if not nums:
        return None
    with localcontext() as ctx:
        ctx.prec = 34
        if fn == "sum":
            r = sum(nums, Decimal(0))
        elif fn == "avg":
            r = sum(nums, Decimal(0)) / len(nums)
        elif fn == "min":
            r = min(nums)
        else:
            r = max(nums)
    d = aggregate_decimals(nums, fn, col)
    if d == "exact":
        return r
    return quantize(r, d)


def aggregate_decimals(nums, fn, col):
    """合计舍入到几位小数（None 为 10 位归整，"exact" 为不舍入）。Excel 的合计公式外包同样位数的 ROUND（精度口径 b）。"""
    if fn == "avg" and col.decimals is None and col.shown_decimals is None:
        # 平均值没给小数位时：比数据本身多不出位，至少 2 位（百分比按小数算，至少 4 位即 2 位百分点），最多 6 位
        data = max((max(0, -v.as_tuple().exponent) for v in nums if v.is_finite()), default=0)
        return min(6, max(data, 4 if col.type == "percent" else 2))
    if col.type == "percent":
        return None if col.decimals is None else col.decimals + 2
    if col.type == "integer" and fn != "avg":
        return "exact"
    return col.shown_decimals if fn == "avg" or col.decimals is not None else None
