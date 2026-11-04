"""安全：不执行代码；SVG 只收纯图形；正文里的原始 HTML 被转义；危险链接不成为链接；只写 workdir。"""
import json
import re
from pathlib import Path

import pytest

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["model.py", "assemble.py", "render.py", "docx_writer.py", "checker.py", "doc_tool.py"]
NS = 'xmlns="http://www.w3.org/2000/svg"'


def test_no_dynamic_code_in_sources():
    for name in SOURCES:
        text = (ROOT / name).read_text(encoding="utf-8")
        for pat in (r"(?<![\w.])eval\(", r"(?<![\w.])exec\(", r"\bsubprocess\b", r"__import__", r"\bpickle\b", r"os\.system"):
            assert not re.search(pat, text), (name, pat)


@pytest.mark.parametrize("svg", [
    f"<svg {NS}><script>alert(1)</script></svg>",
    f'<svg {NS} onload="alert(1)"/>',
    f'<svg {NS}><a href="javascript:alert(1)"><rect width="1" height="1"/></a></svg>',
    f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink"><image xlink:href="https://tracker.example/x.png"/></svg>',
    f"<svg {NS}><foreignObject><div>x</div></foreignObject></svg>",
    f"<svg {NS}><style>@import url(https://x.example/a.css);</style></svg>",
    f'<svg {NS}><rect style="fill:url(https://x.example/p)"/></svg>',
    f'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg {NS}><text>&a;</text></svg>',
    "<html><body/></html>",
    "<svg",
])
def test_svg_rejected(svg, tmp_path):
    d = {"title": "t", "sections": [{"heading": "a"}], "figures": [{"id": "f", "caption": "c", "source": {"svg": svg}}]}
    r = doc_tool.run({"tool": "doc.build", "payload": {"doc": d}, "workdir": str(tmp_path)})
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", r
    assert list(tmp_path.iterdir()) == []


def test_internal_references_in_svg_allowed(tmp_path):
    svg = (f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10"><defs><path id="p" d="M0 0h5"/></defs>'
           f'<use xlink:href="#p"/><rect width="10" height="10" fill="url(#g)"/></svg>')
    d = {"title": "t", "sections": [{"heading": "a", "body": "[[fig:f]]"}], "figures": [{"id": "f", "caption": "c", "source": {"svg": svg}}]}
    assert doc_tool.run({"tool": "doc.build", "payload": {"doc": d}, "workdir": str(tmp_path)})["ok"]


def test_raw_html_and_bad_links_are_neutralized(tmp_path):
    body = "<script>alert(1)</script>\n\n[点我](javascript:alert(1)) [好链接](https://example.com)\n\n<img src=x onerror=alert(1)>"
    d = {"title": "t", "sections": [{"heading": "a", "body": body}]}
    r = doc_tool.run({"tool": "doc.build", "payload": {"doc": d, "formats": ["html"]}, "workdir": str(tmp_path)})
    assert r["ok"]
    html = next((tmp_path / f["path"]).read_text(encoding="utf-8") for f in r["output"]["files"] if f["format"] == "html")
    view = json.loads(next((tmp_path / f["path"]).read_text(encoding="utf-8") for f in r["output"]["files"] if f["format"] == "view"))
    for text in (html, view["sections"][0]["html"]):
        assert "<script>" not in text and "&lt;script&gt;" in text
        assert 'href="javascript' not in text
        assert "<img src=x" not in text
        assert 'href="https://example.com" rel="noopener noreferrer"' in text


def test_writes_only_into_workdir(tmp_path):
    d = {"title": "t", "sections": [{"heading": "a"}]}
    for name in ("../escape", "a/b", "..", ".hidden", "a b"):
        r = doc_tool.run({"tool": "doc.export", "payload": {"doc": d, "name": name, "formats": ["md"]}, "workdir": str(tmp_path)})
        assert not r["ok"], name
    r = doc_tool.run({"tool": "doc.export", "payload": {"doc": d, "formats": ["md"]}, "workdir": "relative/dir"})
    assert not r["ok"] and r["error"]["where"] == "workdir"
    assert list(tmp_path.iterdir()) == []


def test_control_characters_rejected(tmp_path):
    d = {"title": "t", "sections": [{"heading": "a", "body": "x\x1by"}]}
    r = doc_tool.run({"tool": "doc.check", "payload": {"doc": d}})
    assert not r["ok"] and "U+001B" in r["error"]["message"]


def test_timeout_is_structured():
    d = {"title": "t", "sections": [{"heading": f"h{i}", "body": "字" * 2000} for i in range(400)]}
    r = doc_tool.run({"tool": "doc.check", "payload": {"doc": d}, "budget": {"timeout_ms": 1}})
    assert not r["ok"] and r["error"]["code"] == "TIMEOUT"
