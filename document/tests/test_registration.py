"""登记资产自检（TL-12 ①）：例子合 schema；跑例子的输出合 output_schema；样例文档的三件工具输出也合。"""
import json
from pathlib import Path

import jsonschema
import pytest

import doc_tool
import lock

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
    r = doc_tool.run({"tool": tid, "payload": u["input_example"], "workdir": str(tmp_path)})
    assert r["ok"], r
    jsonschema.validate(r["output"], sig["output_schema"])


@pytest.mark.parametrize("sample", SAMPLES, ids=[s.stem for s in SAMPLES])
def test_samples_through_all_tools(sample, tmp_path):
    d = json.loads(sample.read_text(encoding="utf-8"))
    for tid, payload in (("doc.build", {"doc": d, "formats": ["docx", "html"]}),
                         ("doc.check", {"doc": d, "expect": "pages max=80\ncovered"}),
                         ("doc.export", {"doc": d, "formats": ["docx", "md", "html", "json"]})):
        jsonschema.validate(payload, UNITS[tid]["signature"]["input_schema"])
        w = tmp_path / tid
        w.mkdir()
        r = doc_tool.run({"tool": tid, "payload": payload, "workdir": str(w)})
        assert r["ok"], r
        jsonschema.validate(r["output"], UNITS[tid]["signature"]["output_schema"])


def test_schema_and_code_agree_on_rejects(tmp_path):
    """schema 拒收的，代码也拒收（不靠引擎校验兜底）。"""
    bad = [{"title": "t", "sections": []}, {"title": "t", "sections": [{"heading": "a", "level": 5}]},
           {"title": "t", "sections": [{"heading": "a", "x": 1}]}, {"sections": [{"heading": "a"}]}]
    for d in bad:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"doc": d}, UNITS["doc.build"]["signature"]["input_schema"])
        r = doc_tool.run({"tool": "doc.build", "payload": {"doc": d}, "workdir": str(tmp_path)})
        assert not r["ok"] and r["error"]["code"] == "BAD_INPUT"
