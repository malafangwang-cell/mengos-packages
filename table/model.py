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
ROW_KINDS = ("total",)        # row_styles 只按行种类写；小计、组头随 2.2.0 的 G7 一起加
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


def _num_from(v, ctype, where):
    """单元格 → Decimal | None。"""
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
    if ctype == "percent":
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
                 "style", "date_format", "thousands")

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
                 "header_style", "rules", "row_styles", "displays", "raw", "_styles")

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
        o["rows"] = [[_cell_json(c, v) for c, v in zip(self.columns, r)] if not d else
                     {**{c.key: _cell_json(c, v) for c, v in zip(self.columns, r)}, DISPLAY_KEY: _display_json(d)}
                     for r, d in zip(self.rows, self.displays)]
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
        return o

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
    __slots__ = ("title", "subtitle", "meta", "sheets", "sources", "assumptions", "warnings", "_json", "_sha")

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
TABLE_KEYS = ("schema", "title", "subtitle", "meta", "sheets", "sources", "assumptions",
              "columns", "rows", "totals", "caption", "note", "freeze_cols", "name", "lang") + SHEET_STYLE_KEYS
SHEET_KEYS = ("id", "name", "caption", "note", "columns", "rows", "totals", "freeze_cols") + SHEET_STYLE_KEYS
COL_KEYS = ("key", "title", "type", "unit", "decimals", "formula", "width", "align", "style", "date_format", "thousands")


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
    single = [k for k in ("columns", "rows", "totals", "caption", "note", "freeze_cols", "name") + SHEET_STYLE_KEYS if k in raw]
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
        sheets = [{k: raw[k] for k in ("columns", "rows", "totals", "caption", "note", "freeze_cols") + SHEET_STYLE_KEYS if k in raw}]
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
        t.sheets.append(sh)
    ids = [s.id for s in t.sheets if s.id]
    if len(ids) != len(set(ids)):
        raise BadInput("各张表的 id 不能重复", "table.sheets")
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
    # 没写 type 的列按内容推断（公式列恒为数值）
    for j, c in enumerate(sh.columns):
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
        c.align = c.align or ("right" if c.type in NUMERIC else "center" if c.type == "bool" else "left")
    sh.rows = [[_cell(sh.columns[j], v, f"{where}.rows[{ri}][{j}]", t.lang) for j, v in enumerate(r)]
               for ri, r in enumerate(raw_rows)]
    _formulas(sh, where, t)
    sh.totals = _totals(s.get("totals"), sh, f"{where}.totals", t)
    sh.freeze_cols = fc
    sh.header_style = _style(s.get("header_style"), f"{where}.header_style")
    sh.row_styles = _row_styles(s.get("row_styles"), f"{where}.row_styles")
    sh.rules = _rules(s.get("rules"), sh, f"{where}.rules", t)
    if build and not sh.rows:
        t.warnings.append({"where": f"{where}.rows", "code": "no_rows",
                           "message": f"“{sh.name}”还没有行，只交出表头" + ("，合计留空" if sh.totals else "")})
    return sh


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
    return col


def _row(r, where, sh, plain, t, from_model, ri):
    n = len(sh.columns)
    if isinstance(r, dict) and DISPLAY_KEY in r:
        sh.displays.append(_display(r[DISPLAY_KEY], sh, f"{where}.{DISPLAY_KEY}"))
        r = {k: v for k, v in r.items() if k != DISPLAY_KEY}
    else:
        sh.displays.append(None)
    if isinstance(r, dict):
        out = [None] * n
        for k, v in r.items():
            c = sh.find(k) if isinstance(k, str) else None
            if c is None:
                raise BadInput(f"这一行有表里没有的列：{k}", where, "对象写法的键要与列的 key 或标题相同")
            j = sh.columns.index(c)
            if c.formula is not None:
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
            if c.formula is not None:
                if out[j] is not None and not from_model:
                    _formula_given(t, where, c)
                out[j] = None
        return out
    if len(r) == len(plain) and len(plain) < n:
        out = [None] * n
        for j, v in zip(plain, r):
            out[j] = v
        return out
    want = f"列数 {n}" if len(plain) == n else f"列数 {n}，或等于非公式列数 {len(plain)}"
    raise BadInput(f"第 {ri + 1} 行有 {len(r)} 格，表有 {n} 列：数组行的格数须等于{want}（实际 {len(r)}）", where,
                   "空格子写 null；分批追加行请用对象行（列的 key 或标题 → 值）；改了列要把已有的数组行按新列重写")


def _formula_given(t, where, c):
    code = "formula_value_ignored"
    if not any(w["code"] == code and w.get("column") == c.key for w in t.warnings):
        t.warnings.append({"where": where, "code": code, "column": c.key,
                           "message": f"“{c.title}”是公式列，行里给的值不用，按公式算"})


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


def _cell(col, v, where, lang):
    if col.formula is not None:
        return None
    if col.type in NUMERIC:
        return _num_from(v, col.type, where)
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
        return cc.key
    return resolve


def _formulas(sh, where, t):
    kinds = _kinds(sh)
    cols = {}
    for j, c in enumerate(sh.columns):
        if c.formula is None:
            cols[c.key] = [r[j] for r in sh.rows]
    for j, c in enumerate(sh.columns):
        if c.formula is None:
            continue
        w = f"{where}.columns[{j}].formula"
        try:
            c.node = F.parse(c.formula, _resolver(sh, j))
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
        for ri, row in enumerate(sh.rows):
            env = _env(sh, row)
            try:
                v = F.evaluate(c.node, env, cols, ri)
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
                fv, hit = F.float_eval(c.node, env, cols, ri)
                if hit and _float_differs(c, row[j], fv):
                    flt.append((ri, fv))
        sh.raw[c.key] = raw
        cols[c.key] = [r[j] for r in sh.rows]
        if divz:
            t.warnings.append({"where": w, "code": "div_zero", "column": c.key,
                               "message": f"“{c.title}”有 {divz} 行除以零，这些格子留空"})
        _float_warnings(t, sh, w, j, c, flt)


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
            vals[c.key] = aggregate(sh.values(c.key), fn, c)
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
    raw = sh.raw.get(c.key)
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
