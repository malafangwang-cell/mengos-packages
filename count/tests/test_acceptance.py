"""设计-确定性计数工具-2026-11-18 §八 的验收用例（合成夹具，不用真图）。

夹具 tests/fixtures/*.units.json 是 mengosv2 vetc/src/cadx.py 对 vetc/tests/helpers/cad_fixtures.py 里
rack、rack_gap、rack_bad、rack_long 四个合成 DXF 的真实解析输出（只取区块与图块插入汇总两个单元），
格式由 mengosv2 vetc/tests/cad-count-contract.test.ts 钉住。

第一阶段（零引擎改动）工具入口只收调用方给出的来源，行数上限 MAX_INLINE_ROWS。逐条坐标几百行的用例（1、2、6）
在工具入口照规则报 BAD_INPUT（见 test_inline_cap_*）；它们的计数逻辑用 max_rows=None 调同一入口验证，
标为“引擎按引用内联（E-A）后的等价路径”，第一阶段不可达。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from count_tool import MAX_INLINE_ROWS, run  # noqa: E402

FX = ROOT / "tests" / "fixtures"


def units(name):
    return json.loads((FX / f"{name}.units.json").read_text(encoding="utf-8"))


def texts(name, kind="区块"):
    return [u["text"] for u in units(name) if u["kind"] == kind]


def call(tool, payload, max_rows=MAX_INLINE_ROWS):
    return run({"tool": tool, "payload": payload}, max_rows=max_rows)


def ok(tool, payload, max_rows=MAX_INLINE_ROWS):
    r = call(tool, payload, max_rows)
    assert r["ok"], r
    return r["output"]


def bad(tool, payload, max_rows=MAX_INLINE_ROWS):
    r = call(tool, payload, max_rows)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", r
    return r["error"]["message"]


def cad(name, section, kind="区块", sl=None):
    t = texts(name, kind)
    return {"text": t if sl is None else t[sl], "reader": "mengos-cad-v1", "section": section}


NAME = {"col": "名称", "op": "eq", "value": "awegewye4ry4"}
GRID = {"x": "x", "y": "y", "tol": 1}


# ───── 用例 1：F1 计数与二维分布（E-A 等价路径）─────

def test_case1_f1_count_and_grid():
    o = ok("count.rows", {"source": cad("rack", "图块插入"), "where": [NAME], "distribution": GRID}, max_rows=None)
    assert o["count"] == 660
    d = o["distribution"]
    assert d["x"]["distinct"] == 33 and d["x"]["step"] == 2760 and d["x"]["uniform"] is True
    assert d["x"]["min"] == 0 and d["x"]["max"] == 88320
    assert d["y"]["distinct"] == 20 and d["y"]["uniform"] is False
    assert d["y"]["steps"] == [{"step": 1500, "times": 18}, {"step": 900, "times": 1}]
    assert d["grid"] == {**d["grid"], "cols": 33, "rows": 20, "full": True, "missing": 0, "stacked": 0}
    assert o["source"]["rows_declared"] == 660 and o["source"]["rows_read"] == 660
    assert {"name": "rows_read_eq_declared", "ok": True} in o["checks"]


def test_case1_inline_path_via_summary_and_g1_sum():
    """第一阶段可达的做法：汇总单元一行一个块名，按名称取“直接插入”列之和（G-1），得 660。"""
    o = ok("count.rows", {"source": cad("rack", "图块", kind="图块插入汇总"), "where": [NAME],
                          "aggregate": [{"col": "直接插入", "fn": "sum"}]})
    assert o["count"] == 1
    assert o["aggregate"][0]["value"] == 660 and o["aggregate"][0]["rows_unparsed"] == 0
    assert o["source"]["rows_declared"] is None
    assert {"name": "chunks_complete", "ok": True} in o["checks"]


# ───── 用例 2：F2 缺位 ─────

def test_case2_f2_gaps():
    o = ok("count.rows", {"source": cad("rack_gap", "图块插入"), "where": [NAME], "distribution": GRID}, max_rows=None)
    assert o["count"] == 657
    g = o["distribution"]["grid"]
    assert g["full"] is False and g["missing"] == 3 and g["cols"] == 33 and g["rows"] == 20
    ys = [1500 * k for k in range(10)] + [14400 + 1500 * k for k in range(10)]
    assert g["missing_cells"] == sorted([{"x": 2760 * i, "y": ys[j]} for i, j in ((5, 3), (17, 10), (30, 19))],
                                        key=lambda c: (c["x"], c["y"]))


# ───── 用例 3、4：尺寸串与尺寸链 ─────

def test_case3_product_and_chain():
    o = ok("count.series", {"source": cad("rack", "尺寸标注"), "mode": "both", "tol": 1,
                            "product": {"text": "显示文字", "measure": "测量值"},
                            "chain": {"from": "端点1", "to": "端点2", "value": "测量值"}})
    p = o["product"]
    assert p["count"] == 1
    h = p["hits"][0]
    assert (h["left"], h["right"], h["stated_total"], h["product"]) == (33, 2760, 91080, 91080)
    assert h["product_ok"] is True and h["measure"] == 91080 and h["measure_ok"] is True
    assert h["row"] == "区块1/尺寸标注/13"
    c = o["chain"]
    assert c["count"] == 1
    ch = c["chains"][0]
    assert ch["segments"] == 12 and ch["pitch"] == 2760 and ch["uniform"] is True and ch["total"] == 33120
    assert ch["start"] == "0,-1500" and ch["end"] == "33120,-1500"
    assert c["single_segments"] == 1     # 91080 那一条自成一段，不算链


def test_case4_f3_inconsistent_product_listed_not_corrected():
    o = ok("count.series", {"source": cad("rack_bad", "尺寸标注"), "mode": "product", "tol": 1,
                            "product": {"text": ["显示文字"], "measure": "测量值"}})
    h = o["product"]["hits"][0]
    assert h["stated_total"] == 91000 and h["product"] == 91080
    assert h["product_ok"] is False and h["measure_ok"] is False
    assert o["product"]["inconsistent"] == 1


# ───── 用例 5：线段统计按图层、方向、长度筛 ─────

def test_case5_segment_stats():
    for layer, length in (("COL_A", 10280), ("COL_B", 11250)):
        o = ok("count.rows", {"source": cad("rack", "线段统计"),
                              "where": [{"col": "图层", "op": "eq", "value": layer}, {"col": "方向", "op": "eq", "value": "竖直"},
                                        {"col": "长度≈", "op": "eq", "value": length}],
                              "aggregate": [{"col": "根数", "fn": "sum"}]})
        assert o["count"] == 1 and o["aggregate"][0]["value"] == 1100


# ───── 用例 6：F4 分块 ─────

def test_case6_f4_all_chunks_ok():
    o = ok("count.rows", {"source": cad("rack_long", "文字")}, max_rows=None)
    assert o["count"] == 3001
    assert {"name": "chunks_contiguous", "ok": True} in o["checks"]
    assert o["source"]["chunks"] == {"given": 3, "total": 3}


def test_case6_f4_two_chunks_bad_input():
    msg = bad("count.rows", {"source": cad("rack_long", "文字", sl=slice(0, 2))}, max_rows=None)
    assert "不符" in msg
    msg = bad("count.rows", {"source": cad("rack_long", "文字", sl=slice(1, 3))}, max_rows=None)
    assert "不符" in msg or "不连续" in msg


def test_case6_f4_out_of_order_chunks_are_sorted():
    t = texts("rack_long")
    o = ok("count.rows", {"source": {"text": [t[2], t[0], t[1]], "reader": "mengos-cad-v1", "section": "文字"}}, max_rows=None)
    assert o["count"] == 3001


def test_case6_section_wholly_in_one_chunk():
    o = ok("count.rows", {"source": cad("rack_long", "图块插入", sl=slice(2, 3)), "where": [NAME]}, max_rows=None)
    assert o["count"] == 660


# ───── 用例 7：确定性 ─────

def test_case7_byte_identical():
    import subprocess
    env = json.dumps({"tool": "count.series", "payload": {"source": cad("rack", "尺寸标注"), "mode": "both", "tol": 1,
                                                          "product": {"text": "显示文字", "measure": "测量值"},
                                                          "chain": {"from": "端点1", "to": "端点2", "value": "测量值"}}})
    outs = {subprocess.run([sys.executable, str(ROOT / "count_tool.py")], input=env.encode(), capture_output=True,
                           env={"PYTHONHASHSEED": s}).stdout for s in ("1", "77")}
    assert len(outs) == 1 and json.loads(next(iter(outs)))["ok"] is True


# ───── 用例 8：inline 模式（假设声明、行数上限）─────

def test_case8_inline_assumption_and_cap():
    o = ok("count.rows", {"source": cad("rack", "线段统计")})
    assert o["source"]["mode"] == "inline"
    assert o["assumptions"] == ["来源行由调用方转录，程序未与原文逐字核对"]
    msg = bad("count.rows", {"source": cad("rack", "图块插入"), "where": [NAME]})
    assert f"超过上限 {MAX_INLINE_ROWS}" in msg
    rows = [["a", i] for i in range(MAX_INLINE_ROWS + 1)]
    assert f"超过上限 {MAX_INLINE_ROWS}" in bad("count.rows", {"source": {"columns": ["k", "v"], "rows": rows}})
    assert ok("count.rows", {"source": {"columns": ["k", "v"], "rows": rows[:MAX_INLINE_ROWS]}})["count"] == MAX_INLINE_ROWS


def test_inline_cap_applies_to_series_and_coverage():
    assert "超过上限" in bad("count.series", {"source": cad("rack", "图块插入"), "mode": "chain",
                                             "chain": {"from": "x", "to": "y", "value": "x"}})
    assert "超过上限" in bad("count.coverage", {"inventory": {"items": [str(i) for i in range(MAX_INLINE_ROWS + 1)]}, "marks": []})


# ───── 用例 9：覆盖核对 ─────

INV = {"items": [{"id": "S1", "label": "图幅一"}, {"id": "S2"}, {"id": "S3"}]}


def test_case9_coverage():
    allm = [{"id": "S1", "status": "done"}, {"id": "S2", "status": "empty", "note": "本片无相关内容"}, {"id": "S3", "status": "done"}]
    o = ok("count.coverage", {"inventory": INV, "expected_total": 3, "marks": allm})
    assert o["unmarked_count"] == 0 and o["total_ok"] is True and o["status_counts"] == {"done": 2, "empty": 1}
    o = ok("count.coverage", {"inventory": INV, "marks": allm[1:]})
    assert o["unmarked_count"] == 1 and o["unmarked"] == [{"id": "S1", "label": "图幅一"}]
    o = ok("count.coverage", {"inventory": INV, "marks": allm + [{"id": "S9", "status": "done"}, {"id": "S1", "status": "done"}]})
    assert o["unknown_marks"] == ["S9"] and o["duplicate_marks"] == ["S1"] and o["unmarked_count"] == 0
    assert "不符" in bad("count.coverage", {"inventory": INV, "expected_total": 4, "marks": allm})
    assert "清单为空" in bad("count.coverage", {"inventory": {"items": []}, "marks": []})


def test_case9_coverage_inventory_from_rows_list_ids():
    """先数苹果（count.rows list=true 给出稳定序号），再核贴签：清单来自行式来源。"""
    src = cad("rack", "尺寸标注")
    items = ok("count.rows", {"source": src, "list": True})["items"]
    assert [i["id"] for i in items][:2] == ["区块1/尺寸标注/1", "区块1/尺寸标注/2"]
    marks = [{"id": i["id"], "status": "done"} for i in items[:-1]]
    o = ok("count.coverage", {"inventory": {"source": src}, "expected_total": 13, "marks": marks})
    assert o["unmarked"] == [{"id": "区块1/尺寸标注/13"}] and o["source"]["reader"] == "mengos-cad-v1"


# ───── G-2 / G-3 / G-4 ─────

def test_g2_any_of():
    src = cad("rack", "线段统计")
    o = ok("count.rows", {"source": src, "where": [{"col": "方向", "op": "eq", "value": "竖直"}],
                          "any_of": [[{"col": "图层", "op": "eq", "value": "COL_A"}], [{"col": "图层", "op": "eq", "value": "COL_B"}]],
                          "aggregate": [{"col": "根数", "fn": "sum"}]})
    assert o["count"] == 2 and o["aggregate"][0]["value"] == 2200


def test_g3_groups_count():
    o = ok("count.rows", {"source": cad("rack", "线段统计"), "group_by": ["图层"]})
    assert o["groups_count"] == 4
    assert [g["key"]["图层"] for g in o["groups"]] == ["COL_A", "COL_B", "DIM", "RACK"]


def test_g4_agree():
    o = ok("count.agree", {"left": {"value": 33, "from": "count.series 回执 /product/hits/0/left"},
                           "right": {"value": 33, "from": "count.rows 回执 /distribution/x/distinct"}})
    assert o["holds"] is True
    o = ok("count.agree", {"left": {"value": 34, "from": "a"}, "right": {"value": 33, "from": "b"}, "relation": "diff", "diff": 1})
    assert o["holds"] is True
    o = ok("count.agree", {"left": {"value": 32, "from": "a"}, "right": {"value": 33, "from": "b"}})
    assert o["holds"] is False and o["diff_actual"] == -1
