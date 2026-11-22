"""2.3.5 的包内核对（mengosv2《逐字稿-table行宽歧义拒因与编号列type吸收-证件与签名一并报-2026-11-22》F1、F2，立法者 2026-11-22 认可）。
  · F1：编号列写错 type 静默吸收——outline 一律按 text，seq 只认 integer、text，其余按 integer；不报错、不加 warning；对齐随规范后的 type。
  · F2-1：三件工具 rows 句统一（check/export 补对象行一句），formula 说明去“行里不用写”。
  · F2-2：格数不对只陈述规则：“第 i 行有 k 格，这张表有 n 列；数组行每列一格”。
  · F2-3：无歧义的旧宽度静默照旧；公式列数 f 与编号列数 m 都 ≥ 1 且相等时，宽 n − f 有歧义 ⟹ 拒；宽 n − m 没有旧读法 ⟹ 拒。"""
import json
from pathlib import Path

import pytest

from test_220 import run

ROOT = Path(__file__).resolve().parents[1]
UNITS = {u["tool_id"]: u for u in json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))["units"]}
ROWS_NEW = "rows 每行一个数组，按 columns 的顺序每列一格，格数等于列数；每格是字符串、数字、true/false 或 null（空格子）；公式列、编号列的值由工具生成，这两列的格写 null。"
OBJ_ROW = "行也可以写成对象（列的 key 或标题 → 值），缺的格子为空。"


def build(tmp_path, table, name="b"):
    return run("table.build", {"table": table}, tmp_path, name)[0]


# ───────────────────────── F1 编号列 type 吸收 ─────────────────────────
@pytest.mark.parametrize("numbering,written,expect", [
    ("outline", "integer", "text"), ("outline", "number", "text"), ("outline", "text", "text"),
    ("seq", "number", "integer"), ("seq", "money", "integer"), ("seq", "text", "text"), ("seq", "integer", "integer"),
])
def test_numbering_column_type_is_normalized_silently(tmp_path, numbering, written, expect):
    """写错 type 不报错、不加 warning，产出与写规范 type 的逐字节相同（表模型里是规范后的 type）。"""
    def t(ty):
        cols = [{"key": "no", "title": "序号", "numbering": numbering, "type": ty}, {"title": "名称", "type": "text"}]
        tb = {"title": "T", "columns": cols, "rows": [[None, "甲"], [None, "乙"]]}
        if numbering == "outline":
            tb["columns"].insert(1, {"title": "类别", "type": "text"})
            tb["rows"] = [[None, "组件", "甲"], [None, "子件", "乙"]]
            tb["outline_from"] = {"column": "类别", "levels": {"组件": 1, "子件": 2}}
        return tb
    r = build(tmp_path, t(written), "w")
    ok = build(tmp_path, t(expect), "e")
    assert r["ok"] and ok["ok"], (r, ok)
    assert r["output"]["warnings"] == [], r["output"]["warnings"]
    assert r["output"] == ok["output"]


def test_numbering_type_absorption_output_equals_correct_type(tmp_path):
    """写错 type 与写对 type 的产出逐字节相同（对齐等由 type 推出的属性随规范后的 type 走）。"""
    def t(written):
        return {"title": "T", "columns": [{"key": "no", "title": "序号", "numbering": "seq", "type": written},
                                          {"title": "名称", "type": "text"}], "rows": [[None, "甲"], [None, "乙"]]}
    a = build(tmp_path, t("money"), "a")
    b = build(tmp_path, t("integer"), "b")
    assert a["ok"] and b["ok"], (a, b)
    assert a["output"] == b["output"]


# ───────────────────────── F2-1 卡 ─────────────────────────
def test_rows_sentence_is_the_same_on_all_three_cards():
    for tid in ("table.build", "table.check", "table.export"):
        d = UNITS[tid]["signature"]["input_schema"]["properties"]["table"]["description"]
        assert d.count(ROWS_NEW) == 1, tid
        assert "行里不用写" not in d and "有公式列时" not in d and "非公式列数" not in d, tid
        assert "公式列的值由工具算）。" in d, tid
        assert OBJ_ROW.rstrip("。") in d, tid   # build 原有对象行一句（后接分批追加）；check/export 2.3.5 补上
    for tid in ("table.check", "table.export"):
        d = UNITS[tid]["signature"]["input_schema"]["properties"]["table"]["description"]
        assert ROWS_NEW + OBJ_ROW + "格里的值取自某张回执时" in d, tid   # B1 引用句紧跟 rows 句


# ───────────────────────── F2-2 / F2-3 宽度 ─────────────────────────
# 列：序号(编号) 名称 数量 单价 金额(公式)  ⟹ n=5, f=1, m=1（f = m）
AMB = [{"key": "no", "title": "序号", "numbering": "seq"}, {"key": "name", "title": "名称", "type": "text"},
       {"key": "qty", "title": "数量", "type": "integer"}, {"key": "price", "title": "单价", "type": "money"},
       {"key": "amt", "title": "金额", "type": "money", "formula": "数量 * 单价"}]


def _amb(rows):
    return {"title": "T", "columns": AMB, "rows": rows, "totals": ["金额"]}


def test_full_width_input_only_and_object_rows_are_unchanged(tmp_path):
    full = build(tmp_path, _amb([[None, "甲", 2, 10, None], [None, "乙", 3, 5, None]]), "full")
    inputs = build(tmp_path, _amb([["甲", 2, 10], ["乙", 3, 5]]), "inputs")
    objs = build(tmp_path, _amb([{"名称": "甲", "数量": 2, "单价": 10}, {"名称": "乙", "数量": 3, "单价": 5}]), "objs")
    assert full["ok"] and inputs["ok"] and objs["ok"], (full, inputs, objs)
    assert full["output"]["sheets"] == inputs["output"]["sheets"] == objs["output"]["sheets"]
    assert full["output"]["sheets"][0]["totals"][0]["value"] == "35"


@pytest.mark.parametrize("row", [[1, "甲", 2, 10], ["甲", 2, 10, 20]])
def test_f_equals_m_width_n_minus_f_is_rejected(tmp_path, row):
    """f = m = 1：宽 4 既是“不写公式列”（旧读法）也是“不写编号列”，两种对位不同 ⟹ 拒。"""
    r = build(tmp_path, _amb([row]), "amb")
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and r["error"]["where"] == "table.rows[0]", r
    assert r["error"]["message"] == "第 1 行有 4 格，这张表有 5 列；数组行每列一格"
    assert r["error"]["hint"] == "公式列、编号列的格写 null；行也可以写成对象（列的 key 或标题 → 值）；改了列要把已有的数组行按新列重写"


# 列：序号(编号) 名称 数量 单价 金额(公式) 税额(公式)  ⟹ n=6, f=2, m=1（f ≠ m）
NEQ = AMB + [{"key": "tax", "title": "税额", "type": "money", "formula": "金额 * 0.1"}]


def test_f_not_equal_m_width_n_minus_f_keeps_old_reading(tmp_path):
    """f = 2 ≠ m = 1：宽 n − f = 4 只有“不写公式列”一种旧读法（编号格给了值也不用）⟹ 照旧对位。"""
    r = build(tmp_path, {"title": "T", "columns": NEQ, "rows": [[None, "甲", 2, 10]]}, "neq")
    full = build(tmp_path, {"title": "T", "columns": NEQ, "rows": [[None, "甲", 2, 10, None, None]]}, "neqfull")
    assert r["ok"] and full["ok"], (r, full)
    assert r["output"]["sheets"] == full["output"]["sheets"]


def test_f_not_equal_m_width_n_minus_m_is_rejected(tmp_path):
    """f = 2 ≠ m = 1：宽 n − m = 5（不写编号列、保留公式列位）没有旧读法 ⟹ 拒。"""
    r = build(tmp_path, {"title": "T", "columns": NEQ, "rows": [["甲", 2, 10, None, None]]}, "neqm")
    assert not r["ok"] and r["error"]["message"] == "第 1 行有 5 格，这张表有 6 列；数组行每列一格", r


def test_m_zero_formula_omitted_still_reads(tmp_path):
    cols = AMB[1:]   # 无编号列 ⟹ m = 0，不写公式列（宽 3）照旧
    r = build(tmp_path, {"title": "T", "columns": cols, "rows": [["甲", 2, 10]]}, "m0")
    assert r["ok"], r


# ───────────────────────── 一次报全（立法者 2026-11-22 定 A） ─────────────────────────
# 列 type 声明（③）、逐行行宽（②）、逐格（④，只对行宽合格的行）彼此独立：首个错误照旧填 message/where/hint，
#   不止一处时 error.errors 列出全部，每条 {message, where?, hint?}，用现成拒因。
def test_independent_errors_are_reported_together(tmp_path):
    cols = [{"key": "name", "title": "名称", "type": "text"}, {"key": "qty", "title": "数量", "type": "integer"},
            {"key": "price", "title": "单价"},                                   # 被合计引用却没写 type（③）
            {"key": "amt", "title": "金额", "type": "money", "formula": "数量 * 2"}]
    rows = [["甲", 1.5, 3, None],          # 整数列写小数（④）
            ["乙", 2],                     # 行宽不对（②），这一行不做逐格
            ["丙", 2.5, 4, None]]          # 又一处整数列写小数（④）
    r = build(tmp_path, {"title": "T", "columns": cols, "rows": rows, "totals": ["单价"]}, "all")
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", r
    errs = r["error"]["errors"]
    wheres = [e["where"] for e in errs]
    assert wheres == ["table.columns[2].type", "table.rows[1]", "table.rows[0][1]", "table.rows[2][1]"], wheres
    # 首个错误照旧填在 error 本身
    assert (r["error"]["message"], r["error"]["where"], r["error"].get("hint")) == (errs[0]["message"], errs[0]["where"], errs[0].get("hint"))
    assert errs[1]["message"] == "第 2 行有 2 格，这张表有 4 列；数组行每列一格"
    # 每条与单独出错时的拒因逐字相同（不新造）
    one = build(tmp_path, {"title": "T", "columns": cols[:2], "rows": [["甲", 1.5]]}, "one")
    assert one["error"]["message"] == errs[2]["message"] and "errors" not in one["error"]


def test_single_error_has_no_errors_list(tmp_path):
    r = build(tmp_path, _amb([[1, "甲", 2, 10]]), "single")
    assert not r["ok"] and "errors" not in r["error"], r


def test_structure_errors_still_stop_at_the_first(tmp_path):
    """列定义一类（列 key 重复等）彼此有依赖，照旧遇错即停，不带 errors。"""
    r = build(tmp_path, {"title": "T", "columns": [{"key": "a", "title": "甲"}, {"key": "a", "title": "乙"}], "rows": [["x"]]}, "dup")
    assert not r["ok"] and "errors" not in r["error"] and "重复" in r["error"]["message"], r


# ───────────────────────── 2.4.0：必填列、未填项清单、按 $id 并入、整数列格公式带操作数 ─────────────────────────
# （mengosv2《规格改句草案-未填项位置声明与交付子目标结论-2026-11-22》§六 A；17 TL-30e）
def test_unfilled_lists_required_empty_cells_and_sheets_without_rows(tmp_path):
    cols = [{"key": "name", "title": "名称"}, {"key": "qty", "title": "数量", "type": "integer", "required": True},
            {"key": "spec", "title": "规格", "required": True}]
    t = {"title": "库存", "sheets": [
        {"id": "s1", "name": "零件", "columns": cols, "rows": [{"$id": "r1", "name": "轴承", "spec": "6208"}, ["齿轮", 2, ""]]},
        {"id": "s2", "name": "原料", "columns": cols}]}
    r = build(tmp_path, t, "u")
    assert r["ok"], r
    assert r["output"]["unfilled"] == ["表 s1 行 r1 列 qty（数量）未填", "表 s1 第 2 行（没有 $id）列 spec（规格）未填", "表 s2 没有数据行"]


def test_unfilled_empty_when_everything_filled_and_old_tables_unchanged(tmp_path):
    r = build(tmp_path, {"title": "T", "columns": [{"title": "a", "required": True}], "rows": [["x"]]}, "ok")
    assert r["ok"] and r["output"]["unfilled"] == []
    single = build(tmp_path, {"title": "T", "columns": ["a"]}, "empty")          # 单表写法、没有行：表名带引号
    assert single["output"]["unfilled"] == ["表 “T” 没有数据行"]


def test_required_formula_and_numbering_columns_are_not_listed(tmp_path):
    cols = [{"key": "no", "title": "序号", "numbering": "seq", "required": True}, {"key": "q", "title": "数", "type": "integer"},
            {"key": "d", "title": "倍", "type": "integer", "formula": "q * 2", "required": True}]
    r = build(tmp_path, {"title": "T", "columns": cols, "rows": [{"$id": "a", "数": 1}]}, "f")
    assert r["ok"] and r["output"]["unfilled"] == []


def test_required_must_be_boolean(tmp_path):
    r = build(tmp_path, {"title": "T", "columns": [{"title": "a", "required": "yes"}], "rows": [["x"]]}, "bad")
    assert not r["ok"] and r["error"]["where"] == "table.columns[0].required", r


def test_required_round_trips_in_the_model_only_when_true(tmp_path):
    import json as _json
    r, w = run("table.build", {"table": {"title": "T", "columns": [{"title": "a", "required": True}, "b"], "rows": [["x", "y"]]}}, tmp_path, "rt")
    m = _json.loads(next((tmp_path / "rt").glob("*.table.json")).read_text(encoding="utf-8"))
    assert m["sheets"][0]["columns"][0]["required"] is True and "required" not in m["sheets"][0]["columns"][1]


def test_unfilled_is_declared_on_the_output_schema():
    out = UNITS["table.build"]["signature"]["output_schema"]["properties"]["unfilled"]
    assert out["x-mengos-unfilled"] is True and out["type"] == "array" and out["items"] == {"type": "string"}
    for tid in ("table.check", "table.export"):
        assert "x-mengos-unfilled" not in json.dumps(UNITS[tid]["signature"])


def test_integer_cell_expr_with_fraction_lists_operand_values(tmp_path):
    cols = [{"key": "len", "title": "长度", "type": "number"}, {"key": "n", "title": "根数", "type": "integer"}]
    rows = [{"$id": "r1", "长度": 7.5, "根数": 2}, {"$id": "r2", "长度": 3, "根数": {"$expr": "@r1.长度 / 2"}}]
    r = build(tmp_path, {"title": "T", "columns": cols, "rows": rows}, "ex")
    assert not r["ok"], r
    assert r["error"]["message"] == "格公式“@r1.长度 / 2”算出 3.75，“根数”是整数列；式里的值：@r1.长度 = 7.5"
