"""读取器与条件的边界用例。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from count_tool import run  # noqa: E402


def r(tool, payload, max_rows=50):
    return run({"tool": tool, "payload": payload}, max_rows=max_rows)


def err(tool, payload):
    x = r(tool, payload)
    assert x["ok"] is False and x["error"]["code"] == "BAD_INPUT", x
    return x["error"]["message"]


CAD = "#mengos-cad v1\n#单元 图幅 S3｜一层平面｜外接框 0,0,1,1\n#文字（x|y|图层|字高|内容）共 2 条\n1|2|T|5|含|竖线的文字\n3|4|T|5|普通\n#尺寸标注（类型|测量值|显示文字|端点1|端点2|图层）共 0 条\n"


def test_cad_last_column_absorbs_pipes_and_unit_label():
    o = r("count.rows", {"source": {"text": CAD, "reader": "mengos-cad-v1", "section": "文字"}, "where": [{"col": "内容", "op": "contains", "value": "|"}], "list": True})["output"]
    assert o["count"] == 1 and o["items"][0]["id"] == "S3/文字/1" and o["items"][0]["cells"]["内容"] == "含|竖线的文字"


def test_cad_needs_section_when_ambiguous_and_auto_when_single():
    o = r("count.rows", {"source": {"text": CAD, "reader": "mengos-cad-v1"}})["output"]
    assert o["source"]["section"] == "文字"
    assert "没有节" in err("count.rows", {"source": {"text": CAD, "reader": "mengos-cad-v1", "section": "图块插入"}})


def test_cad_rejects_unknown_text_and_mixed_units():
    assert "mengos-cad v1" in err("count.rows", {"source": {"text": "随便一段话", "reader": "mengos-cad-v1"}})
    other = CAD.replace("S3", "S4")
    assert "同一个单元" in err("count.rows", {"source": {"text": [CAD, other], "reader": "mengos-cad-v1"}})


def test_cad_row_with_too_few_cells_is_bad_input():
    bad = CAD.replace("3|4|T|5|普通", "3|4|T")
    assert "列数与表头不符" in err("count.rows", {"source": {"text": bad, "reader": "mengos-cad-v1", "section": "文字"}})


def test_summary_without_declared_count_needs_all_chunks():
    head = "#mengos-cad v1\n#单元 图块插入汇总\n#图块（名称|直接插入|含嵌套总数|直接插入所在单元分布|属性取值）\n"
    c1 = head + "#分块 1/2\nA|3|3|S1×3|\n"
    c2 = head + "#分块 2/2\nB|4|4|S1×4|\n"
    o = r("count.rows", {"source": {"text": [c2, c1], "reader": "mengos-cad-v1"}, "aggregate": [{"col": "直接插入", "fn": "sum"}]})["output"]
    assert o["count"] == 2 and o["aggregate"][0]["value"] == 7
    assert "分块又不全" in err("count.rows", {"source": {"text": [c1], "reader": "mengos-cad-v1"}})


def test_gfm_escaped_pipe_continuation_and_declared():
    t1 = "#mengos-cad v1\n#表 T1｜所在单元 S1｜位置 0,0｜4×2\n| 名称 | 规格 |\n| --- | --- |\n#分块 1/2｜表行 2–3\n| a | x\\|y |\n| b | z |\n"
    t2 = "#mengos-cad v1\n#表 T1｜所在单元 S1｜位置 0,0｜4×2\n| 名称 | 规格 |\n| --- | --- |\n#分块 2/2｜表行 4–4\n| c | w |\n"
    o = r("count.rows", {"source": {"text": [t1, t2], "reader": "gfm"}, "where": [{"col": "规格", "op": "eq", "value": "x|y"}]})["output"]
    assert o["count"] == 1 and o["source"]["rows_declared"] == 3 and o["source"]["unit"] == "T1"
    assert "不符" in err("count.rows", {"source": {"text": [t1], "reader": "gfm"}})


def test_numeric_compare_unparsed_rows_listed():
    o = r("count.rows", {"source": {"columns": ["v"], "rows": [[1], ["x"], ["2.5"], [None]]}, "where": [{"col": "v", "op": "ge", "value": 1}]})["output"]
    assert o["count"] == 2 and o["source"]["rows_unparsed"] == 2 and [u["id"] for u in o["unparsed"]] == ["行/2", "行/4"]


def test_eq_number_vs_string():
    src = {"columns": ["v"], "rows": [["2760"], ["2760.0"], ["02760"]]}
    assert r("count.rows", {"source": src, "where": [{"col": "v", "op": "eq", "value": 2760}]})["output"]["count"] == 3
    assert r("count.rows", {"source": src, "where": [{"col": "v", "op": "eq", "value": "2760"}]})["output"]["count"] == 1


def test_attribute_key():
    src = {"columns": ["名称", "属性"], "rows": [["A", "型号=X1;颜色=红"], ["A", "型号=X2"], ["A", ""]]}
    o = r("count.rows", {"source": src, "where": [{"col": "属性", "key": "型号", "op": "eq", "value": "X1"}]})["output"]
    assert o["count"] == 1


def test_exact_decimal_sum():
    src = {"columns": ["v"], "rows": [["0.1"], ["0.2"], ["0.3"]]}
    a = r("count.rows", {"source": src, "aggregate": [{"col": "v", "fn": "sum"}]})["output"]["aggregate"][0]
    assert a["value_text"] == "0.6" and a["value"] == 0.6


def test_bad_inputs():
    assert "不在表头" in err("count.rows", {"source": {"columns": ["a"], "rows": []}, "where": [{"col": "b", "op": "eq", "value": 1}]})
    assert "正则" in err("count.rows", {"source": {"columns": ["a"], "rows": []}, "where": [{"col": "a", "op": "regex", "value": "("}]})
    assert "之一" in err("count.rows", {"source": {"columns": ["a"], "rows": [], "text": "x", "reader": "gfm"}})
    assert "单元格数" in err("count.rows", {"source": {"columns": ["a", "b"], "rows": [["1"]]}})
    assert "未知工具" in r("count.nope", {})["error"]["message"]


def test_chain_undirected_and_cycle():
    src = {"columns": ["p", "q", "v"], "rows": [["0,0", "1,0", 1], ["2,0", "1,0", 1], ["2,0", "3,0", 1]]}
    o = r("count.series", {"source": src, "mode": "chain", "chain": {"from": "p", "to": "q", "value": "v"}})["output"]["chain"]
    assert o["count"] == 0 or all(c["segments"] < 3 for c in o["chains"])
    o = r("count.series", {"source": src, "mode": "chain", "chain": {"from": "p", "to": "q", "value": "v", "undirected": True}})["output"]["chain"]
    assert o["count"] == 1 and o["chains"][0]["segments"] == 3
    ring = {"columns": ["p", "q", "v"], "rows": [[0, 1, 1], [1, 2, 1], [2, 0, 1]]}
    o = r("count.series", {"source": ring, "mode": "chain", "chain": {"from": "p", "to": "q", "value": "v"}})["output"]["chain"]
    assert o["count"] == 1 and o["chains"][0]["closed"] is True and o["chains"][0]["segments"] == 3
