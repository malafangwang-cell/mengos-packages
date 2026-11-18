"""2.4.0 数据图 chart（设计-长文内置图表-2026-11-18 §四–§七、§十二 C1 验收 a–f）。

金样 tests/fixtures/charts/*.svg 是页面稿（mengosv2 docs/alignment/arch/页面稿-长文内置图表-2026-11-18/charts/）
原样拷贝；立法者 11-18 裁定画法以页面稿为准，所以包内出图必须与它逐字节相同。
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import chart
import doc_tool
import model

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
SAMPLES = json.loads((FIX / "charts" / "samples.json").read_text(encoding="utf-8"))
KEYS = ["bar", "line", "combo", "pie", "edge_negative", "edge_gap", "edge_stacked", "edge_many"]


def _doc(charts: dict, sections=None) -> dict:
    """每张图一节；图按 charts 的顺序放置。"""
    figs = [{"id": k, "caption": cap, "source": {"chart": c}} for k, (cap, c) in charts.items()]
    secs = sections or [{"id": "s1", "heading": "数据", "body": "\n\n".join(f"见图 [[fig:{k}]]：\n\n[[fig:{k}]]" for k in charts)}]
    return {"title": "图表样例", "sections": secs, "figures": figs}


def _run(tool, payload, wd):
    return doc_tool.run({"tool": tool, "payload": payload, "workdir": str(wd)})


def _sample(k):
    """→ (图题, 图表数据)。"""
    return SAMPLES[k]["caption"], json.loads(json.dumps(SAMPLES[k]["chart"]))


def _draw(cap_and_chart):
    cap, c = cap_and_chart
    return chart.render(json.loads(json.dumps(c)), cap)


# ───────────────────────── a. 页面稿 8 组数据：金样、两次与跨进程逐字节相同 ─────────────────────────
@pytest.mark.parametrize("key", KEYS)
def test_page_draft_goldens_byte_identical(key):
    cap, c = _sample(key)
    svg, warnings, _ = chart.render(c, cap)
    assert svg == (FIX / "charts" / f"{key}.svg").read_text(encoding="utf-8")
    assert warnings == SAMPLES[key]["warnings"]
    assert _draw(_sample(key))[0] == svg       # 同一进程再画一次


def test_cross_process_byte_identical():
    code = ("import json,sys,hashlib,chart;S=json.load(open(sys.argv[1]));"
            "print(json.dumps({k:hashlib.sha256(chart.render(v['chart'],v['caption'])[0].encode()).hexdigest() for k,v in S.items()}))")
    env = {**os.environ, "PYTHONHASHSEED": "random", "PYTHONPATH": str(ROOT)}
    outs = [subprocess.run([sys.executable, "-c", code, str(FIX / "charts" / "samples.json")], env=env, cwd=str(ROOT),
                           capture_output=True, text=True, check=True).stdout for _ in range(2)]
    assert outs[0] == outs[1]
    want = {k: hashlib.sha256((FIX / "charts" / f"{k}.svg").read_bytes()).hexdigest() for k in KEYS}
    assert json.loads(outs[0]) == want


def test_chart_svg_passes_the_static_svg_whitelist():
    for k in KEYS:
        svg, _, _ = _draw(_sample(k))
        assert model._check_svg(svg.encode(), k) is not None


def test_stored_chart_data_redraws_the_same_chart():
    """规范模型里存的是数据，不是画好的图；再交一次得到同一张图，整数仍是整数。"""
    for k in KEYS:
        cap, c = _sample(k)
        svg, _, stored = chart.render(c, cap)
        assert chart.render(json.loads(json.dumps(stored)), cap)[0] == svg
        assert chart.render(json.loads(json.dumps(stored)), cap)[2] == stored
    _, _, stored = _draw(_sample("line"))
    assert stored["series"][0]["values"][0] == 41 and isinstance(stored["series"][0]["values"][0], int)


def test_doc_json_stores_chart_data_and_export_from_it_is_identical(tmp_path):
    cap, c = _sample("combo")
    d = _doc({"inv": (cap, c)})
    (tmp_path / "a").mkdir()
    r = _run("doc.build", {"doc": d, "formats": ["html"]}, tmp_path / "a")
    assert r["ok"], r
    model_file = next(f for f in r["output"]["files"] if f["role"] == "document.model")
    stored = json.loads((tmp_path / "a" / model_file["path"]).read_text(encoding="utf-8"))
    assert set(stored["figures"][0]["source"]) == {"chart"} and "<svg" not in json.dumps(stored)
    (tmp_path / "b").mkdir()
    r2 = _run("doc.build", {"doc": stored, "formats": ["html"]}, tmp_path / "b")
    assert r2["ok"], r2
    assert {f["path"]: f["sha256"] for f in r["output"]["files"]} == {f["path"]: f["sha256"] for f in r2["output"]["files"]}


# ───────────────────────── b. §六 每一行：退回原话、且不写任何文件 ─────────────────────────
YEARS = ["2021", "2022", "2023", "2024", "2027"]
REJECT = [
    ("年份跳号（实例①）",
     {"type": "combo", "categories": YEARS,
      "series": [{"name": "投资额", "as": "bar", "unit": "亿元", "values": [12.4, 15.1, 18.6, 21.3, 31.0]},
                 {"name": "同比增速", "as": "line", "unit": "%", "values": [None, 21.8, 23.2, 14.5, 11.1]}]},
     "横轴按年排，2024 之后直接是 2027，中间缺 2 个年",
     "把缺的年补进 categories；确实没有数据的，值写 null，图上会留空并标出"),
    ("季度跳号",
     {"type": "bar", "categories": ["2024Q1", "2024Q2", "2024Q4"], "series": [{"name": "x", "values": [1, 2, 3]}]},
     "横轴按季度排，2024Q2 之后直接是 2024Q4，中间缺 1 个季度", "把缺的季度补进 categories；确实没有数据的，值写 null，图上会留空并标出"),
    ("数的个数与类别对不上",
     {"type": "bar", "unit": "亿元", "categories": ["2022", "2023", "2024"], "series": [{"name": "营业收入", "values": [5.6, 6.9]}]},
     "“营业收入”有 2 个数，类别有 3 个（2022…2024）", "每组数据的个数要与 categories 相同；某一项没有数据写 null"),
    ("数值里带单位",
     {"type": "bar", "categories": ["2022", "2023"], "series": [{"name": "营业收入", "values": ["5.6亿", "6.9亿"]}]},
     "“营业收入”的第 1 个值（2022）不是数：'5.6亿'", "只写数字，不带单位、逗号和百分号；单位写在 unit"),
    ("数值里带逗号",
     {"type": "bar", "categories": ["2022", "2023"], "series": [{"name": "营业收入", "values": ["1,200", 1300]}]},
     "“营业收入”的第 1 个值（2022）不是数：'1,200'", "只写数字，不带单位、逗号和百分号；单位写在 unit"),
    ("饼图单位是 % 而合计不是 100",
     {"type": "pie", "unit": "%", "categories": ["设备购置费", "建筑工程费", "安装工程费", "其他"],
      "series": [{"name": "占比", "values": [45, 22.5, 12, 8]}]},
     "各项占比合计 87.5%，不是 100%", "核对各项数字；如果只列了一部分，把其余的补成一项“其他”"),
    ("饼图有负数",
     {"type": "pie", "unit": "万元", "categories": ["主营业务", "投资收益", "资产减值"],
      "series": [{"name": "利润构成", "values": [820, 140, -210]}]},
     "饼图不能有负数（资产减值）", "有正有负的构成用柱状图"),
    ("饼图合计为 0",
     {"type": "pie", "categories": ["甲", "乙"], "series": [{"name": "x", "values": [0, 0]}]},
     "饼图各项合计为 0，画不出占比", None),
    ("饼图不足两项",
     {"type": "pie", "categories": ["甲"], "series": [{"name": "x", "values": [5]}]},
     "饼图至少两项", None),
    ("组合图只有柱",
     {"type": "combo", "categories": ["A", "B"], "series": [{"name": "x", "as": "bar", "values": [1, 2]}]},
     "组合图要同时有柱和折线；只有一种时用 bar 或 line", None),
    ("组合图单位超过两种",
     {"type": "combo", "categories": ["A", "B"],
      "series": [{"name": "x", "as": "bar", "unit": "亿元", "values": [1, 2]},
                 {"name": "y", "as": "bar", "unit": "万元", "values": [1, 2]},
                 {"name": "z", "as": "line", "unit": "%", "values": [1, 2]}]},
     "组合图里所有柱用同一个单位，所有折线用同一个单位", "单位超过两种时拆成两张图"),
    ("写了颜色",
     {"type": "bar", "categories": ["A", "B"], "colors": ["#ff0000"], "series": [{"name": "x", "values": [1, 2]}]},
     "doc.figures[0].source.chart 有不认识的字段：colors（可用：type, categories, series, unit, forecast_from, decimals, stacked, note）",
     "颜色、字号、坐标范围由工具统一决定，不用写"),
]


@pytest.mark.parametrize("label,c,message,hint", REJECT, ids=[r[0] for r in REJECT])
@pytest.mark.parametrize("tool", ["doc.build", "doc.export"])
def test_inconsistent_data_is_rejected_with_the_designed_words_and_writes_nothing(tmp_path, tool, label, c, message, hint):
    payload = {"doc": _doc({"c1": ("图", c)}), "formats": ["docx", "html"] if tool == "doc.build" else ["pdf", "md", "json"]}
    r = _run(tool, payload, tmp_path)
    assert r["ok"] is False and r["error"]["code"] == "BAD_INPUT", r
    assert r["error"]["message"] == message
    assert r["error"].get("hint") == hint
    assert r["error"]["where"].startswith("doc.figures[0].source.chart")
    assert list(tmp_path.iterdir()) == []


def test_reject_messages_match_the_page_draft_errors_file():
    """页面稿 errors.json 记的是原型的实际输出；包内的原话与它一致（where 换成真实位置）。"""
    errs = json.loads((FIX / "charts" / "errors.json").read_text(encoding="utf-8"))
    for label, e in errs.items():
        with pytest.raises(model.BadInput) as ei:
            chart.render(e["chart"], label)
        assert str(ei.value) == e["error"]["message"]
        assert ei.value.hint == e["error"].get("hint")


def test_schema_rejects_style_fields_and_unit_strings():
    import jsonschema
    reg = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    for u in reg["units"]:
        s = u["signature"]["input_schema"]
        V = jsonschema.Draft202012Validator(s)
        ok = {"doc": {"title": "T", "sections": [{"id": "a", "heading": "A", "body": "[[fig:c]]"}],
                      "figures": [{"id": "c", "caption": "c", "source": {"chart": SAMPLES["combo"]["chart"]}}]}}
        assert V.is_valid(ok), u["tool_id"]
        bad = json.loads(json.dumps(ok))
        bad["doc"]["figures"][0]["source"]["chart"]["colors"] = ["#f00"]
        assert not V.is_valid(bad)
        bad = json.loads(json.dumps(ok))
        bad["doc"]["figures"][0]["source"]["chart"]["series"][0]["values"][0] = "12.4亿"
        assert not V.is_valid(bad)
        assert "x-mengos-data" not in json.dumps(s)          # 裁定 5：图表数据本期不查证件


# ───────────────────────── 提醒与边界 ─────────────────────────
def test_gap_and_pie_merge_warnings_reach_the_tool_result(tmp_path):
    d = _doc({"gap": _sample("edge_gap"), "pie": _sample("pie")})
    r = _run("doc.build", {"doc": d, "formats": ["html"]}, tmp_path)
    assert r["ok"], r
    codes = {(w["code"], w["where"]) for w in r["output"]["warnings"]}
    assert ("chart_gap", "doc.figures[0].source.chart") in codes
    assert ("chart_pie_merged", "doc.figures[1].source.chart") in codes


def test_limits():
    with pytest.raises(model.BadInput, match="最多 24 个类别"):
        chart.render({"type": "bar", "categories": [f"类{i}" for i in range(25)], "series": [{"name": "x", "values": [1] * 25}]}, "t")
    with pytest.raises(model.BadInput, match="最多 6 组"):
        chart.render({"type": "line", "categories": ["a", "b"],
                      "series": [{"name": f"s{i}", "values": [1, 2]} for i in range(7)]}, "t")
    with pytest.raises(model.BadInput, match="饼图最多 30 项"):
        chart.render({"type": "pie", "categories": [f"类{i}" for i in range(31)], "series": [{"name": "x", "values": [1] * 31}]}, "t")
    with pytest.raises(model.BadInput, match="forecast_from 要写 categories 里的一项"):
        chart.render({"type": "line", "categories": ["2020", "2021"], "forecast_from": "2030",
                      "series": [{"name": "x", "values": [1, 2]}]}, "t")


# ───────────────────────── c、d. 四种图进一份样例：各格式都能出；PDF 不报画不了；Word 有矢量与真位图 ─────────────────────────
FOUR = {"bar": _sample("bar"), "line": _sample("line"), "combo": _sample("combo"), "pie": _sample("pie")}


def test_four_charts_export_to_every_format_and_pdf_draws_them(tmp_path):
    d = _doc(FOUR)
    r = _run("doc.export", {"doc": d, "formats": ["docx", "pdf", "html", "md", "json"]}, tmp_path)
    assert r["ok"], r
    files = {f["path"]: f for f in r["output"]["files"]}
    assert not [w for w in r["output"]["warnings"] if w["code"] == "pdf_figure_unsupported"]
    md = next(p for p, f in files.items() if f["format"] == "md")
    for k in FOUR:                                       # Markdown 另附 .svg，与手写 SVG 同路
        svg_name = md.removesuffix(".md") + f".f-{k}.svg"
        assert svg_name in files
        assert (tmp_path / svg_name).read_text(encoding="utf-8") == _draw(FOUR[k])[0]
    html = (tmp_path / next(p for p, f in files.items() if f["format"] == "html")).read_text(encoding="utf-8")
    assert html.count('<figure class="fig"') == 4 and "data:image/svg+xml;base64," in html
    from pypdf import PdfReader
    pdf = PdfReader(str(tmp_path / next(p for p, f in files.items() if f["format"] == "pdf")))
    text = "".join(p.extract_text() for p in pdf.pages)
    for word in ("营业收入", "一期厂区", "同比增速（右轴）", "设备购置费", "预测"):
        assert word in text, word                       # 图里的字在 PDF 里是矢量文字


def _docx_media(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist() if n.startswith("word/media/")}


def test_word_has_vector_part_and_a_real_raster_fallback(tmp_path):
    d = _doc(FOUR)
    r = _run("doc.build", {"doc": d, "formats": ["docx"]}, tmp_path)
    assert r["ok"], r
    docx = tmp_path / next(f["path"] for f in r["output"]["files"] if f["format"] == "docx")
    media = _docx_media(docx)
    svgs = sorted(n for n in media if n.endswith(".svg"))
    pngs = sorted(n for n in media if n.endswith(".png"))
    assert len(svgs) == 4 and len(pngs) == 4
    want = {_draw(FOUR[k])[0].encode() for k in FOUR}
    assert {media[n] for n in svgs} == want
    for n in pngs:
        im = Image.open(io.BytesIO(media[n])).convert("RGB")
        assert im.width == 1440
        colors = {c for _, c in im.getcolors(1 << 20)}
        assert (0xf2, 0xf2, 0xf2) not in colors or len(colors) > 50     # 不是灰框
        assert len(colors) > 50
        assert any(abs(r - 0x2a) < 12 and abs(g - 0x78) < 12 and abs(b - 0xd6) < 12 for r, g, b in colors)   # 第一色位蓝
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode()
    assert xml.count("svgBlip") == 4


def test_raster_is_deterministic():
    svg = _draw(FOUR["combo"])[0]
    assert chart.raster(svg) == chart.raster(svg)


# ───────────────────────── 编号、引用、块清单沿用现有图 ─────────────────────────
def test_chart_numbering_cross_refs_and_blocks(tmp_path):
    figs = {"inv": _sample("combo"), "mix": _sample("pie")}
    d = {"title": "可研", "meta": {"figure_numbering": "chapter"},
         "sections": [{"id": "c1", "heading": "投资", "body": "分年度投资见 [[fig:inv]]，构成见 [[fig:mix]]。\n\n[[fig:inv]]\n\n[[fig:mix]]"}],
         "figures": [{"id": k, "caption": cap, "source": {"chart": c}} for k, (cap, c) in figs.items()]}
    d["figures"].append({"id": "arch", "caption": "架构", "source": {"svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'}})
    d["sections"].append({"id": "c2", "heading": "架构", "body": "[[fig:arch]]"})
    r = _run("doc.build", {"doc": d, "formats": ["docx", "html"]}, tmp_path)
    assert r["ok"], r
    blocks = [b for b in r["output"]["blocks"] if b["kind"] == "figure"]
    assert [(b["figure"], b["source"]) for b in blocks] == [("inv", "chart"), ("mix", "chart"), ("arch", "svg")]
    html = (tmp_path / next(f["path"] for f in r["output"]["files"] if f["format"] == "html")).read_text(encoding="utf-8")
    assert "图 1-1" in html and "图 1-2" in html and 'href="#fig-inv"' in html
    with zipfile.ZipFile(tmp_path / next(f["path"] for f in r["output"]["files"] if f["format"] == "docx")) as z:
        xml = z.read("word/document.xml").decode()
    assert 'w:name="fig_inv"' in xml and 'w:name="fig_mix"' in xml


def test_image_figure_blocks_carry_source_image(tmp_path):
    d = json.loads((ROOT / "samples" / "illustrated.json").read_text(encoding="utf-8"))
    r = _run("doc.build", {"doc": d, "formats": ["html"]}, tmp_path)
    assert r["ok"], r
    assert {b["source"] for b in r["output"]["blocks"] if b["kind"] == "figure"} == {"image"}


# ───────────────────────── e. 旧文档（只有 svg、位图）产出逐字节不变 ─────────────────────────
LEGACY = json.loads((FIX / "legacy_2_3_1_outputs.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(LEGACY))
def test_legacy_documents_unchanged_from_2_3_1(tmp_path, name):
    """tests/fixtures/legacy_2_3_1_outputs.json 由 2.3.1 的代码对 samples/ 跑出（文件 sha256、提醒、块清单）。
    2.4.0 只给图块多一个 source 字段，其余逐字节相同。"""
    doc = json.loads((ROOT / "samples" / name).read_text(encoding="utf-8"))
    want = LEGACY[name]
    (tmp_path / "b").mkdir()
    (tmp_path / "e").mkdir()
    r = _run("doc.build", {"doc": doc, "formats": ["docx", "html"]}, tmp_path / "b")
    assert r["ok"], r
    assert {f["path"]: f["sha256"] for f in r["output"]["files"]} == want["build"]
    assert r["output"]["warnings"] == want["warnings"]
    assert [{k: v for k, v in b.items() if k != "source"} for b in r["output"]["blocks"]] == want["blocks"]
    r = _run("doc.export", {"doc": doc, "formats": ["pdf", "md", "json"]}, tmp_path / "e")
    assert r["ok"], r
    assert {f["path"]: f["sha256"] for f in r["output"]["files"]} == want["export"]
    assert r["output"]["warnings"] == want["export_warnings"]
