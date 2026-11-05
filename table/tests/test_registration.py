"""登记资产自检（TL-12 ①）：例子合 schema；跑例子的输出合 output_schema；样例表的三件工具输出也合。"""
import json
from pathlib import Path

import jsonschema
import pytest

import lock
import table_tool

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
SAMPLES = sorted((ROOT / "samples").glob("*.json"))


def test_version_is_current_lock_hash():
    v = lock.lock_hash()
    assert REG["lock_hash"] == v and all(u["version"] == v for u in REG["units"]), "改动后要运行 python lock.py"


@pytest.mark.parametrize("tid", sorted(UNITS))
def test_input_example_valid_and_output_matches_schema(tid, tmp_path):
    u = UNITS[tid]
    sig = u["signature"]
    jsonschema.validate(u["input_example"], sig["input_schema"])
    r = table_tool.run({"tool": tid, "payload": u["input_example"], "workdir": str(tmp_path)})
    assert r["ok"], r
    jsonschema.validate(r["output"], sig["output_schema"])


def test_check_example_passes(tmp_path):
    r = table_tool.run({"tool": "table.check", "payload": UNITS["table.check"]["input_example"]})
    assert r["ok"] and r["output"]["verdict"] == "pass", r


@pytest.mark.parametrize("sample", SAMPLES, ids=[s.stem for s in SAMPLES])
def test_samples_through_all_tools(sample, tmp_path):
    t = json.loads(sample.read_text(encoding="utf-8"))
    for tid, payload in (("table.build", {"table": t, "formats": ["xlsx", "csv"]}),
                         ("table.check", {"table": t, "expect": "rows min=1"}),
                         ("table.export", {"table": t, "formats": ["xlsx", "csv", "md", "json"]})):
        jsonschema.validate(payload, UNITS[tid]["signature"]["input_schema"])
        w = tmp_path / tid
        w.mkdir()
        r = table_tool.run({"tool": tid, "payload": payload, "workdir": str(w)})
        assert r["ok"], r
        jsonschema.validate(r["output"], UNITS[tid]["signature"]["output_schema"])


def test_schema_and_code_agree_on_rejects(tmp_path):
    """schema 拒收的，代码也拒收（不靠引擎校验兜底）。"""
    bad = [{"columns": ["a"], "rows": []}, {"title": "t", "columns": []}, {"title": "t", "columns": [{"title": "a", "type": "float"}]},
           {"title": "t", "columns": [{"title": "a", "x": 1}]}, {"title": "t", "columns": ["a"], "rows": [[{"v": 1}]]},
           {"title": "t", "columns": [{"title": "a", "decimals": 11}]}]
    for t in bad:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"table": t}, UNITS["table.build"]["signature"]["input_schema"])
        r = table_tool.run({"tool": "table.build", "payload": {"table": t}, "workdir": str(tmp_path)})
        assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", (t, r)


def test_examples_and_nongoals_present():
    for u in REG["units"]:
        cap = u["capability"]
        assert 3 <= len(cap["examples"]) <= 5, u["tool_id"]
        assert cap["non_goals"], u["tool_id"]
        assert u["effect"] == "none" and u["trust_claim"] == "T1"
