"""2.2.0 的包内核对（执行令《首发后-table包2.2.0》G7–G11、G17 包；返工稿 #717）。逐条对照测试集的金样在 golden_cases.json，
这里补金样不便表达的性质：与引擎的接口（x-mengos-expr 的位置、式里数的抽取）、合并代数、表模型往返、只放宽。"""
import io
import json
import re
import zipfile
from pathlib import Path

import jsonschema
import openpyxl
import pytest

import model
import render
import table_tool
from contribution_ref import merge, touched_keys

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
BUILD = UNITS["table.build"]["signature"]["input_schema"]
G = {c["id"]: c for c in json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))}


def run(tool, payload, tmp_path, name="w"):
    w = tmp_path / name
    w.mkdir()
    return table_tool.run({"tool": tool, "payload": payload, "workdir": str(w)}), w


def files(r, w):
    return {f["format"]: (w / f["path"]).read_bytes() for f in r["output"]["files"]}


# ───────────────────────── 与引擎的接口（#719 两条要求） ─────────────────────────
def _reachable(schema, path=""):
    """引擎只沿 properties 与 items 读标注（不进 oneOf、anyOf、if/then/else）。"""
    if not isinstance(schema, dict):
        return
    yield path, schema
    for k, v in (schema.get("properties") or {}).items():
        yield from _reachable(v, f"{path}.{k}")
    if isinstance(schema.get("items"), dict):
        yield from _reachable(schema["items"], f"{path}[]")


@pytest.mark.parametrize("tid", sorted(UNITS))
def test_x_mengos_expr_is_declared_on_every_rows_and_only_where_the_engine_can_see_it(tid):
    s = UNITS[tid]["signature"]["input_schema"]
    reach = dict(_reachable(s))
    rows = [p for p in reach if p.endswith(".rows")]
    assert rows, tid
    for p in rows:
        assert reach[p].get("x-mengos-expr") is True and reach[p].get("x-mengos-data") is True, (tid, p)
    declared = [p for p, n in reach.items() if n.get("x-mengos-expr")]
    assert sorted(declared) == sorted(rows), declared             # 只在 rows 上，公式列等别处不声明
    assert json.dumps(s).count('"x-mengos-expr"') == len(rows)    # oneOf、anyOf 分支里没有（引擎看不见那里）
    for p in rows:                                                 # 17 TL-30b v0.2.99：位数、步长参数的声明在同一层
        assert reach[p]["x-mengos-expr-params"] == {"round": [2], "roundup": [2], "rounddown": [2], "ceiling": [2], "floor": [2]}


def test_cell_schema_accepts_expr_objects_and_nothing_else():
    jsonschema.validate({"table": {"title": "T", "columns": [{"title": "数量", "type": "integer"}], "rows": [[{"$expr": "6*28"}]]}}, BUILD)
    for bad in ({"$expr": ""}, {"$expr": "1", "value": 1}, {"$calc": "1+1", "x": 1}, {"v": 1}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({"table": {"title": "T", "columns": [{"title": "数量", "type": "integer"}], "rows": [[bad]]}}, BUILD)


# 引擎从式里抽数的写法（mengosv2 engine/projection/credentials.ts EXPR_TOKEN，#719）：标识符与 @引用 里的数字不算
EXPR_TOKEN = re.compile(r"@[\w]+(?:/[\w]+)?(?:\.[\w]+)?|[^\W\d][\w]*|(\d+(?:\.\d+)?)")


def engine_numbers(expr):
    import unicodedata
    return [float(m.group(1)) for m in EXPR_TOKEN.finditer(unicodedata.normalize("NFKC", expr)) if m.group(1)]


@pytest.mark.parametrize("expr,nums", [("6*28", [6, 28]), ("@r1.数量*2", [2]), ("@s01/r1.数量", []), ("ceiling(@r1.数量*4*1.005)", [4, 1.005]),
                                       ("ceiling(672*1.005)", [672, 1.005]), ("roundup(颜色1*3)", [3])])
def test_numbers_the_engine_will_check_are_exactly_the_numbers_in_the_expression(expr, nums):
    """取整的步长、位数可省（ceiling(x)）：式里不写，就不用为它找出处；行 id、表 id 里的数字不当成数。"""
    assert engine_numbers(expr) == nums


# 引擎（mengosv2 #734）按声明跳过“恰是一个数”的位数、步长参数：这里照它的切分法核一遍我们的式
def engine_exempt(expr, decl):
    out, i = [], 0
    for m in re.finditer(r"([^\W\d][\w]*)\s*\(", expr):
        idx = decl.get(m.group(1).lower())
        if not idx:
            continue
        depth, arg, start = 0, 1, m.end()
        for k in range(start, len(expr)):
            ch = expr[k]
            if ch in "([":
                depth += 1
            elif ch in ")]":
                if depth == 0:
                    if arg in idx and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", expr[start:k].strip()):
                        out.append(float(expr[start:k]))
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                if arg in idx and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", expr[start:k].strip()):
                    out.append(float(expr[start:k]))
                arg, start = arg + 1, k + 1
    return out


@pytest.mark.parametrize("expr,exempt", [("ceiling(672*1.005, 1)", [1]), ("round(@r1.数量/3, 2)", [2]), ("ceiling(1, 50)", [50]),
                                         ("round(ceiling(@r1.数量, 1), 2)", [1, 2]), ("roundup(@r1.数量*1.05)", [])])
def test_declared_rounding_params_are_the_ones_the_engine_skips(expr, exempt):
    decl = UNITS["table.build"]["signature"]["input_schema"]["properties"]["table"]["properties"]["rows"]["x-mengos-expr-params"]
    assert sorted(engine_exempt(expr, {k: set(v) for k, v in decl.items()})) == sorted(exempt)


def test_formula_and_numbering_columns_refuse_expr(tmp_path):
    for col in ({"title": "金额", "type": "money", "formula": "数量 * 2"}, {"title": "序号", "numbering": "seq"}):
        t = {"title": "T", "columns": [{"title": "数量", "type": "integer"}, col], "rows": [{"数量": 1, col["title"]: {"$expr": "1+1"}}]}
        r, _ = run("table.build", {"table": t}, tmp_path, col["title"])
        assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and "$expr" in r["error"]["message"], r


# ───────────────────────── 合并代数（行带 $id、格带 $expr，分批追加） ─────────────────────────
def test_rows_with_ids_and_exprs_append_through_the_engine_merge(tmp_path):
    cols = [{"key": "name", "title": "名称", "type": "text"}, {"key": "qty", "title": "数量", "type": "integer"}]
    first = {"table": {"title": "T", "sheets": [{"id": "s01", "name": "01立柱", "columns": cols,
                                                "rows": [{"$id": "r1", "名称": "立柱", "数量": {"$expr": "6*28"}}]}]}}
    d1 = {"table": {"sheets": [{"id": "s01", "rows": [{"名称": "立柱型材", "数量": {"$expr": "@r1.数量"}}]}]}}
    assert touched_keys(BUILD, d1) == {"table.sheets#s01.rows+"}
    jsonschema.validate({"base": "v-1", **d1}, BUILD)
    r, w = run("table.build", merge(BUILD, first, d1), tmp_path)
    assert r["ok"], r
    v = json.loads(files(r, w)["view"])
    assert v["sheets"][0]["rows"] == [["立柱", "168"], ["立柱型材", "168"]]


# ───────────────────────── 表模型往返 ─────────────────────────
@pytest.mark.parametrize("cid", ["t8_01_full", "t9_11_deliverable", "t8_03_linked", "t3_07_group_subtotal"])
def test_model_round_trip_keeps_structure_exprs_and_ids(cid, tmp_path):
    r, w = run("table.build", G[cid]["payload"], tmp_path, "b")
    assert r["ok"], r
    m = json.loads(files(r, w)["json"])
    r2, w2 = run("table.export", {"object": m, "formats": ["json"]}, tmp_path, "e")
    assert r2["ok"], r2
    assert r2["output"]["table_sha256"] == r["output"]["table_sha256"]
    a, b = render.to_view(model.normalize(m)), json.loads(files(r, w)["view"])
    a["stats"].pop("warnings"), b["stats"].pop("warnings")      # build 才有的告警（如空表 no_rows）导出时不再报
    assert json.loads(json.dumps(a)) == b


def test_percent_values_from_the_model_are_not_divided_again(tmp_path):
    """2.0.x 起的旧缺口：表模型里百分比已存成小数，从表模型再导出时不能再除以 100。"""
    t = {"title": "T", "columns": [{"title": "部门"}, {"title": "增长", "type": "percent", "decimals": 1}], "rows": [["甲", 12.5]]}
    r, w = run("table.build", {"table": t}, tmp_path, "b")
    m = json.loads(files(r, w)["json"])
    r2, w2 = run("table.export", {"object": m, "formats": ["md", "json"]}, tmp_path, "e")
    assert "| 甲 | 12.5% |" in files(r2, w2)["md"].decode() and r2["output"]["table_sha256"] == r["output"]["table_sha256"]


# ───────────────────────── G7 / G17：行跟着它的 id 走 ─────────────────────────
def test_group_reorder_keeps_cell_references_on_the_right_rows(tmp_path):
    """按一列分组会把同组的行排到一起；格公式按 id 引用，排序以后 Excel 里仍指向原来那一行。"""
    cols = [{"key": "sup", "title": "供应商", "type": "text"}, {"key": "name", "title": "品名", "type": "text"},
            {"key": "qty", "title": "数量", "type": "integer"}]
    rows = [{"$id": "a", "供应商": "甲", "品名": "桌", "数量": 10}, {"$id": "b", "供应商": "乙", "品名": "椅", "数量": {"$expr": "@a.数量*2"}},
            {"$id": "c", "供应商": "甲", "品名": "柜", "数量": {"$expr": "@b.数量+1"}}]
    r, w = run("table.build", {"table": {"title": "T", "columns": cols, "rows": rows, "group": {"by": "供应商"}}}, tmp_path)
    assert r["ok"], r
    v = json.loads(files(r, w)["view"])
    assert [row[1] for row in v["sheets"][0]["rows"]] == ["桌", "柜", "椅"]          # 同组排在一起
    assert [row[2] for row in v["sheets"][0]["rows"]] == ["10", "21", "20"]
    ws = openpyxl.load_workbook(io.BytesIO(files(r, w)["xlsx"])).active
    # 版面：1 表头，2 组头甲，3 桌，4 柜，5 组头乙，6 椅
    assert ws["C4"].value == "=C6+1" and ws["C6"].value == "=C3*2"


def test_ref_no_match_warns_instead_of_silently_zero(tmp_path):
    t = {"title": "T", "sheets": [
        {"id": "bud", "columns": [{"key": "k", "title": "科目", "type": "text"},
                                  {"title": "实际", "type": "money", "formula": "sumif(det.科目, 科目, det.金额)"}], "rows": [["办公耗材"], ["差旅费"]]},
        {"id": "det", "columns": [{"key": "k", "title": "科目", "type": "text"}, {"key": "a", "title": "金额", "type": "money"}], "rows": [["差旅费", 5]]}]}
    r, w = run("table.build", {"table": t}, tmp_path)
    assert [x["code"] for x in r["output"]["warnings"]] == ["ref_no_match"] and "第 1 行" in r["output"]["warnings"][0]["message"]


def test_derived_sheet_rows_are_generated_not_given(tmp_path):
    t = {"title": "T", "sheets": [{"id": "a", "columns": [{"title": "名称", "type": "text"}, {"title": "数量", "type": "integer"}], "rows": [["x", 1]]},
                                  {"id": "d", "columns": [{"title": "名称", "type": "text"}, {"title": "数量", "type": "integer"}],
                                   "derive": {"from": ["a"], "by": ["名称"], "agg": {"数量": "sum"}}, "rows": [["y", 2]]}]}
    r, _ = run("table.build", {"table": t}, tmp_path)
    assert not r["ok"] and r["error"]["where"] == "table.sheets[1].rows"


def test_sheet_cycle_is_rejected_naming_the_sheets(tmp_path):
    def sheet(sid, other):
        return {"id": sid, "name": sid, "columns": [{"key": "k", "title": "科目", "type": "text"}, {"key": "v", "title": "值", "type": "money"},
                                                    {"title": "汇", "type": "money", "formula": f"sumif({other}.科目, 科目, {other}.值)"}], "rows": [["x", 1]]}
    r, _ = run("table.build", {"table": {"title": "T", "sheets": [sheet("a", "b"), sheet("b", "a")]}}, tmp_path)
    assert not r["ok"] and "成环" in r["error"]["message"]


# ───────────────────────── G11 ─────────────────────────
def test_check_output_has_summary_and_problems_and_matches_schema(tmp_path):
    c = G["t9_09_cross_checks"]
    r = table_tool.run({"tool": "table.check", "payload": c["payload"]})
    jsonschema.validate(r["output"], UNITS["table.check"]["signature"]["output_schema"])
    assert r["output"]["summary"].startswith("4 条核对不通过")
    probs = [p for ch in r["output"]["checks"] for p in ch.get("problems", [])]
    assert all({"sheet", "rule", "actual"} <= set(p) for p in probs)


def test_check_never_changes_the_table():
    c = G["t9_09_cross_checks"]
    before = json.dumps(c["payload"], sort_keys=True)
    table_tool.run({"tool": "table.check", "payload": json.loads(before)})
    assert json.dumps(c["payload"], sort_keys=True) == before


# ───────────────────────── 只放宽 ─────────────────────────
def test_csv_of_merged_tables_writes_visible_rows_only(tmp_path):
    r, w = run("table.build", {**G["t5_03_merge_formula"]["payload"], "formats": ["csv"]}, tmp_path)
    lines = files(r, w)["csv"].decode("utf-8-sig").strip().split("\r\n")
    assert len(lines) == 1 + 10                                    # 11 行并成 10 行（看得见的行）


@pytest.mark.parametrize("formula,warn", [("168", True), ("数量*0+168", True), ("0*数量", True), ("单价*数量", False), ("total(数量)", False)])
def test_formula_no_column_warning(formula, warn, tmp_path):
    t = {"title": "T", "columns": [{"title": "数量", "type": "integer"}, {"title": "单价", "type": "money"},
                                  {"title": "金额", "type": "money", "formula": formula}], "rows": [[1, 2]]}
    r, _ = run("table.build", {"table": t}, tmp_path)
    assert ("formula_no_column" in [w["code"] for w in r["output"]["warnings"]]) is warn


@pytest.mark.parametrize("col,vals,warn", [
    ({"title": "单价", "type": "text"}, ["12", "15.5"], True),
    ({"title": "编号", "type": "text"}, ["1", "1.1"], False),                       # 标题像编号
    ({"title": "零件", "type": "text", "identifier": True}, ["12", "15"], False),   # identifier
    ({"title": "零件", "type": "text"}, ["0012", "15"], False),                     # 前导零
    ({"title": "层", "type": "text"}, ["1.10", "2"], False),                        # 小数点后末尾零
    ({"title": "单价"}, ["12", "15"], False),                                       # 没写 type：推断成数，不告警
    ({"title": "名称", "type": "text"}, ["甲", "12"], False)])
def test_numeric_as_text_warning(col, vals, warn, tmp_path):
    t = {"title": "T", "columns": [col], "rows": [[v] for v in vals]}
    r, _ = run("table.build", {"table": t}, tmp_path)
    assert r["ok"], r
    assert ("numeric_as_text" in [w["code"] for w in r["output"]["warnings"]]) is warn


def test_old_tables_have_no_new_view_fields(tmp_path):
    r, w = run("table.build", G["b_formula_totals"]["payload"], tmp_path)
    v = json.loads(files(r, w)["view"])["sheets"][0]
    for k in ("layout", "exprs", "derive", "merge"):
        assert k not in v
