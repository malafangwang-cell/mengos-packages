"""r19（本地实验）：功能清单《表格引用与 COMPARE》A1–A4、A6、B2、B3 的单元验收。"""
import io
import json
import zipfile

import pytest

import model
import table_tool
from checker import run_checks

FACTS = {"id": "facts", "name": "排布事实", "columns": [{"title": "项名", "type": "text"}, {"title": "取数/算式", "type": "text"},
                                                    {"title": "值", "type": "number", "required": True, "count": True}]}


def _facts(rows):
    return {**FACTS, "rows": rows}


def _bom(rows):
    return {"id": "bom", "name": "总清单", "columns": [{"title": "序号", "numbering": "seq"}, {"title": "产品名称", "type": "text"},
                                                     {"title": "数量", "type": "integer", "required": True, "count": True},
                                                     {"title": "备注", "type": "text"}], "rows": rows}


def build(table, tmp_path):
    r = table_tool.run({"tool": "table.build", "payload": {"table": table}, "workdir": str(tmp_path)})
    assert r["ok"], r
    return r["output"]


def check(table, expect):
    r = table_tool.run({"tool": "table.check", "payload": {"table": table, "expect": expect}})
    assert r["ok"], r
    return r["output"]


def values(table):
    t = model.normalize(table)
    return {(sh.name, model.row_name(t, sh, ri), sh.columns[j].title): v
            for sh in t.sheets for ri, r in enumerate(sh.rows) for j, v in enumerate(r)}


BASE = {"title": "T", "sheets": [
    _facts([{"$id": "f1", "项名": "总长", "值": 30000}, {"$id": "f2", "项名": "列距", "值": 3000},
            {"$id": "f3", "项名": "列数", "取数/算式": "G2", "$count": {"值": {"$expr": "排布事实/总长/值 / 排布事实/列距/值"}}}]),
    _bom([{"$id": "b1", "产品名称": "下立柱", "$count": {"数量": {"$expr": "排布事实/列数/值 * 2"}}}])]}


# ─────────── A1 ───────────
def test_a1_1_cross_sheet_path_refs_in_count_cells(tmp_path):
    out = build(BASE, tmp_path)
    assert out["unfilled"] == []
    v = values(BASE)
    assert v[("排布事实", "列数", "值")] == 10 and v[("总清单", "下立柱", "数量")] == 20


def test_a1_2_same_expression_as_check_item_passes():
    expect = "cell 总清单/下立柱/数量 = 排布事实/列数/值 * 2\ncell 排布事实/列数/值 = 排布事实/总长/值 / 排布事实/列距/值"
    out = check(BASE, expect)
    assert [c["verdict"] for c in out["checks"] if c["line"] > 0] == ["pass", "pass"]


def test_a1_3_increment_changes_follow(tmp_path):
    t = json.loads(json.dumps(BASE))
    t["sheets"][0]["rows"][0]["值"] = 60000          # 只改“总长”一格（合并后的整件）
    v = values(t)
    assert v[("排布事实", "列数", "值")] == 20 and v[("总清单", "下立柱", "数量")] == 40
    m = model.normalize(t).to_json()                   # 算式留在表里
    assert {"$expr": "排布事实/列数/值 * 2"} in m["sheets"][1]["rows"][0]["$count"].values()


@pytest.mark.parametrize("expr,needle", [
    ("排布事实/托盘数/值 * 2", "算式里的 排布事实/托盘数/值 在表里没有这一行"),
    ("排布事实/列数/重量 * 2", "算式里的 排布事实/列数/重量 在表里没有这一列"),
    ("排布事实/空格/值 * 2", "它要用的 排布事实/空格/值 还是空的"),
    ("排布事实/同名/值 * 2", "排布事实/同名/值 在表里有 2 行同名"),
])
def test_a1_4_bad_refs_only_cost_that_cell(tmp_path, expr, needle):
    t = json.loads(json.dumps(BASE))
    t["sheets"][0]["rows"] += [{"$id": "e1", "项名": "空格"}, {"$id": "d1", "项名": "同名", "值": 1}, {"$id": "d2", "项名": "同名", "值": 2}]
    t["sheets"][1]["rows"].append({"$id": "b2", "产品名称": "上立柱", "$count": {"数量": {"$expr": expr}}})
    out = build(t, tmp_path)
    assert any(u.startswith("总清单/上立柱/数量 算不出：") and needle in u for u in out["unfilled"]), out["unfilled"]
    assert values(t)[("总清单", "下立柱", "数量")] == 20           # 其余格照常


def test_a1_4_cycle(tmp_path):
    t = json.loads(json.dumps(BASE))
    t["sheets"][1]["rows"] += [{"$id": "c1", "产品名称": "甲", "数量": {"$expr": "总清单/乙/数量 + 1"}},
                               {"$id": "c2", "产品名称": "乙", "数量": {"$expr": "总清单/甲/数量 + 1"}}]
    out = build(t, tmp_path)
    assert "总清单/甲/数量 算不出：这几格互相引用成了环：总清单/甲/数量、总清单/乙/数量" in out["unfilled"]


def test_a1_5_old_at_form_still_works(tmp_path):
    t = {"title": "T", "columns": [{"title": "名称", "type": "text"}, {"title": "数量", "type": "integer"}],
         "rows": [{"$id": "r1", "名称": "a", "数量": 3}, {"$id": "r2", "名称": "b", "数量": {"$expr": "@r1.数量*2"}}]}
    build(t, tmp_path)
    assert values(t)[("T", "b", "数量")] == 6


def test_a1_functions_are_the_checker_set():
    t = json.loads(json.dumps(BASE))
    t["sheets"][0]["rows"].append({"$id": "q", "项名": "根", "值": {"$expr": "sqrt(排布事实/列数/值 * 10) + floor(2.7) + ceiling(0.2) + round(1.25, 1) + rounddown(1.9) + roundup(1.1) + min(1, 2) + max(1, 2) + abs(-1)"}})
    v = values(t)[("排布事实", "根", "值")]
    assert v == 10 + 2 + 1 + model.Decimal("1.3") + 1 + 2 + 1 + 2 + 1
    out = check(t, "cell 排布事实/根/值 = sqrt(排布事实/列数/值 * 10) + floor(2.7) + ceiling(0.2) + round(1.25, 1) + rounddown(1.9) + roundup(1.1) + min(1, 2) + max(1, 2) + abs(-1)")
    assert [c["verdict"] for c in out["checks"] if c["line"] > 0] == ["pass"]


# ─────────── A2 ───────────
def test_a2_table_declares_no_attachment_positions():
    reg = open(model.__file__.replace("model.py", "registration.json"), encoding="utf-8").read()
    assert "x-mengos-attachment" not in reg


# ─────────── A4 ───────────
def test_a4_trace_to_deepest_empty_cell(tmp_path):
    t = {"title": "T", "sheets": [
        _facts([{"$id": "a", "项名": "托盘数"}, {"$id": "b", "项名": "排数", "值": {"$expr": "排布事实/托盘数/值 / 10"}}]),
        _bom([{"$id": "x", "产品名称": "下立柱", "数量": {"$expr": "排布事实/排数/值 * 2"}}])]}
    out = build(t, tmp_path)
    assert "总清单/下立柱/数量 算不出：它要用的 排布事实/排数/值 还是空的（一路追到：排布事实/托盘数/值）" in out["unfilled"]
    assert not any(u == "总清单/下立柱/数量 未填" for u in out["unfilled"])


# ─────────── A6 ───────────
def test_a6_same_label_in_check_unfilled_and_label_function(tmp_path):
    t = {"title": "T", "sheets": [_facts([{"$id": "a", "项名": "列数"}])]}
    out = build(t, tmp_path)
    chk = check(t, "cell 排布事实/列数/值 = 10")
    tm = model.normalize(t)
    label = model.cell_label(tm, tm.sheets[0], 0, 2)
    assert label == "排布事实/列数/值"
    assert out["unfilled"] == [f"{label} 未填"]
    assert chk["failed"][0].startswith(f"{label} 还是空的")
    for s in out["unfilled"] + chk["failed"]:
        assert "/table/sheets/" not in s and "@" not in s


# ─────────── B2 ───────────
def test_b2_bad_cell_only_costs_that_cell(tmp_path):
    t = {"title": "T", "columns": [{"title": "名称", "type": "text"}, {"title": "数量", "type": "integer"}, {"title": "备注", "type": "text"}],
         "rows": [{"$id": "r1", "名称": "a", "数量": {"value": 3}, "备注": "x"}, {"$id": "r2", "名称": "b", "数量": 2.5},
                  {"$id": "r3", "名称": "c", "$count": {"数量": {"$count": {"数量": 1}}}}]}
    out = build(t, tmp_path)
    assert len([u for u in out["unfilled"] if "没有收" in u]) == 3, out["unfilled"]
    assert values(t)[("T", "a", "备注")] == "x"


# ─────────── B3 ───────────
def _export(table, expect, tmp_path):
    obj = {"kind": "produce-record", "tool": "table.build", "args": {"table": table}, **({"export_marks": {"expect": expect}} if expect is not None else {})}
    r = table_tool.run({"tool": "table.export", "payload": {"object": obj, "formats": ["xlsx"]}, "workdir": str(tmp_path)})
    assert r["ok"], r
    data = (tmp_path / r["output"]["files"][0]["path"]).read_bytes()
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data))
    marked = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.fill is not None and c.fill.fgColor is not None and str(c.fill.fgColor.rgb).upper().endswith("FFFF00"):
                    marked.setdefault(ws.title, set()).add((c.row, c.column))
    return wb, marked, data


def test_b3_1_unsourced_number_and_formula_reading_it_are_yellow(tmp_path):
    t = {"title": "T", "sheets": [
        _facts([{"$id": "a", "项名": "列数", "值": {"$unaudited": 10}}]),
        _bom([{"$id": "x", "产品名称": "下立柱", "数量": {"$expr": "排布事实/列数/值 * 2"}}, {"$id": "y", "产品名称": "上立柱", "数量": 7}])]}
    wb, marked, _ = _export(t, None, tmp_path)
    assert marked == {"排布事实": {(2, 3)}, "总清单": {(2, 3)}}
    assert wb["排布事实"].cell(3, 1).value == "标黄数字：未严格审计"
    assert wb["总清单"].cell(4, 1).value == "标黄数字：未严格审计"


def test_b3_2_coverage(tmp_path):
    t = {"title": "T", "sheets": [_bom([{"$id": "x", "产品名称": "下立柱", "数量": 20}, {"$id": "y", "产品名称": "上立柱", "数量": 7},
                                        {"$id": "z", "产品名称": "垫板"}])]}
    expect = "cell 总清单/下立柱/数量 = 20\ncell 总清单/上立柱/数量 = 8"
    wb, marked, _ = _export(t, expect, tmp_path)
    m = marked.get("总清单", set())                     # r20：这张表没有黄格时没有这个键
    assert (2, 3) not in m and (3, 3) not in m          # 核到且过、核到没过：都不标
    assert (4, 3) not in m                              # 空格不标
    assert (2, 2) not in m and (4, 2) not in m          # r20（补一 D1）盖过 B3：文字格一律不标（原为“没被核到而有值的格标黄”）
    assert (2, 1) not in m                              # 编号列不标


def test_b3_4_no_checks_only_unsourced(tmp_path):
    t = {"title": "T", "sheets": [_bom([{"$id": "x", "产品名称": "下立柱", "数量": 20}])]}
    wb, marked, _ = _export(t, None, tmp_path)
    assert marked == {}
    assert all(c.value != "标黄数字：未严格审计" for row in wb["总清单"].iter_rows() for c in row)


def test_b3_5_6_legend_only_row_and_no_notes_entry(tmp_path):
    t = {"title": "T", "sheets": [_bom([{"$id": "x", "产品名称": "下立柱", "数量": {"$unaudited": 20}}]),
                                  {**_bom([{"$id": "y", "产品名称": "环", "数量": 1}]), "id": "b2", "name": "清单二"}],
         "sources": ["图"]}
    wb, marked, data = _export(t, None, tmp_path)
    assert wb["总清单"].cell(3, 1).value == "标黄数字：未严格审计"
    assert wb["清单二"].max_row == 2
    notes = wb["说明"]
    assert all("未严格审计" not in str(c.value) for row in notes.iter_rows() for c in row)


def test_b3_7_8_label_not_in_build_receipt_nor_signature(tmp_path):
    t = {"title": "T", "sheets": [_bom([{"$id": "x", "产品名称": "下立柱", "数量": {"$unaudited": 20}}])]}
    out = build(t, tmp_path)
    s = json.dumps(out, ensure_ascii=False)
    assert "未严格审计" not in s and "标黄" not in s and "unaudited" not in s
    reg = open(model.__file__.replace("model.py", "registration.json"), encoding="utf-8").read()
    assert "$unaudited" not in reg and "unaudited" not in reg


def test_b1_registration_has_no_calc_examples_and_no_old_form():
    reg = open(model.__file__.replace("model.py", "registration.json"), encoding="utf-8").read()
    assert "$calc" not in reg and "@行id" not in reg
    assert reg.count("用 表名/行名/列名 指别的格") == 3
