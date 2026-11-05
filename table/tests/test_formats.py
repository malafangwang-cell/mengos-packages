"""各格式内容正确：xlsx 用 openpyxl 读回，csv/md 看文本。"""
import io
import json
from pathlib import Path

import openpyxl

import table_tool

ROOT = Path(__file__).resolve().parents[1]
BOM = json.loads((ROOT / "samples" / "bom.json").read_text(encoding="utf-8"))


def _build(tmp, t, formats=("xlsx", "csv")):
    r = table_tool.run({"tool": "table.build", "payload": {"table": t, "formats": list(formats)}, "workdir": str(tmp)})
    assert r["ok"], r
    return r["output"], {f["role"]: f for f in r["output"]["files"]}


def test_xlsx_reads_back(tmp_path):
    out, files = _build(tmp_path, BOM)
    wb = openpyxl.load_workbook(tmp_path / files["table.excel"]["path"])
    names = [s["name"] for s in out["sheets"]]
    assert wb.sheetnames[: len(names)] == names
    assert wb.sheetnames[-1] == "说明"
    ws = wb[names[0]]
    assert ws.freeze_panes is not None and ws.auto_filter.ref
    formulas = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
    assert formulas, "公式列应写成 Excel 公式"
    vals = openpyxl.load_workbook(tmp_path / files["table.excel"]["path"], data_only=True)[names[0]]
    cached = [c.value for row in vals.iter_rows(min_row=2) for c in row]
    assert all(not isinstance(v, str) or not v.startswith("=") for v in cached)


def test_simple_formula_and_totals(tmp_path):
    t = {"title": "单价表", "columns": ["名称", {"title": "数量", "type": "integer"}, {"title": "单价", "type": "money"},
                                     {"title": "金额", "type": "money", "formula": "数量*单价"}],
         "rows": [["甲", 2, 10.5], ["乙", 3, 4]], "totals": ["金额"]}
    out, files = _build(tmp_path, t)
    ws = openpyxl.load_workbook(tmp_path / files["table.excel"]["path"]).active
    assert ws["D2"].value == "=B2*C2"
    assert ws["D4"].value == "=SUM(D2:D3)"
    cv = openpyxl.load_workbook(tmp_path / files["table.excel"]["path"], data_only=True).active
    assert cv["D2"].value == 21 and cv["D4"].value == 33
    assert out["sheets"][0]["totals"][0]["value"] == "33"


def test_csv_bom_crlf_and_one_file_per_sheet(tmp_path):
    out, _ = _build(tmp_path, BOM, ("csv",))
    csvs = [f for f in out["files"] if f["format"] == "csv"]
    assert len(csvs) == len(BOM["sheets"])
    raw = (tmp_path / csvs[0]["path"]).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw


def test_percent_points(tmp_path):
    t = {"title": "p", "columns": ["项", {"title": "占比", "type": "percent"}], "rows": [["a", 12.5], ["b", "7.5%"]]}
    out, files = _build(tmp_path, t, ("xlsx",))
    model = json.loads((tmp_path / files["table.model"]["path"]).read_text(encoding="utf-8"))
    vals = [r[1] for r in model["sheets"][0]["rows"]]
    assert vals == ["0.125", "0.075"]
    md = (tmp_path / files["table.text"]["path"]).read_text(encoding="utf-8")
    assert "12.5%" in md and "7.5%" in md


def test_export_from_build_record(tmp_path):
    out, _ = _build(tmp_path, BOM, ())
    rec = {"tool": "table.build", "args": {"table": BOM}, "output": out}
    (tmp_path / "x").mkdir()
    r = table_tool.run({"tool": "table.export", "payload": {"object": rec, "format": "xlsx"}, "workdir": str(tmp_path / "x")})
    assert r["ok"], r
    assert [f["format"] for f in r["output"]["files"]] == ["xlsx"]


def test_top_level_lang_shorthand(tmp_path):
    t = {"title": "p", "lang": "en", "columns": ["a"], "rows": [["x"]]}
    _, files = _build(tmp_path, t, ())
    model = json.loads((tmp_path / files["table.model"]["path"]).read_text(encoding="utf-8"))
    assert model["meta"]["lang"] == "en"
    r = table_tool.run({"tool": "table.build", "payload": {"table": {**t, "meta": {"lang": "zh-CN"}}}, "workdir": str(tmp_path)})
    assert not r["ok"] and r["error"]["where"] == "table.lang"


def test_sheet_level_sources_merge(tmp_path):
    t = {"title": "p", "sources": ["甲"], "sheets": [{"name": "a", "columns": ["x"], "rows": [["1"]], "sources": ["乙", "甲"], "assumptions": ["丙"]}]}
    _, files = _build(tmp_path, t, ())
    model = json.loads((tmp_path / files["table.model"]["path"]).read_text(encoding="utf-8"))
    assert model["sources"] == ["甲", "乙"] and model["assumptions"] == ["丙"]


def test_avg_decimals_and_integer_avg_display(tmp_path):
    t = {"title": "p", "columns": ["a", {"title": "n", "type": "number"}, {"title": "i", "type": "integer"}, {"title": "p", "type": "percent"}],
         "rows": [["x", 1, 1, 10], ["y", 2, 2, 12.5], ["z", 2, 2, 5]],
         "totals": [{"column": "n", "fn": "avg"}, {"column": "i", "fn": "avg"}, {"column": "p", "fn": "avg"}]}
    out, files = _build(tmp_path, t, ("xlsx",))
    assert [x["value"] for x in out["sheets"][0]["totals"]] == ["1.67", "1.67", "0.0917"]
    view = json.loads((tmp_path / files["table.view"]["path"]).read_text(encoding="utf-8"))
    assert view["sheets"][0]["totals"][2] == "1.67"
    ws = openpyxl.load_workbook(tmp_path / files["table.excel"]["path"]).active
    assert ws["C5"].number_format == "#,##0.00"
