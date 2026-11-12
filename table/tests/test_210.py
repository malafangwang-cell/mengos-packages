"""2.1.0 的包内核对（执行令《首发后-table包2.1.0》）：C1 样式跟着行走、C3 15 位有效数字与双精度检测、C4 精度口径 b、
G1–G5 的模型与导出要点。逐条对照测试集的金样在 golden_cases.json（tools/make_goldens.py），这里补金样不便表达的性质。"""
import io
import json
import zipfile
from decimal import Decimal

import jsonschema
import openpyxl
import pytest

import formula as F
import model
import render
import table_tool
from contribution_ref import merge, skeleton, touched_keys

REG = json.loads((model.__file__ and open(__import__("pathlib").Path(model.__file__).with_name("registration.json"), encoding="utf-8").read()))
UNITS = {u["tool_id"]: u for u in REG["units"]}
BUILD = UNITS["table.build"]["signature"]["input_schema"]
COLS = [{"key": "item", "title": "品名"}, {"key": "qty", "title": "数量", "type": "integer"},
        {"key": "price", "title": "单价", "type": "money"}, {"key": "amt", "title": "金额", "type": "money", "formula": "数量 * 单价"}]


def run(tool, payload, tmp_path, name="w"):
    w = tmp_path / name
    w.mkdir()
    r = table_tool.run({"tool": tool, "payload": payload, "workdir": str(w)})
    return r, w


def files(r, w):
    return {f["format"]: (w / f["path"]).read_bytes() for f in r["output"]["files"]}


def view(r, w):
    return json.loads(files(r, w)["view"])


# ───────────────────────── C1 样式跟着行走 ─────────────────────────
def test_display_key_is_declared_not_data_and_rows_stay_data():
    t = BUILD["properties"]["table"]["properties"]
    for rows in (t["rows"], t["sheets"]["items"]["properties"]["rows"]):
        assert rows["x-mengos-data"] is True and rows["x-mengos-merge"] == {"mode": "append"}
        obj = rows["items"]["oneOf"][1]
        assert obj["properties"][model.DISPLAY_KEY]["x-mengos-display"] is True
        assert "x-mengos-data" not in json.dumps(obj["properties"][model.DISPLAY_KEY])
    s = json.dumps(BUILD, ensure_ascii=False)
    assert "cell_styles" not in s and '"rows": [' not in s     # 没有按行号寻址的样式字段（17 TL-30 v0.2.98）


def test_palette_names_cannot_be_read_as_numbers():
    """样式在数据字段 rows 之下：引擎的证件账若不认 x-mengos-display，也不会把颜色当成没有证件的数（08 PD-1e）。"""
    for n in model.COLOR_NAMES:
        with pytest.raises(ValueError):
            float(n)


def test_styles_follow_rows_through_engine_append_merge(tmp_path):
    """分两批追加的行各带 $style：引擎按 append 合并后，样式仍在原来那一行上（不按行号，所以追加、排序都不用平移）。"""
    first = {"table": {"title": "采购", "sheets": [{"id": "p", "name": "采购", "columns": COLS, "totals": ["金额"],
                                                    "rows": [{"品名": "办公桌", "数量": 12, "单价": 850}]}]}}
    d1 = {"table": {"sheets": [{"id": "p", "rows": [{"品名": "投影仪", "数量": 1, "单价": 12800,
                                                       "$style": {"cells": {"单价": {"fill": "黄"}}}}]}]}}
    assert touched_keys(BUILD, d1) == {"table.sheets#p.rows+"}
    jsonschema.validate({"base": "v-1", **d1}, BUILD)
    merged = merge(BUILD, first, d1)
    sk = skeleton(BUILD, merged, True)
    assert "$style" not in sk                                    # 骨架只数行，样式不出现在骨架里
    r, w = run("table.build", merged, tmp_path)
    assert r["ok"], r
    v = view(r, w)
    assert v["sheets"][0]["cell_styles"] == [[1, 2, 0]] and v["sheets"][0]["rows"][1][0] == "投影仪"


def test_display_round_trips_through_the_model(tmp_path):
    """表模型（.table.json）原样带着 $style 与规则；从表模型再导出，表的 sha 与产出台数据不变。"""
    t = {"title": "采购", "columns": COLS, "totals": ["金额"], "header_style": {"fill": "深蓝", "color": "白"},
         "rules": [{"when": "金额 > 10000", "style": {"color": "红"}}],
         "row_styles": [{"kind": "total", "style": {"bold": True}}],
         "rows": [["办公桌", 12, 850], {"品名": "投影仪", "数量": 1, "单价": 12800, "$style": {"row": {"fill": "浅黄"}}}]}
    r, w = run("table.build", {"table": t}, tmp_path, "b")
    assert r["ok"], r
    m = json.loads(files(r, w)["json"])
    r2, w2 = run("table.export", {"object": m, "formats": ["json", "xlsx"]}, tmp_path, "e")
    assert r2["ok"], r2
    assert r2["output"]["table_sha256"] == r["output"]["table_sha256"]
    t2 = model.normalize(m)
    assert render.to_view(t2) == view(r, w)


def test_check_and_export_accept_tables_with_styles(tmp_path):
    t = {"title": "采购", "columns": [*COLS[:2], {**COLS[2], "style": {"bold": True}}, COLS[3]],
         "rows": [{"品名": "桌", "数量": 1, "单价": 5, "$style": {"row": {"fill": "灰"}}}], "rules": [{"when": "数量 > 0", "style": {"italic": True}}]}
    for tid, payload in (("table.check", {"table": t, "expect": "rows min=1"}), ("table.export", {"table": t, "formats": ["csv", "md"]})):
        jsonschema.validate(payload, UNITS[tid]["signature"]["input_schema"])
        r, w = run(tid, payload, tmp_path, tid)
        assert r["ok"], r
    csv = files(r, w)["csv"].decode("utf-8-sig")
    assert csv == "品名,数量,单价,金额\r\n桌,1,5.00,5.00\r\n"               # CSV 只放值，样式不进去


# ───────────────────────── C3 15 位有效数字与双精度检测 ─────────────────────────
@pytest.mark.parametrize("x,want", [("5869050.000000001", "5869050.00000000"), ("0", "0"), ("1786719.0000000002", "1786719.00000000"),
                                    ("0.1234567890123456789", "0.123456789012346"), ("-99.000000000000014", "-99.0000000000000")])
def test_sig_rounds_to_15_significant_digits(x, want):
    assert str(F.sig(Decimal(x))) == want


def test_old_round_is_not_normalized_and_new_functions_are():
    env = {"a": Decimal(1) / Decimal(3) * 3}       # 0.999…（34 位）
    node = F.parse("roundup(a)", lambda n: n)
    assert F.evaluate(node, env) == 1                # 先归整到 15 位，得 1，不是 1.000…→ 进位到 1 以外的数
    node = F.parse("round(a, 2)", lambda n: n)
    assert F.evaluate(node, env) == Decimal("1.00")


def test_excel_side_normalizes_discontinuous_arguments_and_comparisons():
    kinds = {"a": "num", "b": "num", "d": "date", "t": "text"}
    cell = {"a": "A2", "b": "B2", "d": "C2", "t": "D2"}.get
    assert F.to_excel(F.parse("roundup(a * 1.1)", lambda n: n), cell, kinds) == \
        "ROUNDUP(ROUND((A2*1.1),14-INT(LOG10(ABS((A2*1.1))+((A2*1.1)=0)))),0)"
    assert F.to_excel(F.parse("ceiling(a, 50)", lambda n: n), cell, kinds) == "CEILING(ROUND(A2,14-INT(LOG10(ABS(A2)+(A2=0)))),50)"
    assert F.to_excel(F.parse('d > "2026-11-20"', lambda n: n), cell, kinds) == "C2>DATE(2026,11,20)"
    assert F.to_excel(F.parse('t = "宏达家具"', lambda n: n), cell, kinds) == 'D2="宏达家具"'
    assert F.to_excel(F.parse("a > 100%", lambda n: n), cell, kinds) == "ROUND(A2,14-INT(LOG10(ABS(A2)+(A2=0))))>1"
    # 旧函数的 Excel 写法不变（2.0.x 金样 b_formula_excel、b_div_zero 同此）
    assert F.to_excel(F.parse("round(a / b, 2)", lambda n: n), cell, kinds) == "ROUND(A2/B2,2)"


def test_float_check_flags_boundary_cells_only(tmp_path):
    t = {"title": "边界", "columns": [{"key": "n", "title": "基数", "type": "integer"}, {"key": "k", "title": "系数", "type": "number"},
                                    {"title": "取整", "type": "integer", "formula": "roundup(基数 * 系数)"},
                                    {"title": "乘", "type": "number", "formula": "基数 * 系数"}],
         "rows": [[5335500, 1.1], [48, 1.03], [100, 1.5]]}
    r, w = run("table.build", {"table": t}, tmp_path)
    ws = [x for x in r["output"]["warnings"] if x["code"] == "excel_float"]
    assert len(ws) == 1 and "边界!C2" in ws[0]["message"] and "5869051" in ws[0]["message"]   # 连续的乘法不告警


def test_rule_condition_float_check(tmp_path):
    t = {"title": "比较", "columns": [{"key": "a", "title": "甲", "type": "number"}, {"key": "b", "title": "乙", "type": "number"}],
         "rows": [[0.1, 0.3], [5, 1]], "rules": [{"when": "甲 * 3 > 乙", "style": {"color": "红"}}]}
    r, w = run("table.build", {"table": t}, tmp_path)
    assert r["ok"]
    assert [x["code"] for x in r["output"]["warnings"]] == ["excel_float"]   # 0.1×3 在双精度里是 0.30000000000000004 > 0.3
    assert view(r, w)["sheets"][0]["cell_styles"] == [[1, 0, 0], [1, 1, 0]]   # 产出台按十进制：第 1 行不命中


# ───────────────────────── C4 精度口径 b ─────────────────────────
def test_round_wrapper_matches_row_rounding(tmp_path):
    t = {"title": "吨", "columns": [{"key": "kg", "title": "重", "type": "number"},
                                   {"title": "吨", "type": "number", "decimals": 3, "formula": "重 / 1000"},
                                   {"title": "件", "type": "integer", "formula": "重 / 7"}],
         "rows": [[892.8], [54.24]], "totals": ["重", "吨"]}
    r, w = run("table.build", {"table": t}, tmp_path)
    x = files(r, w)["xlsx"]
    wb = openpyxl.load_workbook(io.BytesIO(x))
    assert wb.active["B2"].value == '=IFERROR(ROUND(A2/1000,3),"")'
    assert wb.active["C2"].value == '=IFERROR(ROUND(A2/7,0),"")'
    assert wb.active["B4"].value == "=ROUND(SUM(B2:B3),3)"
    m = json.loads(files(r, w)["json"])
    assert m["sheets"][0]["rows"][0][1] == "0.893" and m["sheets"][0]["rows"][0][2] == "128"


# ───────────────────────── G2 写法与报错 ─────────────────────────
@pytest.mark.parametrize("f,msg", [
    ("if(数量 > 1, 2, 3)", "不收数字常数"), ("数量 > 1", "结果是条件"), ("品名 * 2", "只能用于数"),
    ("品名 > \"a\"", "文字只能比是否相等"), ("1 < 数量 < 3", "比较不能连写"), ("ceiling(数量, 0)", "大于 0"),
    ("total(数量 + 1)", "一列的名字"), ("if(数量, \"a\", \"b\")", "第一个参数要是条件"),
])
def test_formula_errors_name_the_problem(f, msg, tmp_path):
    t = {"title": "T", "columns": [{**COLS[0], "type": "text"}, *COLS[1:], {"title": "新", "type": "number", "formula": f}], "rows": [["桌", 1, 5]]}
    r, _ = run("table.build", {"table": t}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and msg in r["error"]["message"], r


def test_empty_operands_make_empty_results_and_excel_guards_them(tmp_path):
    t = {"title": "空", "columns": [{"key": "a", "title": "甲", "type": "number"}, {"key": "b", "title": "乙", "type": "number"},
                                   {"title": "大", "type": "text", "formula": 'if(甲 > 乙, "甲大", "")'}],
         "rows": [[1, None], [3, 2]]}
    r, w = run("table.build", {"table": t}, tmp_path)
    m = json.loads(files(r, w)["json"])
    assert [row[2] for row in m["sheets"][0]["rows"]] == [None, "甲大"]
    wb = openpyxl.load_workbook(io.BytesIO(files(r, w)["xlsx"]))
    assert wb.active["C2"].value.startswith("=IF(COUNT(A2,B2)=2,IF(")


# ───────────────────────── G3 ─────────────────────────
def test_formula_total_with_missing_referenced_total_is_blank(tmp_path):
    t = {"title": "T", "columns": [{"key": "a", "title": "预算", "type": "money"}, {"key": "b", "title": "实际", "type": "money"},
                                  {"title": "率", "type": "percent", "decimals": 1, "formula": "实际 / 预算"}],
         "rows": [[100, 90]], "totals": ["实际", {"column": "率", "fn": "formula"}]}
    r, w = run("table.build", {"table": t}, tmp_path)
    assert r["output"]["sheets"][0]["totals"][1] == {"column": "率", "fn": "formula", "value": None}
    wb = openpyxl.load_workbook(io.BytesIO(files(r, w)["xlsx"]))
    assert wb.active["C3"].value is None                     # 预算没有合计，Excel 里也留空，不写会被当成 0 的公式


def test_formula_total_rejected_for_non_formula_columns(tmp_path):
    t = {"title": "T", "columns": COLS, "rows": [["桌", 1, 5]], "totals": [{"column": "单价", "fn": "formula"}]}
    r, _ = run("table.build", {"table": t}, tmp_path)
    assert not r["ok"] and r["error"]["where"] == "table.totals[0].fn"


# ───────────────────────── G1 ─────────────────────────
def test_rules_never_touch_the_totals_row(tmp_path):
    t = {"title": "T", "columns": COLS, "rows": [["桌", 20, 850]], "totals": ["金额"], "rules": [{"when": "金额 > 1", "apply_to": "row", "style": {"fill": "红"}}]}
    r, w = run("table.build", {"table": t}, tmp_path)
    v = view(r, w)["sheets"][0]
    assert "totals_styles" not in v and all(c[0] == 0 for c in v["cell_styles"])
    sheet = zipfile.ZipFile(io.BytesIO(files(r, w)["xlsx"])).read("xl/worksheets/sheet1.xml").decode()
    assert '<conditionalFormatting sqref="A2:D2">' in sheet       # 范围只含数据行，不含合计行 3


def test_no_always_true_rules_are_written(tmp_path):
    """C2 退路：不写恒真规则（LibreOffice 实测不按属性合并，readings/table-2.1.0-cf/）。"""
    t = {"title": "T", "columns": COLS, "rules": [{"when": "金额 > 1", "style": {"fill": "红"}}],
         "rows": [{"品名": "桌", "数量": 2, "单价": 850, "$style": {"cells": {"金额": {"fill": "黄"}}}}]}
    r, w = run("table.build", {"table": t}, tmp_path)
    sheet = zipfile.ZipFile(io.BytesIO(files(r, w)["xlsx"])).read("xl/worksheets/sheet1.xml").decode()
    assert "TRUE()" not in sheet and sheet.count("<cfRule") == 1
    assert view(r, w)["sheets"][0]["styles"] == [{"fill": "#FF0000", "fill_dark": "#8E1B1B"}]


def test_rules_limit_and_whole_replacement(tmp_path):
    many = [{"when": f"数量 > {i}", "style": {"bold": True}} for i in range(model.MAX_RULES + 1)]
    r, _ = run("table.build", {"table": {"title": "T", "columns": COLS, "rows": [], "rules": many}}, tmp_path)
    assert not r["ok"] and r["error"]["where"] == "table.rules"
    t = BUILD["properties"]["table"]["properties"]
    assert "x-mengos-merge" not in t["rules"] and "x-mengos-merge" not in t["sheets"]["items"]["properties"]["rules"]   # 不标 by-id，整组替换


def test_english_color_aliases_normalize_to_palette_names(tmp_path):
    t = {"title": "T", "columns": [{"title": "甲", "style": {"fill": "LightYellow", "color": "navy"}}], "rows": [["x"]]}
    r, w = run("table.build", {"table": t}, tmp_path)
    m = json.loads(files(r, w)["json"])
    assert m["sheets"][0]["columns"][0]["style"] == {"fill": "浅黄", "color": "深蓝"}


def test_notes_sheet_lists_rules_in_order(tmp_path):
    t = {"title": "T", "columns": COLS, "rows": [["桌", 2, 850]],
         "rules": [{"when": "金额 > 1000", "style": {"color": "红"}}, {"when": "数量 >= 2", "apply_to": "row", "style": {"bold": True}}]}
    r, w = run("table.build", {"table": t}, tmp_path)
    wb = openpyxl.load_workbook(io.BytesIO(files(r, w)["xlsx"]))
    notes = [c.value for c in wb["说明"]["B"]]
    assert "规则 1：金额 > 1000 → 金额红字" in notes and "规则 2：数量 ≥ 2 → 整行加粗" in notes


# ───────────────────────── G5 ─────────────────────────
@pytest.mark.parametrize("fmt,shown", [("YYYY-MM-DD", "2026-01-05"), ("YYYY/MM/DD", "2026/01/05"), ("YYYY年M月D日", "2026年1月5日"),
                                       ("M月D日", "1月5日"), ("YYYY.MM.DD", "2026.01.05")])
def test_date_formats(fmt, shown, tmp_path):
    t = {"title": "T", "columns": [{"title": "日", "type": "date", "date_format": fmt}], "rows": [["2026-01-05"]]}
    r, w = run("table.build", {"table": t, "formats": ["xlsx", "csv"]}, tmp_path)
    f = files(r, w)
    assert view(r, w)["sheets"][0]["rows"][0][0] == shown
    assert f["csv"].decode("utf-8-sig").endswith("2026-01-05\r\n")
    wb = openpyxl.load_workbook(io.BytesIO(f["xlsx"]))
    assert wb.active["A2"].is_date
