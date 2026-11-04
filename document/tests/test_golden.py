"""金样（认证 ③）：期望值手写，逐条核对。"""
import json
import re
from pathlib import Path

import pytest

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))


def _get(obj, path):
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        obj = obj[int(part[1:-1])] if part.startswith("[") else obj[part]
    return obj


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden(case, tmp_path):
    r = doc_tool.run({"tool": case["tool"], "payload": case["payload"], "workdir": str(tmp_path)})
    exp = dict(case["expect"])
    if any(k.startswith("error.") for k in exp):
        assert not r["ok"], r
        for k, v in exp.items():
            assert _get(r, k) == v, (k, r["error"])
        return
    assert r["ok"], r
    out = r["output"]
    md_has, md_not = exp.pop("md_contains", []), exp.pop("md_lacks", [])
    if md_has or md_not:
        md = next(f for f in out["files"] if f["format"] == "md")
        text = (tmp_path / md["path"]).read_text(encoding="utf-8")
        for s in md_has:
            assert s in text, (s, text)
        for s in md_not:
            assert s not in text, s
    for k, v in exp.items():
        assert _get(out, k) == v, (k, _get(out, k), v)
