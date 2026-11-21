"""2.7.0 零件计划补缺：PDF 转三维实验查实的六处缺口与整件倒角（先红：在 2.7.0-alpha.1 上除对照项外都红）。

1 表达式里的函数；2 正多边形 polygon；3 hole 的 dir=（任意方向）与环形阵列的 axis=；
4 prism 只给部分顶点倒圆；5 圆角、倒角按点选边；6 cad.check 不把两侧同轴盲孔并成通孔；
7 整件倒角（all、vertical、面名）跳过个别容不下的边并告警。
"""
import math

import pytest

from cad_dsl import DslError, parse
from cad_tool import _params, run


def build(plan):
    r = run({"tool": "cad.build", "payload": {"plan": plan, "formats": []}})
    assert r["ok"], r
    return r["output"]


def build_err(plan):
    r = run({"tool": "cad.build", "payload": {"plan": plan, "formats": []}})
    assert not r["ok"], r
    return r["error"]


def vol(plan):
    return build(plan)["measure"]["volume_mm3"]


# ---------------------------------------------------------------- 1 函数
@pytest.mark.parametrize("expr,val", [
    ("sin(30)", 0.5), ("cos(60)", 0.5), ("cos(90)", 0.0), ("sin(180)", 0.0), ("tan(45)", 1.0), ("cos(180)", -1.0),
    ("asin(0.5)", 30.0), ("acos(0)", 90.0), ("atan(1)", 45.0), ("atan2(1,-1)", 135.0),
    ("sqrt(16)", 4.0), ("abs(0-3)", 3.0), ("min(3,1,2)", 1.0), ("max(1,5)", 5.0),
    ("2*sin(30)+1", 2.0), ("-cos(0)", -1.0), ("sqrt(3*3+4*4)", 5.0), ("sin(30)*(1+1)", 1.0),
])
def test_functions_degrees(expr, val):
    st = parse(f"b: box 1 1 1 at=({expr}, 0, 0)")[0]
    assert st.kw["at"][0] == val


def test_function_in_tuple_and_let():
    st = parse("let r = 20\nlet a = 72\nb: box 1 1 1 at=(r*cos(a), r*sin(a), 0)")[0]
    assert st.kw["at"][0] == pytest.approx(20 * math.cos(math.radians(72)), abs=1e-12)
    assert st.kw["at"][1] == pytest.approx(20 * math.sin(math.radians(72)), abs=1e-12)


def test_let_variable_shadows_function_name():
    """let 定义了同名变量就按变量读，与 2.6 一致。"""
    st = parse("let sin = 3\nb: box sin 2 2")[0]
    assert st.pos == [3.0, 2.0, 2.0]


@pytest.mark.parametrize("plan,msg", [
    ("b: box 1 1 tan(90)", "tan"), ("b: box 1 1 asin(2)", "asin"), ("b: box 1 1 sqrt(0-1)", "sqrt"),
    ("b: box 1 1 sin(1,2)", "1 个参数"), ("b: box 1 1 min(1)", "2–20 个参数"), ("b: box 1 1 sin(30", "）"),
])
def test_function_errors(plan, msg):
    with pytest.raises(DslError) as e:
        parse(plan)
    assert e.value.line == 1
    assert msg in e.value.message or msg == "）"


def test_compare_params_keep_function_calls_whole():
    assert _params("h: hole d=10*sin(30) at=(cos(60)*2, 3) through") == \
        ("hole", [("d", "10*sin(30)"), ("at", "(cos(60)*2,3)"), ("arg1", "through")])
    # 非函数名后跟括号的写法照旧
    assert _params("a: prism smooth (1,2) (3,4) (5,6) h=2")[1][:2] == [("arg1", "smooth"), ("arg2", "(1,2)")]


# ---------------------------------------------------------------- 2 正多边形
def test_polygon_d_and_s():
    R = 30
    assert vol("p: polygon n=5 d=60 h=10") == pytest.approx(5 / 2 * R * R * math.sin(2 * math.pi / 5) * 10, rel=1e-7)
    assert vol("p: polygon n=6 s=24 h=8") == pytest.approx(math.sqrt(3) / 2 * 24 ** 2 * 8, rel=1e-7)


def test_polygon_angle_and_plane():
    m = build("p: polygon n=4 d=20 h=5 angle=45")["measure"]["bbox"]["size"]
    assert m[0] == pytest.approx(20 / math.sqrt(2), abs=1e-6)
    m = build("p: polygon n=4 d=20 h=5 plane=yz off=3 at=(1,2)")["measure"]["bbox"]
    assert m["min"][0] == 3.0 and m["size"][0] == 5.0 and m["max"][1] == 11.0


def test_polygon_rounded_and_cut():
    a = math.sqrt(3) / 2 * 24 ** 2
    r = 2
    corner = r * r * (1 / math.tan(math.radians(60)) - (math.pi - math.radians(120)) / 2)
    assert vol("p: polygon n=6 s=24 h=10 r=2") == pytest.approx((a - 6 * corner) * 10, rel=1e-7)
    assert vol("b: box 100 100 10\nk: cut polygon n=6 s=24 h=10 at=(50,50)") == pytest.approx(100 * 100 * 10 - a * 10, rel=1e-7)


@pytest.mark.parametrize("plan", [
    "p: polygon n=2 d=10 h=1", "p: polygon n=5.5 d=10 h=1", "p: polygon n=5 h=1",
    "p: polygon n=5 d=10 s=8 h=1", "p: polygon n=6 s=10 h=1 r=5",
])
def test_polygon_errors(plan):
    assert build_err(plan)["line"] == 1


# ---------------------------------------------------------------- 3 任意方向的孔
def test_hole_dir_oblique_through():
    v = vol("b: box 100 100 20\nh: hole d=10 at=(50,50,10) dir=(1,0,-1) through")
    assert v == pytest.approx(100 * 100 * 20 - math.pi * 25 * 20 * math.sqrt(2), rel=1e-7)


def test_hole_dir_axis_aligned_matches_from():
    a = build("b: box 40 40 20\nh: hole d=8 at=(10,20) from=top depth=12 cbore=(14,3)")
    b = build("b: box 40 40 20\nh: hole d=8 at=(10,20,5) dir=(0,0,-1) depth=12 cbore=(14,3)")
    assert a["measure"]["volume_mm3"] == pytest.approx(b["measure"]["volume_mm3"], rel=1e-9)
    assert a["measure"]["holes"] == b["measure"]["holes"]


def test_hole_dir_normal_to_slope_blind():
    """斜面法向打盲孔：深度从轴与斜面的交点量起，孔口整圈都在斜面上。"""
    plan = "w: prism (0,0) (60,0) (60,20) (0,60) h=40 plane=xz\nh: hole d=10 at=(30,20,40) dir=(-2,0,-3) depth=10"
    plain = vol("w: prism (0,0) (60,0) (60,20) (0,60) h=40 plane=xz")
    # 法线 (2,0,3) 方向的孔：斜截面关于轴对称，去掉的体积正好是 πr²·depth
    assert plain - vol(plan) == pytest.approx(math.pi * 25 * 10, rel=1e-6)


def test_hole_dir_on_slope_leaves_no_lip():
    """竖直孔打进斜面：孔口高的一边也要切净（不留月牙）。"""
    out = build("w: prism (0,0) (60,0) (60,60) h=40 plane=xz\nh: hole d=10 at=(30,20,30) dir=(0,0,-1) depth=10")
    h = out["measure"]["holes"]
    assert len(h) == 1 and h[0]["axis"] == "z"
    plain = vol("w: prism (0,0) (60,0) (60,60) h=40 plane=xz")
    assert plain - out["measure"]["volume_mm3"] == pytest.approx(math.pi * 25 * 10, rel=1e-6)


def test_hole_dir_pattern_default_z_and_axis_kw():
    out = build("p: polygon n=6 s=40 h=20 angle=30\nh: hole d=6 at=(20,0,10) dir=(-1,0,0) depth=8\nph: pattern h circular n=6 center=(0,0)")
    holes = [h for h in out["measure"]["holes"] if h["d"] == 6.0]
    assert len(holes) == 6 and all(not h["through"] and h["depth"] == 8.0 for h in holes)
    # 显式 axis=：从 top 打的孔绕 x 转（2.6 只能绕加工方向 z）
    out = build("c: cylinder d=40 h=40 axis=x\nh: hole d=4 at=(20,0) from=top depth=5\nph: pattern h circular n=4 center=(0,0) axis=x")
    assert len([h for h in out["measure"]["holes"] if h["d"] == 4.0]) == 4


@pytest.mark.parametrize("plan,frag", [
    ("b: box 10 10 10\nh: hole d=3 at=(5,5) dir=(0,0,-1) through", "(x,y,z)"),
    ("b: box 10 10 10\nh: hole d=3 at=(5,5,5) dir=(0,0,-1) from=top through", "from"),
    ("b: box 10 10 10\nh: hole d=3 at=(50,50,50) dir=(0,0,-1) through", "碰不到"),
    ("b: box 10 10 10\nh: hole d=3 at=(5,5,5) dir=(0,0,0) through", "零向量"),
])
def test_hole_dir_errors(plan, frag):
    e = build_err(plan)
    assert e["line"] == 2 and frag in e["message"]


# ---------------------------------------------------------------- 4 部分顶点倒圆
def a_fillet(r):
    return r * r * (1 - math.pi / 4)


@pytest.mark.parametrize("pts,n_round", [
    ("(0,0,5) (40,0) (40,40,5) (0,40)", 2), ("(0,0) (40,0) (40,40,5) (0,40)", 1), ("(0,0,5) (40,0,5) (40,40,5) (0,40)", 3),
])
def test_prism_some_vertices_rounded(pts, n_round):
    assert vol(f"p: prism {pts} h=10") == pytest.approx((1600 - n_round * a_fillet(5)) * 10, rel=1e-7)


def test_prism_some_rounded_concave_and_revolve():
    # L 形轮廓，内角 (20,20) 倒 r3（凹角加料）、外角 (0,40) 倒 r2
    area = 40 * 20 + 20 * 20 + a_fillet(3) - a_fillet(2)
    assert vol("p: prism (0,0) (40,0) (40,20) (20,20,3) (20,40) (0,40,2) h=5") == pytest.approx(area * 5, rel=1e-7)
    # revolve 共用同一轮廓程序
    build("r: revolve (5,0) (20,0,2) (20,10) (5,10) angle=360")


def test_prism_some_rounded_too_big():
    e = build_err("p: prism (0,0) (40,0) (40,40,25) (0,40,20) h=10")
    assert e["line"] == 1 and "装不下" in e["message"] and "减小 r" in e["hint"]


def test_prism_all_rounded_unchanged_path():
    """全部顶点倒圆仍走 2.6 的写法（金样 build-prism-rounded 逐字节不变）。"""
    v = vol("p: prism (0,0,5) (40,0,5) (40,40,5) (0,40,5) h=10")
    assert v == pytest.approx((1600 - 4 * a_fillet(5)) * 10, rel=1e-7)


# ---------------------------------------------------------------- 5 按点选边
def test_pick_two_corners():
    out = build("b: box 120 60 10\nf: fillet r=5 edges=vertical (0,0,5) (120,60,5)")
    assert out["measure"]["volume_mm3"] == pytest.approx((7200 - 2 * a_fillet(5)) * 10, rel=1e-7)
    f = out["features"][1]
    assert f["scope"] == "local" and f["refs"] == []


def test_pick_without_edges_and_with_feature_name():
    assert vol("b: box 120 60 10\nf: fillet r=5 (0,0,5) (120,60,5)") == pytest.approx((7200 - 2 * a_fillet(5)) * 10, rel=1e-7)
    out = build("b: box 40 40 10\nk: add box 10 10 10 at=(15,15,10)\nc: chamfer c=1 edges=k (20,15,20)")
    assert out["measure"]["volume_mm3"] == pytest.approx(40 * 40 * 10 + 1000 - 0.5 * 10, rel=1e-7)
    assert out["features"][2]["refs"] == ["k"] and out["features"][2]["scope"] == "local"


def test_pick_duplicates_collapse():
    assert vol("b: box 120 60 10\nf: fillet r=5 (0,0,5) (0,0,6)") == pytest.approx((7200 - a_fillet(5)) * 10, rel=1e-7)


@pytest.mark.parametrize("plan,frag", [
    ("b: box 10 10 10\nf: fillet r=1 (0,0,0)", "一样近"),
    ("b: box 10 10 10\nf: fillet r=1 (5,5,5)", "离最近的边"),
    ("b: box 10 10 10\nf: fillet r=1 (0,0)", "三个数"),
])
def test_pick_errors(plan, frag):
    e = build_err(plan)
    assert e["line"] == 2 and frag in e["message"]


def test_global_scope_unchanged_without_points():
    out = build("b: box 40 40 20\nf: fillet r=1 edges=vertical")
    assert out["features"][1]["scope"] == "global"


# ---------------------------------------------------------------- 6 同轴盲孔
COAX = "b: box 100 40 40\nl: hole d=10 at=(20,20) from=left depth=30\nr: hole d=10 at=(20,20) from=right depth=30"


def test_coaxial_blind_holes_are_two():
    holes = build(COAX)["measure"]["holes"]
    assert len(holes) == 2 and all(not h["through"] and h["depth"] == 30.0 for h in holes)
    r = run({"tool": "cad.check", "payload": {"plan": COAX, "expect": "holes 2 d=10\nhole d=10 axis=x through"}})
    assert [c["verdict"] for c in r["output"]["checks"]] == ["pass", "fail"]


def test_coaxial_meeting_blind_holes_are_one_through():
    """两侧盲孔在中间接上了，就是一个通孔。"""
    holes = build("b: box 100 40 40\nl: hole d=10 at=(20,20) from=left depth=60\nr: hole d=10 at=(20,20) from=right depth=60")["measure"]["holes"]
    assert len(holes) == 1 and holes[0]["through"]


def test_hole_across_cavity_stays_one():
    holes = build("b: box 100 40 40\ns: shell t=5 open=none\nh: hole d=10 at=(20,20) from=left through")["measure"]["holes"]
    assert len(holes) == 1 and holes[0]["through"]


# ---------------------------------------------------------------- 7 整件倒角跳过个别边
NARROW = "b: box 100 60 20\np: pocket rect w=40 l=0.5 at=(50,30) from=top depth=5\nc: chamfer c=0.3 edges=all"


def test_global_chamfer_skips_narrow_edges():
    out = build(NARROW)
    w = [x for x in out["warnings"] if x["line"] == 3]
    assert len(w) == 1 and "没有倒" in w[0]["message"]
    assert out["measure"]["valid"] and out["measure"]["solids"] == 1


def test_global_chamfer_skip_is_deterministic():
    assert build(NARROW) == build(NARROW)


@pytest.mark.parametrize("plan", [
    "b: box 10 10 10\nc: chamfer c=6 edges=all",                                                   # 大部分边都倒不了：尺寸本身不对
    "b: box 100 60 20\np: pocket rect w=40 l=0.5 at=(50,30) from=top depth=5\nc: chamfer c=0.3 edges=p",   # 按特征名选的边不跳过
    "b: box 100 60 20\np: pocket rect w=40 l=0.5 at=(50,30) from=top depth=5\nc: fillet r=0.3 edges=all",  # 圆角不跳过
])
def test_no_skip_cases_still_error(plan):
    assert build_err(plan)["line"] in (2, 3)
