"""同输入两次产出逐字节相同（TL-12 ②）。"""
import hashlib
import json
from pathlib import Path

import pytest

import table_tool

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = sorted((ROOT / "samples").glob("*.json"))


def _digest(tmp, t):
    r = table_tool.run({"tool": "table.build", "payload": {"table": t, "formats": ["xlsx", "csv"]}, "workdir": str(tmp)})
    assert r["ok"], r
    return {f["path"]: hashlib.sha256((tmp / f["path"]).read_bytes()).hexdigest() for f in r["output"]["files"]}, r["output"]


@pytest.mark.parametrize("sample", SAMPLES, ids=[s.stem for s in SAMPLES])
def test_double_run_identical(sample, tmp_path):
    t = json.loads(sample.read_text(encoding="utf-8"))
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    a, oa = _digest(tmp_path / "a", t)
    b, ob = _digest(tmp_path / "b", t)
    assert a == b and oa == ob
    for f in oa["files"]:
        assert f["sha256"] == a[f["path"]]
