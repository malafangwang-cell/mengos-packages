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
