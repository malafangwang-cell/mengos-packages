"""贡献型接入预检（17 TL-30a；设计 产出不受模型输出长度限制 r8 §五 第 5 条）。cad 2.5.0。

三项预检：① 标注合法　② base 槽唯一　③ 引擎合并金样（tests/fixtures/contribution，引擎自己的夹具逐字节拷贝，其中含 named-lines 相关条目；来源与 sha256 见 SOURCE.json）。
另有包侧自己的核对：cad.build 在贡献型判别下成立、cad.check / cad.export 仍是整体型；行名正则与计划解析器认的行名一致；
整体写法的 schema 与 2.4.4 逐键等价；分次合并出的计划与一次写成的计划交出同一份产物；注释行、空行、空行名的实际读数。
"""
import copy
import hashlib
import json
import re
from pathlib import Path

import jsonschema
import pytest

import cad_dsl
from cad_tool import run
from contribution_ref import (MergeError, base_slot_keys, canonical_json, contribution_info, empty_slots, merge,
                              skeleton, touched_keys, validate_annotations)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "contribution"
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
BUILD = UNITS["cad.build"]["signature"]["input_schema"]
CARD = json.loads((FIX / "card.json").read_text(encoding="utf-8"))["args_schema"]
SOURCE = json.loads((FIX / "SOURCE.json").read_text(encoding="utf-8"))
BASE_DESC = "上一版产物的回执节点 id（取输入材料中标 $best:true 的那条）；给出时只写改动的部分，引擎按标注合并"
# 2.4.4 的 cad.build input_schema 去掉 plan.description 后的规范 JSON sha256（取自 2.4.4 的 registration.json）
V244_BUILD_INPUT_SCHEMA_NO_PLAN_DESC_SHA256 = "5ee2cdd92afde6edf1c9a3030be15711794bb28ed31a0106b8336c9d03a17dcf"
NAME_RE = BUILD["properties"]["plan"]["x-mengos-merge"]["name"]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ───────────────────────── 夹具来源 ─────────────────────────
@pytest.mark.parametrize("name", sorted(SOURCE["files"]))
def test_fixture_sha256_matches_source_record(name):
    assert sha((FIX / name).read_bytes()) == SOURCE["files"][name]["sha256"], f"{name} 与 SOURCE.json 记录的 sha256 不符"


def test_shared_reference_implementation_matches_record():
    assert sha((ROOT / "tests" / "contribution_ref.py").read_bytes()) == SOURCE["shared_with_other_package"]["tests/contribution_ref.py"]


# ───────────────────────── 预检 ① 标注合法 ─────────────────────────
@pytest.mark.parametrize("tid", sorted(UNITS))
def test_annotations_legal_in_every_unit(tid):
    r = validate_annotations(UNITS[tid]["signature"]["input_schema"])
    assert r["ok"], r


def test_name_regex_has_exactly_one_capture_group_and_compiles():
    rx = re.compile(NAME_RE, re.ASCII)
    assert rx.groups == 1


def test_annotation_validator_rejects_illegal_forms():
    def one(node):
        return {"type": "object", "properties": {"p": node}}
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "named-lines", "name": "^h:"}}))["ok"]    # 无捕获组
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "named-lines", "name": "^(a)(b):"}}))["ok"]  # 两个捕获组
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "named-lines"}}))["ok"]                 # 缺 name
    assert not validate_annotations(one({"type": "array", "x-mengos-merge": {"mode": "named-lines", "name": "^(a):"}}))["ok"]  # 标在数组上
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "by-id"}}))["ok"]


# ───────────────────────── 预检 ② base 槽唯一 ─────────────────────────
def test_exactly_one_base_slot_on_cad_build_and_none_elsewhere():
    assert base_slot_keys(BUILD) == ["base"]
    assert base_slot_keys(UNITS["cad.check"]["signature"]["input_schema"]) == []
    assert base_slot_keys(UNITS["cad.export"]["signature"]["input_schema"]) == []


def test_base_slot_text_and_type_are_the_agreed_ones():
    assert BUILD["properties"]["base"] == {"type": "string", "x-mengos-base": True, "description": BASE_DESC}


def test_cad_build_is_contribution_tool_and_others_stay_whole():
    assert contribution_info(BUILD) == {"baseKey": "base"}
    assert contribution_info(UNITS["cad.check"]["signature"]["input_schema"]) is None
    assert contribution_info(UNITS["cad.export"]["signature"]["input_schema"]) is None


def test_check_and_export_input_schemas_have_no_contribution_vocabulary():
    for tid in ("cad.check", "cad.export"):
        assert "x-mengos" not in json.dumps(UNITS[tid]["signature"]["input_schema"])


def test_annotations_are_only_on_reachable_paths():
    for k in ("if", "then", "else"):
        assert "x-mengos" not in json.dumps(BUILD[k])


# ───────────────────────── 预检 ③ 引擎合并金样（引擎自己的夹具，逐字节拷贝） ─────────────────────────
def _fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


ALGEBRA, TOUCHED, EMPTY = _fx("merge-algebra.json"), _fx("merge-touched-keys.json"), _fx("merge-empty-slots.json")
for _f in (ALGEBRA, TOUCHED, EMPTY):
    assert _f["card"] == "card.json"          # 夹具里的 schema 指向同目录 card.json


@pytest.mark.parametrize("case", ALGEBRA["cases"], ids=[c["name"] for c in ALGEBRA["cases"]])
def test_engine_merge_algebra_golden(case):
    sch = case.get("schema", CARD)
    exp = case["expect"]
    if exp["ok"]:
        assert merge(sch, case["P"], case["delta"]) == exp["value"]
    else:
        with pytest.raises(MergeError) as ei:
            merge(sch, case["P"], case["delta"])
        assert (ei.value.instance_path, ei.value.message) == (exp["instancePath"], exp["message"])


@pytest.mark.parametrize("case", TOUCHED["cases"], ids=[c["name"] for c in TOUCHED["cases"]])
def test_engine_touched_keys_golden(case):
    assert sorted(touched_keys(CARD, case["delta"])) == case["keys"]


@pytest.mark.parametrize("case", TOUCHED["disjoint_pairs"], ids=[c["name"] for c in TOUCHED["disjoint_pairs"]])
def test_engine_disjoint_pairs_golden(case):
    inter = touched_keys(CARD, case["a"]) & touched_keys(CARD, case["b"])
    assert (not inter) == case["disjoint"]


@pytest.mark.parametrize("case", EMPTY["cases"], ids=[c["name"] for c in EMPTY["cases"]])
def test_engine_empty_slots_golden(case):
    assert empty_slots(CARD, case["args"]) == case["slots"]


def test_engine_fixtures_cover_named_lines_cases():
    assert any("named-lines" in c["name"] for c in ALGEBRA["cases"]) and any("named-lines" in c["name"] for c in EMPTY["cases"])


# ───────────────────────── 整体写法不变 ─────────────────────────
def _strip(node):
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("x-mengos-merge", "x-mengos-base")}
    if isinstance(node, list):
        return [_strip(x) for x in node]
    return node


def test_whole_mode_schema_equals_2_4_4_schema():
    """不带 base 时走 else 分支：去掉标注与 base 槽、把 else 的 required 叠回主体，再去掉 plan 的说明文字
    （build 的说明多了分次写的约定），应与 2.4.4 的 cad.build input_schema 逐键相同。"""
    s = _strip(copy.deepcopy(BUILD))
    for k in ("if", "then"):
        s.pop(k)
    s["required"] = s.pop("else")["required"]
    s["properties"].pop("base")
    plan_desc = s["properties"]["plan"].pop("description")
    assert plan_desc.startswith(UNITS["cad.check"]["signature"]["input_schema"]["properties"]["plan"]["description"])   # 原说明原样在前
    assert sha(canonical_json(s).encode()) == V244_BUILD_INPUT_SCHEMA_NO_PLAN_DESC_SHA256


def test_whole_mode_still_requires_plan_and_delta_does_not():
    V = jsonschema.Draft202012Validator(BUILD)
    assert V.is_valid({"plan": "base: box 80 50 20"})
    assert not V.is_valid({"name": "x"})                                   # 整体写法缺 plan
    assert not V.is_valid({"formats": ["step"]})
    assert V.is_valid({"base": "v-0003", "plan": "h2: hole d=6 at=center from=top through"})
    assert V.is_valid({"base": "v-0003"})
    assert not V.is_valid({"base": 3, "plan": "x: box 1 1 1"})              # base 是字符串
    assert not V.is_valid({"base": "v-0003", "bogus": 1})                   # 顶层仍不收未知键


# ───────────────────────── 行名正则与计划解析器一致 ─────────────────────────
def _plans():
    out = [(p.name, p.read_text(encoding="utf-8")) for p in sorted((ROOT / "samples").glob("*.cad"))]
    for c in json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8")):
        if "plan" in c["payload"] and isinstance(c["payload"]["plan"], str):
            out.append((c["id"], c["payload"]["plan"]))
    return out


def _parser_name(line):
    """用包自己的计划解析器读这一行：带名字就返回名字，否则 None；读不通的行（金样里的坏计划）返回 'ERR'。"""
    try:
        st = cad_dsl.parse(line)
    except cad_dsl.DslError:
        return "ERR"
    return st[0].name if st else None


def test_name_regex_agrees_with_plan_parser_on_every_line_of_samples_and_goldens():
    rx = re.compile(NAME_RE, re.ASCII)
    n_named = n_unnamed = 0
    for src, plan in _plans():
        for raw in plan.splitlines():
            code = raw.split("#", 1)[0].strip()
            if not code or code.lower().startswith("let "):
                continue
            pn = _parser_name(raw)
            if pn == "ERR":
                continue
            m = rx.search(raw)
            got = None if m is None else m.group(1)
            # 解析器会先把全角冒号等转半角；正则里也认全角冒号。统一以解析器的读法为准
            assert got == pn, (src, raw, got, pn)
            n_named += pn is not None
            n_unnamed += pn is None
    assert n_named > 20 and n_unnamed > 5          # 样例与金样里两类行都有足够多


@pytest.mark.parametrize("line,name", [
    ("base: box 80 50 20", "base"), ("  h1 : hole d=8 at=center from=top through", "h1"),
    ("base： box 80 50 20", "base"), ("底座.一: box 80 50 20", "底座.一"), ("_x9: box 1 1 1", "_x9")])
def test_name_regex_reads_names_the_way_the_parser_does(line, name):
    assert re.compile(NAME_RE, re.ASCII).search(line).group(1) == name
    assert _parser_name(line) == name


@pytest.mark.parametrize("line", [
    "material 6061-T6", "let t = 10", "fillet r=2 edges=all", "chamfer c=0.5 edges=h1", "pattern m1 linear n=4 dx=20",
    "# 注释: 带冒号", "", "   ", "units mm"])
def test_name_regex_does_not_match_unnamed_lines(line):
    assert re.compile(NAME_RE, re.ASCII).search(line) is None


# ───────────────────────── 工具对注释行、空行、空行名的读数 ─────────────────────────
def _build(plan, tmp_path, name="w"):
    w = tmp_path / name
    w.mkdir()
    return run({"tool": "cad.build", "payload": {"plan": plan, "formats": []}, "workdir": str(w)})


def test_comment_lines_blank_lines_and_fullwidth_colon_are_accepted(tmp_path):
    """读数：# 注释行、行尾注释、空行、全角冒号的行名都 ok。"""
    assert _build("# 注释一\nbase: box 80 50 20\n   # 缩进注释\nh1: hole d=20 at=center from=top through # 行尾注释", tmp_path, "a")["ok"]
    assert _build("base: box 80 50 20\n\n   \nh1: hole d=20 at=center from=top through\n\n", tmp_path, "b")["ok"]
    assert _build("base: box 80 50 20\n# 只是注释", tmp_path, "c")["ok"]
    assert _build("base： box 80 50 20", tmp_path, "d")["ok"]


def test_name_only_line_is_rejected_by_the_tool(tmp_path):
    """读数：只有名字、没有操作的行（空行名）被拒，BAD_INPUT「缺少操作名」。所以包的约定是不留空行名，
    cad 没有"空槽中间版本"：只无定向，不影响合并与运行。"""
    for i, plan in enumerate(("base: box 80 50 20\nh1:", "base: box 80 50 20\nh1:\nh2: hole d=10 at=center from=top through")):
        r = _build(plan, tmp_path, f"e{i}")
        assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and "缺少操作名" in r["error"]["message"]
        assert r["error"]["line"] == 2


def test_duplicate_name_is_rejected_which_is_why_merge_replaces_by_name(tmp_path):
    r = _build("base: box 80 50 20\nbase: box 10 10 10", tmp_path)
    assert not r["ok"] and "已经用过" in r["error"]["message"]


def test_unnamed_lines_repeat_harmlessly(tmp_path):
    assert _build("material 6061-T6\nmaterial 7075\nbase: box 80 50 20", tmp_path, "m")["ok"]
    assert _build("let t = 10\nbase: box 80 50 t\nlet t = 20\nw: add box 10 10 t at=(0,0,20)", tmp_path, "l")["ok"]


# ───────────────────────── 分次合并 = 一次写成 ─────────────────────────
WHOLE = "\n".join([
    "# L 形支架",
    "material 6061-T6",
    "let t = 10",
    "base: box 120 60 t",
    "wall: add box 120 t 50 at=(0,50,0)",
    "m1: hole d=8.5 at=(20,25) from=top through cbore=(14,5)",
    "pattern m1 linear n=4 dx=80/3",
    "s1: slot w=8 l=24 at=(60,32) from=back through",
    "chamfer c=0.5 edges=m1",
])
FIRST = "\n".join([
    "# L 形支架",
    "material 6061-T6",
    "let t = 10",
    "base: box 120 60 t",
])


def _M(P, D):
    return merge(BUILD, {"plan": P}, {"plan": D})["plan"]


def test_incremental_contributions_merge_to_the_whole_plan(tmp_path):
    deltas = [
        "wall: add box 120 t 50 at=(0,50,0)",
        "m1: hole d=8.5 at=(20,25) from=top through cbore=(14,5)\npattern m1 linear n=4 dx=80/3",
        "s1: slot w=8 l=24 at=(60,32) from=back through\nchamfer c=0.5 edges=m1",
    ]
    P = FIRST
    for d in deltas:
        P = _M(P, d)
    assert P == WHOLE
    whole = _build(WHOLE, tmp_path, "whole")
    inc = _build(P, tmp_path, "inc")
    assert whole["ok"] and inc["ok"] and whole["output"] == inc["output"]      # plan_sha256、测量值、特征表全相同


def test_replacing_a_named_line_keeps_its_position_and_rebuilds(tmp_path):
    P = _M(WHOLE, "base: box 150 60 t")
    lines = P.split("\n")
    assert lines.index("base: box 150 60 t") == WHOLE.split("\n").index("base: box 120 60 t")
    assert len(lines) == len(WHOLE.split("\n"))
    r = _build(P, tmp_path)
    assert r["ok"] and r["output"]["plan_sha256"] != _build(WHOLE, tmp_path, "w0")["output"]["plan_sha256"]


def test_unnamed_lines_are_appended_not_replaced():
    P = _M(WHOLE, "chamfer c=0.5 edges=m1")
    assert P.split("\n").count("chamfer c=0.5 edges=m1") == 2 and P.endswith("chamfer c=0.5 edges=m1")
    P2 = _M(WHOLE, "# 新注释\n\nlet k = 3")
    assert P2.split("\n")[-3:] == ["# 新注释", "", "let k = 3"]


def test_touched_keys_of_plan_deltas():
    def K(d):
        return touched_keys(BUILD, {"plan": d})
    assert K("m1: hole d=8.5 at=center from=top through") == {"plan@m1"}
    assert K("a: box 1 1 1\nb: box 2 2 2") == {"plan@a", "plan@b"}
    assert K("fillet r=2 edges=all\n# 注") == {"plan@+"}
    assert not (K("m1: hole d=8.5 at=center from=top through") & K("s1: slot w=8 l=24 at=(60,32) from=back through"))
    assert K("m1: hole d=8.5 at=center from=top through") & K("m1: hole d=9 at=center from=top through") == {"plan@m1"}
    assert K("chamfer c=1 edges=all") & K("fillet r=2 edges=all") == {"plan@+"}     # 两件都追加不带名字的行 ⟹ 相交


def test_skeleton_of_plan_lists_names_and_flags_name_only_lines():
    sk = json.loads(skeleton(BUILD, {"plan": "base: box 120 60 10\nh1:\nfillet r=2 edges=all"}, True))
    assert sk["plan"] == [{"empty": False, "name": "base"}, {"empty": True, "name": "h1"}]
    assert "box" not in json.dumps(sk)
    assert empty_slots(BUILD, {"plan": "base: box 120 60 10\nh1:"}) == ["plan@h1"]
