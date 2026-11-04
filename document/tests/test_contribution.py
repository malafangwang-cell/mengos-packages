"""贡献型接入预检（17 TL-30a；设计 产出不受模型输出长度限制 r8 §五 第 5 条）。2.0.0。

三项预检：① 标注合法　② base 槽唯一　③ 引擎合并金样（tests/fixtures/contribution，来源与 sha256 见 SOURCE.json）。
另有包侧自己的核对：doc.build 在贡献型判别下成立；整体写法（不带 base）的 schema 与 1.2.5 相比只多节 id 必填一处（另有 doc 说明文字两处随之改写）；
带 base 的增量能被 schema 接受；空槽的中间版本能被工具接受；分次合并出的文档与一次写成的文档交出同一份产物。
"""
import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

import doc_tool
from contribution_ref import (MergeError, base_slot_keys, canonical_json, contribution_info, empty_slots, merge,
                              skeleton, touched_keys, validate_annotations)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "contribution"
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
BUILD = UNITS["doc.build"]["signature"]["input_schema"]
CARD = json.loads((FIX / "card.json").read_text(encoding="utf-8"))["args_schema"]
GOLD = json.loads((FIX / "merge_golden.json").read_text(encoding="utf-8"))
SOURCE = json.loads((FIX / "SOURCE.json").read_text(encoding="utf-8"))
BASE_DESC = "上一版产物的回执节点 id（取输入材料中标 $best:true 的那条）；给出时只写改动的部分，引擎按标注合并"
# 1.2.5 的 doc.build input_schema 的规范 JSON（键升序、无空白）的 sha256，取自 1.2.5 的 registration.json
V125_BUILD_INPUT_SCHEMA_SHA256 = "3c73a32f03b290a1e255638f675ff8fd1a51b255646429176dda62c522287a1c"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ───────────────────────── 夹具来源 ─────────────────────────
@pytest.mark.parametrize("name", sorted(SOURCE["files"]))
def test_fixture_sha256_matches_source_record(name):
    assert sha((FIX / name).read_bytes()) == SOURCE["files"][name]["sha256"], f"{name} 与 SOURCE.json 记录的 sha256 不符"


# ───────────────────────── 预检 ① 标注合法 ─────────────────────────
@pytest.mark.parametrize("tid", sorted(UNITS))
def test_annotations_legal_in_every_unit(tid):
    r = validate_annotations(UNITS[tid]["signature"]["input_schema"])
    assert r["ok"], r


def test_annotation_validator_rejects_illegal_forms():
    """参照实现自己要能判非法（取自引擎 U3 与 TL-30a 条文），否则 ① 形同虚设。"""
    def one(node):
        return {"type": "object", "properties": {"p": node}}
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "named-lines", "name": "^h:"}}))["ok"]
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "by-id"}}))["ok"]
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "append"}}))["ok"]
    assert not validate_annotations(one({"type": "array", "x-mengos-merge": {"mode": "weird"}}))["ok"]
    assert not validate_annotations(one({"type": "array", "x-mengos-merge": [{"mode": "append"}, {"mode": "by-id"}]}))["ok"]
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "named-lines", "name": "(["}}))["ok"]
    assert validate_annotations(one({"type": "array", "x-mengos-merge": {"mode": "append"}}))["ok"]


# ───────────────────────── 预检 ② base 槽唯一 ─────────────────────────
def test_exactly_one_base_slot_on_doc_build_and_none_elsewhere():
    assert base_slot_keys(BUILD) == ["base"]
    assert base_slot_keys(UNITS["doc.check"]["signature"]["input_schema"]) == []
    assert base_slot_keys(UNITS["doc.export"]["signature"]["input_schema"]) == []


def test_base_slot_text_and_type_are_the_agreed_ones():
    assert BUILD["properties"]["base"] == {"type": "string", "x-mengos-base": True, "description": BASE_DESC}


def test_doc_build_is_contribution_tool_and_others_stay_whole():
    assert contribution_info(BUILD) == {"baseKey": "base"}
    assert contribution_info(UNITS["doc.check"]["signature"]["input_schema"]) is None
    assert contribution_info(UNITS["doc.export"]["signature"]["input_schema"]) is None


def test_annotation_declarations_on_doc_build():
    doc = BUILD["properties"]["doc"]["properties"]
    assert doc["sections"]["x-mengos-merge"] == {"mode": "by-id", "id": "id", "label": "heading", "fill": "body"}
    assert doc["tables"]["x-mengos-merge"] == {"mode": "by-id", "id": "id", "label": "caption"}
    assert doc["tables"]["items"]["properties"]["rows"]["x-mengos-merge"] == {"mode": "append"}
    assert doc["figures"]["x-mengos-merge"] == {"mode": "by-id", "id": "id", "label": "caption"}
    assert doc["requirements"]["x-mengos-merge"] == {"mode": "by-id", "id": "id", "label": "text"}


def test_annotations_are_only_on_reachable_paths():
    """引擎只认可达路径（不进 if/then/else、oneOf 等）：if/then/else 里不得有标注，否则白写。"""
    for k in ("if", "then", "else"):
        assert "x-mengos-merge" not in json.dumps(BUILD[k]) and "x-mengos-base" not in json.dumps(BUILD[k])


# ───────────────────────── 预检 ③ 引擎合并金样 ─────────────────────────
def _schema_of(case):
    return GOLD["named_schema"] if case.get("schema") == "named" else CARD


@pytest.mark.parametrize("case", GOLD["cases"], ids=[c["id"] for c in GOLD["cases"]])
def test_engine_merge_golden(case):
    sch = _schema_of(case)
    kind = case["kind"]
    if kind == "merge":
        if "expect_error" in case:
            with pytest.raises(MergeError) as ei:
                merge(sch, case["P"], case["delta"])
            for k, v in case["expect_error"].items():
                assert getattr(ei.value, "instance_path" if k == "instancePath" else k) == v
        else:
            assert merge(sch, case["P"], case["delta"]) == case["expect"]
    elif kind == "touched":
        assert sorted(touched_keys(sch, case["delta"])) == sorted(case["expect"])
    elif kind == "empty":
        assert empty_slots(sch, case["args"]) == case["expect"]
    elif kind == "empty-after-merge":
        assert empty_slots(sch, merge(sch, case["args"], case["delta"])) == case["expect"]
    else:
        raise AssertionError(kind)


def test_engine_merge_does_not_mutate_inputs():
    P = {"name": "n", "doc": {"sections": [{"id": "s1", "heading": "h"}]}}
    D = {"doc": {"sections": [{"id": "s1", "body": "b"}]}}
    P0, D0 = copy.deepcopy(P), copy.deepcopy(D)
    merge(CARD, P, D)
    assert P == P0 and D == D0


def test_engine_skeleton_golden():
    g = json.loads((FIX / "skeleton-doc.json").read_text(encoding="utf-8"))
    assert skeleton(CARD, g["args"], True) == g["expected_best"]
    assert skeleton(CARD, g["args"], False) == g["expected_not_best"]


def test_golden_card_itself_passes_the_checks():
    assert validate_annotations(CARD)["ok"] and contribution_info(CARD) == {"baseKey": "base"}


# ───────────────────────── 整体写法不变 ─────────────────────────
def _strip(node):
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("x-mengos-merge", "x-mengos-base")}
    if isinstance(node, list):
        return [_strip(x) for x in node]
    return node


def _overlay(base, extra):
    """把 else 分支的约束叠回主体：required 取 else 的，properties / items 逐层叠。"""
    for k, v in extra.items():
        if k == "required":
            base["required"] = list(base.get("required", [])) + [x for x in v if x not in base.get("required", [])]
        else:   # properties / items：逐层叠
            if k == "properties":
                for pk, pv in v.items():
                    _overlay(base[k][pk], pv)
            else:
                _overlay(base[k], v)


def _fold_whole_mode(schema):
    s = _strip(copy.deepcopy(schema))
    for k in ("if", "then"):
        s.pop(k)
    els = s.pop("else")
    s["properties"].pop("base")
    _overlay(s, els)
    return s


def test_whole_mode_schema_equals_1_2_5_schema_plus_section_id():
    """不带 base 时走 else 分支：去掉标注与 base 槽、把 else 叠回主体，再去掉节 id 必填这唯一一处新增，
    应与 1.2.5 的 doc.build input_schema 逐键相同（含 by-id 元素内嵌套的必填）。"""
    folded = _fold_whole_mode(BUILD)
    sec = folded["properties"]["doc"]["properties"]["sections"]["items"]
    assert sec["required"] == ["id", "heading"]
    sec["required"].remove("id")
    # doc 的说明文字有两处有意的改动：节 id 由"可选"改"必填"；不再宣称接受不带 id 的简写。还原这两处再比。
    doc = folded["properties"]["doc"]
    assert "id（必填，供引用和后续修改时定位）" in doc["description"] and "简单写法" not in doc["description"]
    doc["description"] = (doc["description"].replace("id（必填，供引用和后续修改时定位）", "id（可选，供引用和后续修改时定位）")
                          + "也接受只有 {title, sections:[{heading, body}]} 的简单写法。")
    assert sha(canonical_json(folded).encode()) == V125_BUILD_INPUT_SCHEMA_SHA256


def test_element_id_is_required_always_outside_the_branches():
    """四个 by-id 容器的元素 id 恒必填：写在 if/then/else 之外，整体写法与增量都生效。"""
    props = BUILD["properties"]["doc"]["properties"]
    for field in ("sections", "tables", "figures", "requirements"):
        assert "id" in props[field]["items"]["required"], field
    assert "id" not in json.dumps(BUILD["then"]) and BUILD["then"] == {"required": ["base"]}
    assert BUILD["properties"]["doc"].get("required") is None and "required" not in BUILD


def test_doc_check_and_export_input_schemas_have_no_contribution_vocabulary():
    for tid in ("doc.check", "doc.export"):
        assert "x-mengos" not in json.dumps(UNITS[tid]["signature"]["input_schema"])


def test_whole_mode_requires_section_id_and_the_original_fields():
    V = jsonschema.Draft202012Validator(BUILD)
    assert V.is_valid({"doc": {"title": "T", "sections": [{"id": "a", "heading": "A", "body": "x"}]}})
    assert not V.is_valid({"doc": {"title": "T", "sections": [{"heading": "A", "body": "x"}]}})          # 2.0.0：节缺 id 拒收
    assert not V.is_valid({"doc": {"sections": [{"id": "a", "heading": "A"}]}})                          # 缺 title
    assert not V.is_valid({"doc": {"title": "T", "sections": [{"id": "a", "body": "x"}]}})               # 节缺 heading
    assert not V.is_valid({"name": "x"})                                                                 # 缺 doc
    assert not V.is_valid({"doc": {"title": "T", "sections": [{"id": "a", "heading": "A"}],
                                   "tables": [{"id": "t1", "caption": "c"}]}})                           # 表缺 columns / rows


# ───────────────────────── 带 base 的增量 ─────────────────────────
def test_delta_with_base_is_accepted_and_elements_need_ids():
    V = jsonschema.Draft202012Validator(BUILD)
    assert V.is_valid({"base": "v-0007", "doc": {"sections": [{"id": "s2", "body": "新写的正文"}]}})
    assert V.is_valid({"base": "v-0007", "doc": {"tables": [{"id": "t1", "rows": [["周三", "李四"]]}]}})
    assert V.is_valid({"base": "v-0007", "doc": {"title": "改个标题"}})
    assert V.is_valid({"base": "v-0007"})
    assert not V.is_valid({"base": "v-0007", "doc": {"sections": [{"body": "没有 id"}]}})              # by-id 元素 id 恒必填
    assert not V.is_valid({"base": "v-0007", "doc": {"figures": [{"caption": "没有 id"}]}})
    assert not V.is_valid({"base": "v-0007", "bogus": 1})                                             # 顶层仍不收未知键
    assert not V.is_valid({"base": 7, "doc": {}})                                                     # base 是字符串


def test_delta_without_base_gets_no_relaxation():
    V = jsonschema.Draft202012Validator(BUILD)
    assert not V.is_valid({"doc": {"sections": [{"id": "s2", "body": "只有增量"}]}})
    assert not V.is_valid({"doc": {"title": "只改标题"}})


# ───────────────────────── 空槽的中间版本 ─────────────────────────
def _run(tool, payload, tmp_path, name="w"):
    w = tmp_path / name
    w.mkdir()
    return doc_tool.run({"tool": tool, "payload": payload, "workdir": str(w)})


def test_empty_or_absent_body_is_accepted_not_bad_input(tmp_path):
    """TL-30a 接入第 3 条：fill 缺席或空串不报 BAD_INPUT。读数：空串、纯空白、缺席三种都 ok，只出 empty_section 警告。"""
    for i, extra in enumerate(({"body": ""}, {"body": "   "}, {})):
        d = {"title": "T", "sections": [{"id": "s1", "heading": "概述", "body": "本方案。"}, {"id": "s2", "heading": "开放安排", **extra}]}
        jsonschema.validate({"doc": d}, BUILD)
        r = _run("doc.build", {"doc": d}, tmp_path, f"e{i}")
        assert r["ok"], r
        assert [w["code"] for w in r["output"]["warnings"]] == ["empty_section"]
        assert r["output"]["warnings"][0]["where"] == "sections[1]"


# ───────────────────────── 分次合并 = 一次写成 ─────────────────────────
WHOLE = {
    "title": "社区读书角运营方案",
    "meta": {"org": "城东街道", "date": "2026-10-03"},
    "requirements": [{"id": "r1", "text": "给出预算明细", "source": "街道任务书 第 2 条"}],
    "sections": [
        {"id": "bg", "heading": "背景", "body": "居民希望有安静的阅读空间，预算见[[sec:budget]]。"},
        {"id": "open", "heading": "开放安排", "body": "每周开放六天，每天四班。"},
        {"id": "budget", "heading": "预算", "body": "一次性投入约 5000 元，明细见[[tab:t1]]。\n\n[[tab:t1]]", "responds_to": ["r1"]},
    ],
    "tables": [{"id": "t1", "caption": "预算明细", "columns": ["项目", "金额（元）"],
                "rows": [["书架与桌椅", "1,200"], ["首批图书", "3,800"]]}],
}


def _first_version():
    """第一版：标题、各节标题、要求与表的框架已给出，正文空槽，表的行数据还没写。"""
    d = copy.deepcopy(WHOLE)
    for s in d["sections"]:
        s["body"] = ""
    d["tables"][0]["rows"] = []
    return {"doc": d}


def test_incremental_contributions_merge_to_the_whole_document(tmp_path):
    P = _first_version()
    jsonschema.validate(P, BUILD)                      # 第一版（带空槽）是合法的整体写法
    assert empty_slots(BUILD, P) == ["doc.sections#bg", "doc.sections#open", "doc.sections#budget"]
    r = _run("doc.build", P, tmp_path, "v0")
    assert r["ok"] and {w["code"] for w in r["output"]["warnings"]} >= {"empty_section"}

    deltas = [
        {"base": "v-1", "doc": {"sections": [{"id": "bg", "body": WHOLE["sections"][0]["body"]}]}},
        {"base": "v-1", "doc": {"sections": [{"id": "open", "body": WHOLE["sections"][1]["body"]}]}},
        {"base": "v-1", "doc": {"sections": [{"id": "budget", "body": WHOLE["sections"][2]["body"], "responds_to": ["r1"]}]}},
        {"base": "v-1", "doc": {"tables": [{"id": "t1", "rows": WHOLE["tables"][0]["rows"]}]}},
    ]
    # 同批四件的触及键两两不相交 ⟹ 引擎会合并成一次派单
    keys = [touched_keys(BUILD, {k: v for k, v in d.items() if k != "base"}) for d in deltas]
    assert all(not (a & b) for i, a in enumerate(keys) for b in keys[i + 1:]), keys
    merged = P
    for d in deltas:
        delta = {k: v for k, v in d.items() if k != "base"}
        merged = merge(BUILD, merged, delta)
        jsonschema.validate(merged, BUILD)             # 每一步合并结果都过整体写法的 schema（引擎 PD-1 校验的就是它）
    assert merged == {"doc": WHOLE}
    assert empty_slots(BUILD, merged) == []

    whole = _run("doc.build", {"doc": WHOLE}, tmp_path, "whole")
    inc = _run("doc.build", merged, tmp_path, "inc")
    assert whole["ok"] and inc["ok"]
    assert whole["output"] == inc["output"]            # 同一份文档模型：doc_sha256、统计、目录、警告全相同
    for fw, fi in zip(whole["output"]["files"], inc["output"]["files"]):
        assert (tmp_path / "whole" / fw["path"]).read_bytes() == (tmp_path / "inc" / fi["path"]).read_bytes()


def test_overlapping_deltas_are_detected_by_touched_keys():
    a = touched_keys(BUILD, {"doc": {"sections": [{"id": "bg", "body": "甲"}]}})
    b = touched_keys(BUILD, {"doc": {"sections": [{"id": "bg", "body": "乙"}]}})
    c = touched_keys(BUILD, {"doc": {"tables": [{"id": "t1", "rows": [["x", "1"]]}]}})
    d = touched_keys(BUILD, {"doc": {"tables": [{"id": "t1", "rows": [["y", "2"]]}]}})
    e = touched_keys(BUILD, {"doc": {"tables": [{"id": "t1", "caption": "新题注"}]}})
    assert a & b == {"doc.sections#bg.body"}
    assert c & d == {"doc.tables#t1.rows+"}
    assert not (c & e)


def test_skeleton_of_doc_build_first_version_names_the_empty_slots():
    sk = json.loads(skeleton(BUILD, _first_version(), True))
    assert sk["$best"] is True
    assert [(s["id"], s["label"], s["empty"]) for s in sk["doc"]["sections"]] == [
        ("bg", "背景", True), ("open", "开放安排", True), ("budget", "预算", True)]
    assert sk["doc"]["tables"] == [{"id": "t1", "label": "预算明细", "rows": {"$count": 0}}]
    assert "居民" not in json.dumps(sk, ensure_ascii=False)       # 骨架里没有正文
