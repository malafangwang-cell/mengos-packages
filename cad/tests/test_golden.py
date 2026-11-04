"""金样（TL-12 ③）：参考值来自手算或独立计算，见 golden_cases.json 的 source。"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from cad_tool import run

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))


def get(obj, path):
    for k in path.split("."):
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden(case, tmp_path):
    env = {"tool": case["tool"], "payload": case["payload"]}
    if case.get("workdir"):
        env["workdir"] = str(tmp_path)
    res = run(env)
    exp = case["expect"]
    assert res["ok"] is exp["ok"], res
    if not exp["ok"]:
        assert res["error"]["code"] == exp["code"]
        if "line" in exp:
            assert res["error"].get("line") == exp["line"], res
        if "hint_contains" in exp:
            assert exp["hint_contains"] in res["error"].get("hint", ""), res
        return
    out = res["output"]
    for v in exp.get("values", []):
        got = get(out, v["path"])
        assert abs(got - v["value"]) <= abs(v["value"]) * v["rtol"], (v, got)
    for e in exp.get("equals", []):
        assert get(out, e["path"]) == e["value"], (e, get(out, e["path"]))
    for c in exp.get("count", []):
        items = [h for h in get(out, c["path"]) if all(h.get(k) == w for k, w in c["where"].items())]
        assert len(items) == c["value"], (c, items)
    if exp.get("files_verified"):
        for f in out["files"]:
            p = tmp_path / f["path"]
            data = p.read_bytes()
            assert len(data) == f["bytes"] and hashlib.sha256(data).hexdigest() == f["sha256"]
        assert sorted(os.listdir(tmp_path)) == sorted(f["path"] for f in out["files"])   # 只写声明过的文件
