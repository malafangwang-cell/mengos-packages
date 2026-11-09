"""独立审查（2026-10-03）发现的问题，逐条钉成回归测试。每条都曾经导致崩溃、错误输出或绕过检查。"""
import io
import json
import os
import struct
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path

import docx
import pytest
from markdown_it import MarkdownIt

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
NS = 'xmlns="http://www.w3.org/2000/svg"'
MD = MarkdownIt("commonmark").enable(["table"])
JPEG_NO_JFIF = (  # 4×3 的合法 JPEG，去掉了 JFIF 段，以 FF D8 FF DB 开头
    "/9j/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMo"
    "GhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAADAAQDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEA"
    "AAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0"
    "NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ"
    "2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdh"
    "cRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaX"
    "mJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDiqKKK8A/Wz//Z")


def run(tool, payload, workdir=None, **env):
    e = {"tool": tool, "payload": payload, **env}
    if workdir is not None:
        e["workdir"] = str(workdir)
    return doc_tool.run(e)


def build(doc, tmp_path, formats=("docx", "html")):
    r = run("doc.build", {"doc": doc, "formats": list(formats)}, tmp_path)
    assert r["ok"], r
    files = {f["format"] if f["format"] != "figure" else f["path"]: (tmp_path / f["path"]).read_bytes()
             for f in r["output"]["files"]}
    return r["output"], files


def one(heading="A", body="正文", **kw):
    return {"title": "T", "sections": [{"heading": heading, "body": body}], **kw}


def png(w, h, ihdr_only=False):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    if ihdr_only:
        return out
    return out + chunk(b"IDAT", zlib.compress((b"\x00" + b"\xff" * (3 * w)) * h)) + chunk(b"IEND", b"")


def b64(b):
    import base64
    return base64.b64encode(b).decode()


# ---- A. 不再崩溃 ----
@pytest.mark.parametrize("line", [
    '{"tool":["x"],"payload":{}}',
    '{"tool":{"a":1},"payload":{}}',
    '{"tool":"doc.check","payload":{"doc":{"title":"t","sections":[{"heading":"a"}]}},"budget":{"timeout_ms":"inf"}}',
    '{"tool":"doc.check","payload":{"doc":{"title":"t","sections":[{"heading":"a"}]}},"budget":{"timeout_ms":' + "9" * 400 + "}}",
    '{"tool":"doc.check","payload":{"doc":{"title":"t","sections":[{"heading":"a"}]}},"budget":[1]}',
])
def test_envelope_never_kills_the_process(line):
    p = subprocess.run([sys.executable, str(ROOT / "doc_tool.py")], input=line, capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.strip(), p.stderr
    assert json.loads(p.stdout)["error"]["code"] == "BAD_INPUT"


def test_bad_workdir_and_ids_are_bad_input(tmp_path):
    assert doc_tool.run({"tool": "doc.build", "payload": {"doc": one()}, "workdir": 123})["error"]["where"] == "workdir"
    r = run("doc.build", {"doc": {"title": "T", "sections": [{"id": ["a"], "heading": "A"}]}}, tmp_path)
    assert r["error"]["code"] == "BAD_INPUT"


@pytest.mark.parametrize("svg", [f'<svg {NS} width="1e400" height="10"/>', f'<svg {NS} viewBox="0 0 inf 10"/>',
                                 f'<svg {NS} viewBox="0 0 100000 1"/>'])
def test_non_finite_or_extreme_svg_sizes_still_export(svg, tmp_path):
    out, files = build(one(body="[[fig:f]]", figures=[{"id": "f", "caption": "c", "source": {"svg": svg}}]), tmp_path)
    docx.Document(io.BytesIO(files["docx"]))


@pytest.mark.parametrize("data", [png(0, 0), png(0, 5), png(5, 5, ihdr_only=True), png(5, 5)[:-10]])
def test_broken_png_rejected(data, tmp_path):
    r = run("doc.build", {"doc": one(figures=[{"id": "f", "caption": "c", "source": {"media_type": "image/png", "base64": b64(data)}}])},
            tmp_path)
    assert r["error"]["code"] == "BAD_INPUT"
    assert list(tmp_path.iterdir()) == []


def test_jpeg_without_jfif_and_png_embed_in_word(tmp_path):
    figs = [{"id": "j", "caption": "jpeg", "source": {"media_type": "image/jpeg", "base64": JPEG_NO_JFIF}},
            {"id": "p", "caption": "png", "source": {"media_type": "image/png", "base64": b64(png(6, 4))}}]
    out, files = build(one(body="[[fig:j]]\n\n[[fig:p]]", figures=figs), tmp_path)
    z = zipfile.ZipFile(io.BytesIO(files["docx"]))
    media = sorted(n for n in z.namelist() if n.startswith("word/media/"))
    assert media == ["word/media/mengos_img1.jpeg", "word/media/mengos_img2.jpeg"]   # 位图一律以 JPEG 嵌入副本入 Word（2.1.0）
    assert len(docx.Document(io.BytesIO(files["docx"])).inline_shapes) == 2


def test_xml_invalid_characters_from_entities(tmp_path):
    out, files = build(one(body="a &#12; b\n\n| x |\n|--|\n| &#xC; |"), tmp_path)
    docx.Document(io.BytesIO(files["docx"]))


def test_long_multibyte_name_rejected_before_writing(tmp_path):
    r = run("doc.export", {"doc": one(), "name": "😀" * 64, "formats": ["md"]}, tmp_path)
    assert r["error"]["where"] == "name"
    assert list(tmp_path.iterdir()) == []


# ---- B. Word 表格线性 ----
def test_large_table_word_export_is_linear(tmp_path):
    rows = [[f"行{i}"] for i in range(20000)]
    d = one(body="[[tab:t]]", tables=[{"id": "t", "caption": "大表", "columns": ["项"], "rows": rows}])
    t0 = time.time()
    r = run("doc.export", {"doc": d, "formats": ["docx"]}, tmp_path)
    assert r["ok"], r
    assert time.time() - t0 < 20


# ---- C. 代码与引用 ----
@pytest.mark.parametrize("body", [
    "para\n\n    see [[sec:b]]",
    "> ~~~\n> [[sec:b]]\n> ~~~",
    "10. x\n\n    ~~~\n    [[sec:b]]\n    ~~~",
    "```\n    ```\n[[sec:b]]\n```",
])
def test_markers_inside_any_code_are_left_alone(body, tmp_path):
    d = {"title": "T", "sections": [{"heading": "A", "body": body}, {"id": "b", "heading": "B", "body": "x"}]}
    out, files = build(d, tmp_path, formats=())
    md = files["md"].decode()
    body = md[md.index('<a id="sec-s1">'):md.index('<a id="sec-b">')]
    assert "[[sec:b]]" in body and "(#sec-b)" not in body


def test_indented_code_placement_not_taken(tmp_path):
    d = one(body="para\n\n    [[fig:f]]", figures=[{"id": "f", "caption": "c", "source": {"svg": f"<svg {NS}/>"}}])
    out, _ = build(d, tmp_path, formats=())
    assert out["stats"]["figures"] == 0


def test_code_span_does_not_cross_blocks(tmp_path):
    d = {"title": "T", "sections": [{"heading": "A", "body": "- a ` b\n- [[sec:b]] c\n- d ` e"}, {"id": "b", "heading": "B", "body": "x"}]}
    out, files = build(d, tmp_path, formats=())
    assert "[第 2 节](#sec-b)" in files["md"].decode()


def test_ref_inside_link_text_is_plain(tmp_path):
    d = {"title": "T", "sections": [{"heading": "A", "body": "[see [[sec:b]]](https://x.example)"}, {"id": "b", "heading": "B", "body": "x"}]}
    out, files = build(d, tmp_path)
    assert "[see 第 2 节](https://x.example)" in files["md"].decode()
    assert 'href="https://x.example"' in files["html"].decode()


def test_reference_links_survive_placement_split(tmp_path):
    d = one(body="See [the spec][spec].\n\n[[fig:f]]\n\n[spec]: https://example.com/spec",
            figures=[{"id": "f", "caption": "c", "source": {"svg": f"<svg {NS} viewBox='0 0 4 3'/>"}}])
    out, files = build(d, tmp_path)
    assert 'href="https://example.com/spec"' in files["html"].decode()
    view = json.loads(files["view"])
    assert 'href="https://example.com/spec"' in view["sections"][0]["html"]


# ---- D. Markdown ----
def _headings(md_text):
    toks = MD.parse(md_text)
    return [(t.tag, toks[i + 1].content) for i, t in enumerate(toks) if t.type == "heading_open"]


def test_unclosed_fence_does_not_swallow_later_sections(tmp_path):
    d = {"title": "T", "sections": [{"heading": "A", "body": "text\n\n```python\nprint(1)"}, {"heading": "B", "body": "x"}]}
    out, files = build(d, tmp_path, formats=())
    assert ("h2", "2 B") in _headings(files["md"].decode())


def test_titles_and_headings_are_escaped(tmp_path):
    d = {"title": "*Note* [x](y) &amp;", "subtitle": "a ** b",
         "sections": [{"heading": "Section #", "body": "x"}], "meta": {"numbering": "none"}}
    out, files = build(d, tmp_path, formats=())
    hs = _headings(files["md"].decode())
    toks = MD.parse(files["md"].decode())
    assert hs[1] == ("h2", "Section \\#")
    first = toks[1].children
    assert [c.type for c in first] == ["text"] and first[0].content == "*Note* [x](y) &amp;"


def test_table_note_cannot_inject_structure(tmp_path):
    d = one(body="[[tab:t]]", tables=[{"id": "t", "caption": "c", "columns": ["a"], "rows": [["1"]],
                                       "note": "see below\n# Injected heading\n- item"}])
    out, files = build(d, tmp_path, formats=())
    md = files["md"].decode()
    assert all(tag != "h1" or text == "T" for tag, text in _headings(md))
    toks = MD.parse(md)
    items = [toks[i + 2].content for i, t in enumerate(toks) if t.type == "list_item_open"]
    assert "item" not in items and "注：see below\\\n\\# Injected heading\\\n\\- item" in md


def test_headings_in_containers_get_valid_levels(tmp_path):
    out, files = build(one(body="###### deep\n\n> # top\n\n- ## in list"), tmp_path)
    view = json.loads(files["view"])
    html = view["sections"][0]["html"]
    import re
    tags = re.findall(r"<h(-?\d+)", html)
    assert tags and all(3 <= int(t) <= 6 for t in tags), tags
    md_heads = _headings(files["md"].decode())
    assert all(tag in ("h1", "h2") or 3 <= int(tag[1]) <= 6 for tag, _ in md_heads)


# ---- E. Word 列表 ----
def test_ordered_list_start_zero_and_paren_delimiter(tmp_path):
    out, files = build(one(body="0. zero\n1. one\n\n3) three"), tmp_path)
    texts = [p.text for p in docx.Document(io.BytesIO(files["docx"])).paragraphs]
    assert "0.\tzero" in texts and "1.\tone" in texts and "3)\tthree" in texts


# ---- F. SVG 绕过 ----
@pytest.mark.parametrize("svg", [
    f'<svg {NS}><a><animate attributeName="href" values="javascript:alert(1)"/><rect width="1" height="1"/></a></svg>',
    f'<svg {NS} xmlns:xlink="http://www.w3.org/1999/xlink"><a><set attributeName="xlink:href" to="javascript:x"/></a></svg>',
    f'<?xml-stylesheet href="https://evil.example/x.css"?><svg {NS}/>',
    f'<svg {NS}><style>a{{}}<g/>@import url(https://x.example/a.css)</style></svg>',
    f'<svg {NS}><style>@\\69mport "https://x.example/a.css";</style></svg>',
    f'<svg {NS}><rect style="fill:u\\72l(https://x.example/p)"/></svg>',
    f'<svg {NS}><rect style="fill:image-set(&quot;https://x.example/p&quot;)"/></svg>',
    f'<svg {NS}><rect fill="url(https://x.example/p)"/></svg>',
    f'<svg {NS}><rect filter="URL(https://x.example/f)"/></svg>',
    f'<svg {NS}><STYLE>@import url(https://x.example/a.css);</STYLE></svg>',
    f'<svg {NS}><style><![CDATA[@import url(https://x.example/a.css);]]></style></svg>',
    f'<svg {NS}><feImage href="https://x.example/i.png"/></svg>',
    f'<svg {NS}><h:script xmlns:h="http://www.w3.org/1999/xhtml">x()</h:script></svg>',
    '<svg width="10" height="10"><rect width="10" height="10"/></svg>',
    f'<?xml version="1.0" encoding="ISO-8859-1"?><svg {NS}/>',
])
def test_svg_bypasses_rejected(svg, tmp_path):
    r = run("doc.build", {"doc": one(figures=[{"id": "f", "caption": "c", "source": {"svg": svg}}])}, tmp_path)
    assert r["ok"] is False and r["error"]["code"] == "BAD_INPUT", svg


def test_inkscape_style_svg_still_accepted(tmp_path):
    svg = (f'<svg {NS} xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
           f'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" viewBox="0 0 10 10">'
           f'<sodipodi:namedview inkscape:zoom="1"/><defs><linearGradient id="g"><stop offset="0"/></linearGradient></defs>'
           f'<rect width="10" height="10" fill="url(#g)" style="stroke:#000"/></svg>')
    assert run("doc.build", {"doc": one(figures=[{"id": "f", "caption": "c", "source": {"svg": svg}}])}, tmp_path)["ok"]


# ---- G. 核对 ----
def check(doc, expect=None):
    r = run("doc.check", {"doc": doc, **({"expect": expect} if expect is not None else {})})
    assert r["ok"], r
    return r["output"]


def test_covered_with_only_should_requirements():
    d = one(requirements=[{"id": "r1", "text": "x", "priority": "should"}])
    c = check(d, "covered")["checks"][-1]
    assert c["verdict"] == "pass" and "建议项" in c["reason"]
    assert check(one(), "covered")["checks"][-1]["verdict"] == "unknown"


def test_placeholders_are_whole_words():
    out = check(one(body="Mastodon and Photodocumentation in Todos Santos"))
    assert next(c for c in out["checks"] if c["kind"] == "placeholder")["verdict"] == "pass"
    out = check(one(body="TODO: fill"))
    assert next(c for c in out["checks"] if c["kind"] == "placeholder")["verdict"] == "fail"


def test_non_finite_bbox_rejected(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "doc_tool.py"), "doc.check"], capture_output=True, text=True,
                       input='{"title":"t","sections":[{"heading":"a"}],"requirements":[{"id":"r","text":"x","anchor":{"bbox":[0,0,NaN,1]}}]}')
    assert '{"doc"' not in p.stdout
    r = run("doc.check", {"doc": {"title": "t", "sections": [{"heading": "a"}],
                                  "requirements": [{"id": "r", "text": "x", "anchor": {"bbox": [0, 0, float("nan"), 1]}}]}})
    assert r["error"]["code"] == "BAD_INPUT"


# ---- 存疑项里采纳的 ----
@pytest.mark.parametrize("heading,flag", [("24 小时运维保障", False), ("1.5 倍冗余设计", False), ("5 Steps to Success", False),
                                          ("10 Lessons Learned", False), ("3 背景", True), ("1.背景", True), ("三、背景", True)])
def test_hand_numbering_detection(heading, flag):
    d = {"title": "T", "sections": [{"heading": "x", "body": "a"}, {"heading": "y", "body": "a"},
                                    {"heading": heading, "body": "a"}]}
    c = next(c for c in check(d)["checks"] if c["kind"] == "numbering")
    assert (c["verdict"] == "fail") == flag


def test_expect_quoting_and_strict_arguments():
    d = {"title": "T", "sections": [{"heading": "a=b", "body": "x"}, {"heading": "Intro", "body": "y"},
                                    {"heading": "Intro", "level": 2, "body": "z"}]}
    out = check(d, '﻿has "a=b"\nhas Intro level=2')
    assert [c["verdict"] for c in out["checks"][-2:]] == ["pass", "pass"]
    assert "同名" in check(d, "length Intro min=1")["checks"][-1]["note"]
    for bad in ("has Intro level=0", "pages max=3 extra", "length total min=1 min=2", 'contains total " "'):
        r = run("doc.check", {"doc": d, "expect": bad})
        assert r["error"]["code"] == "BAD_INPUT" and r["error"]["line"] == 1, bad
