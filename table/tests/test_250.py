"""2.5.0 的包内核对：数量容器 $count（17 TL-30c）。
  · 对象行的保留键 $count：{列: 值}；schema 上标 x-mengos-count，且沿 properties/items 可达（引擎的证件账能读到）。
  · 证件核对在引擎：裸数、混了原文数的算式被拒，引用、量全由引用给出的算式通过——见 mengosv2 tests/（用本包的真 schema 跑证件账）。
  · 工具侧：引擎换成数以后，$count 里的格并入这一行，与直接写在行里的格一样参与公式、合计与未填项；同一列写两处、表里没有的列、不是值 ⟹ BAD_INPUT。"""
import json
from pathlib import Path

import pytest

from test_220 import run

ROOT = Path(__file__).resolve().parents[1]
UNITS = {u["tool_id"]: u for u in json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))["units"]}
COLS = [{"key": "item", "title": "项名", "type": "text"}, {"key": "src", "title": "取数/算式", "type": "text"},
        {"key": "val", "title": "值", "type": "number", "required": True}]


def call(tmp_path, rows, name="c"):
    return run("table.build", {"table": {"title": "排布事实", "sheets": [{"id": "facts", "name": "排布事实", "columns": COLS, "rows": rows}]}}, tmp_path, name)


def paths_with(node, key, path=""):
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in paths_with(v, key, f"{path}/{i}")]
    if not isinstance(node, dict):
        return []
    return ([path] if node.get(key) is True else []) + [p for k, v in node.items() for p in paths_with(v, key, f"{path}/{k}")]


def reachable(schema, path):
    """沿 properties / items 能不能走到 path（与引擎同口径：不进 oneOf、anyOf、if/then/else）"""
    segs = path.strip("/").split("/")
    i = 0
    while i < len(segs):
        if segs[i] in ("properties",) and i + 1 < len(segs):
            i += 2
        elif segs[i] == "items":
            i += 1
        else:
            return False
    return True


@pytest.mark.parametrize("tool", ["table.build", "table.check", "table.export"])
def test_count_container_declared_and_reachable(tool):
    s = UNITS[tool]["signature"]["input_schema"]
    counts = paths_with(s, "x-mengos-count")
    assert counts and all(p.endswith("/items/properties/$count") for p in counts)
    assert all(reachable(s, p) for p in counts)
    for p in paths_with(s, "x-mengos-display"):
        if p.endswith("/$style"):
            assert reachable(s, p), p          # 2.5.0 顺带：$style 的显示设置声明从此可达
    assert "oneOf" not in json.dumps([s["properties"]["table"]["properties"]["rows"]["items"]])


def test_count_cells_merge_into_row_and_fill_required(tmp_path):
    r, _ = call(tmp_path, [{"$id": "levels", "项名": "横梁层数", "取数/算式": "层间距段数 + 1", "$count": {"值": 5}},
                           {"$id": "rows1", "项名": "托盘区一排数", "$count": {"val": 8}}])
    assert r["ok"], r
    assert r["output"]["unfilled"] == []


def test_missing_count_cell_still_unfilled(tmp_path):
    r, _ = call(tmp_path, [{"$id": "levels", "项名": "横梁层数"}])
    assert r["ok"] and r["output"]["unfilled"] == ["表 facts 行 levels 列 val（值）未填"]


def test_same_output_as_direct_cell(tmp_path):
    a, _ = call(tmp_path, [{"$id": "x", "项名": "列数", "$count": {"值": 10}}], "a")
    b, _ = call(tmp_path, [{"$id": "x", "项名": "列数", "值": 10}], "b")
    # 2.5.3：写进过 $count 的列按 count 列、必填对待，表模型多写这两个列属性（table_sha256 随之不同）；其余回执相同
    strip = lambda o: {k: v for k, v in o["output"].items() if k not in ("files", "receipt_files", "table_sha256")}
    assert json.dumps(strip(a), sort_keys=True, ensure_ascii=False) == json.dumps(strip(b), sort_keys=True, ensure_ascii=False)


def test_count_column_auto_and_unknown_column_kept_out(tmp_path):
    """2.5.3：写进过 $count 的列按 count 列对待——同一列两处写时以 $count 为准（同 2.5.1）；
    $count 里写了表里没有的列 ⟹ 这一格不收，原因进未填项，其余照收。"""
    for i, row in enumerate(({"$id": "x", "项名": "列数", "值": 999, "$count": {"值": 10}}, {"$id": "x", "项名": "列数", "val": 999, "$count": {"值": 10}})):
        r, _ = call(tmp_path, [row], f"c{i}")
        assert r["ok"] and r["output"]["unfilled"] == [], r
    r, _ = call(tmp_path, [{"$id": "x", "项名": "列数", "$count": {"不存在": 1, "值": 3}}], "c9")
    assert r["ok"], r
    assert r["output"]["unfilled"] == ["表 facts 行 x 写了这张表没有的列“不存在”，没有收；这张表的列是：项名、取数/算式、值"]


@pytest.mark.parametrize("row,word", [
    ({"$id": "x", "项名": "列数", "$count": {"值": {"$ref": "n1#/count"}}}, "不是一个值"),
    ({"$id": "x", "项名": "列数", "$count": [10]}, "是对象"),
])
def test_count_bad_input(tmp_path, row, word):
    r, _ = call(tmp_path, [row])
    assert r["ok"] is False and r["error"]["code"] == "BAD_INPUT"
    assert word in json.dumps(r["error"], ensure_ascii=False)
