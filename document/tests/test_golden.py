"""金样（认证 ③）：期望值手写，逐条核对。"""
import json
import re
from pathlib import Path

import pytest

import doc_tool

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))


def _get(obj, path):
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        obj = obj[int(part[1:-1])] if part.startswith("[") else obj[part]
    return obj


def structure_checks(out, wd, exp):
    """2.1.0 起金样可比文件结构：docx_drawings（Word 图形数）、docx_captions（图题样式段落的文字）、
    html_figures（网页 <figure> 数）、md_figure_files（交付的位图附图文件数）。取走 exp 里这几个键。"""
    import re as _re
    import zipfile as _zf
    root = Path(wd)
    byfmt = lambda f: next(x for x in out["files"] if x["format"] == f)
    if "docx_drawings" in exp or "docx_captions" in exp:
        with _zf.ZipFile(root / byfmt("docx")["path"]) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        if "docx_drawings" in exp:
            n = len(_re.findall(r"<w:drawing>", xml))
            assert n == exp.pop("docx_drawings"), f"Word 图形数 {n}"
        if "docx_captions" in exp:
            caps = []
            for p in _re.findall(r"<w:p[ >].*?</w:p>", xml, _re.S):
                if 'w:pStyle w:val="Caption"' in p:
                    caps.append("".join(_re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))
            want = exp.pop("docx_captions")
            assert caps == want, f"Word 图题 {caps}，期望 {want}"
    if "html_figures" in exp:
        n = len(_re.findall(r"<figure[ >]", (root / byfmt("html")["path"]).read_text(encoding="utf-8")))
        assert n == exp.pop("html_figures"), f"网页 <figure> 数 {n}"
    if "md_figure_files" in exp:
        n = sum(1 for x in out["files"] if x["format"] == "figure")
        assert n == exp.pop("md_figure_files"), f"附图文件数 {n}"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden(case, tmp_path):
    r = doc_tool.run({"tool": case["tool"], "payload": case["payload"], "workdir": str(tmp_path)})
    exp = dict(case["expect"])
    if any(k.startswith("error.") for k in exp):
        assert not r["ok"], r
        for k, v in exp.items():
            assert _get(r, k) == v, (k, r["error"])
        return
    assert r["ok"], r
    out = r["output"]
    md_has, md_not = exp.pop("md_contains", []), exp.pop("md_lacks", [])
    if md_has or md_not:
        md = next(f for f in out["files"] if f["format"] == "md")
        text = (tmp_path / md["path"]).read_text(encoding="utf-8")
        for s in md_has:
            assert s in text, (s, text)
        for s in md_not:
            assert s not in text, s
    structure_checks(out, tmp_path, exp)
    for k, v in exp.items():
        assert _get(out, k) == v, (k, _get(out, k), v)
