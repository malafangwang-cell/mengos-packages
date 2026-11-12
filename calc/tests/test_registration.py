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


def test_expr_params_declaration_present_and_well_formed():
    """17 TL-30b（v0.2.99）：位数、步长一类参数在 input_schema 顶层声明 x-mengos-expr-params。

    格式 {"<函数名>": [<参数序号>, …]}，序号从 1 起。本计算器的函数没有这类参数，声明为空对象；
    若以后列入函数，函数名必须是解析器认得的函数（小写），序号不超过该函数的最多参数个数。
    """
    from expr_parser import FUNCTIONS
    for unit in REG["units"]:
        sch = unit["signature"]["input_schema"]
        assert "x-mengos-expr-params" in sch, unit["tool_id"]
        decl = sch["x-mengos-expr-params"]
        assert isinstance(decl, dict), unit["tool_id"]
        for name, idxs in decl.items():
            assert isinstance(name, str) and name == name.lower() and name in FUNCTIONS, (unit["tool_id"], name)
            assert isinstance(idxs, list) and idxs and len(set(idxs)) == len(idxs), (unit["tool_id"], name)
            assert all(type(i) is int and 1 <= i <= FUNCTIONS[name][1] for i in idxs), (unit["tool_id"], name)
        assert decl == {}, (unit["tool_id"], decl)
