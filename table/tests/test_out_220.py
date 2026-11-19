"""2.2.0 做出的旧表在 2.3.x 上逐字节不变（局部追问 r10 架构线补查 b）。
金样 tests/fixtures/out_220.json 由 tools/make_out_220.py 在 table 2.2.0 代码上录（golden_cases.json 里每条成功的
table.build、table.export）。同一入参在本版上：表模型、Markdown、CSV 逐字节相同；产出台数据去掉 2.3.0 新增的输出字段后
逐字节相同；xlsx 逐格的公式与值相同。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
from make_out_220 import run, xlsx_cells  # noqa: E402

import hashlib  # noqa: E402

GOLD = json.loads((ROOT / "tests" / "fixtures" / "out_220.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in (lambda G: G["cases"] if isinstance(G, dict) else G)(json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8")))}
# 2.3.0 产出台数据新增的输出字段（只加，不改原有字段）
NEW_VIEW_FIELDS_230 = ("id", "ids", "src", "col_kinds", "deps", "row_kind", "derived_keys", "layout_keys")


def test_gold_covers_build_and_export():
    tools = {v["tool"] for v in GOLD["cases"].values()}
    assert tools == {"table.build", "table.export"} and len(GOLD["cases"]) >= 40


@pytest.mark.parametrize("cid", sorted(GOLD["cases"]))
def test_same_as_2_2_0(cid, tmp_path):
    import render
    g = GOLD["cases"][cid]
    r = run(ROOT, g["tool"], CASES[cid]["payload"], tmp_path)
    assert r.get("ok"), r
    files = {f["path"]: f for f in r["output"].get("files", [])}
    assert set(files) == set(g["files"])
    for path, want in g["files"].items():
        data = (tmp_path / path).read_bytes()
        assert files[path]["format"] == want["format"]
        if want["format"] == "xlsx":
            assert xlsx_cells(data) == want["xlsx"], path
        elif want["format"] == "view":
            v = json.loads(data)
            for sh in v["sheets"]:
                for k in NEW_VIEW_FIELDS_230:
                    sh.pop(k, None)
            assert hashlib.sha256(render.dumps(v)).hexdigest() == want["sha256"], path
        else:
            assert hashlib.sha256(data).hexdigest() == want["sha256"], path
