"""贡献型接入预检与 2.0.0 契约（17 TL-30a；设计 产出不受模型输出长度限制 r8 §五；执行令-2026-11-05-table包2.0.0 T1–T9）。

三项预检：① 标注合法　② base 槽唯一　③ 引擎合并金样（tests/fixtures/contribution，引擎自己的夹具逐字节拷贝，来源与 sha256 见 SOURCE.json）。
包侧自己的核对（编号对令文用例）：
  TB-5 表专属合并金样（tests/fixtures/table-merge-cases.json）：每例合并后过 schema、再走一遍 table.build；sheet 缺 id ⟹ 合并报错；
  TB-6 整体写法（不带 base）：schema 与 1.0.1 只差 sheet id 必填与说明文字；合规输入的产出与 1.0.1 逐字节相同（金样在 1.0.1 代码上录）；
  TB-7 被公式或合计引用的列缺 type ⟹ BAD_INPUT 点名列；零行、rows 缺席、sheet 无行（有 type）⟹ ok 加 no_rows 警告；
  TB-8 数组行格数不符 ⟹ BAD_INPUT，报错带行号与期望、实际格数，不补 null；
  TB-9 table.check、table.export 的 schema 不含贡献词汇，与 1.0.1 逐键同；接受缺 id 的旧表对象。
"""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

import table_tool
from contribution_ref import (MergeError, base_slot_keys, canonical_json, contribution_info, empty_slots, merge,
                              skeleton, touched_keys, validate_annotations)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
CFIX = FIX / "contribution"
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
BUILD = UNITS["table.build"]["signature"]["input_schema"]
CHECK = UNITS["table.check"]["signature"]["input_schema"]
EXPORT = UNITS["table.export"]["signature"]["input_schema"]
CARD = json.loads((CFIX / "card.json").read_text(encoding="utf-8"))["args_schema"]
SOURCE = json.loads((CFIX / "SOURCE.json").read_text(encoding="utf-8"))
BASE_DESC = "上一版产物的回执节点 id（取输入材料中标 $best:true 的那条）；给出时只写改动的部分，引擎按标注合并"
# 1.0.1 registration.json 里各件 input_schema 的规范 JSON（键升序、无空白）的 sha256，取自 table-1.0.1.zip
V101_BUILD_NO_TABLE_DESC_SHA256 = "4eae9de6c56925cc22c58b15fe82d51f5d467fbed4d2b90b9a42d58547390389"   # 去掉 table.description 后
V101_CHECK_SHA256 = "128fe353b39f77444ebe227e3241c9bdda82f6bfdf10a128d86f3b391fbbb5d1"
V101_EXPORT_SHA256 = "5a75834a179935490070d135d506019e2b398a88bd636159a42f8186c10b68de"
VB = jsonschema.Draft202012Validator(BUILD)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run(tool, payload, tmp_path, name="w"):
    w = tmp_path / name
    w.mkdir()
    return table_tool.run({"tool": tool, "payload": payload, "workdir": str(w)})


# ───────────────────────── 夹具来源 ─────────────────────────
@pytest.mark.parametrize("name", sorted(SOURCE["files"]))
def test_fixture_sha256_matches_source_record(name):
    assert sha((CFIX / name).read_bytes()) == SOURCE["files"][name]["sha256"], f"{name} 与 SOURCE.json 记录的 sha256 不符"


def test_contribution_ref_is_the_shared_copy():
    assert sha((ROOT / "tests" / "contribution_ref.py").read_bytes()) == SOURCE["shared_with_other_package"]["tests/contribution_ref.py"]


# ───────────────────────── 预检 ① 标注合法 ─────────────────────────
@pytest.mark.parametrize("tid", sorted(UNITS))
def test_annotations_legal_in_every_unit(tid):
    r = validate_annotations(UNITS[tid]["signature"]["input_schema"])
    assert r["ok"], r


def test_annotation_validator_rejects_illegal_forms():
    """参照实现自己要能判非法，否则 ① 形同虚设。"""
    def one(node):
        return {"type": "object", "properties": {"p": node}}
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "by-id"}}))["ok"]
    assert not validate_annotations(one({"type": "string", "x-mengos-merge": {"mode": "append"}}))["ok"]
    assert not validate_annotations(one({"type": "array", "x-mengos-merge": {"mode": "weird"}}))["ok"]
    assert not validate_annotations(one({"type": "array", "x-mengos-merge": [{"mode": "append"}, {"mode": "by-id"}]}))["ok"]
    assert validate_annotations(one({"type": "array", "x-mengos-merge": {"mode": "append"}}))["ok"]


# ───────────────────────── 预检 ② base 槽唯一 ─────────────────────────
def test_exactly_one_base_slot_on_table_build_and_none_elsewhere():
    assert base_slot_keys(BUILD) == ["base"]
    assert base_slot_keys(CHECK) == [] and base_slot_keys(EXPORT) == []


def test_base_slot_text_and_type_are_the_agreed_ones():
    assert BUILD["properties"]["base"] == {"type": "string", "x-mengos-base": True, "description": BASE_DESC}


def test_table_build_is_contribution_tool_and_others_stay_whole():
    assert contribution_info(BUILD) == {"baseKey": "base"}
    assert contribution_info(CHECK) is None and contribution_info(EXPORT) is None


def test_annotation_declarations_on_table_build():
    t = BUILD["properties"]["table"]["properties"]
    assert t["sheets"]["x-mengos-merge"] == {"mode": "by-id", "id": "id", "label": "name"}   # 不设 fill（补裁三），与 doc.tables 同形
    assert t["sheets"]["items"]["properties"]["rows"]["x-mengos-merge"] == {"mode": "append"}
    assert t["rows"]["x-mengos-merge"] == {"mode": "append"}
    # rows 仍是数据字段（1.0.1 起），与 append 并存
    assert t["rows"]["x-mengos-data"] is True and t["sheets"]["items"]["properties"]["rows"]["x-mengos-data"] is True
    # columns 不标：新值整体覆盖
    assert "x-mengos-merge" not in t["columns"] and "x-mengos-merge" not in t["sheets"]["items"]["properties"]["columns"]


def test_annotations_are_only_on_reachable_paths():
    """引擎只认可达路径（不进 if/then/else、oneOf）：分支里不得有标注。"""
    for k in ("if", "then", "else"):
        assert "x-mengos-merge" not in json.dumps(BUILD[k]) and "x-mengos-base" not in json.dumps(BUILD[k])


# ───────────────────────── 预检 ③ 引擎合并金样（引擎自己的夹具，逐字节拷贝） ─────────────────────────
def _fx(name):
    return json.loads((CFIX / name).read_text(encoding="utf-8"))


ALGEBRA, TOUCHED, EMPTY = _fx("merge-algebra.json"), _fx("merge-touched-keys.json"), _fx("merge-empty-slots.json")
for _f in (ALGEBRA, TOUCHED, EMPTY):
    assert _f["card"] == "card.json"


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


def test_engine_skeleton_golden():
    g = _fx("skeleton-doc.json")
    assert skeleton(CARD, g["args"], True) == g["expected_best"]
    assert skeleton(CARD, g["args"], False) == g["expected_not_best"]


ROWS_DATA = _fx("merge-table-rows-data.json")


def _ptr(doc, pointer):
    for seg in pointer.split("/")[1:]:
        doc = doc[int(seg)] if isinstance(doc, list) else doc[seg]
    return doc


@pytest.mark.parametrize("case", ROWS_DATA["cases"], ids=[c["name"] for c in ROWS_DATA["cases"]])
def test_engine_table_rows_data_golden(case):
    """引擎夹具 merge-table-rows-data（P1 TB-1）：rows 上 x-mengos-data 与 append 并存。按夹具自带的 schema 跑。"""
    sch, P, D, exp = case["schema"], case["P"], case["delta"], case["expect"]
    assert merge(sch, P, D) == exp["value"]
    assert sorted(touched_keys(sch, D)) == exp["keys"]
    assert skeleton(sch, P, True) == exp["skeleton_P"]
    assert skeleton(sch, exp["value"], True) == exp["skeleton_merged"]
    # 证件账定位：append 元素 ↦ P 的长度 + 增量内下标，两处取到的是同一个值
    src, dst = exp["remap"]["path"], exp["remap"]["merged_path"]
    i, j = int(src.split("/")[3]), int(dst.split("/")[3])
    assert j == len(P["table"]["rows"]) + i
    assert _ptr(D, src) == _ptr(exp["value"], dst)


@pytest.mark.parametrize("case", ROWS_DATA["cases"], ids=[c["name"] for c in ROWS_DATA["cases"]])
def test_table_rows_data_golden_under_the_real_build_schema(case, tmp_path):
    """同一 P、Δ 换成本包 table.build 的真实 schema：合并、触及键、骨架与夹具期望相同，合并结果交 build 可用。"""
    P, D, exp = case["P"], case["delta"], case["expect"]
    assert VB.is_valid(P) and VB.is_valid({"base": "v-1", **D})
    merged = merge(BUILD, P, D)
    assert merged == exp["value"]
    assert sorted(touched_keys(BUILD, D)) == exp["keys"]
    assert skeleton(BUILD, P, True) == exp["skeleton_P"]
    assert skeleton(BUILD, merged, True) == exp["skeleton_merged"]
    jsonschema.validate(merged, BUILD)
    r = run("table.build", merged, tmp_path)
    assert r["ok"] and r["output"]["sheets"][0]["rows"] == len(exp["value"]["table"]["rows"]), r


def test_engine_merge_does_not_mutate_inputs():
    P = {"table": {"title": "T", "sheets": [{"id": "s1", "columns": ["a"], "rows": [["x"]]}]}}
    D = {"table": {"sheets": [{"id": "s1", "rows": [["y"]]}]}}
    P0, D0 = copy.deepcopy(P), copy.deepcopy(D)
    merge(BUILD, P, D)
    assert P == P0 and D == D0


def test_golden_card_itself_passes_the_checks():
    assert validate_annotations(CARD)["ok"] and contribution_info(CARD) == {"baseKey": "base"}


# ───────────────────────── TB-5 表专属合并金样 ─────────────────────────
TMC = json.loads((FIX / "table-merge-cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", TMC, ids=[c["name"] for c in TMC])
def test_table_merge_case_merge_then_build(case, tmp_path):
    P, delta, exp = case["P"], case["delta"], case["expect"]
    assert VB.is_valid(P)                                      # P 是合法的整体写法
    assert VB.is_valid({"base": "v-1", **delta}) == exp["ok"]  # 带 base 的增量：缺 id 的 sheet 被 schema 拒收
    assert sorted(touched_keys(BUILD, delta)) == exp["touched_keys"]
    if not exp["ok"]:
        with pytest.raises(MergeError) as ei:
            merge(BUILD, P, delta)
        assert (ei.value.instance_path, ei.value.message) == (exp["instancePath"], exp["message"])
        return
    merged = merge(BUILD, P, delta)
    assert merged == exp["value"]
    jsonschema.validate(merged, BUILD)                         # 合并结果过整体写法的 schema（引擎 PD-1 校验的就是它）
    r = run("table.build", merged, tmp_path)
    b = exp["build"]
    if b["ok"]:
        assert r["ok"], r
        assert r["output"]["sheets"] == b["sheets"]
        assert [w["code"] for w in r["output"]["warnings"]] == b["warning_codes"]
        if "empty_cells" in b:
            assert r["output"]["stats"]["empty_cells"] == b["empty_cells"]
    else:
        assert not r["ok"] and r["error"]["code"] == b["code"] and r["error"]["where"] == b["where"], r
        for s in b["message_contains"]:
            assert s in r["error"]["message"], (s, r["error"]["message"])


def test_table_merge_cases_cover_the_required_kinds():
    keys = {k for c in TMC for k in c["expect"]["touched_keys"]}
    assert "table.sheets#s1.rows+" in keys and "table.rows+" in keys
    assert any(not c["expect"]["ok"] and c["expect"]["message"] == "by-id 元素缺 id" for c in TMC)


def test_incremental_rows_merge_to_the_table_written_at_once(tmp_path):
    """分三次写（表头、两批对象行）合并出的表，与一次写成的表交出同一份产物。"""
    cols = [{"key": "part", "title": "零件"}, {"key": "qty", "title": "数量", "type": "integer"},
            {"key": "price", "title": "单价", "type": "money", "unit": "元"},
            {"key": "amount", "title": "金额", "type": "money", "unit": "元", "formula": "qty * price"}]
    rows = [{"part": "输入轴", "qty": 1, "price": 860}, {"part": "齿轮", "qty": 2, "price": 1250.5},
            {"part": "轴承 6208", "qty": 4, "price": 95}]
    whole = {"table": {"title": "物料", "sheets": [{"id": "bom", "name": "物料", "columns": cols, "rows": rows, "totals": ["金额"]}]}}
    first = {"table": {"title": "物料", "sheets": [{"id": "bom", "name": "物料", "columns": cols, "totals": ["金额"]}]}}
    jsonschema.validate(first, BUILD)
    assert empty_slots(BUILD, first) == []          # sheets 不设 fill，没有空槽
    r0 = run("table.build", first, tmp_path, "v0")
    assert r0["ok"] and [w["code"] for w in r0["output"]["warnings"]] == ["no_rows"], r0
    d1 = {"table": {"sheets": [{"id": "bom", "rows": rows[:2]}]}}
    d2 = {"table": {"sheets": [{"id": "bom", "rows": rows[2:]}]}}
    assert touched_keys(BUILD, d1) == touched_keys(BUILD, d2) == {"table.sheets#bom.rows+"}   # 同批相交 ⟹ 分轮写
    for d in (d1, d2):
        assert VB.is_valid({"base": "v-1", **d})
    merged = merge(BUILD, merge(BUILD, first, d1), d2)
    assert merged == whole and empty_slots(BUILD, merged) == []
    a, b = run("table.build", whole, tmp_path, "whole"), run("table.build", merged, tmp_path, "inc")
    assert a["ok"] and b["ok"] and a["output"] == b["output"]
    for fa, fb in zip(a["output"]["files"], b["output"]["files"]):
        assert (tmp_path / "whole" / fa["path"]).read_bytes() == (tmp_path / "inc" / fb["path"]).read_bytes()


def test_tb10_skeleton_of_table_build_names_sheets_and_counts_rows():
    """TB-10（补裁三）：sheets 不设 fill，每个 sheet 的骨架为 {id, label, rows:{$count:n}}；rows 缺席的 sheet 不出 rows 键。"""
    args = {"table": {"title": "库存", "sheets": [{"id": "s1", "name": "零件", "columns": ["名称"], "rows": [["轴承"], ["齿轮"]]},
                                                  {"id": "s2", "name": "原料", "columns": ["名称"]},
                                                  {"id": "s3", "name": "备件", "columns": ["名称"], "rows": []}]}}
    sk = json.loads(skeleton(BUILD, args, True))
    assert sk["table"]["sheets"] == [{"id": "s1", "label": "零件", "rows": {"$count": 2}},
                                     {"id": "s2", "label": "原料"},
                                     {"id": "s3", "label": "备件", "rows": {"$count": 0}}]
    assert empty_slots(BUILD, args) == []
    assert "轴承" not in json.dumps(sk, ensure_ascii=False)
    single = json.loads(skeleton(BUILD, {"table": {"title": "T", "columns": ["a"], "rows": [["x"]]}}, False))
    assert single["table"]["rows"] == {"$count": 1} and single["$best"] is False


# ───────────────────────── T2 sheet id 恒必填（只在 build） ─────────────────────────
def test_sheet_id_is_required_always_outside_the_branches():
    sheets = BUILD["properties"]["table"]["properties"]["sheets"]
    assert sheets["items"]["required"] == ["id"]
    assert BUILD["then"] == {"required": ["base"]} and BUILD["if"] == {"required": ["base"]}
    assert "id" not in json.dumps(BUILD["else"]["properties"]["table"]["properties"]["sheets"]["items"]["required"])
    assert "required" not in BUILD and "required" not in BUILD["properties"]["table"]


def test_whole_mode_requires_sheet_id_and_the_original_fields():
    ok = {"table": {"title": "T", "sheets": [{"id": "s1", "columns": ["a"], "rows": [["x"]]}]}}
    assert VB.is_valid(ok)
    assert VB.is_valid({"table": {"title": "T", "columns": ["a"], "rows": [["x"]]}})                 # 单表写法没有 sheet id
    assert not VB.is_valid({"table": {"title": "T", "sheets": [{"columns": ["a"], "rows": [["x"]]}]}})   # 2.0.0：sheet 缺 id 拒收
    assert not VB.is_valid({"table": {"sheets": [{"id": "s1", "columns": ["a"]}]}})                    # 缺 title
    assert not VB.is_valid({"table": {"title": "T", "sheets": [{"id": "s1", "rows": [["x"]]}]}})         # sheet 缺 columns
    assert not VB.is_valid({"name": "x"})                                                              # 缺 table


def test_delta_with_base_is_accepted_and_sheets_need_ids():
    assert VB.is_valid({"base": "v-0007", "table": {"sheets": [{"id": "s1", "rows": [{"名称": "齿轮"}]}]}})
    assert VB.is_valid({"base": "v-0007", "table": {"rows": [["x"]]}})
    assert VB.is_valid({"base": "v-0007", "table": {"title": "改个标题"}})
    assert VB.is_valid({"base": "v-0007"})
    assert not VB.is_valid({"base": "v-0007", "table": {"sheets": [{"rows": [["x"]]}]}})   # sheet id 恒必填
    assert not VB.is_valid({"base": "v-0007", "bogus": 1})
    assert not VB.is_valid({"base": 7, "table": {}})


def test_delta_without_base_gets_no_relaxation():
    assert not VB.is_valid({"table": {"sheets": [{"id": "s1", "rows": [["x"]]}]}})
    assert not VB.is_valid({"table": {"rows": [["x"]]}})


# ───────────────────────── TB-6 整体写法与 1.0.1 等价 ─────────────────────────
def _strip(node):
    if isinstance(node, dict):
        return {k: _strip(v) for k, v in node.items() if k not in ("x-mengos-merge", "x-mengos-base")}
    if isinstance(node, list):
        return [_strip(x) for x in node]
    return node


def _overlay(base, extra):
    for k, v in extra.items():
        if k == "required":
            base["required"] = list(base.get("required", [])) + [x for x in v if x not in base.get("required", [])]
        elif k == "properties":
            for pk, pv in v.items():
                _overlay(base[k][pk], pv)
        else:
            _overlay(base[k], v)


def test_whole_mode_schema_equals_1_0_1_schema_plus_sheet_id():
    """不带 base 时走 else：去掉贡献标注与 base 槽、把 else 叠回主体，再去掉 sheet id 必填这一处新增、
    去掉 table 的说明文字（2.0.0 改写了），应与 1.0.1 的 table.build input_schema 逐键相同。x-mengos-data 保留。"""
    s = _strip(copy.deepcopy(BUILD))
    s.pop("if"), s.pop("then")
    els = s.pop("else")
    s["properties"].pop("base")
    _overlay(s, els)
    s["required"] = s.pop("required")
    items = s["properties"]["table"]["properties"]["sheets"]["items"]
    assert items["required"] == ["id", "columns"]
    items["required"].remove("id")
    s["properties"]["table"].pop("description")
    assert sha(canonical_json(s).encode()) == V101_BUILD_NO_TABLE_DESC_SHA256


def test_build_description_states_the_2_0_0_rules():
    d = BUILD["properties"]["table"]["description"]
    for phrase in ("id 必填", "被公式或合计引用的列必须写 type", "只做 count 的列也要写 type（text 即可）", "格数等于列数",
                   "有公式列时也可以只写非公式列，格数等于非公式列数", "分批追加行时请用对象行", "改了列要把已有的数组行按新列重写"):
        assert phrase in d, phrase


WM = json.loads((FIX / "whole-mode-1.0.1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", WM["cases"], ids=[c["id"] for c in WM["cases"]])
def test_whole_mode_output_byte_identical_to_1_0_1(case, tmp_path):
    """同一进程入口、同一信封，stdout 一行与 1.0.1 逐字节相同，产出文件逐个 sha256 相同。"""
    assert VB.is_valid(case["payload"]) and "base" not in case["payload"]
    w = tmp_path / "w"
    w.mkdir()
    env = {"tool": "table.build", "payload": case["payload"], "workdir": str(w)}
    p = subprocess.run([sys.executable, str(ROOT / "table_tool.py")], input=json.dumps(env, ensure_ascii=False).encode(),
                       capture_output=True, cwd=str(ROOT), timeout=120)
    line = p.stdout.decode("utf-8")
    files = {f["path"]: sha((w / f["path"]).read_bytes()) for f in json.loads(line)["output"]["files"]}
    assert line == case["stdout"]
    assert files == case["file_sha256"]


def test_whole_mode_fixture_was_recorded_on_1_0_1():
    assert WM["recorded_on"] == {"package": "table", "version": "1.0.1", "lock": "0c8725745e60700f",
                                 "content_hash": "9d32fbe4082c6032ed5c5cff20c093dac1c4ef7f6411914242dd428a336cb64e"}
    assert len(WM["cases"]) >= 5


# ───────────────────────── TB-7 被引用列须写 type；无行的表 ok 加警告 ─────────────────────────
@pytest.mark.parametrize("cols,totals,where,names", [
    ([{"key": "a", "title": "单价"}, {"key": "n", "title": "数量", "type": "integer"}, {"title": "金额", "type": "money", "formula": "a * n"}],
     None, "table.columns[0].type", ["单价", "公式列“金额”"]),
    ([{"key": "a", "title": "单价", "type": "money"}, {"title": "数量"}], ["数量"], "table.columns[1].type", ["数量", "合计（sum）"]),
    ([{"title": "牌号"}, {"title": "价格", "type": "money"}], [{"column": "牌号", "fn": "count"}], "table.columns[0].type", ["牌号", "合计（count）"]),
    ([{"key": "a", "title": "甲", "type": "number"}, {"key": "r", "title": "倍", "formula": "a * 2"}, {"title": "再倍", "type": "number", "formula": "r * 2"}],
     None, "table.columns[1].type", ["倍", "公式列“再倍”"]),
])
def test_referenced_column_without_type_is_bad_input_naming_it(cols, totals, where, names, tmp_path):
    for i, rows in enumerate(([], [[1, 2, 3][:len([c for c in cols if "formula" not in c])]])):
        t = {"title": "T", "columns": cols, "rows": rows}
        if totals:
            t["totals"] = totals
        r = run("table.build", {"table": t}, tmp_path, f"r{i}")
        assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and r["error"]["where"] == where, r
        for n in names:
            assert n in r["error"]["message"], (n, r["error"]["message"])


def test_referenced_column_rule_also_in_sheets(tmp_path):
    t = {"title": "T", "sheets": [{"id": "s1", "columns": [{"title": "a", "type": "number"}], "totals": ["a"], "rows": [[1]]},
                                  {"id": "s2", "columns": [{"title": "b"}], "totals": ["b"], "rows": [[2]]}]}
    r = run("table.build", {"table": t}, tmp_path)
    assert not r["ok"] and r["error"]["where"] == "table.sheets[1].columns[0].type", r


@pytest.mark.parametrize("label,table,where", [
    ("零行", {"title": "T", "columns": [{"key": "a", "title": "数量", "type": "integer"}, {"title": "倍", "type": "integer", "formula": "a * 2"}],
             "rows": [], "totals": ["倍"]}, "table.rows"),
    ("rows 缺席", {"title": "T", "columns": [{"title": "金额", "type": "money"}], "totals": ["金额"]}, "table.rows"),
    ("sheet 无行", {"title": "T", "sheets": [{"id": "s1", "name": "甲", "columns": [{"title": "金额", "type": "money"}], "rows": [[1]]},
                                            {"id": "s2", "name": "乙", "columns": [{"title": "金额", "type": "money"}], "totals": ["金额"]}]},
     "table.sheets[1].rows"),
])
def test_tables_without_rows_are_ok_with_warning(label, table, where, tmp_path):
    jsonschema.validate({"table": table}, BUILD)
    r = run("table.build", {"table": table}, tmp_path)
    assert r["ok"], (label, r)
    ws = [w for w in r["output"]["warnings"] if w["code"] == "no_rows"]
    assert [w["where"] for w in ws] == [where], (label, r["output"]["warnings"])
    assert all(t.get("value") is None for s in r["output"]["sheets"] if s["rows"] == 0 for t in s.get("totals", []))


def test_unreferenced_columns_still_inferred(tmp_path):
    r = run("table.build", {"table": {"title": "T", "columns": ["名称", "数量"], "rows": [["a", 1]]}}, tmp_path)
    assert r["ok"] and r["output"]["warnings"] == []
    m = json.loads((tmp_path / "w" / "T.table.json").read_text(encoding="utf-8"))
    assert [c["type"] for c in m["sheets"][0]["columns"]] == ["text", "integer"]


def test_check_and_export_keep_1_x_typing_rules(tmp_path):
    """被引用列缺 type、表无行：核对与导出照 1.x 口径（收的是表对象，不收紧，也不加警告）。"""
    t = {"title": "T", "columns": ["名称", "数量"], "rows": [["a", 1], ["b", 2]], "totals": ["数量"]}
    rc = run("table.check", {"table": t, "expect": "total 数量 sum=3"}, tmp_path, "c")
    assert rc["ok"] and rc["output"]["verdict"] == "pass", rc
    re_ = run("table.export", {"table": {**t, "rows": []}, "formats": ["md"]}, tmp_path, "e")
    assert not re_["ok"] and re_["error"]["code"] == "BAD_INPUT"   # 1.x：零行时推断为文字列，不能 sum（与 1.0.1 同）
    re2 = run("table.export", {"table": {"title": "T", "columns": [{"title": "数量", "type": "integer"}]}, "formats": ["md"]}, tmp_path, "e2")
    assert re2["ok"] and re2["output"]["warnings"] == [], re2


# ───────────────────────── TB-8 数组行严格 ─────────────────────────
def test_array_row_length_mismatch_reports_row_number_expected_and_actual(tmp_path):
    t = {"title": "T", "columns": [{"title": "a", "type": "text"}, {"title": "b", "type": "text"}, {"title": "c", "type": "text"}],
         "rows": [["1", "2", "3"], ["1", "2"]]}
    r = run("table.build", {"table": t}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and r["error"]["where"] == "table.rows[1]", r
    for s in ("第 2 行", "有 2 格", "表有 3 列", "须等于列数 3（实际 2）"):
        assert s in r["error"]["message"], (s, r["error"]["message"])
    assert "对象行" in r["error"]["hint"]


def test_short_array_row_is_not_padded_with_null(tmp_path):
    """不补 null：比列数少的数组行（又不等于非公式列数）一律拒收，长的也拒收。"""
    cols = [{"key": "a", "title": "a", "type": "number"}, {"key": "b", "title": "b", "type": "number"},
            {"title": "s", "type": "number", "formula": "a + b"}, {"title": "备注", "type": "text"}]
    for i, row in enumerate(([1], [1, 2], [1, 2, None, "x", "y"])):
        r = run("table.build", {"table": {"title": "T", "columns": cols, "rows": [row]}}, tmp_path, f"r{i}")
        assert not r["ok"] and r["error"]["where"] == "table.rows[0]", (row, r)
        assert f"须等于列数 4，或等于非公式列数 3（实际 {len(row)}）" in r["error"]["message"], r["error"]["message"]
    ok = run("table.build", {"table": {"title": "T", "columns": cols, "rows": [[1, 2, "x"], [1, 2, None, "y"]]}}, tmp_path, "ok")
    assert ok["ok"], ok   # 等于列数，或等于非公式列数（1.0.1 起的写法）


# ───────────────────────── TB-9 核对与导出 ─────────────────────────
def test_check_and_export_input_schemas_have_no_contribution_vocabulary():
    for s in (CHECK, EXPORT):
        assert "x-mengos-base" not in json.dumps(s) and "x-mengos-merge" not in json.dumps(s)


def test_check_and_export_input_schemas_equal_1_0_1():
    assert sha(canonical_json(CHECK).encode()) == V101_CHECK_SHA256
    assert sha(canonical_json(EXPORT).encode()) == V101_EXPORT_SHA256


def test_check_and_export_accept_old_table_objects_without_sheet_id(tmp_path):
    old = {"title": "库存", "sheets": [{"name": "甲", "columns": ["名称", "库存"], "rows": [["轴承", 46]]},
                                       {"name": "乙", "columns": ["名称", "库存"], "rows": [["圆钢", 12], ["板材", 3]]}]}
    record = {"tool": "table.build", "args": {"table": old}, "output": {}}
    for tid, payload in (("table.check", {"object": record, "expect": "sheet=乙 total 库存 sum=15"}),
                         ("table.check", {"table": old, "expect": "rows min=1"}),
                         ("table.export", {"object": record, "formats": ["json", "md"]}),
                         ("table.export", {"table": old, "formats": ["csv"]})):
        jsonschema.validate(payload, UNITS[tid]["signature"]["input_schema"])
        r = run(tid, payload, tmp_path, f"{tid}-{len(list(tmp_path.iterdir()))}")
        assert r["ok"], (tid, r)
        if tid == "table.check":
            assert r["output"]["verdict"] == "pass"
    model = json.loads(next((tmp_path).glob("table.export-*/*.table.json")).read_text(encoding="utf-8"))
    assert all("id" not in s for s in model["sheets"])   # 旧表没有 id，导出的表模型也不编造 id
