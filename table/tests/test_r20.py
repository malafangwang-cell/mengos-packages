"""r20（本地实验）：功能清单《表格引用与 COMPARE》补一 D1（黄底收窄）、D3（自检类核对项的话、核对项带提示）、D4（恒真核对项的记号）的单元验收。"""
import io

import table_tool
from checker import split_hint

FACTS = {"id": "facts", "name": "排布事实", "columns": [{"title": "项名", "type": "text"}, {"title": "取数/算式", "type": "text"},
                                                    {"title": "值", "type": "number", "required": True, "count": True}]}


def _facts(rows):
    return {**FACTS, "rows": rows}


def _bom(rows):
    return {"id": "bom", "name": "总清单", "columns": [{"title": "序号", "numbering": "seq"}, {"title": "产品名称", "type": "text"},
                                                     {"title": "数量", "type": "number", "required": True, "count": True},
                                                     {"title": "备注", "type": "text"}], "rows": rows}


def check(table, expect):
    r = table_tool.run({"tool": "table.check", "payload": {"table": table, "expect": expect}})
    assert r["ok"], r
    return r["output"]


def _export(table, expect, tmp_path):
    obj = {"kind": "produce-record", "tool": "table.build", "args": {"table": table}, **({"export_marks": {"expect": expect}} if expect is not None else {})}
    r = table_tool.run({"tool": "table.export", "payload": {"object": obj, "formats": ["xlsx"]}, "workdir": str(tmp_path)})
    assert r["ok"], r
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO((tmp_path / r["output"]["files"][0]["path"]).read_bytes()))
    marked = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.fill is not None and c.fill.fgColor is not None and str(c.fill.fgColor.rgb).upper().endswith("FFFF00"):
                    marked.setdefault(ws.title, set()).add((c.row, c.column))
    return wb, marked


# 排布事实：总长、列距是读出量（有出处）；列数是格公式；层段数没有出处；备用数没有任何核对项碰到
ROWS = [
    {"$id": "r1", "项名": "总长", "取数/算式": "主视图", "值": 9000},
    {"$id": "r2", "项名": "列距", "取数/算式": "主视图", "值": 3000},
    {"$id": "r3", "项名": "列数", "取数/算式": "总长 ÷ 列距", "值": {"$expr": "排布事实/总长/值 / 排布事实/列距/值"}},
    {"$id": "r4", "项名": "层段数", "取数/算式": "主视图", "值": {"$unaudited": 9}},
    {"$id": "r5", "项名": "备用数", "取数/算式": "图上", "值": 5},
    {"$id": "r6", "项名": "列数加一", "取数/算式": "", "值": {"$expr": "排布事实/列数/值 + 1"}},
    {"$id": "r7", "项名": "备用数加一", "取数/算式": "", "值": {"$expr": "排布事实/备用数/值 + 1"}},
]


def _cells(marked, row_ids):
    """排布事实里第几行（数据行从工作簿第 2 行起）的值格（第 3 列）是否标黄。"""
    return {rid: (i + 2, 3) in marked.get("排布事实", set()) for i, rid in enumerate(row_ids)}


# ---------------------------------------------------------------- D1
def test_d1_1_text_cells_never_yellow(tmp_path):
    t = {"title": "T", "sheets": [_facts(ROWS)]}
    for expect in (None, "cell 排布事实/列数/值 = 排布事实/总长/值 / 排布事实/列距/值", "cell 排布事实/备用数/值 = 6"):
        _, marked = _export(t, expect, tmp_path)
        assert all(col == 3 for (_, col) in marked.get("排布事实", set())), (expect, marked)


def test_d1_2_three_rules_not_yellow_3_others_yellow(tmp_path):
    t = {"title": "T", "sheets": [_facts(ROWS)]}
    expect = ("cell 排布事实/列数/值 = 排布事实/总长/值 / 排布事实/列距/值\ncell 排布事实/层段数/值 = 3 * 3\n"
              "cell 排布事实/列数加一/值 = 排布事实/总长/值 / 排布事实/列距/值 + 1")
    _, marked = _export(t, expect, tmp_path)
    got = _cells(marked, [r["$id"] for r in ROWS])
    assert got["r3"] is False        # 规则 1：核到且通过（列数）
    assert got["r4"] is False        # 规则 1：核到且通过，即便没有出处（层段数）
    assert got["r1"] is False and got["r2"] is False     # 规则 2：有出处、被通过的核对项读到（总长、列距）
    assert got["r6"] is False        # 规则 3：格公式，用到的格都不带标记（列数加一）
    assert got["r5"] is True         # 有出处但没有任何核对项碰到（备用数）
    assert got["r7"] is True         # 格公式引用了黄格（备用数加一）


def test_d1_3_unsourced_number_yellow(tmp_path):
    t = {"title": "T", "sheets": [_facts(ROWS)]}
    _, marked = _export(t, "cell 排布事实/列数/值 = 排布事实/总长/值 / 排布事实/列距/值", tmp_path)
    got = _cells(marked, [r["$id"] for r in ROWS])
    assert got["r4"] is True         # 直接写的数（没有出处）、没有核对项核到
    # 没有出处的数被通过的核对项读到也不算（规则 2 要“有出处”）
    t2 = {"title": "T", "sheets": [_facts([{"$id": "a", "项名": "甲", "值": {"$unaudited": 4}}, {"$id": "b", "项名": "乙", "值": 8}])]}
    _, m2 = _export(t2, "cell 排布事实/乙/值 = 排布事实/甲/值 * 2", tmp_path)
    assert (2, 3) in m2["排布事实"] and (3, 3) not in m2["排布事实"]


def test_d1_4_covered_but_failing_not_yellow(tmp_path):
    t = {"title": "T", "sheets": [_facts(ROWS)]}
    _, marked = _export(t, "cell 排布事实/备用数/值 = 6", tmp_path)
    assert _cells(marked, [r["$id"] for r in ROWS])["r5"] is False


def test_d1_reads_of_failing_check_do_not_count(tmp_path):
    t = {"title": "T", "sheets": [_facts([{"$id": "a", "项名": "甲", "值": 4}, {"$id": "b", "项名": "乙", "值": 9}])]}
    _, marked = _export(t, "cell 排布事实/乙/值 = 排布事实/甲/值 * 2", tmp_path)
    assert (2, 3) in marked["排布事实"]      # 甲只被一条没过的核对项读到：标黄


def test_d1_restating_check_does_not_vouch_for_inputs(tmp_path):
    # 恒真的核对项（就是列数的格公式）通过，不算“读到”总长、列距
    t = {"title": "T", "sheets": [_facts(ROWS[:3])]}
    _, marked = _export(t, "cell 排布事实/列数/值 = 排布事实/总长/值 / 排布事实/列距/值", tmp_path)
    assert (2, 3) in marked["排布事实"] and (3, 3) in marked["排布事实"] and (4, 3) not in marked["排布事实"]


def test_d1_no_checks_only_unsourced_and_derived(tmp_path):
    t = {"title": "T", "sheets": [_facts(ROWS)]}
    _, marked = _export(t, None, tmp_path)
    assert marked == {"排布事实": {(5, 3)}}   # 只有层段数（没有出处）；没有格公式引用它


def test_d1_legend_row_unchanged(tmp_path):
    t = {"title": "T", "sheets": [_facts(ROWS)]}
    wb, marked = _export(t, "cell 排布事实/列数/值 = 排布事实/总长/值 / 排布事实/列距/值", tmp_path)
    ws = wb["排布事实"]
    assert ws.cell(ws.max_row, 1).value == "标黄数字：未严格审计"


# ---------------------------------------------------------------- D3
PALLET = [
    {"$id": "p1", "项名": "托盘数", "值": 100},
    {"$id": "p2", "项名": "列数", "值": 3},
    {"$id": "p3", "项名": "层数", "值": 11},
    {"$id": "p4", "项名": "排数", "值": {"$expr": "排布事实/托盘数/值 / (排布事实/列数/值 * 排布事实/层数/值)"}},
    {"$id": "p5", "项名": "组数", "值": {"$expr": "排布事实/排数/值 / 2"}},
]
INT = "cell 排布事实/排数/值 = floor(排布事实/排数/值)"
HINT = "排数应为整数；层间距的段数只数一条竖向尺寸链上的（G3），主视图上的那条链最可靠。"


def test_d3_1_self_check_on_formula_names_inputs():
    out = check({"title": "T", "sheets": [_facts(PALLET)]}, INT)
    c = [x for x in out["checks"] if x["line"] == 1][0]
    assert c["verdict"] == "fail" and c.get("self") is True
    assert "把这一格改成它" not in c["message"]
    assert c["message"] == ("排布事实/排数/值 现为 3.0303030303，核对项‘" + INT + "’不过；这一格是算出来的，不要直接改它，"
                            "重新读它用到的读出量：排布事实/托盘数/值、排布事实/列数/值、排布事实/层数/值")
    # 追到底：组数的格公式经排数读到三件读出量
    out2 = check({"title": "T", "sheets": [_facts(PALLET)]}, "cell 排布事实/组数/值 = floor(排布事实/组数/值)")
    m = [x for x in out2["checks"] if x["line"] == 1][0]["message"]
    assert m.endswith("重新读它用到的读出量：排布事实/托盘数/值、排布事实/列数/值、排布事实/层数/值")


def test_d3_2_hint_appended_on_failure_only():
    line = INT + " # 提示：" + HINT
    out = check({"title": "T", "sheets": [_facts(PALLET)]}, line)
    c = [x for x in out["checks"] if x["line"] == 1][0]
    assert c["src"] == INT and c["hint"] == HINT
    assert c["message"].endswith("。提示：" + HINT)
    assert out["failed"][0].endswith("。提示：" + HINT)
    ok = [dict(r) for r in PALLET]
    ok[2] = {"$id": "p3", "项名": "层数", "值": 10}
    ok[0] = {"$id": "p1", "项名": "托盘数", "值": 90}
    out2 = check({"title": "T", "sheets": [_facts(ok)]}, line)
    c2 = [x for x in out2["checks"] if x["line"] == 1][0]
    assert c2["verdict"] == "pass" and "message" not in c2 and HINT not in str(out2["failed"])


def test_d3_3_non_self_check_message_unchanged():
    out = check({"title": "T", "sheets": [_facts(PALLET)]}, "cell 排布事实/组数/值 = 7")
    c = [x for x in out["checks"] if x["line"] == 1][0]
    assert "self" not in c
    assert c["message"].endswith("按规范它应等于 7，把这一格改成它")
    # 自检类、但被核的格不是格公式（直接写的数）：r21 起改为读出格的自检话（立法者 2026-11-24：自检类一律不说“把这一格改成它”，见 test_r21.py）
    t = [dict(r) for r in PALLET]
    t[3] = {"$id": "p4", "项名": "排数", "值": 3.5}
    c2 = [x for x in check({"title": "T", "sheets": [_facts(t)]}, INT)["checks"] if x["line"] == 1][0]
    assert c2["message"] == "排布事实/排数/值 现为 3.5，核对项‘" + INT + "’不过；重新读这一格"


def test_d3_hint_split_keeps_hash_in_text():
    assert split_hint('text 总清单/背拉接地件/规格 = "10#角钢*150L"') == ('text 总清单/背拉接地件/规格 = "10#角钢*150L"', None)
    assert split_hint("cell a/b/c = 1 # 提示：看图") == ("cell a/b/c = 1", "看图")
    assert split_hint("cell a/b/c = 1  #提示:看图") == ("cell a/b/c = 1", "看图")


# ---------------------------------------------------------------- D4
def test_d4_restates_flag_and_inputs():
    expect = "cell 排布事实/排数/值 = 排布事实/托盘数/值 / (排布事实/列数/值 * 排布事实/层数/值)\n" + INT + "\ncell 排布事实/托盘数/值 = 100"
    out = check({"title": "T", "sheets": [_facts(PALLET)]}, expect)
    cs = {x["line"]: x for x in out["checks"] if x["line"] > 0}
    assert cs[1]["verdict"] == "pass" and cs[1].get("restates") is True
    assert [p["label"] for p in cs[1]["inputs"]] == ["排布事实/托盘数/值", "排布事实/列数/值", "排布事实/层数/值"]
    assert "restates" not in cs[2] and "restates" not in cs[3]
    # 同一个式子换个写法（多空格、@行id.列）也认
    out2 = check({"title": "T", "sheets": [_facts(PALLET)]}, "cell 排布事实/排数/值 = 排布事实/托盘数/值/(排布事实/列数/值*排布事实/层数/值)")
    assert [x for x in out2["checks"] if x["line"] == 1][0].get("restates") is True
    # 被核的格是直接写的数：不是恒真的
    t = [dict(r) for r in PALLET]
    t[3] = {"$id": "p4", "项名": "排数", "值": 16}
    out3 = check({"title": "T", "sheets": [_facts(t)]}, expect.splitlines()[0])
    c3 = [x for x in out3["checks"] if x["line"] == 1][0]
    assert c3["verdict"] == "fail" and "restates" not in c3 and "inputs" not in c3
