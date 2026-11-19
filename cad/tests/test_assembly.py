"""cad.assemble 第 1 阶段（立项 §九 第 1 阶段验收 1–10）：包内离线验证，不接引擎、不进登记。

两道题的装配计划是人手写的：samples/assembly/vise.json（题 A 平口虎钳）、reducer.json（题 B 两级直齿减速器）。
"""
import copy
import csv
import io
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import assembly
from assembly import run

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {n: json.loads((ROOT / "samples" / "assembly" / f"{n}.json").read_text(encoding="utf-8")) for n in ("vise", "reducer")}
ALL = ["step", "glb", "csv", "svg", "dxf"]
EXPECT = {"vise": (8, 12), "reducer": (19, 29)}     # 零件种数、实例数（按计划手数）


def _sub(payload, workdir, seed):
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    line = json.dumps({"tool": "cad.assemble", "payload": payload, "workdir": str(workdir)}, ensure_ascii=False)
    p = subprocess.run([sys.executable, str(ROOT / "assembly.py")], input=line, capture_output=True, text=True,
                       env=env, timeout=300)
    return p.stdout


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """两道题各跑两次：两个进程、不同哈希种子，全部格式。"""
    out = {}
    for name, doc in SAMPLES.items():
        payload = dict(doc, formats=ALL)
        a, b = tmp_path_factory.mktemp(name + "_a"), tmp_path_factory.mktemp(name + "_b")
        oa, ob = _sub(payload, a, 1), _sub(payload, b, 987)
        out[name] = (oa, ob, a, b)
    return out


def _out(runs, name):
    res = json.loads(runs[name][0])
    assert res["ok"], res
    return res["output"], runs[name][2]


def _layout_variant(name, old, new, formats=()):
    doc = copy.deepcopy(SAMPLES[name])
    assert old in doc["layout"], old
    doc["layout"] = doc["layout"].replace(old, new)
    doc["formats"] = list(formats)
    return run({"tool": "cad.assemble", "payload": doc})


# ---------------------------------------------------------------- 1 建得出来，件数一致
@pytest.mark.parametrize("name", ["vise", "reducer"])
def test_builds_with_planned_counts(runs, name):
    o, _ = _out(runs, name)
    kinds, insts = EXPECT[name]
    assert o["measure"]["parts"] == kinds == len(o["bom"]) == len(SAMPLES[name]["parts"])
    assert o["measure"]["instances"] == insts == len(o["instances"]) == sum(r["qty"] for r in o["bom"])
    assert all(c["status"] == "满足" and c["dof"] == 0 for c in o["constraints"])
    assert o["warnings"] == []


# ---------------------------------------------------------------- 2 确定性
@pytest.mark.parametrize("name", ["vise", "reducer"])
def test_double_run_bytes(runs, name):
    oa, ob, a, b = runs[name]
    assert json.loads(oa)["ok"], oa
    assert oa == ob
    files = sorted(os.listdir(a))
    assert files == sorted(os.listdir(b)) and len(files) == 5
    for f in files:
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


# ---------------------------------------------------------------- 3 STEP 第三方读回
def _step_entities(text):
    body = text.split("DATA;", 1)[1].split("ENDSEC;", 1)[0]
    ents = {}
    for chunk in body.split(";"):
        chunk = " ".join(chunk.split())
        m = re.match(r"#(\d+) = ([A-Z_]+)\((.*)\)$", chunk)
        if m:
            ents[int(m.group(1))] = (m.group(2), m.group(3))
    return ents


def _step_str(s):
    """ISO 10303-21 字符串（只认本工具会写的 \\X2\\…\\X0\\ 与 '' 转义）。"""
    def x2(m):
        h = m.group(1)
        return bytes.fromhex(h).decode("utf-16-be")
    return re.sub(r"\\X2\\([0-9A-F]+)\\X0\\", x2, s).replace("''", "'")


def _step_structure(path):
    """不经几何内核，按 ISO 10303-21 文本读装配结构：产品名、实例名、实例 → 产品。"""
    ents = _step_entities(path.read_text(encoding="ascii"))
    pd_to_product = {}
    for k, (t, a) in ents.items():
        if t == "PRODUCT_DEFINITION":
            form = int(re.findall(r"#(\d+)", a)[0])
            prod = int(re.findall(r"#(\d+)", ents[form][1])[0])
            pd_to_product[k] = _step_str(re.match(r"'((?:[^']|'')*)'", ents[prod][1]).group(1))
    nauo = []
    for k, (t, a) in sorted(ents.items()):
        if t == "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
            strs = re.findall(r"'((?:[^']|'')*)'", a)
            refs = [int(x) for x in re.findall(r"#(\d+)", re.sub(r"'(?:[^']|'')*'", "''", a))]   # 行名里可有 #
            nauo.append((_step_str(strs[1]), pd_to_product[refs[0]], pd_to_product[refs[1]]))
    return nauo


@pytest.mark.parametrize("name", ["vise", "reducer"])
def test_step_structure_names_and_counts(runs, name):
    o, d = _out(runs, name)
    nauo = _step_structure(d / f"{name}.step")
    assert [n[0] for n in nauo] == [i["row"] for i in o["instances"]]          # 实例名 = 行名，顺序一致
    assert [n[2] for n in nauo] == [i["part"] for i in o["instances"]]         # 实例 → 零件
    assert {n[1] for n in nauo} == {name}                                      # 都挂在装配体根下
    counts = {}
    for _, _, p in nauo:
        counts[p] = counts.get(p, 0) + 1
    assert counts == {r["part"]: r["qty"] for r in o["bom"]}


@pytest.mark.parametrize("name", ["vise", "reducer"])
def test_step_readback_volume_and_labels(runs, name):
    from build123d import import_step
    o, d = _out(runs, name)
    a = import_step(str(d / f"{name}.step"))
    kids = list(a.children)
    assert a.label == name
    assert [k.label for k in kids] == [i["part"] for i in o["instances"]]
    assert abs(a.volume - o["measure"]["volume_mm3"]) / o["measure"]["volume_mm3"] < 1e-6
    for k, inst in zip(kids, o["instances"]):
        bb = k.bounding_box()
        lo, hi = inst["bbox"]
        assert all(abs(x - y) < 0.05 for x, y in zip((bb.min.X, bb.min.Y, bb.min.Z), lo)), (inst["row"], bb, lo)
        assert all(abs(x - y) < 0.05 for x, y in zip((bb.max.X, bb.max.Y, bb.max.Z), hi)), (inst["row"], bb, hi)


# ---------------------------------------------------------------- 4 干涉
@pytest.mark.parametrize("name", ["vise", "reducer"])
def test_correct_layout_has_no_interference(runs, name):
    o, _ = _out(runs, name)
    assert o["interference"]["count"] == 0 and o["interference"]["hits"] == []
    assert o["interference"]["pairs_checked"] > 0


def test_shaft_pushed_5mm_reports_pair_and_volume():
    """中间轴沿轴向挪 5 mm，后端插进后闭盖（闭盖72，实心盘）：公共体积 = π·17.5²·5。"""
    r = _layout_variant("reducer", "s2:  put 中间轴 coaxial=b.孔2 face=bottom to=b.box.front flush",
                        "s2:  put 中间轴 coaxial=b.孔2 face=bottom to=b.box.front flush gap=-5")
    assert r["ok"], r
    hits = r["output"]["interference"]["hits"]
    pairs = {frozenset((h["a"], h["b"])): h for h in hits}
    assert frozenset(("s2", "e4")) in pairs, hits
    want = math.pi * 17.5 ** 2 * 5
    got = pairs[frozenset(("s2", "e4"))]["volume_mm3"]
    assert abs(got - want) / want < 1e-3, (got, want)
    assert len(hits) == 1, hits      # 齿轮随轴肩一起挪，啮合仍对齿，不出别的干涉


def test_vise_screw_pushed_into_movable_jaw():
    """虎钳丝杠挪 5 mm（轴肩离开固定钳身端面），没有别的件被顶到时不报；挪进去 5 mm 插进钳身端座。"""
    r = _layout_variant("vise", "s:   put 丝杠 coaxial=b.孔 face=肩.top to=b.left angle=0",
                        "s:   put 丝杠 coaxial=b.孔 face=肩.top to=b.left gap=-5 angle=0")
    assert r["ok"], r
    hits = r["output"]["interference"]["hits"]
    pairs = {frozenset((h["a"], h["b"])): h for h in hits}
    # 轴肩 d=28 插进端座 5 mm；端座里孔 d=18 → 公共体积 = π(14² − 9²)·5
    want = math.pi * (14 ** 2 - 9 ** 2) * 5
    got = pairs[frozenset(("b", "s"))]["volume_mm3"]
    assert abs(got - want) / want < 1e-3, (got, want)


# ---------------------------------------------------------------- 5 啮合
def test_mesh_pairs_do_not_interfere(runs):
    o, _ = _out(runs, "reducer")
    m = {(x["a"], x["b"]): x for x in o["mesh"]}
    assert set(m) == {("g1", "g2"), ("g3", "g4")}
    for x in m.values():
        assert x["ok"] and x["common_mm3"] <= x["limit_mm3"]
    assert m[("g1", "g2")]["center_distance"] == 90.0 and m[("g3", "g4")]["center_distance"] == 138.0


@pytest.mark.parametrize("row,z", [("g2", 70), ("g4", 72)])
def test_without_mesh_half_pitch_off_interferes(runs, row, z):
    """去掉 mesh=，改成 angle=（啮合算出的转角 + 半个齿距）：齿顶对齿顶，要报干涉。"""
    o, _ = _out(runs, "reducer")
    rot = next(c for c in o["constraints"] if c["row"] == row)["mesh_rotation_deg"]
    line = next(ln for ln in SAMPLES["reducer"]["layout"].splitlines() if ln.startswith(row + ":"))
    other = "g1" if row == "g2" else "g3"
    bad = line.replace(f"mesh={other}", f"angle={rot + 180 / z:.6f}")
    r = _layout_variant("reducer", line, bad)
    assert r["ok"], r
    hits = r["output"]["interference"]["hits"]
    assert any({h["a"], h["b"]} == {other, row} and h["volume_mm3"] > 1 for h in hits), hits
    # 对照：同样写 angle=，取啮合算出的转角本身，不报
    good = line.replace(f"mesh={other}", f"angle={rot:.6f}")
    r2 = _layout_variant("reducer", line, good)
    assert r2["ok"] and not any({h["a"], h["b"]} == {other, row} for h in r2["output"]["interference"]["hits"])


def test_mesh_wrong_center_distance_is_conflict():
    doc = copy.deepcopy(SAMPLES["reducer"])
    for p in doc["parts"]:
        if p["id"] == "齿轮2":
            p["plan"] = p["plan"].replace("z=70", "z=71")
    doc["formats"] = []
    r = run({"tool": "cad.assemble", "payload": doc})
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT"
    pr = r["error"]["problems"]
    assert pr[0]["row"] == "g2" and pr[0]["status"] == "冲突" and "中心距 90.000" in pr[0]["message"] and "91.000" in pr[0]["message"]


# ---------------------------------------------------------------- 6 欠约束与冲突：带行号，一次报全
def test_underconstrained_and_conflicts_reported_all_at_once():
    doc = copy.deepcopy(SAMPLES["vise"])
    lay = doc["layout"]
    rep = {
        "m:   put 活动钳身 coaxial=b.孔 face=right to=p1.left gap=90 angle=0": "m:   put 活动钳身 coaxial=b.孔 angle=0",
        "n:   put 螺母 coaxial=m.孔 face=bottom to=m.left flush": "n:   put 螺母 coaxial=b.孔 face=bottom to=b.base.top",
        "h:   put 手柄 at=(-23,0,45)": "h:   put 手柄 at=(-23,0,45) coaxial=s.横孔",
        "r:   put 挡圈 coaxial=s face=bottom to=b.end.right": "r:   put 挡圈 face=bottom to=b.end.right",
    }
    for k, v in rep.items():
        assert k in lay
        lay = lay.replace(k, v)
    doc["layout"], doc["formats"] = lay, []
    r = run({"tool": "cad.assemble", "payload": doc})
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT"
    pr = {p["row"]: p for p in r["error"]["problems"] if p["row"]}
    lines = {ln.split(":")[0].strip(): i for i, ln in enumerate(lay.splitlines(), 1) if ":" in ln and not ln.startswith("#")}
    assert pr["m"]["status"] == "欠约束" and pr["m"]["free"] == ["沿轴移动"] and pr["m"]["line"] == lines["m"]
    assert pr["n"]["status"] == "冲突" and "90.000°" in pr["n"]["message"] and pr["n"]["line"] == lines["n"]
    assert pr["h"]["status"] == "冲突" and pr["h"]["line"] == lines["h"]
    assert pr["r"]["status"] == "欠约束" and pr["r"]["line"] == lines["r"] and len(pr["r"]["free"]) == 2
    # 引用了出错行的行：只说先改那一行，不连锁报别的
    assert pr["p2"]["status"] == "引用错误" and "m 本身有错" in pr["p2"]["message"]
    for p in r["error"]["problems"]:
        assert p["message"].startswith(f"第 {p['line']} 行")
    assert r["error"]["line"] == min(p["line"] for p in r["error"]["problems"])


def test_flush_offset_conflict_reports_difference():
    r = _layout_variant("vise", "p1:  put 钳口板 face=right to=b.jaw.left face2=bottom to2=b.base.top gap2=10 face3=front to3=b.front flush3",
                        "p1:  put 钳口板 face=right to=b.jaw.left face2=bottom to2=b.base.top gap2=10 face3=front to3=b.front flush3 face=right")
    assert not r["ok"]          # 参数重复：解析器当场报，带行号
    assert r["error"]["line"] == 3
    r = _layout_variant("vise", "face3=front to3=b.front flush3\nsc1:",
                        "face3=front to3=b.front flush3\nq: put 钳口板 face=right to=b.jaw.left face2=bottom to2=b.base.top gap2=10 face3=front to3=b.front flush3\nsc1:")
    assert r["ok"]   # 同一位置再放一块：摆位本身没问题，由干涉检查报出
    assert any({h["a"], h["b"]} == {"p1", "q"} for h in r["output"]["interference"]["hits"])


def test_part_plan_errors_are_all_reported_with_part_and_line():
    doc = copy.deepcopy(SAMPLES["vise"])
    doc["parts"][1]["plan"] = doc["parts"][1]["plan"].replace("plate: box 10 100 40", "plate: box 10 w 40")
    doc["parts"][2]["plan"] = doc["parts"][2]["plan"].replace("shank: cylinder", "shank: cylindr")
    doc["formats"] = []
    r = run({"tool": "cad.assemble", "payload": doc})
    assert not r["ok"]
    pr = r["error"]["problems"]
    assert [(p["part"], p["line"]) for p in pr] == [("钳口板", 2), ("螺钉", 2)]


# ---------------------------------------------------------------- 明细表、外形
def test_bom_csv_matches_record(runs):
    o, d = _out(runs, "reducer")
    raw = (d / "reducer.bom.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0] == ["序号", "名称", "数量", "材料", "单件质量(g)", "合计质量(g)"]
    body = rows[1:-1]
    assert [r[1] for r in body] == [b["part"] for b in o["bom"]]
    assert [int(r[2]) for r in body] == [b["qty"] for b in o["bom"]]
    assert rows[-1][1] == "合计" and int(rows[-1][2]) == 29
    assert abs(float(rows[-1][5]) - o["measure"]["mass_g"]) < 1e-3
    assert abs(sum(b["total_mass_g"] for b in o["bom"]) - o["measure"]["mass_g"]) < 1e-3


def test_reducer_ratio_and_center_distances(runs):
    """题 B 的设计读数：传动比乘积与 12.5 相差不超过 5%；每对齿轮轴距 = m(z1+z2)/2。"""
    o, _ = _out(runs, "reducer")
    (a, b) = o["mesh"]
    ratio = (a["z"][1] / a["z"][0]) * (b["z"][1] / b["z"][0])
    assert abs(ratio - 12.5) / 12.5 < 0.05
    for x in (a, b):
        assert abs(x["center_distance"] - x["m"] * sum(x["z"]) / 2) < 1e-6


def test_vise_opening_is_80(runs):
    o, _ = _out(runs, "vise")
    bb = {i["row"]: i["bbox"] for i in o["instances"]}
    assert abs(bb["p1"][0][0] - bb["p2"][1][0] - 80) < 1e-6        # 两钳口板夹持面之间
    assert abs((bb["p1"][1][1] - bb["p1"][0][1]) - 100) < 1e-6      # 钳口宽 100


# ---------------------------------------------------------------- 8 GLB
def test_glb_two_level_nodes_and_shared_meshes(runs):
    import struct
    o, d = _out(runs, "reducer")
    data = (d / "reducer.glb").read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    g = json.loads(data[20:20 + n])
    root = g["nodes"][0]
    assert root["extras"]["assembly"] is True
    inst_nodes = [g["nodes"][i] for i in root["children"]]
    assert [x["name"] for x in inst_nodes] == [i["row"] for i in o["instances"]]
    assert [x["extras"]["item"] for x in inst_nodes] == [i["item"] for i in o["instances"]]
    for x in inst_nodes:
        kids = [g["nodes"][k] for k in x["children"]]
        assert kids and all("mesh" in k for k in kids)
    # 同一零件的实例共用网格
    by_part = {}
    for x in inst_nodes:
        meshes = tuple(g["nodes"][k]["mesh"] for k in x["children"])
        by_part.setdefault(x["extras"]["part"], set()).add(meshes)
    assert all(len(v) == 1 for v in by_part.values())
    assert o["triangles"]["unique"] < o["triangles"]["shown"]


def test_glb_readback_trimesh(runs):
    import trimesh
    o, d = _out(runs, "vise")
    sc = trimesh.load(str(d / "vise.glb"), force="scene")
    vol = 0.0
    for node in sc.graph.nodes_geometry:
        tf, gname = sc.graph[node]
        geom = sc.geometry[gname]
        if isinstance(geom, trimesh.Trimesh) and "edges" not in gname:
            m = geom.copy()
            m.apply_transform(tf)
            vol += m.volume
    # 网格单位为米；每个特征一块网格，体积按块相加（特征网格共同围成零件表面）
    assert abs(vol * 1e9 - o["measure"]["volume_mm3"]) / o["measure"]["volume_mm3"] < 0.005


# ---------------------------------------------------------------- 10 装配三视图
@pytest.mark.parametrize("name", ["vise", "reducer"])
def test_drawings_extents_match_bbox(runs, name):
    import ezdxf
    import geometry
    o, d = _out(runs, name)
    size = o["measure"]["bbox"]["size"]
    svg = (d / f"{name}.svg").read_text(encoding="utf-8")
    assert f"外形 {size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f}" in svg
    for v in ("主视图", "俯视图", "左视图"):
        assert v in svg
    doc = ezdxf.read(io.StringIO((d / f"{name}.dxf").read_text(encoding="utf-8")))
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"visible", "hidden", "text"} <= layers
    # 三个视图的外框（消隐投影的范围）与整体包围盒一致：主视 x×z，俯视 x×y，左视 y×z
    from build123d import Compound
    from assembly import Layout, _build_parts, _layout
    parts = _build_parts(SAMPLES[name]["parts"])
    L = _layout(parts, SAMPLES[name]["layout"])
    comp = Compound([i.shape for i in L.insts])
    _, frames = geometry._layout(comp)
    w = {k: (f[2] - f[0], f[3] - f[1]) for k, f in frames.items()}
    tol = 0.05
    assert abs(w["front"][0] - size[0]) < tol and abs(w["front"][1] - size[2]) < tol, (w, size)
    assert abs(w["top"][0] - size[0]) < tol and abs(w["top"][1] - size[1]) < tol, (w, size)
    assert abs(w["left"][0] - size[1]) < tol and abs(w["left"][1] - size[2]) < tol, (w, size)


# ---------------------------------------------------------------- 入参与安全
def test_no_eval_exec_in_assembly_source():
    text = (ROOT / "assembly.py").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])(eval|exec|compile)\s*\(", text)
    assert "getattr(" not in text


@pytest.mark.parametrize("payload,frag", [
    ({}, "parts"),
    ({"parts": [], "layout": "b: fix x"}, "parts"),
    ({"parts": [{"id": "a.b", "plan": "b: box 1 1 1"}], "layout": "b: fix a.b"}, "不含点"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}, {"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a"}, "重复"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": ""}, "layout"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a", "formats": ["stl"]}, "不支持的格式"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a", "base": "x"}, "不认识的字段"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: put a at=(0,0,0)"}, "fix"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a\nc: put a"}, "欠约束"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a\nc: put a coaxial=b"}, "没有可用的轴"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a\nb: fix a"}, "已经用过"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b.c: fix a"}, "不能带点"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a\npattern b linear n=100000 dx=1"}, "2–100"),
    ({"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a\nc: put a face=top to=b.nosuch"}, "nosuch"),
])
def test_bad_inputs_fail_structured(payload, frag):
    payload = dict(payload)
    payload.setdefault("formats", [])
    r = run({"tool": "cad.assemble", "payload": payload})
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", r
    assert frag in r["error"]["message"], r["error"]


def test_files_need_workdir():
    r = run({"tool": "cad.assemble", "payload": {"parts": [{"id": "a", "plan": "b: box 1 1 1"}], "layout": "b: fix a"}})
    assert not r["ok"] and "workdir" in r["error"]["message"]


def test_unused_part_warns():
    r = run({"tool": "cad.assemble", "payload": {"parts": [{"id": "a", "plan": "b: box 1 1 1"}, {"id": "c", "plan": "b: box 1 1 1"}],
                                                 "layout": "b: fix a", "formats": []}})
    assert r["ok"] and r["output"]["warnings"][0]["code"] == "unused_part"


def test_spin_default_warns_only_for_non_axisymmetric():
    plans = [{"id": "base", "plan": "b: box 40 40 10 at=(-20,-20,-10)\nh: cut cylinder d=10 h=12 at=(0,0,-11)"},
             {"id": "pin", "plan": "p: cylinder d=10 h=30"},
             {"id": "key", "plan": "p: cylinder d=10 h=30\nf: cut box 20 4 40 at=(-10,3,-5)"}]
    r = run({"tool": "cad.assemble", "payload": {"parts": plans, "formats": [], "layout":
             "b: fix base\np: put pin coaxial=b.h face=bottom to=b.bottom flush\nk: put key coaxial=b.h face=bottom to=b.top"}})
    assert r["ok"], r
    w = r["output"]["warnings"]
    assert [x["row"] for x in w] == ["k"] and w[0]["code"] == "spin_default"


def test_circular_pattern_and_given_pose():
    plans = [{"id": "disc", "plan": "d: cylinder d=100 h=10\nc: cut cylinder d=20 h=12 at=(0,0,-1)\nh: hole d=8 at=(40,0) from=top through\npattern h circular n=6 center=(0,0)"},
             {"id": "bolt", "plan": "s: cylinder d=8 h=10\nhead: add cylinder d=13 h=5 at=(0,0,10)"}]
    r = run({"tool": "cad.assemble", "payload": {"parts": plans, "formats": [], "layout":
             "d: fix disc rot=(0,0,0) at=(0,0,0)\nb1: put bolt coaxial=d.h face=head.bottom to=d.top\npattern b1 circular n=6 axis=d.c"}})
    assert r["ok"], r
    o = r["output"]
    assert o["measure"]["instances"] == 7 and o["interference"]["count"] == 0
    ctr = [((i["bbox"][0][0] + i["bbox"][1][0]) / 2, (i["bbox"][0][1] + i["bbox"][1][1]) / 2) for i in o["instances"][1:]]
    for k, (x, y) in enumerate(ctr):
        ang = math.radians(60 * k)
        assert abs(x - 40 * math.cos(ang)) < 1e-3 and abs(y - 40 * math.sin(ang)) < 1e-3
    # 给定位姿：at、rot 都写
    r = run({"tool": "cad.assemble", "payload": {"parts": plans, "formats": [], "layout":
             "d: fix disc\nb: put bolt at=(0,0,50) rot=(90,0,0)"}})
    assert r["ok"]
    lo, hi = r["output"]["instances"][1]["bbox"]
    assert abs(lo[1] - (-15)) < 1e-3 and abs(hi[1] - 0) < 1e-3       # z 轴转到 -y


def test_old_tools_and_lock_untouched():
    """第 1 阶段不进登记：lock 覆盖的文件与登记都没动，四件旧工具的版本不变（旧工具输出逐字节不变由原有测试覆盖）。"""
    from lock import SOURCES, lock_hash
    reg = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    assert reg["lock_hash"] == lock_hash() == "3625f3c31608de88"
    assert "assembly.py" not in SOURCES
    assert sorted(u["tool_id"] for u in reg["units"]) == ["cad.build", "cad.check", "cad.compare", "cad.export"]
