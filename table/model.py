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
FNS = ("sum", "avg", "min", "max", "count")
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
    __slots__ = ("key", "title", "type", "unit", "decimals", "formula", "node", "align", "width", "inferred")

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
        return o

    @property
    def shown_decimals(self):
        return self.decimals if self.decimals is not None else DEFAULT_DECIMALS.get(self.type)


class Sheet:
    __slots__ = ("id", "name", "caption", "note", "columns", "rows", "totals", "freeze_cols", "formula_errors")

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
        o["rows"] = [[_cell_json(c, v) for c, v in zip(self.columns, r)] for r in self.rows]
        if self.totals:
            o["totals"] = [{"column": k, "fn": fn, "value": None if v is None else dec_str(v)} for k, fn, v in self.totals]
        if self.freeze_cols:
            o["freeze_cols"] = self.freeze_cols
        if self.note:
            o["note"] = self.note
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
TABLE_KEYS = ("schema", "title", "subtitle", "meta", "sheets", "sources", "assumptions",
              "columns", "rows", "totals", "caption", "note", "freeze_cols", "name", "lang")
SHEET_KEYS = ("id", "name", "caption", "note", "columns", "rows", "totals", "freeze_cols")
COL_KEYS = ("key", "title", "type", "unit", "decimals", "formula", "width", "align")


def normalize(raw) -> Table:
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
    single = [k for k in ("columns", "rows", "totals", "caption", "note", "freeze_cols", "name") if k in raw]
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
        sheets = [{k: raw[k] for k in ("columns", "rows", "totals", "caption", "note", "freeze_cols") if k in raw}]
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
        sh = _sheet(s, w, i, t, used, from_model)
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


def _sheet(s, where, i, t, used, from_model) -> Sheet:
    _allowed(s, SHEET_KEYS, where)
    sh = Sheet()
    sh.formula_errors = []
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
    plain = [j for j, c in enumerate(sh.columns) if c.formula is None]
    raw_rows = [_row(r, f"{where}.rows[{ri}]", sh, plain, t, from_model) for ri, r in enumerate(rows)]
    # 没写 type 的列按内容推断（公式列恒为数值）
    for j, c in enumerate(sh.columns):
        if c.type is None:
            c.type = "number" if c.formula is not None else infer_type([r[j] for r in raw_rows])
            c.inferred = True
        if c.formula is not None and c.type not in NUMERIC:
            raise BadInput("公式列的 type 只能是数值类：integer、number、money、percent", f"{where}.columns[{j}].type")
        if c.decimals is not None and c.type not in NUMERIC:
            raise BadInput("decimals 只用于数值列", f"{where}.columns[{j}].decimals")
        c.align = c.align or ("right" if c.type in NUMERIC else "center" if c.type == "bool" else "left")
    sh.rows = [[_cell(sh.columns[j], v, f"{where}.rows[{ri}][{j}]", t.lang) for j, v in enumerate(r)]
               for ri, r in enumerate(raw_rows)]
    _formulas(sh, where, t)
    sh.totals = _totals(s.get("totals"), sh, f"{where}.totals")
    sh.freeze_cols = fc
    return sh


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
    return col


def _row(r, where, sh, plain, t, from_model):
    n = len(sh.columns)
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
    want = f"{n} 格" if len(plain) == n else f"{n} 格（或不含公式列的 {len(plain)} 格）"
    raise BadInput(f"这一行有 {len(r)} 格，表有 {want}", where, "每行的格数与列数相同；空格子写 null")


def _formula_given(t, where, c):
    code = "formula_value_ignored"
    if not any(w["code"] == code and w.get("column") == c.key for w in t.warnings):
        t.warnings.append({"where": where, "code": code, "column": c.key,
                           "message": f"“{c.title}”是公式列，行里给的值不用，按公式算"})


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


def _formulas(sh, where, t):
    done = set()
    for j, c in enumerate(sh.columns):
        if c.formula is None:
            continue
        w = f"{where}.columns[{j}].formula"

        def resolve(name, _j=j):
            cc = sh.find(name)
            if cc is None:
                raise F.FormulaError(f"公式里的“{name}”不是这张表的列（用列的 key 或标题）")
            if cc.type not in NUMERIC:
                raise F.FormulaError(f"“{cc.title}”不是数值列，不能参与计算")
            k = sh.columns.index(cc)
            if cc.formula is not None and k >= _j:
                raise F.FormulaError(f"公式只能引用它左边的公式列（“{cc.title}”在右边）")
            if k == _j:
                raise F.FormulaError("公式不能引用自己")
            return cc.key
        try:
            c.node = F.parse(c.formula, resolve)
        except F.FormulaError as e:
            raise BadInput(f"公式“{c.formula}”：{e}", w) from None
        divz = 0
        for ri, row in enumerate(sh.rows):
            env = {cc.key: row[k] for k, cc in enumerate(sh.columns) if cc.type in NUMERIC}
            try:
                v = F.evaluate(c.node, env)
            except F.DivZero:
                v = None
                divz += 1
                sh.formula_errors.append({"row": ri, "column": c.key})
            except F.FormulaError as e:
                raise BadInput(f"公式“{c.formula}”：{e}", w) from None
            if v is not None and c.type == "integer":
                v = v.quantize(Decimal(1), rounding=ROUND_HALF_UP)
            row[j] = None if v is None else quantize(v, c.decimals if c.type != "percent" or c.decimals is None else c.decimals + 2)
        if divz:
            t.warnings.append({"where": w, "code": "div_zero", "column": c.key,
                               "message": f"“{c.title}”有 {divz} 行除以零，这些格子留空"})


def _totals(spec, sh, where):
    if spec is None:
        return []
    if not isinstance(spec, list) or len(spec) > MAX_COLS:
        raise BadInput("totals 是合计的数组：[{column, fn}]，fn 为 sum / avg / min / max / count；只写列名时按 sum", where)
    out, seen = [], set()
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
            raise BadInput("fn 只能是 sum、avg、min、max、count", f"{w}.fn")
        if fn != "count" and c.type not in NUMERIC:
            raise BadInput(f"“{c.title}”不是数值列，只能 count", f"{w}.fn")
        if c.key in seen:
            raise BadInput(f"“{c.title}”的合计写了两次", w)
        seen.add(c.key)
        out.append((c.key, fn, aggregate(sh.values(c.key), fn, c)))
    order = {c.key: k for k, c in enumerate(sh.columns)}
    return sorted(out, key=lambda x: order[x[0]])


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
    if fn == "avg" and col.decimals is None and col.shown_decimals is None:
        # 平均值没给小数位时：比数据本身多不出位，至少 2 位（百分比按小数算，至少 4 位即 2 位百分点），最多 6 位
        data = max((max(0, -v.as_tuple().exponent) for v in nums if v.is_finite()), default=0)
        return quantize(r, min(6, max(data, 4 if col.type == "percent" else 2)))
    if col.type == "percent":
        return quantize(r, None if col.decimals is None else col.decimals + 2)
    if col.type == "integer" and fn != "avg":
        return r
    return quantize(r, col.shown_decimals if fn == "avg" or col.decimals is not None else None)
