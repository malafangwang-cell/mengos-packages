"""2.7.1：cad.check 的核验接入声明（17 TL-21a；mengosv2《逐字稿-零件建模四条约束与cad.check核验接入-2026-11-21》§三）。
照 TL-21a 认证程序要核的几项在包内先核一遍：for 里的类型已登记；predicate 的 pointer 在 output_schema 中可解析、value 符合该处 schema；
input 的 best 占位至多一处，其余键都是 cad.check 的入参。再用声明的 input 实跑：一个连成一体的零件判 pass，两块分开的判 fail。"""
import copy
import json
from pathlib import Path

import jsonschema

from cad_tool import run

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
V = UNITS["cad.check"]["verify"]


def _best_paths(node, path=""):
    if isinstance(node, dict):
        if set(node) == {"$best"}:
            return [path]
        return [p for k, v in node.items() for p in _best_paths(v, f"{path}/{k}")]
    if isinstance(node, list):
        return [p for i, v in enumerate(node) for p in _best_paths(v, f"{path}/{i}")]
    return []


def _resolve(schema, pointer):
    for part in pointer.lstrip("/").split("/"):
        schema = schema["properties"][part]
    return schema


def test_declared_on_check_only_with_tl21a_shape():
    assert [tid for tid, u in UNITS.items() if "verify" in u] == ["cad.check"]
    assert set(V) == {"for", "input", "predicate"}
    assert V == {"for": ["cad_part"], "input": {"plan": {"$best": "/plan"}, "expect": "solids 1\nvalid"},
                 "predicate": {"pointer": "/verdict", "op": "equals", "value": "pass"}}


def test_certifier_checks():
    types = {t["name"] for t in M["types"]}
    assert set(V["for"]) <= types
    out = UNITS["cad.check"]["signature"]["output_schema"]
    jsonschema.validate(V["predicate"]["value"], _resolve(out, V["predicate"]["pointer"]))
    assert len(_best_paths(V["input"])) <= 1
    inp = UNITS["cad.check"]["signature"]["input_schema"]
    assert set(V["input"]) <= set(inp["properties"]) and set(inp["required"]) <= set(V["input"])


def _fill(plan):
    payload = copy.deepcopy(V["input"])
    payload["plan"] = plan          # $best 指向产物的 /plan，这里直接放一份计划
    return payload


def test_template_runs(tmp_path):
    one = run({"tool": "cad.check", "payload": _fill("base: box 80 50 20\nh1: hole d=20 at=center from=top through")})
    assert one["ok"] and one["output"]["verdict"] == V["predicate"]["value"], one
    two = run({"tool": "cad.check", "payload": _fill("a: box 10 10 10\nb: box 10 10 10 at=(50,0,0)")})
    assert two["ok"] and two["output"]["verdict"] == "fail", two
