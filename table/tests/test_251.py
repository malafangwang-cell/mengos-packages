"""2.5.1 的包内核对：列属性 count: true——这一列只认经 $count 写入的格。
  · 别处写的值（对象行的普通键、数组行的格）不进表，回执 unfilled 逐格列出（带表、行、列），不报错、不整件拒；
  · 经 $count 写入照常；没标 count 的列照旧（含同一列写两处仍拒）；
  · count 列两处都写时以 $count 为准（带 base 并入时上一版的普通格不作数）；表模型写出、读回后仍算经 $count 写入。"""
import json
from pathlib import Path

import model
from test_220 import run

ROOT = Path(__file__).resolve().parents[1]
UNITS = {u["tool_id"]: u for u in json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))["units"]}
COLS = [{"key": "item", "title": "项名", "type": "text"}, {"key": "val", "title": "值", "type": "number", "count": True}]
MSG = "表 facts 行 {rid} 列 val（值）的值写进这一行的 $count"


def call(tmp_path, rows, cols=COLS, name="c"):
    r, _ = run("table.build", {"table": {"title": "排布事实", "sheets": [{"id": "facts", "name": "排布事实", "columns": cols, "rows": rows}]}}, tmp_path, name)
    return r


def cell(r, ri=0, key="值"):
    sh = r["output"]["sheets"][0]
    return sh


def test_count_attribute_in_schema_all_tools():
    for u in UNITS.values():
        s = json.dumps(u["signature"]["input_schema"], ensure_ascii=False)
        assert '"count": {"type": "boolean"}' in s


def test_plain_value_in_count_column_goes_to_unfilled_not_table(tmp_path):
    r = call(tmp_path, [{"$id": "levels", "项名": "横梁层数", "值": 5}])
    assert r["ok"], r
    assert r["output"]["unfilled"] == [MSG.format(rid="levels")]
    t = model.normalize({"title": "排布事实", "sheets": [{"id": "facts", "name": "排布事实", "columns": COLS, "rows": [{"$id": "levels", "项名": "横梁层数", "值": 5}]}]}, build=True)
    assert t.sheets[0].rows[0][1] is None                      # 值不进表


def test_value_via_count_is_filled(tmp_path):
    r = call(tmp_path, [{"$id": "levels", "项名": "横梁层数", "$count": {"值": 5}}])
    assert r["ok"] and r["output"]["unfilled"] == []


def test_array_row_count_cell_is_unfilled(tmp_path):
    r = call(tmp_path, [["横梁层数", 5]])
    assert r["ok"] and r["output"]["unfilled"] == ["表 facts 第 1 行（没有 $id）列 val（值）的值写进这一行的 $count"]


def test_without_count_attribute_unchanged(tmp_path):
    cols = [COLS[0], {"key": "val", "title": "值", "type": "number"}]
    r = call(tmp_path, [{"$id": "x", "项名": "列数", "值": 10}], cols)
    assert r["ok"] and r["output"]["unfilled"] == []
    bad = call(tmp_path, [{"$id": "x", "项名": "列数", "值": 10, "$count": {"值": 10}}], cols, "b")
    assert bad["ok"] is False and "各写了一处" in json.dumps(bad["error"], ensure_ascii=False)


def test_count_column_both_places_count_wins(tmp_path):
    r = call(tmp_path, [{"$id": "x", "项名": "列数", "值": 999, "$count": {"值": 10}}])
    assert r["ok"] and r["output"]["unfilled"] == []
    t = model.normalize({"title": "T", "sheets": [{"id": "facts", "columns": COLS, "rows": [{"$id": "x", "项名": "列数", "值": 999, "$count": {"值": 10}}]}]}, build=True)
    assert str(t.sheets[0].rows[0][1]) == "10"


def test_empty_count_cell_not_listed_unless_required(tmp_path):
    r = call(tmp_path, [{"$id": "x", "项名": "列数"}])
    assert r["ok"] and r["output"]["unfilled"] == []
    cols = [COLS[0], {**COLS[1], "required": True}]
    r2 = call(tmp_path, [{"$id": "x", "项名": "列数"}], cols, "r")
    assert r2["output"]["unfilled"] == ["表 facts 行 x 列 val（值）未填"]


def test_model_round_trip_keeps_counted_cells():
    src = {"title": "T", "sheets": [{"id": "facts", "columns": COLS, "rows": [{"$id": "x", "项名": "列数", "$count": {"值": 10}}]}]}
    t = model.normalize(src, build=True)
    j = t.to_json()
    row = j["sheets"][0]["rows"][0]
    assert row["$count"] == {"val": "10"} and "val" not in {k for k in row if k != "$count"}
    t2 = model.normalize(j, build=True)
    assert str(t2.sheets[0].rows[0][1]) == "10" and model.unfilled(t2) == []
