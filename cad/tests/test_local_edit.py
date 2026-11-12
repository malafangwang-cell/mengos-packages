"""局部修改用的输出（cad 2.6.0；执行令《局部追问 · cad 包补强》K1–K9、K11–K14）。

每一项先红后绿：在 2.5.2 上本文件全红（见 PR 读数）。法兰取交互定稿 #728 的写法（proto-cad.html）：
行行有名，留一行无名的倒角演示“不可选”。
"""
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from cad_tool import run
from contribution_ref import merge

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
BUILD = UNITS["cad.build"]["signature"]["input_schema"]
V252 = ROOT / "tests" / "fixtures" / "v252"
ALL = ["step", "glb", "stl", "3mf", "svg", "dxf"]

FLANGE = """# 法兰：Φ120 盘 + Φ60 凸台，中心孔 Φ30，6×Φ10 均布螺栓孔（PCD 90）
material Q235
let D = 120
plate: cylinder d=D h=12
boss: cylinder d=60 h=18 at=(0,0,12)
bore: hole d=30 at=center from=top through
b1: hole d=10 at=(45,0) from=bottom through
ring: pattern b1 circular n=6 center=(0,0)
fl: fillet r=2 edges=boss
chamfer c=1 edges=bottom"""
NAMED = "\n".join(FLANGE.split("\n")[:9])          # 去掉无名倒角：全具名


def build(plan, tmp_path=None, formats=()):
    env = {"tool": "cad.build", "payload": {"plan": plan, "name": "p", "formats": list(formats)}}
    if formats:
        env["workdir"] = str(tmp_path)
    r = run(env)
    assert r["ok"], r
    return r["output"]


def feat(out, fid):
    return next(f for f in out["features"] if f["id"] == fid)


def glb_json(path):
    data = Path(path).read_bytes()
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n]), data


def compare(old, new):
    r = run({"tool": "cad.compare", "payload": {"old": old, "new": new}})
    return r


# ───────────────────────── K1 行行有名（C1）─────────────────────────
def test_k1_unnamed_feature_line_warns_with_line_and_auto_id():
    out = build("b: box 10 10 10\nchamfer c=1")
    w = [x for x in out["warnings"] if x.get("code") == "unnamed_feature"]
    assert w == [{"line": 2, "code": "unnamed_feature", "feature": "chamfer#1", "message": w[0]["message"]}]
    assert "chamfer#1" in w[0]["message"]


def test_k1_fully_named_plan_has_no_warnings():
    assert build(NAMED)["warnings"] == []


def test_k1_unnamed_warning_covers_every_feature_kind():
    out = build("box 60 40 20\nadd box 10 10 10 at=(0,0,20)\nh: hole d=5 at=(30,20) from=bottom depth=5\n"
                "pattern h linear n=2 dx=10\nmirror h plane=yz off=30\nshell t=2 open=top\nfillet r=0.5 edges=h\nchamfer c=0.3 edges=bottom")
    got = [(x["line"], x["feature"]) for x in out["warnings"] if x.get("code") == "unnamed_feature"]
    assert got == [(1, "box#1"), (2, "add#1"), (4, "pattern#1"), (5, "mirror#1"), (6, "shell#1"), (7, "fillet#1"), (8, "chamfer#1")]


def test_k1_build_description_requires_names():
    d = BUILD["properties"]["plan"]["description"]
    assert "都要写名字" in d and "unnamed_feature" in d and "想以后还能改的特征都写上名字" not in d


@pytest.mark.parametrize("name", ["base", "flange", "bracket", "box_pocket", "gear"])
def test_k1_old_samples_unchanged_except_added_fields_and_unnamed_warnings(tmp_path, name):
    """“只放宽”：2.5.2 已有的每个字段逐字节不变；只多出新字段与 unnamed_feature 告警。
    文件：STEP、STL、3MF、SVG、DXF 的 sha256 与 2.5.2 相同；GLB 去掉节点 extras 里新加的 faces 后与 2.5.2 逐字节相同。"""
    old = json.loads((V252 / f"{name}.json").read_text(encoding="utf-8"))["output"]
    plan = (ROOT / "samples" / f"{name}.cad").read_text(encoding="utf-8")
    env = {"tool": "cad.build", "payload": {"plan": plan, "name": name, "formats": ALL}, "workdir": str(tmp_path)}
    p = subprocess.run([sys.executable, str(ROOT / "cad_tool.py")], input=json.dumps(env), capture_output=True,
                       text=True, timeout=300)                                   # 与 2.5.2 读数同走进程入口（固定哈希种子）
    new = json.loads(p.stdout)["output"]
    assert set(new) - set(old) == {"lines", "part"}
    for k in ("name", "plan_sha256", "measure"):
        assert new[k] == old[k], k
    assert [{k: f[k] for k in ("id", "op", "line", "src", "faces")} for f in new["features"]] == old["features"]
    assert [w for w in new["warnings"] if w.get("code") != "unnamed_feature"] == old["warnings"]
    assert new["warnings"][:len(old["warnings"])] == old["warnings"]          # 新告警排在后面，旧告警下标不变
    for fn, fo in zip(new["files"], old["files"]):
        if fn["format"] != "glb":
            assert fn == fo, fn["format"]
    g, data = glb_json(tmp_path / f"{name}.glb")
    for nd in g["nodes"]:
        nd.get("extras", {}).pop("faces", None)
    js = json.dumps(g, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode()
    js += b" " * ((-len(js)) % 4)
    n = struct.unpack("<I", data[12:16])[0]
    rest = data[20 + n:]
    old_glb = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + len(rest)) + struct.pack("<II", len(js), 0x4E4F534A) + js + rest
    fo = next(f for f in old["files"] if f["format"] == "glb")
    assert hashlib.sha256(old_glb).hexdigest() == fo["sha256"]


# ───────────────────────── K2 计划行与特征一一对应；可选清单 ─────────────────────────
def test_k2_lines_match_plan_line_by_line():
    out = build(FLANGE)
    lines = out["lines"]
    assert [x["line"] for x in lines] == list(range(1, 11))
    assert [x["kind"] for x in lines] == ["comment", "declaration", "declaration", "feature", "feature", "feature",
                                          "feature", "copy", "modifier", "modifier"]
    named = [x for x in lines if x.get("name")]
    assert [x["name"] for x in named] == ["plate", "boss", "bore", "b1", "ring", "fl"]
    assert all(x["feature_id"] == x["name"] for x in named)                   # 每个具名特征行恰好一个特征 id
    ids = [x["feature_id"] for x in lines if "feature_id" in x]
    assert ids == [f["id"] for f in out["features"]] and len(set(ids)) == len(ids)   # 反之亦然


def test_k2_declarations_not_selectable_unnamed_has_why_not():
    out = build(FLANGE)
    by = {x["line"]: x for x in out["lines"]}
    assert by[2]["selectable"] is False and by[2]["why_not"] == "declaration"   # material
    assert by[3]["selectable"] is False and by[3]["why_not"] == "declaration"   # let
    assert by[10]["selectable"] is False and by[10]["why_not"] == "unnamed"
    c = feat(out, "chamfer#1")
    assert c["selectable"] is False and c["why_not"] == "unnamed"
    assert feat(out, "boss")["selectable"] is True and "why_not" not in feat(out, "boss")


def test_k2_named_let_and_units_are_declarations():
    out = build("u: units mm\nk: let w = 20\nm: material 6061\nb: box w 10 10")
    assert [(x["name"], x["kind"], x["selectable"]) for x in out["lines"]] == [
        ("u", "declaration", False), ("k", "declaration", False), ("m", "declaration", False), ("b", "feature", True)]


def test_k2_zero_face_feature_is_selectable_with_zero_faces():
    out = build("b: box 40 40 10\nh1: hole d=10 at=center from=top depth=5\nh2: hole d=10 at=center from=top depth=5")
    h2 = feat(out, "h2")
    assert h2["faces"] == 0 and h2["selectable"] is True and h2["face_digest"] == []


# ───────────────────────── K3 阵列与镜像分组 ─────────────────────────
def test_k3_pattern_group_and_instance_per_copy(tmp_path):
    out = build(NAMED, tmp_path, ["glb"])
    assert feat(out, "ring")["group"] == {"kind": "pattern", "source": "b1", "instances": 6}
    g, _ = glb_json(tmp_path / "p.glb")
    ring = next(n for n in g["nodes"] if n.get("name") == "ring")
    assert ring["extras"]["feature"] == "ring"
    inst = sorted({f["instance"] for f in ring["extras"]["faces"]})
    assert inst == [1, 2, 3, 4, 5]                                             # 复制出来的 5 个，各不相同；源孔是 b1
    b1 = next(n for n in g["nodes"] if n.get("name") == "b1")
    assert all("instance" not in f for f in b1["extras"]["faces"])


def test_k3_mirror_group():
    out = build("base: box 100 20 10\nrib: add box 10 20 30 at=(5,0,10)\nmr: mirror rib plane=yz off=50")
    assert feat(out, "mr")["group"] == {"kind": "mirror", "source": "rib", "instances": 2}
    assert "group" not in feat(out, "rib")


def test_k3_grid_instances_count_all():
    out = build("base: box 100 60 3\nh1: hole d=5 at=(20,15) from=top through\ng: pattern h1 grid n=7 m=4 dx=10 dy=10")
    assert feat(out, "g")["group"]["instances"] == 28


# ───────────────────────── K4 面摘要（C2）─────────────────────────
def test_k4_digest_is_deterministic_and_sorted():
    a, b = build(NAMED), build(NAMED)
    assert json.dumps(a["features"], sort_keys=True) == json.dumps(b["features"], sort_keys=True)
    for f in a["features"]:
        assert f["face_digest"] == sorted(f["face_digest"])
        assert len(f["face_digest"]) == f["faces"]
        assert all(round(area, 3) == area for _, area in f["face_digest"])


# ───────────────────────── K5 比较单元（C2）：调研 §3.1 法兰五例 ─────────────────────────
FIVE = [   # (改动, 改了, 随动, 被修剪)：调研-CAD局部追问技术可行性 §3.1 路 A 表；fillet#1 即本稿的 fl，pattern#1 即 ring
    ("boss: cylinder d=60 h=18 at=(0,0,12)", "boss: cylinder d=70 h=18 at=(0,0,12)", ["boss"], ["fl"], ["plate"]),
    ("boss: cylinder d=60 h=18 at=(0,0,12)", "boss: cylinder d=60 h=25 at=(0,0,12)", ["boss"], ["fl"], ["bore"]),
    ("bore: hole d=30 at=center from=top through", "bore: hole d=36 at=center from=top through", ["bore"], [], ["plate", "boss"]),
    ("b1: hole d=10 at=(45,0) from=bottom through", "b1: hole d=12 at=(45,0) from=bottom through", ["b1"], ["ring"], ["plate"]),
    ("plate: cylinder d=D h=12", "plate: cylinder d=140 h=12", ["plate"], [], []),
]


@pytest.mark.parametrize("a,b,changed,followed,trimmed", FIVE, ids=["boss-d", "boss-h", "bore-d", "b1-d", "plate-d"])
def test_k5_compare_five_flange_cases(a, b, changed, followed, trimmed):
    old, new = build(NAMED), build(NAMED.replace(a, b))
    r = compare(old, new)
    assert r["ok"], r
    o = r["output"]
    assert (o["changed"], o["followed"], sorted(o["trimmed"])) == (changed, followed, sorted(trimmed))
    assert o["added"] == [] and o["removed"] == [] and o["part_changed"] == []


def test_k5_area_only_change_is_trimmed_not_followed():
    old, new = build(NAMED), build(NAMED.replace("boss: cylinder d=60", "boss: cylinder d=70"))
    o = compare(old, new)["output"]
    assert "plate" in o["trimmed"] and "plate" not in o["followed"]
    p0, p1 = feat(old, "plate")["face_digest"], feat(new, "plate")["face_digest"]
    assert {k for k, _ in p0} == {k for k, _ in p1} and p0 != p1


def test_k5_old_table_without_digest_is_bad_input_with_rebuild_hint():
    old = json.loads((V252 / "flange.json").read_text(encoding="utf-8"))["output"]
    new = build((ROOT / "samples" / "flange.cad").read_text(encoding="utf-8"))
    r = compare(old, new)
    assert r["ok"] is False and r["error"]["code"] == "BAD_INPUT"
    assert "重建一次" in r["error"]["hint"]


def test_k5_added_and_removed():
    old = build(NAMED)
    new = build(NAMED + "\nb2: hole d=6 at=(0,45) from=top through")
    o = compare(old, new)["output"]
    assert o["added"] == ["b2"] and o["removed"] == []
    assert compare(new, old)["output"]["removed"] == ["b2"]


def test_k5_comment_or_spacing_only_edit_is_not_a_change():
    old = build(NAMED)
    new = build(NAMED.replace("boss: cylinder d=60 h=18 at=(0,0,12)", "boss:  cylinder d=60  h=18 at=(0, 0, 12)   # 凸台"))
    o = compare(old, new)["output"]
    assert o["changed"] == [] and o["param_diffs"] == []


# ───────────────────────── K6 事前预告（C3）─────────────────────────
def test_k6_refs_and_referenced_by():
    out = build(FLANGE)
    assert feat(out, "fl")["refs"] == ["boss"]
    assert feat(out, "ring")["refs"] == ["b1"]
    assert "fl" in feat(out, "boss")["referenced_by"]
    assert "ring" in feat(out, "b1")["referenced_by"]
    assert feat(out, "chamfer#1")["refs"] == []                              # edges=bottom 不是特征名
    assert feat(out, "plate")["referenced_by"] == []                         # 隐式依赖不算（只是下限）


# ───────────────────────── K7 归属不确定（C4）─────────────────────────
def test_k7_sphere_cut_later_has_uncertain_faces(tmp_path):
    out = build("s: sphere d=40\nh: hole d=10 at=center from=top through", tmp_path, ["glb"])
    assert sum(f["uncertain_faces"] for f in out["features"]) > 0
    g, _ = glb_json(tmp_path / "p.glb")
    flags = [fc for n in g["nodes"] for fc in n.get("extras", {}).get("faces", []) if fc.get("uncertain")]
    assert flags


@pytest.mark.parametrize("plan", [
    "b: box 40 40 10",
    "c: cylinder d=30 h=10",
    "b: box 40 40 10\nh: hole d=10 at=center from=top through\nk: add cylinder d=10 h=5 at=(5,5,10)",
])
def test_k7_box_cylinder_hole_have_none(tmp_path, plan):
    out = build(plan, tmp_path, ["glb"])
    assert all(f["uncertain_faces"] == 0 for f in out["features"])
    g, _ = glb_json(tmp_path / "p.glb")
    assert not [fc for n in g["nodes"] for fc in n.get("extras", {}).get("faces", []) if fc.get("uncertain")]


# ───────────────────────── K8 局部补丁形状（复审 G1）─────────────────────────
LP = REG.get("local_patch") or {}


def test_k8_local_patch_schema_compiles_and_rejects_unnamed_lines():
    jsonschema.Draft202012Validator.check_schema(LP["schema"])
    V = jsonschema.Draft202012Validator(LP["schema"])
    for ok in (["boss: cylinder d=70 h=18 at=(0,0,12)"], ["凸台.上: cylinder d=70 h=18"], ["b2：hole d=6 at=(0,45) from=top through"]):
        assert V.is_valid({"lines": ok}), ok
    for bad in (["chamfer c=1"], ["h1:"], ["h1: # 只有名字"], ["let w = 3"], [], ["a: box 1 1 1\nb: box 2 2 2"]):
        assert not V.is_valid({"lines": bad}), bad
    assert not V.is_valid({"lines": ["a: box 1 1 1"], "x": 1})


def test_k8_local_patch_is_versioned_with_the_tool():
    m = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
    assert "registration.json" in m["tools_lock"]["covers"]                    # 随包版本走：改它 lock 就变
    assert LP["tool_id"] == "cad.build" and LP["field"] == "plan"
    for w in ("名字", "整行替换", "追加在计划末尾", "只写要改"):
        assert w in LP["description"]
    name_rx = BUILD["properties"]["plan"]["x-mengos-merge"]["name"]
    assert name_rx.split("(", 1)[1].split(")")[0] in LP["schema"]["properties"]["lines"]["items"]["pattern"]


# ───────────────────────── K9 按行合并的金样 ─────────────────────────
MERGE = json.loads((ROOT / "tests" / "fixtures" / "local" / "merge_goldens.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", MERGE, ids=[c["id"] for c in MERGE])
def test_k9_merged_patch_builds_identical_to_handwritten_plan(case):
    merged = merge(BUILD, {"plan": case["base"]}, {"plan": "\n".join(case["patch"])})["plan"]
    assert merged == case["whole"]
    a = run({"tool": "cad.build", "payload": {"plan": merged, "name": "p", "formats": []}})
    b = run({"tool": "cad.build", "payload": {"plan": case["whole"], "name": "p", "formats": []}})
    assert a["ok"], a
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)
    if case.get("stays_at"):
        assert merged.split("\n")[case["stays_at"] - 1] == case["patch"][0]
    if case.get("appended"):
        assert merged.split("\n")[-1] == case["patch"][-1]


def test_k9_merge_goldens_cover_chinese_and_dotted_names():
    pats = [l for c in MERGE for l in c["patch"]]
    assert any(any("一" <= ch <= "鿿" for ch in l.split(":")[0]) for l in pats)
    assert any("." in l.split(":")[0] for l in pats)
    assert any(c.get("stays_at") for c in MERGE) and any(c.get("appended") for c in MERGE)


# ───────────────────────── K11 声明行与零件级属性（C6）─────────────────────────
def test_k11_new_named_material_line_is_declaration_and_compare_reports_part():
    old = build(NAMED)
    new = build(NAMED + "\nmat2: material 7075")                              # 增量里写出的声明行，按 named-lines 追加在末尾
    last = new["lines"][-1]
    assert (last["name"], last["kind"], last["selectable"]) == ("mat2", "declaration", False)
    o = compare(old, new)["output"]
    assert o["part_changed"] == ["material", "density", "mass"]
    assert o["changed"] == [] and o["param_diffs"] == []


def test_k11_geometry_change_alone_does_not_list_mass():
    o = compare(build(NAMED), build(NAMED.replace("b1: hole d=10", "b1: hole d=12")))["output"]
    assert o["part_changed"] == []


def test_k11_modifier_and_copy_kinds():
    by = {x.get("name"): x["kind"] for x in build(FLANGE)["lines"]}
    assert by["fl"] == "modifier" and by["ring"] == "copy" and by["plate"] == "feature"


# ───────────────────────── K12 全局 / 局部（C7）─────────────────────────
def test_k12_scope():
    out = build("b: box 40 40 20\nk: add cylinder d=10 h=5 at=(20,20,20)\nf1: fillet r=1 edges=k\n"
                "f2: fillet r=1 edges=vertical\nc1: chamfer c=0.5 edges=bottom\ns: shell t=2 open=bottom\nf3: fillet r=0.3 edges=all")
    sc = {f["id"]: f["scope"] for f in out["features"]}
    assert sc == {"b": "local", "k": "local", "f1": "local", "f2": "global", "c1": "global", "s": "global", "f3": "global"}
    assert {x["name"]: x["scope"] for x in out["lines"]} == sc


def test_k12_fillet_without_edges_defaults_to_all_and_is_global():
    out = build("b: box 40 40 20\nf: fillet r=1")
    assert feat(out, "f")["scope"] == "global"


# ───────────────────────── K13 点中的面（C8）─────────────────────────
def test_k13_picked_face_key_matches_feature_table(tmp_path):
    out = build("s: sphere d=40\nh: hole d=10 at=center from=top through", tmp_path, ["glb"])
    g, _ = glb_json(tmp_path / "p.glb")
    seen = 0
    for n in g["nodes"]:
        ex = n.get("extras", {})
        if "faces" not in ex:
            continue
        keys = {k for k, _ in feat(out, ex["feature"])["face_digest"]}
        tri_total = 0
        for fc in ex["faces"]:
            assert fc["face_key"] in keys
            tri_total += fc["tris"][1]
            if fc["face_key"].startswith("O|"):
                assert fc["uncertain"] is True
                seen += 1
        acc = g["accessors"][g["meshes"][n["mesh"]]["primitives"][0]["indices"]]
        assert tri_total * 3 == acc["count"]                                   # 面的区间铺满这一节点的三角形
    assert seen > 0


# ───────────────────────── K14 逐行参数差（C9）─────────────────────────
def test_k14_param_diffs_only_on_changed_line_raw_values():
    o = compare(build(NAMED), build(NAMED.replace("boss: cylinder d=60", "boss: cylinder d=70")))["output"]
    assert o["param_diffs"] == [{"name": "boss", "param": "d", "before": "60", "after": "70"}]
    assert "fl" in o["followed"]


def test_k14_raw_values_positional_and_expressions():
    old = build("base: box 120 60 10\nm1: hole d=8.5 at=(20,25) from=top through\np: pattern m1 linear n=4 dx=80/3")
    new = build("base: box 150 60 10\nm1: hole d=8.5 at=(20,25) from=top through\np: pattern m1 linear n=4 dx=100/3")
    o = compare(old, new)["output"]
    assert o["param_diffs"] == [{"name": "base", "param": "arg1", "before": "120", "after": "150"},
                                {"name": "p", "param": "dx", "before": "80/3", "after": "100/3"}]


# ───────────────────────── 登记 ─────────────────────────
def test_compare_registration_is_check_and_only_takes_feature_tables():
    u = UNITS["cad.compare"]
    assert u["capability"]["ops"] == ["check"]
    assert u["capability"]["in_types"] == ["cad_feature_table"] and u["capability"]["out_types"] == ["cad_diff"]
    assert "review_coverage" not in u                                         # 普通计算件，不是审核工具
