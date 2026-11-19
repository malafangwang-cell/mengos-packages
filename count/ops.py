"""条件、分组、列求和、数值列间隔（一维、二维分布）。只认列名与取值，不认任何行业词。

数一律按十进制精确解析（Decimal），回执里整数写整数、非整数写最短十进制；同一入参逐字节相同。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from readers import BadInput, Table

OPS = ("eq", "ne", "in", "contains", "regex", "lt", "le", "gt", "ge", "between")
NUM_OPS = {"lt", "le", "gt", "ge", "between"}
NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
MAX_REGEX = 200


def parse_num(s) -> Decimal | None:
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return Decimal(str(s))
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not NUM_RE.match(t):
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def num_out(d: Decimal):
    """回执里的数：整数写 int，其余写 float（取最短十进制表示）。"""
    d = d.normalize() if d != 0 else Decimal(0)
    if d == d.to_integral_value():
        return int(d)
    return float(format(d, "f"))


def num_text(d: Decimal) -> str:
    if d == d.to_integral_value():
        return str(int(d))
    return format(d.normalize(), "f")


class Cond:
    def __init__(self, spec, columns):
        if not isinstance(spec, dict):
            raise BadInput("条件须为对象 {col, op, value}")
        self.col = spec.get("col")
        self.op = spec.get("op")
        self.key = spec.get("key")
        self.value = spec.get("value")
        if self.col not in columns:
            raise BadInput(f"条件里的列“{self.col}”不在表头里；表头：{'|'.join(columns)}")
        self.idx = columns.index(self.col)
        if self.op not in OPS:
            raise BadInput(f"op 须为 {', '.join(OPS)} 之一")
        if self.key is not None and not (isinstance(self.key, str) and self.key):
            raise BadInput("key 须为非空字符串")
        v = self.value
        if self.op == "in":
            if not isinstance(v, list) or not v or not all(isinstance(x, (str, int, float)) and not isinstance(x, bool) for x in v):
                raise BadInput("in 的 value 须为非空的字符串或数数组")
        elif self.op == "between":
            if not isinstance(v, list) or len(v) != 2 or any(parse_num(x) is None for x in v):
                raise BadInput("between 的 value 须为两个数 [下限, 上限]")
            self.lo, self.hi = parse_num(v[0]), parse_num(v[1])
            if self.lo > self.hi:
                raise BadInput("between 的下限大于上限")
        elif self.op in NUM_OPS:
            if parse_num(v) is None:
                raise BadInput(f"{self.op} 的 value 须为数")
            self.num = parse_num(v)
        elif self.op == "regex":
            if not isinstance(v, str) or not v or len(v) > MAX_REGEX:
                raise BadInput(f"regex 的 value 须为 1 至 {MAX_REGEX} 字的正则")
            try:
                self.rx = re.compile(v)
            except re.error as e:
                raise BadInput(f"正则写法有误：{e}") from None
        elif self.op == "contains":
            if not isinstance(v, str) or not v:
                raise BadInput("contains 的 value 须为非空字符串")
        else:  # eq / ne
            if not isinstance(v, (str, int, float)) or isinstance(v, bool):
                raise BadInput(f"{self.op} 的 value 须为字符串或数")

    def echo(self):
        d = {"col": self.col, "op": self.op, "value": self.value}
        if self.key is not None:
            d["key"] = self.key
        return d

    def cell(self, cells):
        raw = cells[self.idx]
        if self.key is None:
            return raw
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k == self.key:
                    return v
        return None

    @staticmethod
    def _eq(cell: str, v) -> bool:
        if isinstance(v, str):
            return cell == v
        a = parse_num(cell)
        return a is not None and a == parse_num(v)

    def test(self, cells):
        """返回 True / False，或 None 表示数值比较时该格解析不了（计入 rows_unparsed）。"""
        c = self.cell(cells)
        if c is None:
            return self.op == "ne"
        op = self.op
        if op == "eq":
            return self._eq(c, self.value)
        if op == "ne":
            return not self._eq(c, self.value)
        if op == "in":
            return any(self._eq(c, x) for x in self.value)
        if op == "contains":
            return self.value in c
        if op == "regex":
            return self.rx.search(c) is not None
        n = parse_num(c)
        if n is None:
            return None
        if op == "between":
            return self.lo <= n <= self.hi
        return {"lt": n < self.num, "le": n <= self.num, "gt": n > self.num, "ge": n >= self.num}[op]


class Filter:
    """where 各条为“且”；any_of 为若干组，组内“且”、组间“或”（G-2）。两者同时给出时取交。"""

    def __init__(self, where, any_of, columns):
        where = where or []
        any_of = any_of or []
        if not isinstance(where, list) or not isinstance(any_of, list):
            raise BadInput("where 与 any_of 须为数组")
        self.where = [Cond(c, columns) for c in where]
        self.any_of = []
        for g in any_of:
            if not isinstance(g, list) or not g:
                raise BadInput("any_of 的每一组须为非空条件数组")
            self.any_of.append([Cond(c, columns) for c in g])

    def echo(self):
        return {"where": [c.echo() for c in self.where], "any_of": [[c.echo() for c in g] for g in self.any_of]}

    def scan(self, rows):
        """逐行判断（不建行表）：命中 ⟹ (True, rid, cells)；数值比较解析不了 ⟹ (False, rid, {id, col, value})；不中不出。"""
        for rid, cells in rows:
            bad = None
            ok = True
            for c in self.where:
                r = c.test(cells)
                if r is None:
                    bad = c; ok = False; break
                if not r:
                    ok = False; break
            if ok and self.any_of:
                hit = False
                for g in self.any_of:
                    gok = True
                    for c in g:
                        r = c.test(cells)
                        if r is None:
                            bad = bad or c; gok = False; break
                        if not r:
                            gok = False; break
                    if gok:
                        hit = True; break
                ok = hit
                if hit:
                    bad = None
            if ok:
                yield True, rid, cells
            elif bad is not None:
                yield False, rid, {"id": rid, "col": bad.col, "value": bad.cell(cells)}

    def apply(self, table: Table):
        matched, unparsed = [], []
        for hit, rid, x in self.scan(table.rows):
            if hit:
                matched.append((rid, x))
            else:
                unparsed.append(x)
        return matched, unparsed


def col_index(columns, name, what):
    if not isinstance(name, str) or name not in columns:
        raise BadInput(f"{what} 的列“{name}”不在表头里；表头：{'|'.join(columns)}")
    return columns.index(name)


# ───────── 列求和（G-1）─────────

AGG_FNS = ("sum", "min", "max")


def parse_aggregate(spec, columns):
    if spec is None:
        return []
    if not isinstance(spec, list) or len(spec) > 10:
        raise BadInput("aggregate 须为至多 10 项的数组")
    out = []
    for a in spec:
        if not isinstance(a, dict) or a.get("fn") not in AGG_FNS:
            raise BadInput("aggregate 每项须为 {col, fn}，fn ∈ sum、min、max")
        out.append((a["col"], col_index(columns, a.get("col"), "aggregate"), a["fn"]))
    return out


class Agg:
    """一项列求和的累计（逐行加，不留行）：与先收齐再求和同一次序、同一结果。"""

    def __init__(self, col, i, fn):
        self.col, self.i, self.fn = col, i, fn
        self.v = None
        self.used = 0
        self.bad = 0
        self.bad_ids = []

    def add(self, rid, n):
        """n：该行这一列解析出的数（parse_num 的结果，None 表示解析不了）；同一行的数由调用方解析一次，分组与总计共用。"""
        if n is None:
            self.bad += 1
            if len(self.bad_ids) < 50:
                self.bad_ids.append(rid)
            return
        self.used += 1
        if self.v is None:
            self.v = Decimal(0) + n if self.fn == "sum" else n
        elif self.fn == "sum":
            self.v += n
        elif (n < self.v) if self.fn == "min" else (n > self.v):
            self.v = n

    def result(self):
        value = text = None
        if self.used:
            value, text = num_out(self.v), num_text(self.v)
        return {"col": self.col, "fn": self.fn, "value": value, "value_text": text, "rows_used": self.used,
                "rows_unparsed": self.bad, "unparsed_ids": self.bad_ids}


def aggregate(rows, aggs):
    acc = [Agg(col, i, fn) for col, i, fn in aggs]
    for rid, cells in rows:
        for a in acc:
            a.add(rid, parse_num(cells[a.i]))
    return [a.result() for a in acc]


# ───────── 数值列间隔：聚类、步长、等距、网格 ─────────

def clusters(values: list[Decimal], tol: Decimal) -> list[Decimal]:
    """排序后相邻差 ≤ tol 的并成一簇，簇的代表值取簇内最小值。"""
    reps = []
    last = None
    for v in sorted(values):
        if last is None or v - last > tol:
            reps.append(v)
        last = v
    return reps


def which_cluster(v: Decimal, reps: list[Decimal], tol: Decimal) -> int:
    # reps 升序；v 落在 reps[k] 起、相邻差 ≤ tol 的链上 ⟹ 取不大于 v 的最大代表值
    lo, hi = 0, len(reps) - 1
    k = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if reps[mid] <= v:
            k = mid; lo = mid + 1
        else:
            hi = mid - 1
    return k


def axis(values: list[Decimal], tol: Decimal) -> dict:
    reps = clusters(values, tol)
    steps = [reps[i + 1] - reps[i] for i in range(len(reps) - 1)]
    groups: list[list] = []          # [代表步长, 次数]，按出现顺序合并（容差内视为同一步长）
    for s in steps:
        for g in groups:
            if abs(g[0] - s) <= tol:
                g[1] += 1
                break
        else:
            groups.append([s, 1])
    uniform = len(groups) == 1
    return {
        "distinct": len(reps),
        "min": num_out(reps[0]) if reps else None,
        "max": num_out(reps[-1]) if reps else None,
        "step": num_out(groups[0][0]) if uniform else None,
        "uniform": uniform,
        "steps": [{"step": num_out(s), "times": t} for s, t in groups],
        "positions": [num_out(r) for r in reps] if len(reps) <= 200 else None,
    }, reps


class Dist:
    """一维、二维分布的累计：只留不同取值（点）与各点的次数，不留行；聚类、步长、网格只看取值与次数。"""

    def __init__(self, spec, columns):
        if not isinstance(spec, dict):
            raise BadInput("distribution 须为对象 {x, y?, tol}")
        tol = parse_num(spec.get("tol", 0))
        if tol is None or tol < 0:
            raise BadInput("distribution.tol 须为非负数")
        self.tol = tol
        self.xi = col_index(columns, spec.get("x"), "distribution.x")
        self.yi = col_index(columns, spec["y"], "distribution.y") if spec.get("y") is not None else None
        self.echo = {"x": spec.get("x"), "tol": num_out(tol)}
        if self.yi is not None:
            self.echo["y"] = spec["y"]
        self.pts: dict[tuple, int] = {}
        self.used = 0
        self.bad = 0
        self.bad_ids = []

    def add(self, rid, cells):
        x = parse_num(cells[self.xi])
        y = parse_num(cells[self.yi]) if self.yi is not None else Decimal(0)
        if x is None or y is None:
            self.bad += 1
            if len(self.bad_ids) < 50:
                self.bad_ids.append(rid)
            return
        self.used += 1
        self.pts[(x, y)] = self.pts.get((x, y), 0) + 1

    def result(self):
        tol, yi = self.tol, self.yi
        out = {"what": self.echo, "rows_used": self.used, "rows_unparsed": self.bad, "unparsed_ids": self.bad_ids}
        if not self.used:
            out["x"] = None
            return out
        out["x"], xr = axis([p[0] for p in self.pts], tol)
        if yi is not None:
            out["y"], yr = axis([p[1] for p in self.pts], tol)
            cells = {}
            for (x, y), c in self.pts.items():
                k = (which_cluster(x, xr, tol), which_cluster(y, yr, tol))
                cells[k] = cells.get(k, 0) + c
            size = len(xr) * len(yr)
            out["grid"] = {
                "cols": len(xr), "rows": len(yr), "cells": size,
                "occupied": len(cells), "missing": size - len(cells),
                "stacked": sum(c - 1 for c in cells.values()),
                "full": len(cells) == size and self.used == size,
                "missing_cells": [{"x": num_out(xr[i]), "y": num_out(yr[j])}
                                  for i in range(len(xr)) for j in range(len(yr)) if (i, j) not in cells][:50],
            }
        return out


def distribution(rows, spec, columns):
    d = Dist(spec, columns)
    for rid, cells in rows:
        d.add(rid, cells)
    return d.result()
