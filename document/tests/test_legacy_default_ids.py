"""工具自己的缺省 id 行为（工具代码未改）：节不带 id 时，工具按 s1、s2… 缺省，缺省 id 与显式 id 相同时拒收。

2.0.0 起 doc.build 的 input_schema 要求每节带 id，引擎按 schema 先校验，缺 id 的入参到不了工具；
这里不经 schema、直接调工具，守住工具侧行为不变（doc.check、doc.export 的 schema 仍接受缺 id 的节）。
"""
import json
from pathlib import Path

import jsonschema
import pytest

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
UNITS = {u["tool_id"]: u for u in REG["units"]}
OLD_SHAPE = {"title": "读书角方案", "sections": [{"heading": "背景", "body": "社区需要。"}, {"heading": "预算", "body": "五千元。"}]}


def _run(tool, payload, tmp_path):
    return doc_tool.run({"tool": tool, "payload": payload, "workdir": str(tmp_path)})


def test_tool_still_defaults_section_ids(tmp_path):
    r = _run("doc.build", {"doc": OLD_SHAPE}, tmp_path)
    assert r["ok"], r
    assert [o["id"] for o in r["output"]["outline"]] == ["s1", "s2"]


def test_default_id_clash_still_rejected_by_the_tool(tmp_path):
    d = {"title": "T", "sections": [{"heading": "A", "body": "正文。", "id": "s2"}, {"heading": "B", "body": "正文。"}]}
    r = _run("doc.build", {"doc": d}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and r["error"]["where"] == "doc.sections[1].id"


def test_schema_split_build_requires_id_check_and_export_do_not():
    payload = {"doc": OLD_SHAPE}
    assert not jsonschema.Draft202012Validator(UNITS["doc.build"]["signature"]["input_schema"]).is_valid(payload)
    assert jsonschema.Draft202012Validator(UNITS["doc.check"]["signature"]["input_schema"]).is_valid(payload)
    assert jsonschema.Draft202012Validator(UNITS["doc.export"]["signature"]["input_schema"]).is_valid(payload)
