"""17 TL-9b：派生下载按 {object: 规范对象, format|formats} 调导出工具（1.2.4）。

规范对象是排版那一步的产出记录（tool、args、output）；文档内容取自 args.doc。
W-9 H2 读数：1.2.3 只认 doc，派生下载 502（不认识的字段：format, object）。
"""
import json
import re
from pathlib import Path

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
DOC = json.loads((ROOT / "samples" / "reading_corner.json").read_text(encoding="utf-8"))
REG = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))


def _export(payload, d):
    return doc_tool.run({"tool": "doc.export", "payload": payload, "workdir": str(d)})


def _record(tmp_path, name=None):
    d = tmp_path / "build"
    d.mkdir()
    args = {"doc": DOC} | ({"name": name} if name else {})
    r = doc_tool.run({"tool": "doc.build", "payload": args, "workdir": str(d)})
    assert r["ok"], r
    return {"tool": "doc.build", "args": args, "output": r["output"]}


def test_object_with_single_format_as_engine_sends(tmp_path):
    """引擎在 schema 不声明 formats 时发 format（derived-export.ts）；两种键形都要接。"""
    rec = _record(tmp_path)
    for i, payload in enumerate([{"object": rec, "format": "docx"}, {"object": rec, "formats": ["docx"]}]):
        d = tmp_path / f"e{i}"
        d.mkdir()
        r = _export(payload, d)
        assert r["ok"], r
        f0 = r["output"]["files"][0]
        assert f0["format"] == "docx" and f0["sha256"]          # 端点取 files[0].sha256 为派生对象


def test_object_equals_doc(tmp_path):
    """给 object 与直接给 doc，产出逐字节相同；名字沿用排版时的 name。"""
    rec = _record(tmp_path, name="读书角方案")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    ra = _export({"object": rec, "formats": ["docx", "md"]}, a)
    rb = _export({"doc": DOC, "name": "读书角方案", "formats": ["docx", "md"]}, b)
    assert ra["ok"] and rb["ok"], (ra, rb)
    assert ra["output"] == rb["output"]
    assert ra["output"]["name"] == "读书角方案"


def test_object_errors(tmp_path):
    rec = _record(tmp_path)
    cases = [
        ({"object": rec, "doc": DOC, "formats": ["docx"]}, "二选一"),
        ({"formats": ["docx"]}, "二选一"),
        ({"object": "abc", "formats": ["docx"]}, "JSON 对象"),
        ({"object": {"tool": "cad.build", "args": {"plan": "box 1 1 1"}}, "formats": ["docx"]}, "不是文档"),
        ({"object": {"tool": "doc.build", "args": {}}, "formats": ["docx"]}, "没有文档内容"),
        ({"object": rec, "format": "docx", "formats": ["docx"]}, "二选一"),
        ({"object": rec, "format": "odt"}, "不支持的格式"),      # 2.2.0 起 pdf 已支持，改用仍不支持的 odt
    ]
    for payload, words in cases:
        r = _export(payload, tmp_path)
        assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and words in r["error"]["message"], (payload.keys(), r)
        assert not re.search(r"\b(?:doc|cad)\.(?:build|check|export)\b", r["error"]["message"]), r


def test_schema_declares_tl9b_shape():
    u = next(u for u in REG["units"] if u["tool_id"] == "doc.export")
    sch = u["signature"]["input_schema"]
    assert {"object", "formats", "format", "doc"} <= set(sch["properties"])
    assert sch["oneOf"] == [{"required": ["doc"]}, {"required": ["object"]}]


def test_model_facing_text_names_no_tool():
    """给模型看的文字不点名工具（说明里点名别的工具，选择模型会被带去调那件）。"""
    pat = re.compile(r"\b(?:doc|cad|calc|math|probe)\.(?:build|check|export|eval|solve|make)\b")

    def strings(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
        elif isinstance(o, str):
            yield o

    for u in REG["units"]:
        body = {k: v for k, v in u.items() if k != "tool_id"}
        hits = [s for s in strings(body) if pat.search(s)]
        assert not hits, (u["tool_id"], hits)
