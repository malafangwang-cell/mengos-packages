"""2.3.2 的包内核对（mengosv2 工单 P4；设计-模型指程序抄 §五“表格自动序号列”）。
table 2.2.0 起已有 numbering: seq（序号由工具编，行里不用写）；2.3.2 只在 table 字段说明里点出“序号”（P5 B2；引用写法 B1 暂缓），
执行体不改。这里钉住工单 P4 对序号列的验收：双跑一致；排序、插行、删行（整张表重写）后序号照规则重排；
序号不在入参里（模型写了也不用，出 formula_value_ignored 警告），所以不进证件账（08 PD-1e 只核入参的数据字段）。"""
import json

from test_220 import files, run

COLS = [{"key": "no", "title": "序号", "numbering": "seq"}, {"key": "n", "title": "名称"}, {"key": "q", "title": "数量", "type": "integer"}]


def view(tmp_path, rows, name):
    r, w = run("table.build", {"table": {"title": "t", "columns": COLS, "rows": rows}}, tmp_path, name)
    assert r["ok"], r
    return r, json.loads(files(r, w)["view"])["sheets"][0]


def col(v, j):
    return [row[j] for row in v["rows"]]


def test_seq_generated_and_deterministic(tmp_path):
    r1, v1 = view(tmp_path, [["甲", 3], ["乙", 5], ["丙", 2]], "a")
    r2, v2 = view(tmp_path, [["甲", 3], ["乙", 5], ["丙", 2]], "b")
    assert col(v1, 0) == ["1", "2", "3"] and v1["col_kinds"][0] == "numbering"
    assert r1["output"]["table_sha256"] == r2["output"]["table_sha256"] and v1 == v2


def test_seq_renumbers_after_sort_insert_delete(tmp_path):
    _, sort = view(tmp_path, [["丙", 2], ["甲", 3], ["乙", 5]], "sort")
    assert col(sort, 1) == ["丙", "甲", "乙"] and col(sort, 0) == ["1", "2", "3"]
    _, ins = view(tmp_path, [["甲", 3], ["丁", 7], ["乙", 5], ["丙", 2]], "ins")
    assert col(ins, 1) == ["甲", "丁", "乙", "丙"] and col(ins, 0) == ["1", "2", "3", "4"]
    _, dele = view(tmp_path, [["甲", 3], ["丙", 2]], "del")
    assert col(dele, 1) == ["甲", "丙"] and col(dele, 0) == ["1", "2"]


def test_seq_value_written_by_model_is_not_used(tmp_path):
    """序号列格里写了数：不用，照规则编，出警告；工具编的序号从不出现在入参里。"""
    r, v = view(tmp_path, [[9, "甲", 3], [8, "乙", 5]], "given")
    assert col(v, 0) == ["1", "2"]
    assert [w["code"] for w in r["output"]["warnings"]] == ["formula_value_ignored"]
