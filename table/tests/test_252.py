"""2.5.2 的包内核对：count 列按规范留空的写法 {"$blank": 条文号}（写在 $count 里）。
  · 这一格留空、不计入未填（含 required），回执 blanks 每格一条、带条文号；没有留空格时回执不带 blanks（旧回执逐字节不变）。
  · 条文号只核写法（字母开头，如 R2.3、T9），不核是否本 run 引过的规范——工具拿不到锚点。
  · $blank 只用于标了 count 的列；同一列 $blank 与直接写在行里的值同在时，按 2.5.1 的规矩以 $count 为准（直接写的值不进表），不报错。
  · 表模型写出、读回后留空与条文号照旧。"""
import json

import pytest

import model
from test_220 import run

COLS = [{"key": "name", "title": "产品名称", "type": "text"}, {"key": "qty", "title": "数量", "type": "integer", "count": True, "required": True}]


def call(tmp_path, rows, cols=COLS, name="c"):
    r, _ = run("table.build", {"table": {"title": "总清单", "sheets": [{"id": "total", "name": "总清单", "columns": cols, "rows": rows}]}}, tmp_path, name)
    return r


def test_blank_not_unfilled_and_recorded(tmp_path):
    r = call(tmp_path, [{"$id": "r1", "产品名称": "立柱片", "$count": {"数量": 12}},
                        {"$id": "r2", "产品名称": "货架安装说明", "$count": {"数量": {"$blank": "R2.3"}}}])
    assert r["ok"], r
    assert r["output"]["unfilled"] == []
    assert r["output"]["blanks"] == ["表 total 行 r2 列 qty（数量）按 R2.3 留空"]


def test_no_blanks_key_when_none(tmp_path):
    r = call(tmp_path, [{"$id": "r1", "产品名称": "立柱片", "$count": {"数量": 12}}])
    assert r["ok"] and "blanks" not in r["output"]


def test_blank_cell_is_empty_in_table():
    t = model.normalize({"title": "T", "sheets": [{"id": "total", "columns": COLS, "rows": [{"$id": "r2", "产品名称": "x", "$count": {"数量": {"$blank": "R2.3"}}}]}]}, build=True)
    assert t.sheets[0].rows[0][1] is None and model.unfilled(t) == []


@pytest.mark.parametrize("v", [{"$blank": ""}, {"$blank": "2.3"}, {"$blank": 3}, {"$blank": "R2.3", "x": 1}, {"$blank": "R 2.3"}])
def test_blank_bad_shape(tmp_path, v):
    r = call(tmp_path, [{"$id": "r2", "产品名称": "x", "$count": {"数量": v}}])
    assert r["ok"] is False and r["error"]["code"] == "BAD_INPUT"


def test_blank_only_for_count_columns(tmp_path):
    cols = [{"key": "name", "title": "产品名称", "type": "text"}, {"key": "qty", "title": "数量", "type": "integer"}]
    # 2.5.3：写进过 $count 的列按 count 列对待，所以经 $count 写的 $blank 总在 count 列上，照收
    r = call(tmp_path, [{"$id": "r2", "产品名称": "x", "$count": {"数量": {"$blank": "R2.3"}}}], cols)
    assert r["ok"] and r["output"]["blanks"] == ["表 total 行 r2 列 qty（数量）按 R2.3 留空"], r


def test_blank_with_direct_value_count_wins(tmp_path):
    r = call(tmp_path, [{"$id": "r2", "产品名称": "x", "数量": 5, "$count": {"数量": {"$blank": "R2.3"}}}])
    assert r["ok"] and r["output"]["unfilled"] == [] and r["output"]["blanks"] == ["表 total 行 r2 列 qty（数量）按 R2.3 留空"]


def test_round_trip_keeps_blank():
    src = {"title": "T", "sheets": [{"id": "total", "columns": COLS, "rows": [{"$id": "r2", "产品名称": "x", "$count": {"数量": {"$blank": "R2.3"}}}]}]}
    j = model.normalize(src, build=True).to_json()
    assert j["sheets"][0]["rows"][0]["$count"] == {"qty": {"$blank": "R2.3"}}
    t2 = model.normalize(j, build=True)
    assert model.unfilled(t2) == [] and model.blanks(t2) == ["表 total 行 r2 列 qty（数量）按 R2.3 留空"]


def test_schema_accepts_blank_in_count():
    from pathlib import Path
    from jsonschema import Draft202012Validator
    reg = json.loads((Path(__file__).resolve().parents[1] / "registration.json").read_text(encoding="utf-8"))
    s = next(u for u in reg["units"] if u["tool_id"] == "table.build")["signature"]["input_schema"]
    v = Draft202012Validator(s)
    ok = {"table": {"title": "T", "sheets": [{"id": "total", "columns": COLS, "rows": [{"$id": "r2", "$count": {"数量": {"$blank": "R2.3"}}}]}]}}
    bad = {"table": {"title": "T", "sheets": [{"id": "total", "columns": COLS, "rows": [{"$id": "r2", "$count": {"数量": {"$blank": "2.3"}}}]}]}}
    assert v.is_valid(ok) and not v.is_valid(bad)
