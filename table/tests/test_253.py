"""2.5.3 的包内核对：按格核对的两类核对项（cell、text）、回执 failed 与 table.check 的核验接入声明（17 TL-21a）。
依据 mengosv2《规格改句草案-规范包核对项经核验判据循环-2026-11-23》§一、§2.2；用例数据为编造。"""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from test_220 import run

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
V = UNITS["table.check"]["verify"]

FACTS = {"id": "facts", "name": "事实", "columns": [{"key": "item", "title": "项名", "type": "text"}, {"key": "val", "title": "值", "type": "number"}],
         "rows": [{"$id": "a", "项名": "甲数", "值": 12}, {"$id": "b", "项名": "乙数", "值": 3}, {"$id": "c", "项名": "边长", "值": 1250}]}
LIST = {"id": "list", "name": "清单", "columns": [{"key": "name", "title": "名称", "type": "text"}, {"key": "spec", "title": "规格", "type": "text"},
                                                  {"key": "qty", "title": "数量", "type": "number"}, {"key": "uw", "title": "单重/面积", "type": "number"}],
        "rows": [{"$id": "p1", "名称": "甲件", "规格": "50*20*1250", "数量": 8, "单重/面积": 2.5}, {"$id": "p2", "名称": "乙件", "规格": "M10*25", "数量": 7}]}


def table(*sheets):
    return {"title": "T", "sheets": copy.deepcopy(list(sheets))}


def check(tmp_path, t, expect, name="w"):
    r, _ = run("table.check", {"table": t, "expect": expect}, tmp_path, name)
    assert r["ok"], r
    return r["output"]


@pytest.mark.parametrize("line,verdict", [
    ("cell 清单/p1/数量 = 事实/a/值 / 事实/b/值 * 2", "pass"),           # 相等
    ("cell 清单/甲件/数量 = 8", "pass"),                                  # 行按前三列里的文字找
    ("cell 清单/p2/数量 = 事实/a/值 / 事实/b/值 * 2", "fail"),            # 不等
    ("cell 清单/p2/数量 = 7.4 tol=0.5", "pass"),                         # 含 tol
    ("cell 清单/p1/数量 = ceiling(事实/a/值 / 5)", "fail"),
    ("cell 清单/p1/单重/面积 = 2.5", "pass"),                             # 列名里有 /
    ("cell 清单/p1/重量 = 1", "fail"),                                   # 格（列）不存在
    ("cell 清单/丙件/数量 = 1", "fail"),                                  # 行不存在
    ("cell 清单/p2/单重/面积 = 1", "fail"),                               # 格为空
    ('text 清单/p1/规格 = "{事实/c/值}"', "pass"),                        # 含有
    ('text 清单/p1/规格 = "50*20*{=事实/c/值 - 50}"', "fail"),            # 不含
    ('text 清单/p2/规格 = "{事实/z/值}"', "fail"),                        # 模板里的格不存在
])
def test_cell_and_text(tmp_path, line, verdict):
    out = check(tmp_path, table(FACTS, LIST), line)
    mine = [c for c in out["checks"] if c["line"] > 0]
    assert len(mine) == 1 and mine[0]["kind"] == line[:4] and mine[0]["verdict"] == verdict, mine
    assert out["verdict"] == verdict
    assert (out["failed"] == []) == (verdict == "pass")


def test_failed_messages_name_cell_value_and_rule(tmp_path):
    out = check(tmp_path, table(FACTS, LIST), "\n".join([
        "cell 清单/p2/数量 = 事实/a/值 / 事实/b/值 * 2",
        'text 清单/p2/规格 = "M10*{事实/b/值}"',
        "cell 清单/丙件/数量 = 1",
    ]))
    assert out["failed"] == [
        "清单/p2/数量 现为 7；按规范它应等于 事实/a/值 / 事实/b/值 * 2，把这一格改成它；"
        "清单/p2/规格 现为“M10*25”；按规范这一格里应有“M10*3”（按 事实/b/值），把这一格改成含它的写法",
        "表 清单 里没有名为“丙件”的行：新增一行、名字写“丙件”，已有这一项而名字不同的把名字改成它（行的名字写在这一行的前三列里）；"
        "按规范它应等于 1，把这一格改成它",
    ]


def test_failed_only_lists_cell_and_text(tmp_path):
    out = check(tmp_path, table(FACTS, LIST), "rows min=9 sheet=清单")
    assert out["verdict"] == "fail" and out["failed"] == []


def test_corrected_item_disappears(tmp_path):
    t = table(FACTS, LIST)
    line = "cell 清单/p2/数量 = 事实/a/值 / 事实/b/值 * 2"
    assert len(check(tmp_path, t, line, "a")["failed"]) == 1
    t["sheets"][1]["rows"][1]["数量"] = 8
    out = check(tmp_path, t, line, "b")
    assert out["verdict"] == "pass" and out["failed"] == []


def test_failed_in_output_schema():
    out = UNITS["table.check"]["signature"]["output_schema"]
    assert out["properties"]["failed"] == {"type": "array", "items": {"type": "string"}}
    assert "failed" in out["required"]
    assert {"cell", "text"} <= set(UNITS["table.check"]["capability"]["constraints"]["kinds"])


# ───────────────────────── 核验接入声明（17 TL-21a） ─────────────────────────
def _slots(node, key):
    if isinstance(node, dict):
        if set(node) == {key}:
            return 1
        return sum(_slots(v, key) for v in node.values())
    if isinstance(node, list):
        return sum(_slots(v, key) for v in node)
    return 0


def test_verify_declared_on_check_only():
    assert [tid for tid, u in UNITS.items() if "verify" in u] == ["table.check"]
    assert V == {"for": ["table"], "input": {"table": {"$best": "/table"}, "expect": {"$checks": True}},
                 "predicate": {"pointer": "/verdict", "op": "equals", "value": "pass"}, "report": {"pointer": "/failed"}}


def test_verify_certifier_checks():
    assert set(V["for"]) <= {t["name"] for t in M["types"]}
    out = UNITS["table.check"]["signature"]["output_schema"]
    jsonschema.validate(V["predicate"]["value"], out["properties"]["verdict"])
    rep = out["properties"][V["report"]["pointer"].lstrip("/")]
    assert rep["type"] == "array" and rep["items"]["type"] == "string"
    assert _slots(V["input"], "$best") == 1 and _slots(V["input"], "$checks") == 1
    inp = UNITS["table.check"]["signature"]["input_schema"]
    assert set(V["input"]) <= set(inp["properties"])


def test_verify_template_runs(tmp_path):
    """照引擎的换法：$best 换成产物那次 table.build 的 /table，$checks 换成核对项各行以换行相接"""
    payload = copy.deepcopy(V["input"])
    payload["table"] = table(FACTS, LIST)
    payload["expect"] = "\n".join(["cell 清单/p1/数量 = 事实/a/值 / 事实/b/值 * 2", 'text 清单/p1/规格 = "{事实/c/值}"'])
    r, _ = run("table.check", payload, tmp_path, "ok")
    assert r["ok"] and r["output"]["verdict"] == V["predicate"]["value"] and r["output"]["failed"] == []
    payload["expect"] += "\ncell 清单/p2/数量 = 8"
    r, _ = run("table.check", payload, tmp_path, "bad")
    assert r["ok"] and r["output"]["verdict"] == "fail" and len(r["output"]["failed"]) == 1
