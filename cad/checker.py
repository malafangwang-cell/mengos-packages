"""cad.check：按期望清单逐条核对零件，三值判定（pass / fail / unknown）。

期望清单与计划同一种行语法，一行一条：

    bbox 80 50 20 tol=0.05          # 外形尺寸（x y z），缺省 tol=0.01 mm
    fits 130 70 60                  # 能放进这个包络（允许换方向）
    volume 73700 rtol=0.001         # 体积 mm³，缺省 rtol=0.001
    area 21000 rtol=0.01            # 表面积 mm²
    mass 199 rtol=0.01              # 质量 g（计划里要有 material，否则 unknown）
    mass max=350                    # 上下限：max= / min=，可与单位连用（mass max=0.35 kg）
    com (40,25,10) tol=0.1          # 质心
    solids 1                        # 实体个数
    valid                           # B-rep 有效
    watertight                      # 网格水密（3D 打印前查）
    holes 7                         # 孔的总数
    holes 6 d=10                    # 直径为 10 的孔有 6 个
    hole d=10 axis=z at=(45,0) through     # 存在这样一个孔；可加 depth= cbore=(D,深) csk=(D,角)
    feature boss                    # 计划里有这个特征，且它在零件上还有面

判定只依据测量值，不依据计划文字；单条 unknown 不算失败，总判定见 overall()。
"""
from __future__ import annotations

import math

from cad_dsl import DslError, parse

KINDS = ["bbox", "fits", "volume", "area", "mass", "com", "solids", "valid", "watertight", "holes", "hole", "feature"]
MAX_CHECKS = 200


def _num(st, key, default):
    v = st.kw.get(key, default)
    if not isinstance(v, (int, float)) or v < 0:
        raise DslError(st.line, f"第 {st.line} 行：{key} 应当是非负数")
    return float(v)


def _close(a, b, tol):
    return abs(a - b) <= tol + 1e-12


def _fmt(x):
    if isinstance(x, float):
        return float(f"{x:.6g}")
    if isinstance(x, (list, tuple)):
        return [_fmt(v) for v in x]
    return x


def _allowed(st, keys):
    extra = set(st.kw) - set(keys)
    if extra:
        raise DslError(st.line, f"第 {st.line} 行（{st.op}）：不认识的参数 {'、'.join(sorted(extra))}")


def _pos_nums(st, n, what):
    xs = [p for p in st.pos if isinstance(p, float)]
    if len(xs) != n or len(st.pos) != n:
        raise DslError(st.line, f"第 {st.line} 行（{st.op}）：应当写 {n} 个数（{what}）")
    return xs


def _match_hole(h, st, tol):
    """返回不匹配的原因列表；空表示匹配。"""
    why = []
    if "d" in st.kw and not _close(h["d"], float(st.kw["d"]), tol):
        why.append(f"d={h['d']}")
    if "axis" in st.kw and h["axis"] != st.kw["axis"]:
        why.append(f"axis={h['axis']}")
    if "at" in st.kw:
        at = st.kw["at"]
        if not h["at"] or not isinstance(at, tuple) or len(at) != 2 or any(not _close(a, b, tol) for a, b in zip(h["at"], at)):
            why.append(f"at={h['at']}")
    if "through" in st.pos and not h["through"]:
        why.append("不通")
    if "blind" in st.pos and h["through"]:
        why.append("是通孔")
    if "depth" in st.kw and (h["through"] or not _close(h.get("depth", -1), float(st.kw["depth"]), tol)):
        why.append(f"depth={h.get('depth', 'through')}")
    if "cbore" in st.kw:
        D, dd = st.kw["cbore"] if isinstance(st.kw["cbore"], tuple) and len(st.kw["cbore"]) == 2 else (None, None)
        cb = h.get("cbore")
        if D is None or not cb or not _close(cb["d"], D, tol) or not _close(cb["depth"], dd, tol):
            why.append(f"cbore={cb}")
    if "csk" in st.kw:
        D, ang = st.kw["csk"] if isinstance(st.kw["csk"], tuple) and len(st.kw["csk"]) == 2 else (None, None)
        ck = h.get("csk")
        if D is None or not ck or not _close(ck["d"], D, max(tol, 0.05)) or not _close(ck["angle"], ang, 0.5):
            why.append(f"csk={ck}")
    return why


def run_checks(text: str, m: dict, features: list) -> list[dict]:
    stmts = parse(text)
    if len(stmts) > MAX_CHECKS:
        raise DslError(0, f"期望超过 {MAX_CHECKS} 条")
    out = []
    for st in stmts:
        if st.op not in KINDS:
            raise DslError(st.line, f"第 {st.line} 行：不认识的期望“{st.op}”", "可用：" + "、".join(KINDS))
        r = {"line": st.line, "src": st.src, "kind": st.op}
        size = m["bbox"]["size"]
        if st.op == "bbox":
            _allowed(st, ["tol"])
            want = _pos_nums(st, 3, "x y z 三个方向的外形尺寸")
            tol = _num(st, "tol", 0.01)
            ok = all(_close(a, b, tol) for a, b in zip(size, want))
            r.update(expected=_fmt(want), actual=_fmt(size), tol=tol)
        elif st.op == "fits":
            _allowed(st, ["tol"])
            env = _pos_nums(st, 3, "包络的三个尺寸")
            tol = _num(st, "tol", 0.0)
            ok = all(a <= b + tol for a, b in zip(sorted(size), sorted(env)))
            r.update(expected=_fmt(env), actual=_fmt(size), tol=tol, note="按排序后的尺寸比较，允许换方向摆放")
        elif st.op in ("volume", "area", "mass"):
            _allowed(st, ["rtol", "tol", "max", "min"])
            scale = {"g": 1.0, "kg": 1000.0, "mm3": 1.0, "cm3": 1000.0, "mm2": 1.0, "cm2": 100.0}
            unit = st.pos[-1] if st.pos and isinstance(st.pos[-1], str) else None
            if unit is not None and unit.lower() not in scale:
                raise DslError(st.line, f"第 {st.line} 行（{st.op}）：单位只认 g、kg、mm3、cm3、mm2、cm2")
            if unit is not None:
                st.pos = st.pos[:-1]
            actual = {"volume": m["volume_mm3"], "area": m["area_mm2"], "mass": m["mass_g"]}[st.op]
            k = scale[unit.lower()] if unit else 1.0
            if not st.pos and ("max" in st.kw or "min" in st.kw):       # 上下限：mass max=350、volume min=1e5 max=2e5
                lo = _num(st, "min", 0.0) * k if "min" in st.kw else None
                hi = _num(st, "max", 0.0) * k if "max" in st.kw else None
                exp_ = {k2: _fmt(v) for k2, v in (("min", lo), ("max", hi)) if v is not None}
                if actual is None:
                    r.update(verdict="unknown", expected=exp_, actual=None,
                             reason="计划里没有写 material，或材料不在密度表里，算不出质量")
                    out.append(r)
                    continue
                ok = (lo is None or actual >= lo - 1e-9) and (hi is None or actual <= hi + 1e-9)
                r.update(expected=exp_, actual=_fmt(actual))
                if not ok:
                    r["reason"] = f"超出上限 {hi:g}" if hi is not None and actual > hi else f"低于下限 {lo:g}"
                r["verdict"] = "pass" if ok else "fail"
                out.append(r)
                continue
            want = _pos_nums(st, 1, {"volume": "体积 mm³", "area": "表面积 mm²", "mass": "质量 g"}[st.op])[0] * k
            if actual is None:
                r.update(verdict="unknown", expected=_fmt(want), actual=None,
                         reason="计划里没有写 material，或材料不在密度表里，算不出质量")
                out.append(r)
                continue
            tol = _num(st, "tol", 0.0) if "tol" in st.kw else abs(want) * _num(st, "rtol", 0.001)
            ok = _close(actual, want, tol)
            r.update(expected=_fmt(want), actual=_fmt(actual), tol=_fmt(tol))
        elif st.op == "com":
            _allowed(st, ["tol"])
            want = st.pos[0] if len(st.pos) == 1 and isinstance(st.pos[0], tuple) and len(st.pos[0]) == 3 else None
            if want is None:
                raise DslError(st.line, f"第 {st.line} 行（com）：写成 com (x,y,z)")
            tol = _num(st, "tol", 0.01)
            ok = all(_close(a, b, tol) for a, b in zip(m["center_of_mass"], want))
            r.update(expected=_fmt(list(want)), actual=_fmt(m["center_of_mass"]), tol=tol)
        elif st.op == "solids":
            _allowed(st, [])
            want = _pos_nums(st, 1, "实体个数")[0]
            ok = m["solids"] == want
            r.update(expected=int(want), actual=m["solids"])
        elif st.op == "valid":
            _allowed(st, [])
            ok = m["valid"]
            r.update(expected=True, actual=m["valid"])
        elif st.op == "watertight":
            _allowed(st, [])
            if "watertight" not in m:
                r.update(verdict="unknown", reason="没有生成网格")
                out.append(r)
                continue
            ok = m["watertight"]
            r.update(expected=True, actual=m["watertight"])
        elif st.op == "holes":
            _allowed(st, ["d", "tol", "axis"])
            want = _pos_nums(st, 1, "孔的个数")[0]
            tol = _num(st, "tol", 0.01)
            hs = [h for h in m["holes"] if ("d" not in st.kw or _close(h["d"], float(st.kw["d"]), tol))
                  and ("axis" not in st.kw or h["axis"] == st.kw["axis"])]
            ok = len(hs) == want
            r.update(expected=int(want), actual=len(hs))
        elif st.op == "hole":
            _allowed(st, ["d", "axis", "at", "depth", "cbore", "csk", "tol"])
            bad = [p for p in st.pos if p not in ("through", "blind")]
            if bad:
                raise DslError(st.line, f"第 {st.line} 行（hole）：不认识“{bad[0]}”，只能写 through 或 blind")
            tol = _num(st, "tol", 0.01)
            reasons = [(h, _match_hole(h, st, tol)) for h in m["holes"]]
            hit = [h for h, why in reasons if not why]
            ok = bool(hit)
            r.update(expected={k: _fmt(list(v) if isinstance(v, tuple) else v) for k, v in st.kw.items()} | ({"through": True} if "through" in st.pos else {}),
                     actual=_fmt(hit[0]) if hit else None)
            if not ok:
                near = min(reasons, key=lambda x: len(x[1]))[0] if reasons else None
                r["reason"] = "没有匹配的孔" + (f"；最接近的是 d={near['d']} at={near['at']}" if near else "；零件上没有孔")
        elif st.op == "feature":
            _allowed(st, [])
            if len(st.pos) != 1 or not isinstance(st.pos[0], str):
                raise DslError(st.line, f"第 {st.line} 行（feature）：写成 feature 名字")
            f = next((x for x in features if x["id"] == st.pos[0]), None)
            ok = bool(f and f["faces"] > 0)
            r.update(expected=st.pos[0], actual=(f and {"line": f["line"], "faces": f["faces"]}))
            if not ok:
                r["reason"] = "计划里没有这个特征" if f is None else "这个特征的面已经全部被后续操作去掉"
        r["verdict"] = "pass" if ok else "fail"
        out.append(r)
    return out


def overall(checks: list[dict]) -> str:
    vs = {c["verdict"] for c in checks}
    if "fail" in vs:
        return "fail"
    if "unknown" in vs:
        return "unknown"
    return "pass"
