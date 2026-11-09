"""2.1.0 图文能力：位图嵌入副本、上限、边界（含接近 20 张 2K 图）、确定性。

图片全部由 tools/synth.py 程序生成，不入库大文件。
"""
import base64
import hashlib
import io
import json
import re
import struct
import sys
import time
import zipfile
import zlib
from pathlib import Path

import pytest
from PIL import Image

import doc_tool
import model

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import synth  # noqa: E402

MB = 1024 * 1024


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _fig(i, data, mt="image/png", caption=None):
    return {"id": i, "caption": caption or f"图题{i}", "source": {"media_type": mt, "base64": _b64(data)}}


def _doc(figs, body=None, sections=None):
    ids = [f["id"] for f in figs]
    body = body if body is not None else "\n\n".join(f"[[fig:{i}]]" for i in ids)
    return {"title": "图文", "sections": sections or [{"id": "s1", "heading": "节", "body": body}], "figures": figs}


def _run(tool, payload, wd):
    return doc_tool.run({"tool": tool, "payload": payload, "workdir": str(wd)})


def _build(doc, wd, formats=("docx", "html")):
    r = _run("doc.build", {"doc": doc, "formats": list(formats)}, wd)
    assert r["ok"], r
    return r["output"], {f["path"]: (Path(wd) / f["path"]).read_bytes() for f in r["output"]["files"]}


def _with_chunk(png: bytes, size: int) -> bytes:
    """在 IEND 前插一个合法的私有辅助块（Pillow 跳过），把文件撑到指定字节数；CRC 有效。"""
    pad = size - len(png) - 12
    assert pad >= 0
    kind, data = b"zzZz", b"\0" * pad
    chunk = struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return png[:-12] + chunk + png[-12:]


# ---------------------------------------------------------------- D1 嵌入副本
def _embed_size(png_bytes):
    return Image.open(io.BytesIO(model.make_embed(png_bytes))).size


def test_embed_2048_square_becomes_1600():
    e = model.make_embed(synth.png(2048, 2048, 1))
    im = Image.open(io.BytesIO(e))
    assert im.format == "JPEG" and im.size == (1600, 1600)


def test_embed_keeps_small_size_converts_to_jpeg():
    e = model.make_embed(synth.png(800, 600, 2))
    im = Image.open(io.BytesIO(e))
    assert im.format == "JPEG" and im.size == (800, 600)


def test_embed_threshold_edges():
    assert _embed_size(synth.png(1600, 1000, 1)) == (1600, 1000)       # 恰为 1600：不动
    assert _embed_size(synth.png(1601, 1000, 1)) == (1600, 999)        # 超 1px：等比缩，高 1000×1600/1601=999.4 四舍五入为 999
    assert _embed_size(synth.png(1000, 3200, 1)) == (500, 1600)        # 竖图按长边


def test_embed_transparent_png_composited_on_white():
    left_opaque = Image.new("RGBA", (64, 64), (200, 0, 0, 0))              # 整幅全透明，RGB 为红
    left_opaque.paste(Image.new("RGBA", (16, 64), (200, 0, 0, 255)), (0, 0))   # 左侧一条不透明红
    buf = io.BytesIO()
    left_opaque.save(buf, "PNG")
    im = Image.open(io.BytesIO(model.make_embed(buf.getvalue()))).convert("RGB")
    assert all(c >= 250 for c in im.getpixel((50, 32))), im.getpixel((50, 32))      # 透明处：白底，不是红也不是黑
    r, g, b = im.getpixel((4, 32))
    assert r > 150 and g < 80 and b < 80, (r, g, b)                                  # 不透明处：仍是红


def test_embed_strips_exif_and_icc():
    base = Image.new("RGB", (40, 30), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"
    buf = io.BytesIO()
    base.save(buf, "JPEG", exif=exif, icc_profile=b"x" * 200)
    src = buf.getvalue()
    assert b"SecretCam" in src
    e = model.make_embed(src)
    assert b"SecretCam" not in e and b"Exif" not in e and b"ICC_PROFILE" not in e


def test_embed_is_byte_deterministic():
    p = synth.png(2048, 1536, 4)
    assert model.make_embed(p) == model.make_embed(p)


def _png_with_idat(w, h, idat_data):
    def ch(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + ch(b"IDAT", idat_data) + ch(b"IEND", b""))


CORRUPT = b"this is not a zlib stream" * 4


def test_embed_rejects_undecodable():
    """结构完整（块、CRC、尺寸都对）但 IDAT 不是合法的压缩流：嵌入副本这一步拒收，写明位置。"""
    short = _png_with_idat(40, 30, CORRUPT)
    with pytest.raises(model.BadInput) as ei:
        model.make_embed(short, "doc.figures[0].source")
    assert ei.value.where == "doc.figures[0].source" and "无法解码" in str(ei.value)


def test_undecodable_figure_rejects_whole_build(tmp_path):
    short = _png_with_idat(40, 30, CORRUPT)
    r = _run("doc.build", {"doc": _doc([_fig("bad", short)])}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT" and r["error"]["where"] == "doc.figures[0].source"


def test_word_html_use_embed_original_is_separate_file_model_references_it(tmp_path):
    orig = synth.png(2048, 2048, 5)
    out, files = _build(_doc([_fig("big", orig)]), tmp_path)
    z = zipfile.ZipFile(io.BytesIO(files["图文.docx"]))
    media = [n for n in z.namelist() if n.startswith("word/media/")]
    assert len(media) == 1
    im = Image.open(io.BytesIO(z.read(media[0])))
    assert im.format == "JPEG" and im.size == (1600, 1600)
    html = files["图文.html"].decode("utf-8")
    m = re.search(r'src="data:image/jpeg;base64,([A-Za-z0-9+/=]+)"', html)
    assert m and Image.open(io.BytesIO(base64.b64decode(m.group(1)))).size == (1600, 1600)
    assert "data:image/png" not in html
    # 原图：单独成文件 figures/<id>.<ext>，role document.figure_original，原字节不改
    originals = [f for f in out["files"] if f["role"] == "document.figure_original"]
    assert [f["path"] for f in originals] == ["figures/big.png"] and files["figures/big.png"] == orig
    assert originals[0]["sha256"] == hashlib.sha256(orig).hexdigest() and originals[0]["bytes"] == len(orig)
    # Markdown 直接引用这个文件（不另存一份）
    md = files["图文.md"].decode("utf-8")
    assert "](figures/big.png)" in md and not [f for f in out["files"] if f["path"].startswith("图文.f-")]
    # 规范模型：内嵌嵌入副本，按哈希引用原图，不含原图的 base64
    fig = json.loads(files["图文.doc.json"])["figures"][0]
    assert fig["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(fig["source"]["base64"]) == model.make_embed(orig)
    assert fig["source"]["original"] == {"sha256": hashlib.sha256(orig).hexdigest(), "bytes": len(orig),
                                         "media_type": "image/png", "path": "figures/big.png"}
    assert _b64(orig) not in files["图文.doc.json"].decode("utf-8")
    # 产出台数据的节 html：嵌入副本
    view = files["图文.view.json"].decode("utf-8")
    assert "data:image/jpeg;base64" in view and "data:image/png" not in view


def test_originals_are_emitted_whatever_formats_are_chosen(tmp_path):
    out, files = _build(_doc([_fig("a", synth.png(64, 48, 1)), _fig("b", synth.png(64, 48, 2))]), tmp_path, formats=())
    assert sorted(f["path"] for f in out["files"] if f["role"] == "document.figure_original") == ["figures/a.png", "figures/b.png"]


def test_export_includes_originals_only_for_md_and_json(tmp_path):
    d = _doc([_fig("a", synth.png(64, 48, 1))])
    for i, (fmts, want) in enumerate(((["docx"], False), (["pdf"], False), (["html"], False), (["md"], True), (["json"], True))):
        wd = tmp_path / f"e{i}"
        wd.mkdir()
        r = _run("doc.export", {"doc": d, "formats": fmts}, wd)
        assert r["ok"], r
        has = any(f["role"] == "document.figure_original" for f in r["output"]["files"])
        assert has == want, (fmts, r["output"]["files"])


def test_svg_stays_inline_and_markdown_still_attaches_it(tmp_path):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10"><rect width="10" height="10"/></svg>'
    d = {"title": "T", "sections": [{"id": "s", "heading": "h", "body": "[[fig:v]]"}],
         "figures": [{"id": "v", "caption": "矢量", "source": {"svg": svg}}]}
    out, files = _build(d, tmp_path)
    assert not [f for f in out["files"] if f["role"] == "document.figure_original"]
    assert json.loads(files["T.doc.json"] if "T.doc.json" in files else next(v for k, v in files.items() if k.endswith(".doc.json")))["figures"][0]["source"] == {"svg": svg}
    assert [f["role"] for f in out["files"] if f["format"] == "figure"] == ["document.figure"]


def test_build_twice_is_byte_identical(tmp_path):
    figs = [_fig(f"f{i}", synth.png(1800, 1200, i)) for i in range(3)]
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir(), d2.mkdir()
    o1, f1 = _build(_doc(figs), d1)
    o2, f2 = _build(_doc(figs), d2)
    assert f1 == f2
    assert [x["sha256"] for x in o1["files"]] == [x["sha256"] for x in o2["files"]]


# ---------------------------------------------------------------- D2 上限
def test_single_image_15mb_accepted_17mb_rejected(tmp_path):
    small = synth.png(64, 48, 1)
    ok = _with_chunk(small, 15 * MB)
    out, _ = _build(_doc([_fig("ok", ok)]), tmp_path, formats=("docx",))
    assert out["stats"]["figures"] == 1
    big = _with_chunk(small, 17 * MB)
    r = _run("doc.build", {"doc": _doc([_fig("huge", big)])}, tmp_path / "x")
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT"
    msg = r["error"]["message"]
    assert "huge" in msg and str(len(big)) in msg and str(16 * MB) in msg, msg
    assert r["error"]["where"] == "doc.figures[0].source"


def _norm(blob):
    return model.normalize({"title": "t", "sections": [{"id": "a", "heading": "h", "body": "[[fig:x]]"}],
                            "figures": [_fig("x", blob)]})


def test_exact_limit_boundary():
    small = synth.png(64, 48, 1)
    assert len(_norm(_with_chunk(small, model.LIMITS["image_bytes"])).figures) == 1      # 恰 16 MB：收
    with pytest.raises(model.BadInput) as ei:
        _norm(_with_chunk(small, model.LIMITS["image_bytes"] + 1))                        # 多 1 字节：拒
    assert "x" in str(ei.value) and str(model.LIMITS["image_bytes"] + 1) in str(ei.value)


def test_twenty_2k_pngs_succeed_and_report_timing(tmp_path):
    figs = [_fig(f"p{i:02d}", synth.png(2048, 2048, i), caption=f"第{i}张") for i in range(1, 21)]
    t0 = time.time()
    out, files = _build(_doc(figs), tmp_path)
    dt = time.time() - t0
    assert out["stats"]["figures"] == 20
    assert out["warnings"] == [] or all(w["code"] != "figure_orphan" for w in out["warnings"])
    for f in out["files"]:
        assert f["bytes"] < 48 * MB, f
    assert sum(f["bytes"] for f in out["files"]) < 512 * MB
    z = zipfile.ZipFile(io.BytesIO(files["图文.docx"]))
    media = [n for n in z.namelist() if n.startswith("word/media/")]
    assert len(media) == 20
    assert all(Image.open(io.BytesIO(z.read(n))).size == (1600, 1600) for n in media)
    print(f"\n[读数] 20 张 2048² PNG：doc.build(docx+html) {dt:.2f}s；"
          f"docx {len(files['图文.docx'])} B，html {len(files['图文.html'])} B；"
          f"原图合计 {sum(len(base64.b64decode(f['source']['base64'])) for f in _doc(figs)['figures'])} B")
    assert dt < 30, f"耗时 {dt:.1f}s 超过 30s：需按 README 调 cost.timeout"


def test_twenty_incompressible_2k_pngs_succeed(tmp_path):
    """令文裁决：20 张不可压缩 2K PNG（每张约 12.6 MB，原图合计约 250 MB）整篇成功；.doc.json < 48 MB 且不含原图 base64；
    原图文件 20 个，sha256 与 .doc.json 的 original.sha256 逐一相等。"""
    variants = [synth.png(2048, 2048, 100 + k, noise=True) for k in range(4)]
    figs = [_fig(f"n{i:02d}", variants[i % 4]) for i in range(20)]
    t0 = time.time()
    out, files = _build(_doc(figs), tmp_path)
    dt = time.time() - t0
    by_path = {f["path"]: f for f in out["files"]}
    model_file = next(f for f in out["files"] if f["role"] == "document.model")
    assert model_file["bytes"] < 48 * MB
    originals = [f for f in out["files"] if f["role"] == "document.figure_original"]
    assert len(originals) == 20 and sum(f["bytes"] for f in originals) > 240 * MB
    doc_json = json.loads(files[model_file["path"]])
    for fig in doc_json["figures"]:
        o = fig["source"]["original"]
        assert by_path[o["path"]]["sha256"] == o["sha256"] and by_path[o["path"]]["bytes"] == o["bytes"]
    assert all(f["bytes"] < 48 * MB for f in out["files"] if f["role"] != "document.figure_original")
    assert sum(f["bytes"] for f in out["files"]) < 512 * MB
    print(f"\n[读数] 20 张不可压缩 2K PNG：doc.build {dt:.1f}s；.doc.json {model_file['bytes']} B；"
          f"原图合计 {sum(f['bytes'] for f in originals)} B；产出合计 {sum(f['bytes'] for f in out['files'])} B")
    assert dt < 30, f"耗时 {dt:.1f}s 超过 30s：需调 cost.timeout"


def test_noise_images_exceed_embed_budget_with_clear_error(tmp_path):
    """噪声图几乎不可压缩，嵌入副本仍有约 1.7 MB 一张：30 张合计超 36 MB 时整篇拒收并写明数字。
    （原图合计约 230 MB，低于 320 MB，所以被拒的是嵌入合计。）"""
    variants = [synth.png(1600, 1600, 20 + k, noise=True) for k in range(3)]
    figs = [_fig(f"n{i:02d}", variants[i % 3]) for i in range(30)]
    assert sum(len(variants[i % 3]) for i in range(30)) < model.LIMITS["originals_total_bytes"]
    r = _run("doc.build", {"doc": _doc(figs)}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", r
    msg = r["error"]["message"]
    assert "嵌入" in msg and str(model.LIMITS["images_total_bytes"]) in msg and "图 n" in msg, msg
    assert model.LIMITS["images_total_bytes"] == 36 * MB


def test_originals_total_limit(tmp_path):
    small = synth.png(32, 32, 1)
    blob = _with_chunk(small, 15 * MB)
    figs = [_fig(f"o{i}", blob) for i in range(22)]          # 22×15MB = 330MB > 320MB；每张嵌入副本很小
    r = _run("doc.build", {"doc": _doc(figs)}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT"
    assert "原图合计" in r["error"]["message"] and str(model.LIMITS["originals_total_bytes"]) in r["error"]["message"]


def test_dimension_cap_message_names_figure(tmp_path):
    ihdr = struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0)

    def ch(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    huge = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", ihdr) + ch(b"IDAT", zlib.compress(b"\0")) + ch(b"IEND", b"")
    r = _run("doc.build", {"doc": _doc([_fig("px", huge)])}, tmp_path)
    assert not r["ok"] and "px" in r["error"]["message"] and "像素" in r["error"]["message"]


# ---------------------------------------------------------------- D5 放置
def test_same_section_two_figures_keep_order(tmp_path):
    figs = [_fig("b", synth.png(60, 40, 2), caption="乙"), _fig("a", synth.png(60, 40, 1), caption="甲")]
    out, files = _build(_doc(figs, body="[[fig:a]]\n\n[[fig:b]]"), tmp_path)
    md = files["图文.md"].decode("utf-8")
    assert md.index("*图 1　甲*") < md.index("*图 2　乙*")


def test_unplaced_unreferenced_figure_warns_orphan(tmp_path):
    figs = [_fig("used", synth.png(60, 40, 1)), _fig("lonely", synth.png(60, 40, 2))]
    out, _ = _build(_doc(figs, body="[[fig:used]]"), tmp_path)
    orphans = [w for w in out["warnings"] if w["code"] == "figure_orphan"]
    assert len(orphans) == 1 and "lonely" in orphans[0]["message"]


def test_model_file_over_single_file_limit_is_rejected_at_input(tmp_path):
    """嵌入副本合计未超 36 MB，但加上大段正文后规范模型文件会超过 48 MB：在输入阶段报 BAD_INPUT，不留到写文件时。"""
    variants = [synth.png(1600, 1600, 40 + k, noise=True) for k in range(3)]
    figs = [_fig(f"m{i:02d}", variants[i % 3]) for i in range(17)]          # 嵌入副本约 33 MB，base64 后约 44 MB
    body = "字" * 200_000                                                    # 每节 60 万字节
    secs = [{"id": f"s{i}", "heading": f"节{i}", "body": body if i else "\n\n".join(f"[[fig:m{j:02d}]]" for j in range(17))}
            for i in range(15)]                                              # 约 9 MB 正文
    r = _run("doc.build", {"doc": _doc(figs, sections=secs)}, tmp_path)
    assert not r["ok"] and r["error"]["code"] == "BAD_INPUT", r.get("error")
    assert "文档模型文件" in r["error"]["message"] and str(48 * MB) in r["error"]["message"]
    assert list(tmp_path.iterdir()) == []                                   # 不留半截文件
