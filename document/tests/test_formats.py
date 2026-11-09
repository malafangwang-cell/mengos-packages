"""导出格式的结构自检：Word 能打开且结构对；网页 id 唯一；Markdown 链接都有落点；产出台数据齐全。"""
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import docx
import pytest

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
BID = json.loads((ROOT / "samples" / "bid_tech.json").read_text(encoding="utf-8"))
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("bid")
    r = doc_tool.run({"tool": "doc.build", "payload": {"doc": BID, "formats": ["docx", "html"]}, "workdir": str(d)})
    assert r["ok"], r
    files = {f["format"] if f["format"] != "figure" else f["path"]: (d / f["path"]).read_bytes() for f in r["output"]["files"]}
    return r["output"], files


def test_files_match_manifest(built, tmp_path):
    out, _ = built
    import hashlib
    for f in out["files"]:
        assert f["bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", f["sha256"])
        assert "/" not in f["path"] and not f["path"].startswith(".")
    assert len({f["path"] for f in out["files"]}) == len(out["files"])
    assert hashlib.sha256(built[1]["docx"]).hexdigest() == next(f["sha256"] for f in out["files"] if f["format"] == "docx")


def test_docx_structure(built):
    out, files = built
    d = docx.Document(io.BytesIO(files["docx"]))
    heads = [(p.style.name, p.text) for p in d.paragraphs if p.style.name.startswith("Heading")]
    assert heads[0] == ("Heading 1", "第一章　项目理解")
    assert ("Heading 2", "2.1 视频监控子系统") in heads
    assert heads[-1] == ("Heading 1", "附：要求响应对照表")
    body = d.element.body
    marks = {e.get(W + "name") for e in body.iter(W + "bookmarkStart")}
    for o in out["outline"]:
        assert "sec_" + o["id"] in marks
    assert {"fig_arch", "fig_gantt", "tab_devices", "tab_staff", "sec__trace"} <= marks
    anchors = {e.get(W + "anchor") for e in body.iter(W + "hyperlink") if e.get(W + "anchor")}
    assert anchors <= marks, anchors - marks                     # 每个内部链接都有落点
    instr = " ".join(e.text for e in body.iter(W + "instrText"))
    assert "TOC" in instr
    assert len(d.tables) == 3                                    # 两张表 + 对照表
    assert d.tables[0].rows[0].cells[0].text == "设备"
    assert d.core_properties.title == BID["title"]


def test_docx_package_is_normalized(built):
    z = zipfile.ZipFile(io.BytesIO(built[1]["docx"]))
    assert all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in z.infolist())
    names = z.namelist()
    assert "docProps/thumbnail.jpeg" not in names
    svgs = [n for n in names if n.endswith(".svg")]
    assert len(svgs) == 2
    ct = z.read("[Content_Types].xml").decode()
    assert all(f'PartName="/{n}" ContentType="image/svg+xml"' in ct for n in svgs)
    doc = z.read("word/document.xml").decode()
    assert doc.count("asvg:svgBlip") == 2


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.hrefs, self.tags = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "a" and a.get("href", "").startswith("#"):
            self.hrefs.append(a["href"][1:])


def test_html_ids_unique_and_links_land(built):
    p = _Ids()
    p.feed(built[1]["html"].decode("utf-8"))
    assert len(p.ids) == len(set(p.ids))
    assert set(p.hrefs) <= set(p.ids), set(p.hrefs) - set(p.ids)
    assert "script" not in p.tags


def test_markdown_links_land(built):
    md = built[1]["md"].decode("utf-8")
    targets = set(re.findall(r'<a id="([^"]+)"></a>', md))
    links = set(re.findall(r"\]\(#([^)]+)\)", md))
    assert links and links <= targets, links - targets
    for fn in re.findall(r"!\[[^\]]*\]\(([^)#]+)\)", md):
        assert fn in built[1], fn                                 # 图片文件随 Markdown 一并交付


def test_view_has_everything_the_desk_needs(built):
    v = json.loads(built[1]["view"])
    assert v["schema"] == "mengos.document.view/1"
    assert [s["id"] for s in v["sections"]] == [t["id"] for t in v["toc"]]
    assert all(s["html"] for s in v["sections"])
    assert {r["id"]: r["covered"] for r in v["requirements"]} == {f"r{i}": True for i in range(1, 7)}
    assert v["requirements"][0]["anchor"] == {"page": 18}
    assert v["appendix"][0]["id"] == "_trace"
    assert v["stats"]["must_covered"] == 5


def test_model_file_is_canonical(built):
    m = json.loads(built[1]["json"])
    assert m["schema"] == "mengos.document/1"
    assert all(set(s) == {"id", "level", "heading", "body", "responds_to"} for s in m["sections"])
    assert m["meta"]["numbering"] == "chapter" and m["meta"]["lang"] == "zh-CN"


def test_only_text_images_tables(tmp_path):
    """1.1.0：图随内容给出；对象库引用不再接受。"""
    d = {"title": "t", "sections": [{"heading": "a"}],
         "figures": [{"id": "f", "caption": "c", "source": {"object": "0" * 64, "media_type": "image/png"}}]}
    r = doc_tool.run({"tool": "doc.build", "payload": {"doc": d}, "workdir": str(tmp_path)})
    assert not r["ok"] and r["error"]["where"] == "doc.figures[0].source"


def test_html_has_no_browser_print_hint_and_keeps_print_css(built):
    """2.2.0：PDF 改由导出直接交付，网页里不再教人“浏览器里打印”；打印样式仍在。"""
    page = built[1]["html"].decode("utf-8")
    assert "print-hint" not in page and "另存为 PDF" not in page
    assert "@media print{body{" in page and "@page{size:A4;margin:25mm 22mm}" in page
