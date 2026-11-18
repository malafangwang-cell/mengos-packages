"""2.3.0 B1 的包内核对（mengosv2 局部追问设计 r9.2 §4.1、§4.4、§4.5；L13；终审 M4）。先红测试：在 2.2.0 上这些都不成立。
  · 规范化入参：sheets 写法、每张表有 id（单表补 _sa）、对象行带 $id（缺的补 _r 加字母）、补丁已施加并清空；
  · 旧产出（数组行、单表写法）补号后视图逐格相同，按规范化入参再建一次也逐格相同；
  · row_patch：改一格、删一行、在某行后插一行，与整表重写逐格相同；§4.4 ①–⑤ 各一条；
  · 单表底稿加补丁（引擎包成 sheets: [{id: _sa, row_patch}]）合进唯一的那张表，不多出表；
  · 视图：单元种类、每格依赖、派生行（row_kind derived、来源键）、生成行的键（与 layout 对齐）。"""
import copy
import json

import pytest

import canon
import model
import render
import table_tool
from contribution_ref import merge

from test_220 import BUILD, G, files, run


def build(tmp_path, table, name="b"):
    r, w = run("table.build", {"table": table}, tmp_path, name)
    assert r["ok"], r
    return r["output"], json.loads(files(r, w)["view"])


def bad(tmp_path, table, name="x"):
    r, _ = run("table.build", {"table": table}, tmp_path, name)
    assert not r["ok"], r
    return r["error"]["message"]


def cells(view):
    """每张表：⟨表 id, 行 id⟩ → 这一行的显示格（逐格比对用；不比字段次序）。"""
    out = {}
    for s in view["sheets"]:
        for rid, row in zip(s.get("ids") or [None] * len(s["rows"]), s["rows"]):
            out[(s.get("id"), rid)] = row
        out[(s.get("id"), "$order")] = s.get("ids")
        out[(s.get("id"), "$totals")] = s.get("totals")
    return out


BOM = {"title": "物料", "columns": [{"key": "name", "title": "名称"}, {"key": "qty", "title": "数量", "type": "integer"},
                                   {"key": "price", "title": "单价", "type": "money"},
                                   {"key": "amt", "title": "金额", "type": "money", "formula": "数量 * 单价"}],
       "rows": [["输入轴", 1, 860], ["齿轮", 2, 1250.5], ["轴承", 4, 95]], "totals": ["金额"]}


# ───────────────────────── 规范化入参（§4.1） ─────────────────────────
def test_normalized_input_is_sheets_form_with_ids_and_object_rows(tmp_path):
    out, view = build(tmp_path, BOM)
    n = out["normalized"]
    assert "columns" not in n and len(n["sheets"]) == 1
    s = n["sheets"][0]
    assert s["id"] == "_sa" and s["name"] == "物料"
    assert s["rows"] == [{"$id": "_ra", "name": "输入轴", "qty": 1, "price": 860},
                         {"$id": "_rb", "name": "齿轮", "qty": 2, "price": 1250.5},
                         {"$id": "_rc", "name": "轴承", "qty": 4, "price": 95}]     # 公式列的格不写
    assert view["sheets"][0]["id"] == "_sa" and view["sheets"][0]["ids"] == ["_ra", "_rb", "_rc"]


@pytest.mark.parametrize("cid", ["b_simple", "t3_07_group_subtotal", "t9_07_cell_exprs", "t5_03_merge_formula", "t6_04_derive_summary"])
def test_old_inputs_get_ids_and_rebuilding_the_normalized_input_gives_the_same_view(cid, tmp_path):
    out, view = build(tmp_path, G[cid]["payload"]["table"], "a")
    out2, view2 = build(tmp_path, out["normalized"], "b")
    assert cells(view2) == cells(view)
    assert out2["normalized"] == out["normalized"]                       # 规范化是幂等的
    assert len(view2["sheets"]) == len(view["sheets"])


def test_issued_ids_skip_ids_already_used(tmp_path):
    t = {**BOM, "rows": [["输入轴", 1, 860], {"$id": "_rb", "名称": "齿轮", "数量": 2, "单价": 1250.5}, ["轴承", 4, 95]]}
    out, view = build(tmp_path, t)
    assert [r["$id"] for r in out["normalized"]["sheets"][0]["rows"]] == ["_ra", "_rb", "_rc"]
    t["rows"][0] = {"$id": "_ra", "名称": "输入轴", "数量": 1, "单价": 860}
    t["rows"][2] = ["轴承", 4, 95]
    t["rows"][1] = ["齿轮", 2, 1250.5]
    out, _ = build(tmp_path, t, "c")
    assert [r["$id"] for r in out["normalized"]["sheets"][0]["rows"]] == ["_ra", "_rb", "_rc"]


def test_table_model_of_an_old_input_carries_no_issued_ids(tmp_path):
    r, w = run("table.build", {"table": BOM}, tmp_path)
    assert "_ra" not in files(r, w)["json"].decode()                    # 表模型逐字节照旧（见 test_contribution 的 1.0.1 比对）


@pytest.mark.parametrize("table,where", [
    ({**BOM, "rows": [{"$id": "_r1", "名称": "x", "数量": 1, "单价": 1}]}, "_r1"),
    ({"title": "T", "sheets": [{"id": "_s1", "columns": ["a"], "rows": [["x"]]}]}, "_s1"),
])
def test_reserved_prefixes_are_rejected(table, where, tmp_path):
    assert where in bad(tmp_path, table)


# ───────────────────────── row_patch（§4.4） ─────────────────────────
def base(tmp_path):
    out, _ = build(tmp_path, BOM, "base")
    return out["normalized"]


def patched(n, patch):
    n = copy.deepcopy(n)
    n["sheets"][0]["row_patch"] = patch
    return n


def test_patch_one_cell_equals_whole_rewrite_and_does_not_accumulate(tmp_path):
    n = base(tmp_path)
    out, view = build(tmp_path, patched(n, [{"$id": "_rb", "数量": 3}]), "p")
    whole = {**BOM, "rows": [["输入轴", 1, 860], ["齿轮", 3, 1250.5], ["轴承", 4, 95]]}
    _, view_w = build(tmp_path, whole, "w")
    assert cells(view) == cells(view_w)
    assert "row_patch" not in out["normalized"]["sheets"][0]                       # ① 补丁施加进 rows、清空
    assert out["normalized"]["sheets"][0]["rows"][1] == {"$id": "_rb", "name": "齿轮", "qty": 3, "price": 1250.5}


def test_patch_delete_and_insert_equal_whole_rewrite(tmp_path):
    n = base(tmp_path)
    p = [{"$id": "_ra", "$delete": True}, {"$id": "x1", "$after": "_rb", "名称": "端盖", "数量": 2, "单价": 40},
         {"$id": "x2", "$after": "_rb", "名称": "螺钉", "数量": 8, "单价": 1}]
    out, view = build(tmp_path, patched(n, p), "p")
    assert view["sheets"][0]["ids"] == ["_rb", "x1", "x2", "_rc"]                  # ③ 同一 $after 按出现的次序
    whole = {**BOM, "rows": [["齿轮", 2, 1250.5], ["端盖", 2, 40], ["螺钉", 8, 1], ["轴承", 4, 95]]}
    _, view_w = build(tmp_path, whole, "w")
    assert [r for s in view["sheets"] for r in s["rows"]] == [r for s in view_w["sheets"] for r in s["rows"]]
    assert view["sheets"][0]["totals"] == view_w["sheets"][0]["totals"]


def test_patch_clear_a_cell_and_null_is_rejected(tmp_path):
    n = base(tmp_path)
    out, _ = build(tmp_path, patched(n, [{"$id": "_rc", "单价": {"$clear": True}}]), "p")
    assert out["normalized"]["sheets"][0]["rows"][2] == {"$id": "_rc", "name": "轴承", "qty": 4}   # ② 清空一格
    assert "$clear" in bad(tmp_path, patched(n, [{"$id": "_rc", "单价": None}]))


@pytest.mark.parametrize("patch,say", [
    ([{"$id": "_ra", "$delete": True}, {"$id": "x1", "$after": "_ra", "名称": "a"}], "删了"),
    ([{"$id": "x1", "$after": "nope", "名称": "a"}], "找不到这一行"),
    ([{"$id": "x1", "$after": "x2", "名称": "a"}, {"$id": "x2", "$after": "x1", "名称": "b"}], "成环"),
])
def test_after_pointing_to_deleted_missing_or_cycle_is_named(patch, say, tmp_path):
    msg = bad(tmp_path, patched(base(tmp_path), patch))
    assert say in msg and "$after" in msg


def test_moving_an_existing_row_with_after_is_allowed(tmp_path):
    _, view = build(tmp_path, patched(base(tmp_path), [{"$id": "_ra", "$after": "_rc"}]), "p")
    assert view["sheets"][0]["ids"] == ["_rb", "_rc", "_ra"]                       # ④ 等于移行，由调用方的不变量判


def test_unknown_id_without_after_and_deleting_a_referenced_row(tmp_path):
    n = base(tmp_path)
    assert "找不到这一行：zz" in bad(tmp_path, patched(n, [{"$id": "zz", "数量": 1}]))   # ⑤
    n2 = copy.deepcopy(n)
    n2["sheets"][0]["rows"][2]["qty"] = {"$expr": "@_ra.数量*4"}
    msg = bad(tmp_path, patched(n2, [{"$id": "_ra", "$delete": True}]), "y")
    assert "_ra" in msg and "_sa/_rc.qty" in msg


@pytest.mark.parametrize("patch,say", [
    ([{"$id": "_ra", "金额": 1}], "公式列"),
    ([{"$id": "_rz", "$after": "_ra", "名称": "a"}], "_r 开头"),
    ([{"$id": "_ra", "颜色": "红"}], "表里没有的列"),
])
def test_patch_rejects_formula_cells_reserved_new_ids_and_unknown_columns(patch, say, tmp_path):
    assert say in bad(tmp_path, patched(base(tmp_path), patch))


def test_patch_on_a_derived_sheet_is_rejected(tmp_path):
    t = copy.deepcopy(G["t6_04_derive_summary"]["payload"]["table"])
    d = next(s for s in t["sheets"] if s.get("derive"))
    d["row_patch"] = [{"$id": "_ra", "$delete": True}]
    assert "派生表" in bad(tmp_path, t)


def test_single_sheet_base_plus_engine_wrapped_patch_stays_one_sheet(tmp_path):
    """终审 M4 第 1 条：引擎把补丁包成 sheets: [{id: 选区的表, …补丁}]，按 input_schema（sheets by-id）合进底稿，不多出一张表。"""
    n = base(tmp_path)
    delta = {"sheets": [{"id": "_sa", "row_patch": [{"$id": "_rb", "数量": 5}]}]}
    merged = merge(BUILD["properties"]["table"], n, delta)
    out, view = build(tmp_path, merged, "m")
    assert len(view["sheets"]) == 1 and view["sheets"][0]["id"] == "_sa"
    assert out["normalized"]["sheets"][0]["rows"][1]["qty"] == 5


def test_row_patch_is_declared_by_id_and_carries_the_expr_and_data_marks():
    rp = BUILD["properties"]["table"]["properties"]["sheets"]["items"]["properties"]["row_patch"]
    assert rp["x-mengos-merge"] == {"mode": "by-id", "id": "$id"}
    assert rp["x-mengos-data"] is True and rp["x-mengos-expr"] is True
    assert "row_patch" in BUILD["properties"]["table"]["properties"]                 # 单表写法也收（顶层）


def test_registration_publishes_the_local_patch_shape():
    from test_220 import REG
    lp = REG["local_patch"]
    assert lp["tool_id"] == "table.build" and lp["field"] == "table" and lp["wrap"] == "sheet"
    assert set(lp["schema"]["properties"]) == {"row_patch", "columns", "totals"}


# ───────────────────────── 视图：单元种类、依赖、行种类与键（§4.1、§4.5；r8 §4.4） ─────────────────────────
def test_cell_kinds_and_dependencies(tmp_path):
    t = {**BOM, "columns": [{"key": "no", "title": "序号", "numbering": "seq"}] + BOM["columns"],
         "rows": [{"$id": "r1", "名称": "输入轴", "数量": 1, "单价": 860}, {"$id": "r2", "名称": "齿轮", "数量": {"$expr": "@r1.数量*2"}, "单价": 1250.5}]}
    _, view = build(tmp_path, t)
    s = view["sheets"][0]
    assert s["col_kinds"] == ["numbering", "input", "input", "input", "formula"]
    assert s["deps"]["columns"] == {"amt": ["price", "qty"]}
    assert s["deps"]["cells"] == [[1, 2, [["_sa", "r1", "qty"]], []]]                 # 带式的格引用了 r1 的数量
    assert s["exprs"][0][:2] == [1, 2] and "totals" in s


def test_generated_rows_carry_kind_and_key(tmp_path):
    _, view = build(tmp_path, G["t3_07_group_subtotal"]["payload"]["table"])
    s = view["sheets"][0]
    assert len(s["layout_keys"]) == len(s["layout"])
    pairs = [(o["k"], k) for o, k in zip(s["layout"], s["layout_keys"]) if o["k"] in ("g", "s")]
    assert ("g", "宏达家具") in pairs and ("s", "宏达家具") in pairs
    assert all(k is None for o, k in zip(s["layout"], s["layout_keys"]) if o["k"] == "d")


def test_merged_rows_key_on_the_merge_key(tmp_path):
    _, view = build(tmp_path, G["t5_03_merge_formula"]["payload"]["table"])
    s = view["sheets"][0]
    ks = [k for o, k in zip(s["layout"], s["layout_keys"]) if o["k"] == "m"]
    assert ks and all(isinstance(k, list) and k for k in ks)


def test_derived_rows_are_kind_derived_keyed_by_their_source_rows(tmp_path):
    _, view = build(tmp_path, G["t6_04_derive_summary"]["payload"]["table"])
    d = next(s for s in view["sheets"] if s.get("row_kind") == "derived")
    assert "ids" not in d and len(d["derived_keys"]) == len(d["rows"])
    assert all(k and all("/" in x for x in k) for k in d["derived_keys"])


def test_canonical_is_pure_and_matches_model_issuing(tmp_path):
    t = copy.deepcopy(BOM)
    n = canon.canonical(t)
    assert t == BOM                                                                   # 不改原入参
    m = model.normalize(t, True)
    assert [r["$id"] for r in n["sheets"][0]["rows"]] == m.sheets[0].row_ids
    assert render.to_view(m)["sheets"][0]["ids"] == m.sheets[0].row_ids
