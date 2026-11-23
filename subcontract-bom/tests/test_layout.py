"""rack.layout 算法单测（设计稿三、四；r3 〇补）。金样另在 golden_cases.json，由 tools/run_golden.py 跑。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import layout  # noqa: E402
import rack_tool  # noqa: E402

BASE = {"run_length": 27600, "column_pitch": 2760, "level_segments": 4, "beam_clear": 2700,
        "zones": {"甲": {"pallets": 800, "pallet_plan_a": 1200, "pallet_plan_b": 1000},
                  "乙": {"pallets": 400, "pallet_plan_a": 1000, "pallet_plan_b": 1000}}}


def run(fd):
    return rack_tool.run({"tool": "rack.layout", "payload": {"from_drawing": fd}})


def nc(res):
    return {e["item"]: e for e in res["output"]["not_computed"]}


def test_positive_all_items():
    out = run(BASE)["output"]
    assert out["computed"]["total"] == {"rows": 12, "groups": 6, "aisles": 3}
    assert out["not_computed"] == [] and out["assumptions"] == []
    assert [s["clause"] for s in out["steps"]][:3] == ["G2", "G2", "G3"]


def test_inputs_are_not_echoed_in_computed():
    out = run(BASE)["output"]["computed"]
    for k in ("run_length", "column_pitch", "beam_clear", "level_segments"):
        assert k not in out


def test_needs_trace_to_missing_inputs_and_reason_names_upstream():
    fd = json.loads(json.dumps(BASE))
    del fd["level_segments"]
    e = nc(run(fd))
    assert e["levels"]["needs"] == ["level_segments"]
    assert e["zones/甲/aisles"]["needs"] == ["level_segments"]
    assert "zones/甲/groups" in e["zones/甲/aisles"]["reason"]


def test_invalid_has_empty_needs_and_operand_values():
    fd = json.loads(json.dumps(BASE))
    fd["zones"]["甲"]["pallets"] = 810
    e = nc(run(fd))["zones/甲/rows"]
    assert e["needs"] == [] and "810" in e["reason"]


def test_downstream_of_invalid_has_empty_needs():
    fd = json.loads(json.dumps(BASE))
    fd["run_length"] = 27000
    assert nc(run(fd))["zones/乙/aisles"]["needs"] == []


def test_columns_alternative_needs():
    fd = {"level_segments": 4}
    r = run(fd)
    assert nc(r)["columns"]["needs"] == ["columns_read"]
    fd = {"level_segments": 4, "run_length": 27600}
    assert nc(run(fd))["columns"]["needs"] == ["column_pitch"]


def test_invalid_columns_read_reported():
    r = run({"columns_read": 10.5, "level_segments": 4})
    assert nc(r)["columns"]["needs"] == [] and "frames_per_row" in nc(r)


@pytest.mark.parametrize("v", [0, -3, 2.5, "x", True, [], {}])
def test_bad_level_segments_never_raises(v):
    r = run({"level_segments": v, "columns_read": 10})
    assert r["ok"] is True and "levels" in nc(r)


def test_nothing_computable_is_failure():
    assert run({})["ok"] is False
    assert run({"level_segments": 0})["ok"] is False


def test_null_counts_as_missing():
    r = run({"columns_read": 10, "level_segments": None})
    assert nc(r)["levels"]["needs"] == ["level_segments"]


@pytest.mark.parametrize("payload", [
    None, [], {"from_drawing": 1}, {"from_drawing": {}, "x": 1}, {"from_drawing": {"aisle": 1}},
    {"from_drawing": {"zones": []}}, {"from_drawing": {"zones": {"a/b": {}}}}, {"from_drawing": {"zones": {"": {}}}},
    {"from_drawing": {"zones": {"a" * 33: {}}}}, {"from_drawing": {"zones": {"a": {"depth": 1}}}},
    {"from_drawing": {"zones": {f"z{i}": {} for i in range(21)}}},
])
def test_shape_errors_are_bad_input(payload):
    r = rack_tool.run({"tool": "rack.layout", "payload": payload})
    assert r["ok"] is False and r["error"]["code"] == "BAD_INPUT"


def test_unknown_tool():
    assert rack_tool.run({"tool": "rack.other", "payload": {}})["error"]["code"] == "BAD_INPUT"


def test_decimal_dimensions_exact():
    # 总长、列距带小数时按有理数精确除
    fd = dict(BASE, run_length="27600.5", column_pitch="2760.05")
    assert run(fd)["output"]["computed"]["columns"] == 10


def test_floor_only_on_pallets_per_cell():
    fd = dict(BASE, beam_clear=2999.9)
    assert run(fd)["output"]["computed"]["zones"]["甲"]["pallets_per_cell"] == 2


def test_process_entry_is_deterministic_bytes():
    env = json.dumps({"tool": "rack.layout", "payload": {"from_drawing": BASE}}, ensure_ascii=False).encode()
    outs = {subprocess.run([sys.executable, str(ROOT / "rack_tool.py")], input=env, capture_output=True).stdout for _ in range(2)}
    assert len(outs) == 1
    assert json.loads(outs.pop())["ok"] is True


def test_bad_json_line():
    p = subprocess.run([sys.executable, str(ROOT / "rack_tool.py")], input=b"not json\n", capture_output=True)
    assert json.loads(p.stdout)["error"]["code"] == "BAD_INPUT"


def test_zone_order_independent():
    a = run(BASE)
    fd = dict(BASE, zones={"乙": BASE["zones"]["乙"], "甲": BASE["zones"]["甲"]})
    assert json.dumps(run(fd), sort_keys=True) == json.dumps(a, sort_keys=True)
