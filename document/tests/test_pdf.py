"""PDF 导出（2.2.0）：确定性、结构、字体嵌入、目录页码、书签、内部链接、降级提醒。

结构检查用纯 Python 的 pypdf（只在 dev 依赖里）读回生成的 PDF。
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pypdf import PdfReader

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = sorted((ROOT / "samples").glob("*.json"))
sys.path.insert(0, str(ROOT / "tools"))
import synth  # noqa: E402


def export_pdf(doc, tmp_path, name="x"):
    r = doc_tool.run({"tool": "doc.export", "payload": {"doc": doc, "formats": ["pdf"], "name": name}, "workdir": str(tmp_path)})
    assert r["ok"], r
    f = r["output"]["files"][0]
    assert f["format"] == "pdf" and f["role"] == "document.pdf" and f["media_type"] == "application/pdf"
    data = (Path(tmp_path) / f["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == f["sha256"] and len(data) == f["bytes"]
    return data, r["output"]


def sub(tmp_path, name):
    p = Path(tmp_path) / name
    p.mkdir()
    return str(p)


def expected_outline(d):
    """期望的书签：直接取装配结果里各节带编号的标题与层级（0 起），有要求对照表时末尾加附录。"""
    a = doc_tool._assembled({"doc": d})
    out = [(o.sec.level - 1, o.display) for o in a.sections]
    if a.doc.meta["trace_table"] and a.doc.requirements:
        out.append((0, a.words["trace"]))
    return out


def load(name):
    return json.loads((ROOT / "samples" / f"{name}.json").read_text(encoding="utf-8"))


def outline_items(reader):
    out = []

    def walk(nodes, depth):
        for n in nodes:
            if isinstance(n, list):
                walk(n, depth + 1)
            else:
                out.append((depth, n.title, reader.get_destination_page_number(n) + 1))
    walk(reader.outline, 0)
    return out


def link_count(reader):
    n = 0
    for p in reader.pages:
        for a in p.get("/Annots") or []:
            a = a.get_object()
            if a.get("/Subtype") == "/Link" and ("/Dest" in a or "/A" in a):
                n += 1
    return n


def font_names(reader):
    names = {}
    for p in reader.pages:
        for f in (p["/Resources"].get("/Font") or {}).values():
            f = f.get_object()
            fd = f["/DescendantFonts"][0].get_object()["/FontDescriptor"].get_object() if "/DescendantFonts" in f else f.get("/FontDescriptor")
            names[str(f["/BaseFont"])] = fd is not None and any(k.startswith("/FontFile") for k in fd)
    return names


# ---------------------------------------------------------------- 每份样例都能出 PDF，双跑逐字节相同
@pytest.mark.parametrize("sample", SAMPLES, ids=[s.stem for s in SAMPLES])
def test_every_sample_exports_and_is_byte_deterministic(sample, tmp_path):
    d = json.loads(sample.read_text(encoding="utf-8"))
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    p1, _ = export_pdf(d, a)
    p2, _ = export_pdf(d, b)
    assert p1.startswith(b"%PDF-") and p1 == p2
    r = PdfReader(io.BytesIO(p1))
    assert len(r.pages) >= 1
    assert all(font_names(r).values()), font_names(r)           # 所有字体都是嵌入的子集，没有未嵌入的 Helvetica
    assert all(re.match(r"/[A-Z]{6}\+", n) for n in font_names(r)), font_names(r)


def test_deterministic_across_processes_and_hash_seeds(tmp_path):
    """不同进程、不同哈希种子、不同工作目录，字节一致；PDF 里不含当前时间。"""
    code = ("import sys, json, doc_tool, hashlib, tempfile\n"
            "d = json.load(open(sys.argv[1], encoding='utf-8'))\n"
            "w = tempfile.mkdtemp()\n"
            "r = doc_tool.run({'tool': 'doc.export', 'payload': {'doc': d, 'formats': ['pdf'], 'name': 'x'}, 'workdir': w})\n"
            "print(r['output']['files'][0]['sha256'])\n")
    sums = set()
    for seed in ("0", "1", "12345"):
        out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); exec(sys.argv.pop(1))" % str(ROOT),
                              code, str(ROOT / "samples" / "bid_tech.json")],
                             capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": seed}, cwd=str(tmp_path))
        assert out.returncode == 0, out.stderr[-500:]
        sums.add(out.stdout.strip())
    assert len(sums) == 1


def test_no_wallclock_in_metadata(tmp_path):
    data, _ = export_pdf(load("reading_corner"), tmp_path)
    md = PdfReader(io.BytesIO(data)).metadata
    assert md["/CreationDate"] == "D:20000101000000+00'00'" and md["/ModDate"] == md["/CreationDate"]
    assert md["/Title"] == load("reading_corner")["title"]


# ---------------------------------------------------------------- 结构金样（中文、英文各一份）
def test_zh_bid_structure(tmp_path):
    d = load("bid_tech")
    data, out = export_pdf(d, tmp_path)
    r = PdfReader(io.BytesIO(data))
    assert 5 <= len(r.pages) <= 8
    # 书签树：与章节一致，层级对应
    items = outline_items(r)
    assert [(lv, t) for lv, t, _ in items] == expected_outline(d)
    assert items[-1][1] == "附：要求响应对照表"
    # 目录项页码与书签一致且单调不减
    toc_text = r.pages[1].extract_text()
    toc_text = toc_text[toc_text.index("目录"):]                  # 页脚页码在文字流的最前面，目录从“目录”起
    nums = [int(x) for x in re.findall(r"^(\d+)$", toc_text, re.M)]
    pages = [pg for _, _, pg in items]
    assert nums == pages and pages == sorted(pages)
    # 第 1 页是封面：无页码；其后每页有页码
    assert "城东街道智慧社区安防改造项目" in r.pages[0].extract_text()
    for i, p in enumerate(r.pages[1:], start=2):
        assert p.extract_text().strip().split("\n")[0].strip() == str(i), i      # 页脚在页面内容流最前
    # 各节标题带编号出现在正文里；图题、表题文字在
    text = "\n".join(p.extract_text() for p in r.pages[2:])
    for t in ("第一章 项目理解", "第二章 总体设计", "2.1 视频监控子系统", "图 2-1 系统总体架构", "表 2-1 主要设备清单"):
        assert t in text, t
    assert text.index("表 2-1 主要设备清单") < text.index("型号规格")          # 表题在表（表头）上
    assert text.index("图 2-1 系统总体架构") < text.index("架构遵循")          # 图题在图下：题后才是图后的正文
    # 内部链接：目录（含附录）+ 正文里的 [[sec:]]/[[fig:]]/[[tab:]]
    assert link_count(r) >= len(items) + 4
    assert out["warnings"] == []


def test_en_brief_structure(tmp_path):
    d = load("brief_en")
    data, out = export_pdf(d, tmp_path)
    r = PdfReader(io.BytesIO(data))
    assert len(r.pages) == 1
    t = r.pages[0].extract_text()
    for s in ("Pilot Results: Smart Water Meters", "Quarterly brief", "1 Summary", "2 Rollout", "3 Next steps",
              "Table 1. Key indicators", "1,200 meters", "Section 2"):
        assert s in t, s
    assert [x[1] for x in outline_items(r)] == ["1 Summary", "2 Rollout", "3 Next steps"]
    assert link_count(r) == 2                      # 文中“表 1”“第 2 节”两处引用；无目录（toc=false）
    assert t.index("Table 1. Key indicators") < t.index("Average repair time")
    assert out["warnings"] == []


def test_bitmap_sample_pdf_uses_embedded_jpeg_copies(tmp_path):
    data, _ = export_pdf(load("illustrated"), tmp_path)
    r = PdfReader(io.BytesIO(data))
    imgs = [im for p in r.pages for im in p.images]
    assert len(imgs) == 3 and all(im.image.format == "JPEG" for im in imgs)
    text = "\n".join(p.extract_text() for p in r.pages)
    for c in ("图 1 入口布置", "图 2 展板", "图 3 签到台"):
        assert c in text, c


# ---------------------------------------------------------------- 边界
def test_outline_kind_with_empty_sections(tmp_path):
    d = {"kind": "outline", "title": "年度报告提纲", "sections": [
        {"id": "a", "heading": "背景", "level": 1}, {"id": "b", "heading": "现状", "level": 2},
        {"id": "c", "heading": "目标", "level": 1, "body": ""}]}
    data, out = export_pdf(d, tmp_path)
    r = PdfReader(io.BytesIO(data))
    assert [t for _, t, _ in outline_items(r)] == ["1 背景", "1.1 现状", "2 目标"]
    assert out["warnings"] == []                    # 提纲允许空节，不报 empty_section，PDF 也不加提醒


def test_cover_toc_flags(tmp_path):
    d = {"title": "T", "meta": {"cover": True, "toc": False}, "sections": [{"id": "a", "heading": "甲", "body": "正文"}]}
    data, _ = export_pdf(d, tmp_path)
    r = PdfReader(io.BytesIO(data))
    assert len(r.pages) == 2 and "目录" not in r.pages[0].extract_text() + r.pages[1].extract_text()


def test_svg_that_cannot_be_drawn_gets_placeholder_and_warning(tmp_path, monkeypatch):
    import svglib.svglib as sv

    def boom(*a, **k):
        raise ValueError("unsupported")
    monkeypatch.setattr(sv, "svg2rlg", boom)
    d = load("bid_tech")
    data, out = export_pdf(d, tmp_path)
    codes = [w["code"] for w in out["warnings"]]
    assert codes.count("pdf_figure_unsupported") == 2          # bid_tech 有两张 SVG 图
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
    assert text.count("此图无法在 PDF 中绘制") == 2 and "图 2-1 系统总体架构" in text         # 图题仍在
    # 另两种格式不受影响：同一份文档照常出 Word
    r = doc_tool.run({"tool": "doc.export", "payload": {"doc": d, "formats": ["docx"]}, "workdir": sub(tmp_path, "w")})
    assert r["ok"] and r["output"]["warnings"] == []


def test_chars_missing_from_bundled_fonts_are_reported(tmp_path):
    d = {"title": "T", "sections": [{"id": "a", "heading": "甲", "body": "笑脸 😀 与 𠀀。"}]}
    data, out = export_pdf(d, tmp_path)
    w = [x for x in out["warnings"] if x["code"] == "pdf_glyph_missing"]
    assert len(w) == 1 and "😀" in w[0]["message"]


def test_svg_text_uses_bundled_fonts_not_system_fonts(tmp_path, monkeypatch):
    """SVG 里写的字体名一律落到随包字体：不得调用 fc-match 之类的系统字体查找。"""
    import subprocess as sp

    def no_spawn(*a, **k):
        raise AssertionError("PDF 排版不得启动子进程查系统字体")
    monkeypatch.setattr(sp, "Popen", no_spawn)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40" width="100" height="40">'
           '<text x="5" y="25" font-family="Arial, Menlo, sans-serif" font-size="14">中文 Label</text></svg>')
    d = {"title": "T", "sections": [{"id": "a", "heading": "甲", "body": "[[fig:s]]"}],
         "figures": [{"id": "s", "caption": "矢量", "source": {"svg": svg}}]}
    data, out = export_pdf(d, tmp_path)
    r = PdfReader(io.BytesIO(data))
    assert out["warnings"] == [] and all(font_names(r).values())
    assert "中文 Label" in r.pages[0].extract_text()


def test_long_table_and_code_and_lists_paginate(tmp_path):
    rows = "\n".join(f"| 行{i} | {'数据' * 20} | {i} |" for i in range(200))
    body = ("段落 **粗体** *斜体* `code` ~~删除~~ [链接](https://example.com)。\n\n- 一\n  - 二\n    - 三\n\n1. 甲\n2. 乙\n\n> 引用段落\n\n"
            "```\n" + "\n".join(f"  line {i}  中文" for i in range(120)) + "\n```\n\n| 项 | 说明 | 数 |\n|---|---|--:|\n" + rows)
    d = {"title": "长", "sections": [{"id": "a", "heading": "甲", "body": body}]}
    data, out = export_pdf(d, tmp_path)
    r = PdfReader(io.BytesIO(data))
    assert len(r.pages) >= 5
    text = "\n".join(p.extract_text() for p in r.pages)
    assert "line 119" in text and "行199" in text and "引用段落" in text


def test_single_huge_cell_does_not_crash(tmp_path):
    d = {"title": "T", "sections": [{"id": "a", "heading": "甲", "body": "[[tab:t]]"}],
         "tables": [{"id": "t", "caption": "c", "columns": ["窄"], "rows": [["字" * 1990]] * 3 + [["x"]]}]}
    data, _ = export_pdf(d, tmp_path)
    assert len(PdfReader(io.BytesIO(data)).pages) >= 2


def test_export_pdf_via_object_and_formats_vocabulary(tmp_path):
    d = load("reading_corner")
    r = doc_tool.run({"tool": "doc.export", "payload": {"object": {"tool": "doc.build", "args": {"doc": d, "name": "n1"}}, "format": "pdf"},
                      "workdir": str(tmp_path)})
    assert r["ok"] and [f["path"] for f in r["output"]["files"]] == ["n1.pdf"]
    r = doc_tool.run({"tool": "doc.export", "payload": {"doc": d, "formats": ["docx", "pdf", "md"]}, "workdir": sub(tmp_path, "m")})
    assert [f["format"] for f in r["output"]["files"]] == ["docx", "pdf", "md"]
    r = doc_tool.run({"tool": "doc.build", "payload": {"doc": d, "formats": ["pdf"]}, "workdir": sub(tmp_path, "b")})
    assert not r["ok"] and r["error"]["where"] == "formats"           # doc.build 不出 PDF


def test_twenty_2k_pngs_pdf_size_and_time(tmp_path):
    """令文 P6：20 张 2K 图的 PDF 体积与耗时读数。"""
    figs = [{"id": f"p{i:02d}", "caption": f"第{i}张", "source": {"media_type": "image/png", "base64": synth.b64png(2048, 2048, i)}}
            for i in range(1, 21)]
    d = {"title": "图文", "sections": [{"id": "s1", "heading": "节", "body": "\n\n".join(f"[[fig:p{i:02d}]]" for i in range(1, 21))}],
         "figures": figs}
    t0 = time.time()
    data, out = export_pdf(d, tmp_path)
    dt = time.time() - t0
    print(f"\n[读数] 20 张 2048² PNG：doc.export(pdf) {dt:.2f}s，PDF {len(data)} B，{len(PdfReader(io.BytesIO(data)).pages)} 页")
    assert len(data) < 64 * 1024 * 1024 and dt < 30
