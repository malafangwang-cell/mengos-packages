"""登记资产自检（TL-12 ① schema、④ 版本）。"""
import json
from pathlib import Path

import jsonschema

from cad_tool import TOOLS, run
from lock import lock_hash

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
VERBS = {"compute", "check", "retrieve", "execute", "generate", "convert"}


def test_units_match_entry_tools():
    assert sorted(u["tool_id"] for u in REG["units"]) == sorted(TOOLS)


def test_version_is_current_lock_hash():
    assert REG["lock_hash"] == lock_hash()
    assert all(u["version"] == lock_hash() for u in REG["units"])


def test_fields_and_verbs():
    for u in REG["units"]:
        for k in ("tool_id", "version", "signature", "input_example", "executor", "effect", "cost", "capability", "trust_claim"):
            assert k in u, (u["tool_id"], k)
        assert set(u["capability"]["ops"]) <= VERBS
        assert 3 <= len(u["capability"]["examples"]) <= 5
        assert u["effect"] == "none"
    check = next(u for u in REG["units"] if u["tool_id"] == "cad.check")
    assert "check" in check["capability"]["ops"] and check["review_coverage"]["by_predicate"]


def test_examples_follow_schemas(tmp_path):
    for u in REG["units"]:
        sig = u["signature"]
        jsonschema.validate(u["input_example"], sig["input_schema"])
        d = tmp_path / u["tool_id"]
        d.mkdir()
        res = run({"tool": u["tool_id"], "payload": u["input_example"], "workdir": str(d)})
        assert res["ok"], res
        jsonschema.validate(res["output"], sig["output_schema"])


def test_golden_payloads_follow_schemas(tmp_path):
    units = {u["tool_id"]: u for u in REG["units"]}
    for i, case in enumerate(CASES):
        sig = units[case["tool"]]["signature"]
        d = tmp_path / str(i)
        d.mkdir()
        res = run({"tool": case["tool"], "payload": case["payload"], "workdir": str(d) if case.get("workdir") else None})
        if case["expect"]["ok"]:
            jsonschema.validate(case["payload"], sig["input_schema"])
            jsonschema.validate(res["output"], sig["output_schema"])


def test_registration_has_no_integral_floats():
    """2.6.1：安装器（引擎，JS）按 JSON.stringify 规范化登记重算 lock，1254.0 写成 1254；lock.py（Python）写成 1254.0。
    两边对整数值的浮点写法不同 ⟹ 重算不符、安装被拒。登记里的数一律写成整数或非整数小数。"""
    bad = []

    def walk(v, path):
        if isinstance(v, float) and v.is_integer():
            bad.append(path)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
    walk(REG, "")
    assert not bad, bad
