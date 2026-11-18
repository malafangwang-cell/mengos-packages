"""登记资产自检（TL-12 ① schema、④ 版本），以及常量与登记一致。"""
import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from count_tool import MAX_INLINE_ROWS, TOOLS, run  # noqa: E402
from lock import lock_hash  # noqa: E402
import make_registration  # noqa: E402

REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
SEL = json.loads((ROOT / "selection_cases.json").read_text(encoding="utf-8"))
MAN = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}


def test_registration_is_generated_from_single_source():
    gen = dict(make_registration.REG)
    reg = dict(REG)
    gen_units = [dict(u, version="") for u in gen["units"]]
    reg_units = [dict(u, version="") for u in reg["units"]]
    assert gen_units == reg_units and {**gen, "units": 0, "lock_hash": ""} == {**reg, "units": 0, "lock_hash": ""}


def test_units_match_entry_tools():
    assert sorted(UNITS) == sorted(TOOLS) == sorted(MAN["tool_titles"])


def test_version_is_current_lock_hash():
    assert REG["lock_hash"] == lock_hash()
    assert all(u["version"] == lock_hash() for u in REG["units"])


def test_t1_none_process():
    for u in REG["units"]:
        assert (u["trust_claim"], u["effect"], u["executor"]["kind"]) == ("T1", "none", "process")


def test_max_inline_rows_matches_registration():
    assert make_registration.MAX_INLINE_ROWS == MAX_INLINE_ROWS
    for tid in ("count.rows", "count.series", "count.coverage"):
        assert UNITS[tid]["capability"]["constraints"]["max_inline_rows"] == MAX_INLINE_ROWS
    assert UNITS["count.rows"]["signature"]["input_schema"]["properties"]["source"]["properties"]["rows"]["maxItems"] == MAX_INLINE_ROWS


def test_data_field_declarations():
    """来源行与互证的两个数声明为数据字段（17 TL-30）：其中的数要有证件。"""
    rows = UNITS["count.rows"]["signature"]["input_schema"]["properties"]["source"]["properties"]["rows"]
    assert rows["x-mengos-data"] is True
    for side in ("left", "right"):
        assert UNITS["count.agree"]["signature"]["input_schema"]["properties"][side]["properties"]["value"]["x-mengos-data"] is True


def test_examples_follow_schemas():
    for u in REG["units"]:
        sig = u["signature"]
        jsonschema.validate(u["input_example"], sig["input_schema"])
        res = run({"tool": u["tool_id"], "payload": u["input_example"]})
        assert res["ok"], res
        jsonschema.validate(res["output"], sig["output_schema"])


def test_golden_payloads_follow_schemas():
    for c in CASES:
        sig = UNITS[c["tool"]]["signature"]
        if c["id"] == "rows-over-cap":     # 故意超 maxItems，测执行体自己的上限
            assert not jsonschema.Draft202012Validator(sig["input_schema"]).is_valid(c["payload"])
        else:
            jsonschema.validate(c["payload"], sig["input_schema"])
        res = run({"tool": c["tool"], "payload": c["payload"]})
        if res["ok"]:
            jsonschema.validate(res["output"], sig["output_schema"])


def test_capability_shape():
    for u in REG["units"]:
        cap = u["capability"]
        assert 3 <= len(cap["examples"]) <= 5
        assert all(isinstance(e, dict) and e["input"] and e["output"] for e in cap["examples"])
        if "check" in cap["ops"]:
            assert u.get("review_coverage")


def test_selection_cases_per_tool():
    for tid in UNITS:
        pos = [s for s in SEL if s["tool_id"] == tid and s["expect_selected"]]
        neg = [s for s in SEL if s["tool_id"] == tid and not s["expect_selected"]]
        assert len(pos) >= 3 and len(neg) >= 3, tid


def test_no_domain_words_in_executor_sources():
    """工具保持通用：执行体源码不出现行业词（图块、货架、立柱、横梁、巷道、图幅、分解单）。注释与说明文字除外的检查简化为全文扫描。"""
    words = ("货架", "立柱", "横梁", "巷道", "分解单", "投标")
    for name in ("ops.py", "series.py", "coverage.py", "count_tool.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for w in words:
            assert w not in text, (name, w)
