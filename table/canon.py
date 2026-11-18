"""规范化入参与按行 id 的补丁（2.3.0 B1；mengosv2 局部追问设计 r9.2 §4.1、§4.4；L13）。

table.build 的产出里给出“规范化入参”，局部修改的下一步以它为底稿：
  · 恒为 sheets 写法，每张表有 id：单表写法换成一张表，表 id 由包补 `_sa`（不含数字；与 `_r` 一样由包保留）；
  · 行一律是对象行（列的 key → 格），数组行按列序换过来；公式列、编号列的格不写（工具算）；
  · 缺 id 的行按入参行序补 `_r` 加字母序号（_ra、_rb … _rz、_raa …），跳过已用的 id；
  · `row_patch` 已施加进 rows、补丁清空——补丁不跨步累积（§4.4 ①）。

`row_patch`（表级，可选）：
  · 每项带 `$id`；同一 id 写几次就依次施加，后写的覆盖；
  · 已有的行：写到的格替换，`{"$clear": true}` 清空一格（§4.4 ②；null 在引擎合并里是删键，到这里就不该出现）；`$style` 按键合并；
  · `{"$id": …, "$delete": true}` 删行；被别的格 `@行id.列` 引用的行不能删，点名引用它的格（§4.4 ⑤）；
  · 新行写 `$after`（插在哪一行后面；同一 `$after` 的几行按出现的次序排，§4.4 ③）；已有的行写 `$after` 等于移行（§4.4 ④，由调用方的不变量去判）；
  · `$after` 指向已删的行、不存在的行或成环 ⟹ BAD_INPUT 并点名；id 不存在又没写 `$after` ⟹ BAD_INPUT“找不到这一行”（§4.4 ⑤）；
  · 新行的 id 不能用 `_r` 开头（包保留）；派生表没有自己的行，不能写 row_patch。
"""
from __future__ import annotations

import copy
import re

from model import (BadInput, DISPLAY_KEY, EXPR_KEY, ID_KEY, KEY_RE, SINGLE_SHEET_ID, STRUCT_KEYS, SHEET_STYLE_KEYS,
                   _column, _norm, check_row_id, check_sheet_id, issue_ids)

PATCH_KEY = "row_patch"
DELETE_KEY = "$delete"
AFTER_KEY = "$after"
CLEAR_KEY = "$clear"
REF = re.compile(r"@(?:(\w+)/)?(\w+)\.\w+")  # 格公式里引用别的行（与 formula.TOKEN 的 ref 同读法）
SINGLE_KEYS = ("columns", "rows", "totals", "caption", "note", "freeze_cols") + SHEET_STYLE_KEYS + STRUCT_KEYS + (PATCH_KEY,)


def has_patch(raw) -> bool:
    if not isinstance(raw, dict):
        return False
    if PATCH_KEY in raw:
        return True
    return isinstance(raw.get("sheets"), list) and any(isinstance(s, dict) and PATCH_KEY in s for s in raw["sheets"])


class _Cols:
    def __init__(self, cols, where):
        self.cols = [_column(c, f"{where}.columns[{j}]", j) for j, c in enumerate(cols)]

    def find(self, name):
        """与 model.Sheet.find 同读法：key，再标题，再“标题(单位)”。"""
        if not isinstance(name, str):
            return None
        n = _norm(name)
        for c in self.cols:
            if c.key == name:
                return c
        for c in self.cols:
            if _norm(c.title) == n:
                return c
        for c in self.cols:
            if c.unit and _norm(f"{c.title}({c.unit})") == n:
                return c
        return None


def _object_row(r, cols: _Cols, where):
    """一行 → 对象行（列的 key → 格）。公式列、编号列的格不写。格数对不上的数组行原样返回，由 model 报错。"""
    computed = lambda c: c.formula is not None or c.numbering is not None
    if isinstance(r, dict):
        out = {}
        for k, v in r.items():
            if k in (ID_KEY, DISPLAY_KEY):
                out[k] = v
                continue
            c = cols.find(k)
            if c is None:
                return r                     # 表里没有的列：原样，由 model 报错
            if computed(c):
                continue
            if v is not None:
                out[c.key] = v
        return out
    if not isinstance(r, list):
        return r
    n = len(cols.cols)
    plain = [j for j, c in enumerate(cols.cols) if c.formula is None]
    inputs = [j for j in plain if cols.cols[j].numbering is None]
    if len(r) == n:
        idx = list(range(n))
    elif len(r) == len(plain) and len(plain) < n:
        idx = plain
    elif len(inputs) < len(plain) and len(r) == len(inputs):
        idx = inputs
    else:
        return r
    out = {}
    for j, v in zip(idx, r):
        c = cols.cols[j]
        if computed(c) or v is None:
            continue
        out[c.key] = v
    return out


def canonical(raw: dict) -> dict:
    """规范化入参（不改 raw）。raw 的结构不合规时尽量原样留着，由 model.normalize 报出原来的错误。"""
    raw = copy.deepcopy(raw)
    if "sheets" in raw:
        top = {k: v for k, v in raw.items() if k != "sheets"}
        sheets = raw["sheets"] if isinstance(raw["sheets"], list) else []
        where = [f"table.sheets[{i}]" for i in range(len(sheets))]
    else:
        top = {k: v for k, v in raw.items() if k not in SINGLE_KEYS and k != "name"}
        s = {k: raw[k] for k in SINGLE_KEYS if k in raw}
        s = {"id": SINGLE_SHEET_ID, "name": raw.get("name") if raw.get("name") is not None else raw.get("title"), **s}
        sheets, where = [s], ["table"]
    out_sheets = []
    for s, w in zip(sheets, where):
        if not isinstance(s, dict) or not isinstance(s.get("columns"), list):
            out_sheets.append(s)
            continue
        s = dict(s)
        check_sheet_id(s.get("id"), f"{w}.id")
        patch = s.pop(PATCH_KEY, None)
        if s.get("derive") is not None:
            if patch is not None:
                raise BadInput("派生表的行由工具从各分部生成，不能写 row_patch；要改，改分部里的那一行", f"{w}.{PATCH_KEY}")
            out_sheets.append(s)
            continue
        try:
            cols = _Cols(s["columns"], w)
        except BadInput:
            out_sheets.append(s)            # 列定义不合规：由 model 报
            continue
        rows = s.get("rows", [])
        if not isinstance(rows, list):
            out_sheets.append(s)
            continue
        rows = [_object_row(r, cols, f"{w}.rows[{ri}]") for ri, r in enumerate(rows)]
        if any(not isinstance(r, dict) for r in rows):
            s["rows"] = rows                 # 有格数对不上的数组行：交 model 报错
            out_sheets.append(s)
            continue
        for ri, r in enumerate(rows):
            check_row_id(r.get(ID_KEY), f"{w}.rows[{ri}].{ID_KEY}")
        ids = issue_ids([r.get(ID_KEY) if isinstance(r.get(ID_KEY), str) else None for r in rows])
        rows = [{ID_KEY: rid, **{k: v for k, v in r.items() if k != ID_KEY}} for r, rid in zip(rows, ids)]
        if patch is not None:
            rows = apply_patch(rows, patch, cols, f"{w}.{PATCH_KEY}")
        s["rows"] = rows
        out_sheets.append(s)
    out = dict(top)
    out["sheets"] = out_sheets
    _check_deleted_refs(raw, out)
    return out


# ---------------------------------------------------------------- row_patch（§4.4）
def apply_patch(rows, patch, cols: _Cols, where):
    if not isinstance(patch, list):
        raise BadInput("row_patch 是补丁的数组：每项 {\"$id\": 行 id, 列: 新值…}", where)
    rows = [dict(r) for r in rows]
    by_id = {r[ID_KEY]: r for r in rows}
    deleted, moves, new_ids = set(), [], []
    for i, p in enumerate(patch):
        w = f"{where}[{i}]"
        if not isinstance(p, dict):
            raise BadInput("每项补丁是对象：{\"$id\": 行 id, 列: 新值…}", w)
        rid = p.get(ID_KEY)
        if not isinstance(rid, str) or not KEY_RE.match(rid):
            raise BadInput(f"每项补丁要写 {ID_KEY}（行 id：字母、数字、下划线，字母或下划线开头）", f"{w}.{ID_KEY}")
        if p.get(DELETE_KEY) is not None:
            if p.get(DELETE_KEY) is not True or set(p) - {ID_KEY, DELETE_KEY}:
                raise BadInput(f"删行写 {{\"{ID_KEY}\": \"{rid}\", \"{DELETE_KEY}\": true}}，不再写别的", w)
            if rid not in by_id or rid in deleted:
                raise BadInput(f"找不到这一行：{rid}", w, "删行写的是已有的行 id")
            deleted.add(rid)
            continue
        if rid in deleted:
            raise BadInput(f"找不到这一行：{rid}（同一份补丁里已经删了）", w)
        if rid not in by_id:
            if AFTER_KEY not in p:
                raise BadInput(f"找不到这一行：{rid}", w, f"改已有的行写它的 {ID_KEY}；新插一行写 {AFTER_KEY}（插在哪一行后面）")
            if rid.startswith("_r"):
                raise BadInput(f"新行的 id {rid}：以 _r 开头的行 id 由表格工具保留，请换一个", f"{w}.{ID_KEY}")
            by_id[rid] = {ID_KEY: rid}
            new_ids.append(rid)
        row = by_id[rid]
        for k, v in p.items():
            if k in (ID_KEY, AFTER_KEY):
                continue
            if k == DISPLAY_KEY:
                if not isinstance(v, dict):
                    raise BadInput(f"{DISPLAY_KEY} 是对象：{{row, cells}}", f"{w}.{k}")
                row[k] = _merge_obj(row.get(k), v)
                continue
            c = cols.find(k)
            if c is None:
                raise BadInput(f"这一行有表里没有的列：{k}", w, "补丁的键要与列的 key 或标题相同")
            if c.formula is not None or c.numbering is not None:
                raise BadInput(f"“{c.title}”是{'公式列' if c.formula else '编号列'}，由工具算，补丁里不写；要改，改这一列的定义", f"{w}.{k}")
            if v is None:
                raise BadInput(f"清空一格写 {{\"{CLEAR_KEY}\": true}}", f"{w}.{k}")
            if isinstance(v, dict) and CLEAR_KEY in v:
                if v != {CLEAR_KEY: True}:
                    raise BadInput(f"清空一格写 {{\"{CLEAR_KEY}\": true}}，不再写别的", f"{w}.{k}")
                row.pop(c.key, None)
                continue
            row[c.key] = v
        if AFTER_KEY in p:
            a = p[AFTER_KEY]
            if not isinstance(a, str):
                raise BadInput(f"{AFTER_KEY} 写行 id：插在哪一行后面", f"{w}.{AFTER_KEY}")
            moves = [m for m in moves if m[0] != rid] + [(rid, a, w)]
    # 施加：删行，再把要挪、要插的行按补丁里出现的次序放到位
    moving = {m[0] for m in moves}
    order = [r[ID_KEY] for r in rows if r[ID_KEY] not in deleted and r[ID_KEY] not in moving]
    last_of = {}
    pending = list(moves)
    while pending:
        rest = []
        for rid, a, w in pending:
            if a in order and a != rid:
                at = order.index(last_of.get(a, a))
                order.insert(at + 1, rid)
                last_of[a] = rid
            else:
                rest.append((rid, a, w))
        if len(rest) == len(pending):
            rid, a, w = rest[0]
            if a in deleted:
                raise BadInput(f"{AFTER_KEY} {a}：这一行在同一份补丁里删了", f"{w}.{AFTER_KEY}")
            if a not in by_id:
                raise BadInput(f"{AFTER_KEY} {a}：找不到这一行", f"{w}.{AFTER_KEY}")
            raise BadInput(f"{AFTER_KEY} 成环：{'、'.join(x[0] for x in rest)} 互相插在对方后面", f"{w}.{AFTER_KEY}")
        pending = rest
    return [by_id[rid] for rid in order]


def _merge_obj(a, b):
    if not isinstance(a, dict):
        return copy.deepcopy(b)
    out = dict(a)
    for k, v in b.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_obj(out[k], v)
        else:
            out[k] = v
    return out


def _check_deleted_refs(raw, out):
    """被 `@行id.列` 引用的行被删 ⟹ BAD_INPUT，列出引用它的格（§4.4 ⑤）。"""
    sheets = raw.get("sheets") if "sheets" in raw else [{**{k: raw[k] for k in SINGLE_KEYS if k in raw}, "id": SINGLE_SHEET_ID}]
    if not isinstance(sheets, list):
        return
    gone = set()
    for s in sheets:
        if not isinstance(s, dict) or not isinstance(s.get(PATCH_KEY), list):
            continue
        sid = s.get("id", SINGLE_SHEET_ID)
        gone |= {(sid, p[ID_KEY]) for p in s[PATCH_KEY] if isinstance(p, dict) and p.get(DELETE_KEY) is True and isinstance(p.get(ID_KEY), str)}
    if not gone:
        return
    hits = []
    for s in out["sheets"]:
        if not isinstance(s, dict) or not isinstance(s.get("rows"), list):
            continue
        sid = s.get("id")
        for r in s["rows"]:
            if not isinstance(r, dict):
                continue
            for k, v in r.items():
                if isinstance(v, dict) and isinstance(v.get(EXPR_KEY), str):
                    for m in REF.finditer(v[EXPR_KEY]):
                        target = (m.group(1) or sid, m.group(2))
                        if target in gone:
                            hits.append((target[1], f"{sid}/{r.get(ID_KEY)}.{k}"))
    if hits:
        rid = hits[0][0]
        cells = "、".join(h[1] for h in hits if h[0] == rid)
        raise BadInput(f"行 {rid} 被别的格引用，不能删：{cells}", "row_patch", "先改掉引用它的格，或者不删这一行")

