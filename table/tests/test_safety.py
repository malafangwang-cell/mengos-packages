"""安全与边界：CSV 注入、超限、坏公式、无网络依赖。"""
import json
from pathlib import Path

import pytest

import table_tool

ROOT = Path(__file__).resolve().parents[1]


def _run(tool, payload, tmp):
    return table_tool.run({"tool": tool, "payload": payload, "workdir": str(tmp)})


def test_csv_injection_neutralized(tmp_path):
    t = {"title": "x", "columns": ["a"], "rows": [["=HYPERLINK(\"http://e\")"], ["+1"], ["@SUM(A1)"]]}
    r = _run("table.build", {"table": t, "formats": ["csv", "xlsx"]}, tmp_path)
    assert r["ok"], r
    csv = next(f for f in r["output"]["files"] if f["format"] == "csv")
    text = (tmp_path / csv["path"]).read_text(encoding="utf-8-sig")
    assert "'=HYPERLINK" in text and "'+1" in text and "'@SUM" in text
    import openpyxl
    x = next(f for f in r["output"]["files"] if f["format"] == "xlsx")
    ws = openpyxl.load_workbook(tmp_path / x["path"]).active
    assert ws["A2"].data_type == "s", "文本单元格不能变成公式"


@pytest.mark.parametrize("t,frag", [
    ({"title": "x", "columns": ["a", {"title": "b", "formula": "a+"}], "rows": [[1]]}, "公式"),
    ({"title": "x", "columns": [{"title": "a", "type": "text"}, {"title": "b", "formula": "a*2"}], "rows": [["q"]]}, "数值"),
    ({"title": "x", "columns": [{"title": "a", "type": "integer"}, {"title": "b", "formula": "zz*2"}], "rows": [[1]]}, "zz"),
    ({"title": "x", "columns": [{"title": "a", "type": "integer"}], "rows": [["abc"]]}, None),
])
def test_bad_input_has_location(t, frag, tmp_path):
    r = _run("table.build", {"table": t}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", r
    assert r["error"]["where"], r
    if frag:
        assert frag in r["error"]["message"] + r["error"].get("hint", ""), r


def test_row_limit(tmp_path):
    t = {"title": "x", "columns": ["a"], "rows": [[i] for i in range(100001)]}
    r = _run("table.build", {"table": t}, tmp_path)
    assert not r["ok"] and r["error"]["code"] in ("BAD_INPUT", "RESOURCE_LIMIT")


def test_div_zero_is_warning_not_crash(tmp_path):
    t = {"title": "x", "columns": [{"title": "a", "type": "number"}, {"title": "b", "type": "number"},
                                   {"title": "c", "formula": "a/b"}], "rows": [[1, 0], [4, 2]]}
    r = _run("table.build", {"table": t}, tmp_path)
    assert r["ok"] and r["output"]["warnings"], r


def test_no_network_imports():
    for f in ("model.py", "formula.py", "render.py", "xlsx_writer.py", "checker.py", "table_tool.py"):
        src = (ROOT / f).read_text(encoding="utf-8")
        for bad in ("import socket", "urllib", "requests", "http.client", "subprocess"):
            assert bad not in src, (f, bad)


def test_unknown_payload_key_rejected(tmp_path):
    r = _run("table.build", {"table": {"title": "x", "columns": ["a"], "rows": [[1]]}, "bogus": 1}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT"
