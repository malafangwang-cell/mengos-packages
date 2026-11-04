"""生成 golden_cases.json。参考值尽量来自手算（与工具无关）；回归值另行标注。"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = lambda n: (ROOT / "samples" / f"{n}.cad").read_text(encoding="utf-8")
pi = math.pi
d_fillet = lambda r: r * (10 - 3 * pi) / (12 - 3 * pi)           # 圆角截面形心到角点的距离（沿各边）
a_fillet = lambda r: r * r * (1 - pi / 4)                       # 圆角截面面积


def gear_area(m, z, alpha_deg=20, N=4000, bore=0.0):
    alpha = math.radians(alpha_deg); r = m * z / 2; rb = r * math.cos(alpha); ra = r + m; rf = r - 1.25 * m
    inv = lambda p: math.tan(p) - p; beta = pi / (2 * z) + inv(alpha); r0 = max(rb, rf); pitch = 2 * pi / z
    psi = lambda rho: beta if rho <= rb else beta - inv(math.acos(rb / rho))
    pts = []
    for k in range(z):
        c = k * pitch
        fl = [r0 + (ra - r0) * i / N for i in range(N + 1)]
        if rf < rb: pts.append((rf, c - beta))
        pts += [(rho, c - psi(rho)) for rho in fl]
        a, b = c - psi(ra), c + psi(ra); pts += [(ra, a + (b - a) * i / N) for i in range(1, N)]
        pts += [(rho, c + psi(rho)) for rho in reversed(fl)]
        if rf < rb: pts.append((rf, c + beta))
        a0 = c + (beta if rf < rb else psi(rf)); a1 = c + pitch - (beta if rf < rb else psi(r0))
        pts += [(rf if rf < rb else r0, a0 + (a1 - a0) * i / N) for i in range(1, N)]
    xy = [(p * math.cos(t), p * math.sin(t)) for p, t in pts]
    A = 0.5 * abs(sum(xy[i][0] * xy[(i + 1) % len(xy)][1] - xy[(i + 1) % len(xy)][0] * xy[i][1] for i in range(len(xy))))
    return A - pi * (bore / 2) ** 2


ring = 2 * pi * (10 + 0.5 / 3) * 0.125                           # 孔口 0.5 倒角环（Pappus）
v_base = 80 * 50 * 20 - pi * 100 * 20 - 2 * ring
v_flange = (pi * 60 ** 2 * 12 + pi * 30 ** 2 * 18 - pi * 15 ** 2 * 30 - 6 * pi * 25 * 12
            + a_fillet(2) * 2 * pi * (30 + d_fillet(2)) - a_fillet(2) * 2 * pi * (30 - d_fillet(2)))
v_bracket_nofillet = (120 * 60 * 10 + 120 * 10 * 40 - 4 * pi * 4.25 ** 2 * 10 - 4 * pi * (7 ** 2 - 4.25 ** 2) * 5
                      - (16 * 8 + pi * 16) * 10 + 2 * 0.5 * 40 * 40 * 6)
v_box = 100 * 60 * 40 - 95 * 55 * 37.5 - (30 * 15 - (4 - pi) * 9) * 2.5
v_gear = gear_area(2, 30, bore=12) * 12

cases = [
    {"id": "build-base", "tool": "cad.build", "payload": {"plan": S("base"), "name": "base", "formats": []},
     "expect": {"ok": True, "values": [
         {"path": "measure.volume_mm3", "value": round(v_base, 6), "rtol": 1e-7, "source": "手算：80·50·20 − π·10²·20 − 两个 0.5 倒角环（Pappus）"},
         {"path": "measure.mass_g", "value": round(v_base * 2.7 / 1000, 6), "rtol": 1e-7, "source": "体积 × 2.70 g/cm³"}],
         "equals": [{"path": "measure.bbox.size", "value": [80.0, 50.0, 20.0]},
                    {"path": "measure.holes.0.d", "value": 20.0}, {"path": "measure.holes.0.through", "value": True},
                    {"path": "measure.solids", "value": 1}, {"path": "measure.valid", "value": True},
                    {"path": "features.1.id", "value": "hole1"}, {"path": "features.1.line", "value": 4}]}},
    {"id": "build-flange", "tool": "cad.build", "payload": {"plan": S("flange"), "name": "flange", "formats": []},
     "expect": {"ok": True, "values": [
         {"path": "measure.volume_mm3", "value": round(v_flange, 6), "rtol": 1e-7,
          "source": "手算：盘 + 凸台 − 中心孔 − 6 螺栓孔；凸台根部凹圆角加、顶边凸圆角减（Pappus，形心距 r(10−3π)/(12−3π)）"}],
         "equals": [{"path": "measure.bbox.size", "value": [120.0, 120.0, 30.0]}, {"path": "measure.watertight", "value": True}],
         "count": [{"path": "measure.holes", "where": {"d": 10.0, "through": True}, "value": 6},
                   {"path": "measure.holes", "where": {"d": 30.0, "through": True}, "value": 1}]}},
    {"id": "build-bracket-nofillet", "tool": "cad.build",
     "payload": {"plan": S("bracket").replace("fillet r=3 edges=vertical", ""), "name": "bracket", "formats": []},
     "expect": {"ok": True, "values": [
         {"path": "measure.volume_mm3", "value": round(v_bracket_nofillet, 6), "rtol": 1e-7,
          "source": "手算：底板 + 立板 − 4×(Φ8.5 孔 + Φ14×5 沉头) − 长圆槽 × 壁厚 + 2 道三角筋"}],
         "count": [{"path": "measure.holes", "where": {"d": 8.5, "through": True}, "value": 4}]}},
    {"id": "build-bracket", "tool": "cad.build", "payload": {"plan": S("bracket"), "name": "bracket", "formats": []},
     "expect": {"ok": True, "values": [
         {"path": "measure.volume_mm3", "value": round(v_bracket_nofillet - a_fillet(3) * 120 + a_fillet(3) * 80, 3), "rtol": 5e-5,
          "source": "手算近似：无圆角体积 − 凸棱 120 mm × 圆角截面 + 凹棱 80 mm × 圆角截面；筋顶端效应约 3 mm³，故放宽到 5e-5"}],
         "equals": [{"path": "measure.bbox.size", "value": [120.0, 60.0, 50.0]}]}},
    {"id": "build-box", "tool": "cad.build", "payload": {"plan": S("box_pocket"), "name": "box", "formats": []},
     "expect": {"ok": True, "values": [
         {"path": "measure.volume_mm3", "value": round(v_box, 6), "rtol": 1e-7,
          "source": "手算：外 100·60·40 − 内 95·55·37.5 − 圆角窗 (30·15 − (4−π)·3²)·2.5"}],
         "equals": [{"path": "measure.watertight", "value": True}, {"path": "measure.holes", "value": []}]}},
    {"id": "build-gear", "tool": "cad.build", "payload": {"plan": S("gear"), "name": "gear", "formats": []},
     "expect": {"ok": True, "values": [
         {"path": "measure.volume_mm3", "value": round(v_gear, 3), "rtol": 2e-5,
          "source": "独立计算：渐开线齿廓按 4000 点/段的多边形面积 × 齿宽 − 轴孔；工具用样条拟合齿廓，相对误差 < 1e-5"}],
         "equals": [{"path": "measure.bbox.size.0", "value": 64.0}]}},
    {"id": "build-files", "tool": "cad.build", "workdir": True,
     "payload": {"plan": S("base"), "name": "base", "formats": ["step", "glb", "stl", "3mf", "svg", "dxf"]},
     "expect": {"ok": True, "equals": [{"path": "files.0.format", "value": "step"}, {"path": "files.5.format", "value": "dxf"}],
                "files_verified": True}},
    {"id": "check-pass", "tool": "cad.check",
     "payload": {"plan": S("flange"), "expect": "bbox 120 120 30\nholes 6 d=10\nhole d=30 axis=z at=(0,0) through\nmass 1.254 kg rtol=0.001\nfits 125 125 35\nwatertight\nfeature boss"},
     "expect": {"ok": True, "equals": [{"path": "verdict", "value": "pass"}, {"path": "covered", "value": True}]}},
    {"id": "check-fail", "tool": "cad.check",
     "payload": {"plan": S("flange"), "expect": "holes 8 d=10\nbbox 120 120 30"},
     "expect": {"ok": True, "equals": [{"path": "verdict", "value": "fail"}, {"path": "checks.0.verdict", "value": "fail"},
                                       {"path": "checks.0.actual", "value": 6}, {"path": "checks.1.verdict", "value": "pass"}]}},
    {"id": "check-unknown", "tool": "cad.check",
     "payload": {"plan": "b: box 10 10 10", "expect": "mass 2 g\nvolume 1000"},
     "expect": {"ok": True, "equals": [{"path": "verdict", "value": "unknown"}, {"path": "covered", "value": False},
                                       {"path": "checks.0.verdict", "value": "unknown"}, {"path": "checks.1.verdict", "value": "pass"}]}},
    {"id": "check-bounds", "tool": "cad.check",
     "payload": {"plan": S("bracket"), "expect": "mass max=300\nmass max=0.35 kg\nvolume min=1e5 max=2e5"},
     "expect": {"ok": True, "equals": [{"path": "verdict", "value": "fail"}, {"path": "checks.0.verdict", "value": "fail"},
                                       {"path": "checks.1.verdict", "value": "pass"}, {"path": "checks.2.verdict", "value": "pass"}]}},
    {"id": "check-hole-mismatch", "tool": "cad.check",
     "payload": {"plan": S("bracket"), "expect": "hole d=8.5 cbore=(14,5) through\nhole d=8.5 cbore=(16,5) through"},
     "expect": {"ok": True, "equals": [{"path": "checks.0.verdict", "value": "pass"}, {"path": "checks.1.verdict", "value": "fail"}]}},
    {"id": "export-stl", "tool": "cad.export", "workdir": True,
     "payload": {"plan": S("box_pocket"), "name": "box", "formats": ["stl"]},
     "expect": {"ok": True, "equals": [{"path": "files.0.path", "value": "box.stl"}], "files_verified": True}},
    {"id": "err-unknown-op", "tool": "cad.build", "payload": {"plan": "b: box 10 10 10\nb2: torus d=5"},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 2}},
    {"id": "err-empty-part", "tool": "cad.build", "payload": {"plan": "b: box 10 10 10\nhole d=50 from=top through", "formats": []},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 2}},
    {"id": "err-fillet-too-big", "tool": "cad.build", "payload": {"plan": "b: box 10 10 10\nfillet r=6 edges=all", "formats": []},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 2, "hint_contains": "最大圆角"}},
    {"id": "err-undefined-var", "tool": "cad.build", "payload": {"plan": "b: box w 10 10", "formats": []},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 1, "hint_contains": "let"}},
    {"id": "err-no-workdir", "tool": "cad.export", "payload": {"plan": "b: box 10 10 10", "formats": ["step"]},
     "expect": {"ok": False, "code": "BAD_INPUT"}},
    {"id": "err-blind-into-air", "tool": "cad.build",
     "payload": {"plan": "b: box 40 40 10\nh: hole d=10 at=center from=top through\nh2: hole d=4 at=center from=top depth=3", "formats": []},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 3}},
    {"id": "err-bad-check", "tool": "cad.check", "payload": {"plan": "b: box 10 10 10", "expect": "density 2"},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 1}},
]
# ---- 2.3.0 新操作（参考值手算，与工具无关）----
def pappus(poly):
    """回转体体积 = 2π·∫∫ r dA：多边形 (r,z) 的一阶矩（格林公式）。"""
    n = len(poly); m = 0.0
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        m += (x0 + x1) * (x0 * y1 - x1 * y0) / 6
    return 2 * pi * abs(m)


PULLEY = [(12.5, 0), (60, 0), (60, 10), (48, 14), (48, 16), (60, 20), (60, 40), (12.5, 40)]
L_helix = 8 * math.sqrt((20 * pi) ** 2 + 6 ** 2)
V = lambda cid, plan, vol, src, rtol=1e-7, size=None, extra=None: {
    "id": cid, "tool": "cad.build", "payload": {"plan": plan, "name": cid.replace("build-", ""), "formats": []},
    "expect": {"ok": True, "values": [{"path": "measure.volume_mm3", "value": round(vol, 6), "rtol": rtol, "source": src}],
               "equals": ([{"path": "measure.bbox.size", "value": size}] if size else []) + [{"path": "measure.solids", "value": 1}] + (extra or [])}}
cases += [
    V("build-revolve-ring", "revolve (5,0) (10,0) (10,20) (5,20)", pi * (100 - 25) * 20, "手算：π(10²−5²)·20", size=[20.0, 20.0, 20.0]),
    V("build-revolve-pulley", "revolve " + " ".join(f"({r},{z})" for r, z in PULLEY), pappus(PULLEY),
      "手算：截面多边形绕 z 轴回转，Pappus（一阶矩按格林公式）", size=[120.0, 120.0, 40.0]),
    V("build-prism-rounded", "prism (0,0,5) (40,0,5) (40,40,5) (0,40,5) h=10", (1600 - (4 - pi) * 25) * 10,
      "手算：(40² − (4−π)·5²)·10", size=[40.0, 40.0, 10.0]),
    V("build-prism-twist", "prism (-50,-5) (50,-5) (50,5) (-50,5) h=20 twist=30", 100 * 10 * 20,
      "手算：扭转不改变截面面积，体积 = 100·10·20", rtol=1e-6),
    V("build-sweep-tube", "sweep d=12 id=8 (0,0,0) (0,0,50)", pi * (36 - 16) * 50, "手算：π(6²−4²)·50", size=[12.0, 12.0, 50.0]),
    V("build-sweep-bend", "sweep d=12 (0,0,46) (0,0,6) (100,0,6) (100,0,46) r=15",
      pi * 36 * (2 * 25 + 70 + 2 * (pi / 2) * 15), "手算：π·6²·中心线长（两段直 25、底边 70、两段 R15 四分之一弧；Pappus）",
      rtol=1e-6, size=[112.0, 12.0, 46.0]),
    V("build-helix", "helix d=20 pitch=6 h=48 wire=2", pi * 1 * L_helix,
      "手算：π·1²·螺旋线长，线长 = 圈数·√((πD)²+p²)", rtol=1e-5),
    V("build-grid", "base: box 100 60 3\nh1: hole d=5 at=(20,15) from=top through\npattern h1 grid n=7 m=4 dx=10 dy=10",
      100 * 60 * 3 - 28 * pi * 2.5 ** 2 * 3, "手算：板 − 28 个 Φ5 通孔", extra=[{"path": "features.2.op", "value": "pattern"}]),
    V("build-mirror", "base: box 100 20 10\nrib: add box 10 20 30 at=(5,0,10)\nmirror rib plane=yz off=50",
      100 * 20 * 10 + 2 * 10 * 20 * 30, "手算：板 + 两块筋", size=[100.0, 20.0, 40.0]),
    V("build-expr-minus", "let c = 25\nlet hb = 5\nbox 10 10 c-hb", 2000, "手算：10·10·(25−5)；c-hb 按减法读"),
    V("build-eng-symbols", "plate: cylinder d=Φ40 h=10mm\nbore: hole d=Ø10 at=center from=top through\nv: cut cylinder d=Φ20 h=2mm at=(0,0,8)\nb: hole d=⌀4 at=(15,0) from=top through\npattern b circular n=4 center=(0,0) angle=360°",
      pi * (20 ** 2 * 10 - 5 ** 2 * 10 - 10 ** 2 * 2 + 5 ** 2 * 2 - 4 * 2 ** 2 * 10), "手算：Φ40×10 盘 − Φ10 通孔 − 顶面 Φ20 深 2 的沉台（与通孔重叠部分扣回）− 4 个 Φ4 通孔（在沉台外）；记号 Φ Ø ⌀ ° mm 按 2.4.0 规范化"),
    {"id": "export-from-object", "tool": "cad.export", "workdir": True,
     "payload": {"object": {"tool": "cad.build", "args": {"plan": "b: box 10 10 10"}}, "name": "obj", "format": "stl"},
     "expect": {"ok": True, "equals": [{"path": "files.0.format", "value": "stl"}]}},
    {"id": "err-sweep-tight-bend", "tool": "cad.build",
     "payload": {"plan": "sweep d=12 (0,0,40) (0,0,0) (50,0,0) r=4", "formats": []},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 1, "hint_contains": "r 至少"}},
    {"id": "err-unknown-symbol-hint", "tool": "cad.build",
     "payload": {"plan": "box 10 10 10\nb: box 5 5 5±0.1", "formats": []},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 2, "hint_contains": "公差"}},
    {"id": "err-helix-wire-pitch", "tool": "cad.build",
     "payload": {"plan": "helix d=20 pitch=2 h=20 wire=2", "formats": []},
     "expect": {"ok": False, "code": "BAD_INPUT", "line": 1}},
]
(ROOT / "golden_cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(len(cases), "cases")
