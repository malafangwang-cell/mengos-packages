"""rack.layout 的算法（设计-域包排布计算工具 三、四；r3 〇补）。

只做本包 G2、G3、G5、G6 写明的推算：不读图、不做判断、不取整凑数。
全部按有理数精确计算；除法只在整除时成立；floor 只用在 G5 写明取整的那一步。
算不出的项不出值，在 not_computed 里逐项说明；needs 一律写一路追到底仍缺的入参名（调度 2026-11-23 裁）。
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction

import text

TOP_INPUTS = ("columns_read", "run_length", "column_pitch", "level_segments", "beam_clear")
ZONE_INPUTS = ("pallets", "pallet_plan_a", "pallet_plan_b")
ZONE_ITEMS = ("pallets_per_cell", "rows", "groups", "aisles")
TOTAL_ITEMS = ("rows", "groups", "aisles")
ZONE_NAME = re.compile(r"^[^/~#]{1,32}$")
MAX_ZONES = 20


class ShapeError(Exception):
    """入参形状不对（签名层面）；message 是出问题的位置。"""


# ---------- 读数 ----------

def _num(v):
    """入参读成有理数；读不成 ⟹ None。数量位置经引擎替换后是数，或能读成数的字符串。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return Fraction(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return Fraction(Decimal(repr(v)))
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            d = Decimal(s)
        except InvalidOperation:
            return None
        if not d.is_finite():
            return None
        return Fraction(d)
    return None


def _show(x):
    """有理数写回 JSON：整数写整数；有限小数写十进制字符串；其余写 p/q。"""
    if isinstance(x, Fraction):
        if x.denominator == 1:
            return x.numerator
        d = x.denominator
        while d % 2 == 0:
            d //= 2
        while d % 5 == 0:
            d //= 5
        if d == 1:
            return format(Decimal(x.numerator) / Decimal(x.denominator), "f")
        return f"{x.numerator}/{x.denominator}"
    return x


def _is_pos_int(x):
    return x is not None and x.denominator == 1 and x > 0


# ---------- 结果 ----------

class Ok:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class Fail:
    __slots__ = ("kind", "needs", "upstream", "formula", "operands")

    def __init__(self, kind, needs=(), upstream=(), formula="", operands=None):
        self.kind = kind            # missing | upstream | invalid
        self.needs = set(needs)
        self.upstream = list(upstream)
        self.formula = formula
        self.operands = operands or {}


def parse(payload):
    """形状核对；返回 (top, zones)：top 为 {名: 原值}，zones 为 {区名: {名: 原值}}；缺席与 null 都不进。"""
    if not isinstance(payload, dict):
        raise ShapeError("/")
    for k in payload:
        if k != "from_drawing":
            raise ShapeError(f"/{k}")
    fd = payload.get("from_drawing")
    if not isinstance(fd, dict):
        raise ShapeError("/from_drawing")
    top, zones = {}, {}
    for k, v in fd.items():
        if k in TOP_INPUTS:
            if v is not None:
                top[k] = v
        elif k == "zones":
            if v is None:
                continue
            if not isinstance(v, dict):
                raise ShapeError("/from_drawing/zones")
            if len(v) > MAX_ZONES:
                raise ShapeError("/from_drawing/zones")
            for name, zv in v.items():
                if not ZONE_NAME.match(name):
                    raise ShapeError("/from_drawing/zones")
                if not isinstance(zv, dict):
                    raise ShapeError(f"/from_drawing/zones/{name}")
                z = {}
                for zk, zval in zv.items():
                    if zk not in ZONE_INPUTS:
                        raise ShapeError(f"/from_drawing/zones/{name}/{zk}")
                    if zval is not None:
                        z[zk] = zval
                zones[name] = z
        else:
            raise ShapeError(f"/from_drawing/{k}")
    return top, zones


# ---------- 推算 ----------

def compute(payload):
    """返回 (output, nothing)：nothing 为 True 时一项也算不出，调用方给失败回执。"""
    top, zones = parse(payload)
    zone_names = sorted(zones)
    order = list(TOP_INPUTS)
    for z in zone_names:
        order += [f"zones/{z}/{k}" for k in ZONE_INPUTS]
    order.append("zones")
    rank = {name: i for i, name in enumerate(order)}

    results = {}     # 出参名 → Ok | Fail（只含要报告的项）
    steps = []

    def val(name):
        return _num(top[name]) if name in top else None

    def raw(name):
        return top.get(name)

    def up(*pairs):
        """pairs: (出参名, 结果)；返回 (已失败的上游名, 追到底的 needs)。"""
        names, needs = [], set()
        for n, r in pairs:
            if isinstance(r, Fail):
                names.append(n)
                needs |= r.needs
        return names, needs

    def step(item, clause, formula, operands, result, note=None):
        s = {"item": item, "clause": clause, "formula": formula,
             "operands": {k: _show(v) for k, v in operands.items()}, "result": _show(result)}
        if note is not None:
            s["note"] = note
        steps.append(s)

    # 列数 N（G2）：照读优先；否则总长 ÷ 列距
    n_res = None
    if "columns_read" in top:
        c = val("columns_read")
        if _is_pos_int(c):
            n_res = Ok(c)
            ops = {"columns_read": c}
            note = None
            rl, cp = val("run_length"), val("column_pitch")
            if "run_length" in top and "column_pitch" in top and rl is not None and cp is not None:
                ops.update({"run_length": rl, "column_pitch": cp})
                if c * cp != rl:
                    note = text.W3_STEP_INCONSISTENT
            step("columns", "G2", "columns_read", ops, c, note)
        else:
            n_res = Fail("invalid", formula="columns_read", operands={"columns_read": raw("columns_read")})
            results["columns"] = n_res
    else:
        missing = [k for k in ("run_length", "column_pitch") if k not in top]
        if len(missing) == 2:
            n_res = Fail("missing", needs=["columns_read"])
        elif missing:
            n_res = Fail("missing", needs=missing)
        else:
            rl, cp = val("run_length"), val("column_pitch")
            if rl is None or cp is None or rl <= 0 or cp <= 0 or (rl / cp).denominator != 1:
                n_res = Fail("invalid", formula="run_length ÷ column_pitch",
                             operands={"run_length": raw("run_length"), "column_pitch": raw("column_pitch")})
            else:
                n = rl / cp
                n_res = Ok(n)
                step("columns", "G2", "run_length ÷ column_pitch", {"run_length": rl, "column_pitch": cp}, n)
        results["columns"] = n_res

    # 每排立柱片数（G2）
    if isinstance(n_res, Ok):
        results["frames_per_row"] = Ok(n_res.value + 1)
        step("frames_per_row", "G2", "columns + 1", {"columns": n_res.value}, n_res.value + 1)
    else:
        names, needs = up(("columns", n_res))
        results["frames_per_row"] = Fail("upstream", needs=needs, upstream=names)

    # 层数（G3）
    if "level_segments" not in top:
        lv = Fail("missing", needs=["level_segments"])
    else:
        s = val("level_segments")
        if _is_pos_int(s):
            lv = Ok(s + 1)
            step("levels", "G3", "level_segments + 1", {"level_segments": s}, s + 1)
        else:
            lv = Fail("invalid", formula="level_segments + 1", operands={"level_segments": raw("level_segments")})
    results["levels"] = lv

    # 各区（G5、G6）
    zone_results = {}
    for z in zone_names:
        zin = zones[z]
        p = f"zones/{z}"
        zr = {}

        # 每格每层托盘数
        miss = [k for k in ("beam_clear",) if k not in top] + [f"{p}/{k}" for k in ("pallet_plan_a", "pallet_plan_b") if k not in zin]
        if miss:
            ppc = Fail("missing", needs=miss)
        else:
            ce, a, b = val("beam_clear"), _num(zin["pallet_plan_a"]), _num(zin["pallet_plan_b"])
            formula = "floor(beam_clear ÷ min(pallet_plan_a, pallet_plan_b))"
            if None in (ce, a, b) or ce <= 0 or a <= 0 or b <= 0:
                ppc = Fail("invalid", formula=formula, operands={"beam_clear": raw("beam_clear"),
                           "pallet_plan_a": zin["pallet_plan_a"], "pallet_plan_b": zin["pallet_plan_b"]})
            else:
                k = Fraction(math.floor(ce / min(a, b)))
                ops = {"beam_clear": ce, "pallet_plan_a": a, "pallet_plan_b": b}
                if k < 1:
                    ppc = Fail("invalid", formula=formula, operands=ops)
                else:
                    ppc = Ok(k)
                    step(f"{p}/pallets_per_cell", "G5", formula, ops, k)
        zr["pallets_per_cell"] = ppc

        # 排数
        formula = "pallets ÷ (columns × levels × pallets_per_cell)"
        names, needs = up(("columns", n_res), ("levels", lv), (f"{p}/pallets_per_cell", ppc))
        if "pallets" not in zin:
            needs.add(f"{p}/pallets")
        if names:
            rows = Fail("upstream", needs=needs, upstream=names)
        elif "pallets" not in zin:
            rows = Fail("missing", needs=needs)
        else:
            pal = _num(zin["pallets"])
            denom = n_res.value * lv.value * ppc.value
            ops = {"pallets": pal if pal is not None else zin["pallets"], "columns": n_res.value,
                   "levels": lv.value, "pallets_per_cell": ppc.value}
            if not _is_pos_int(pal) or (pal / denom).denominator != 1:
                rows = Fail("invalid", formula=formula, operands=ops)
            else:
                rows = Ok(pal / denom)
                step(f"{p}/rows", "G5", formula, ops, rows.value)
        zr["rows"] = rows

        # 组数、巷道数
        prev_name, prev = f"{p}/rows", rows
        for item, var in (("groups", "rows"), ("aisles", "groups")):
            formula = f"{var} ÷ 2"
            if isinstance(prev, Fail):
                names, needs = up((prev_name, prev))
                cur = Fail("upstream", needs=needs, upstream=names)
            elif prev.value % 2 != 0:
                cur = Fail("invalid", formula=formula, operands={var: prev.value})
            else:
                cur = Ok(prev.value / 2)
                step(f"{p}/{item}", "G6", formula, {var: prev.value}, cur.value)
            zr[item] = cur
            prev_name, prev = f"{p}/{item}", cur

        zone_results[z] = zr
        for item in ZONE_ITEMS:
            results[f"{p}/{item}"] = zr[item]

    # 合计（G6）
    for item in TOTAL_ITEMS:
        name = f"total/{item}"
        if not zone_names:
            results[name] = Fail("missing", needs=["zones"])
            continue
        names, needs = up(*((f"zones/{z}/{item}", zone_results[z][item]) for z in zone_names))
        if names:
            results[name] = Fail("upstream", needs=needs, upstream=names)
        else:
            total = sum((zone_results[z][item].value for z in zone_names), Fraction(0))
            results[name] = Ok(total)
            step(name, "G6", f"Σ zones/*/{item}", {f"zones/{z}/{item}": zone_results[z][item].value for z in zone_names}, total)

    # ---------- 组装回执 ----------
    computed, not_computed = {}, []
    for name, r in results.items():
        if isinstance(r, Ok):
            if name == "columns" and "columns_read" in top:
                continue   # 照读的列数不回显（设计稿二.3）
            cur = computed
            parts = name.split("/")
            for seg in parts[:-1]:
                cur = cur.setdefault(seg, {})
            cur[parts[-1]] = int(r.value)
        else:
            needs = sorted(r.needs, key=lambda k: rank.get(k, len(rank)))
            if r.kind == "missing":
                reason = text.W3_MISSING.format(item=name, needs="、".join(needs))
            elif r.kind == "upstream":
                reason = text.W3_UPSTREAM.format(item=name, upstream="、".join(r.upstream))
            else:
                reason = text.W3_INVALID.format(item=name, formula=r.formula,
                                                operands="、".join(f"{k}={_show(v) if isinstance(v, Fraction) else v}" for k, v in r.operands.items()))
            not_computed.append({"item": name, "reason": reason, "needs": needs})

    output = {"computed": computed, "not_computed": not_computed, "steps": steps, "assumptions": []}
    return output, not computed
