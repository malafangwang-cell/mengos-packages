"""登记资产自检（对应 TL-12 ① schema 与 ④ 版本）。"""
import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from calc_tool import TOOLS, run  # noqa: E402
from lock import lock_hash  # noqa: E402

REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))


def test_units_match_entry_tools():
    assert sorted(u["tool_id"] for u in REG["units"]) == sorted(TOOLS)


def test_version_is_current_lock_hash():
    assert REG["lock_hash"] == lock_hash()
    assert all(u["version"] == lock_hash() for u in REG["units"])


def test_examples_follow_schemas():
    for unit in REG["units"]:
        sig = unit["signature"]
        jsonschema.validate(unit["input_example"], sig["input_schema"])
        res = run({"tool": unit["tool_id"], "payload": unit["input_example"]})
        assert res["ok"], res
        jsonschema.validate(res["output"], sig["output_schema"])


def test_golden_payloads_follow_input_schema_and_outputs_follow_output_schema():
    units = {u["tool_id"]: u for u in REG["units"]}
    for case in CASES:
        sig = units[case["tool"]]["signature"]
        jsonschema.validate(case["payload"], sig["input_schema"])
        res = run({"tool": case["tool"], "payload": case["payload"]})
        if res["ok"]:
            jsonschema.validate(res["output"], sig["output_schema"])


def test_capability_examples_3_to_5():
    for unit in REG["units"]:
        assert 3 <= len(unit["capability"]["examples"]) <= 5, unit["tool_id"]


def _paths_with(node, key, path=""):
    out = []
    if isinstance(node, dict):
        if node.get(key) is True:
            out.append(path)
        for k, v in node.items():
            out += _paths_with(v, key, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _paths_with(v, key, f"{path}/{i}")
    return out


C2 = "拿回的精确值与近似值可以在产物里引用。"   # mengosv2 P5 C2 批定原文（立法者 2026-11-21）


def test_ref_marks_match_c2():
    """2.2.4（mengosv2 工单 P4；kernel-spec 17 TL-30d）：calc.evaluate 根说明末尾是 C2 原文；
    x-mengos-ref 只标 C2 说的精确值（value）与近似值（approx），只在输出上；algebra、check_equal 不标、不带这句。"""
    units = {u["tool_id"]: u for u in REG["units"]}
    ev = units["calc.evaluate"]["signature"]
    assert ev["input_schema"]["description"].endswith("和十进制近似。" + C2)
    assert _paths_with(ev["output_schema"], "x-mengos-ref") == ["/properties/value", "/properties/approx"]
    for u in REG["units"]:
        assert _paths_with(u["signature"]["input_schema"], "x-mengos-ref") == []
        if u["tool_id"] != "calc.evaluate":
            assert _paths_with(u["signature"]["output_schema"], "x-mengos-ref") == []
            assert C2 not in json.dumps(u, ensure_ascii=False)
