"""金样运行入口（TL-12 ③，WP-W6 §2 certification_material.golden_runner）。

certify 在安装区用包环境的解释器运行本文件：
  python tools/run_golden.py [--tool <tool_id>]
本文件不导入包内模块：每条金样都按与引擎相同的进程入口与信封调用工具
（stdin 一行 JSON：{"tool", "payload", "budget", "workdir"}，stdout 一行 JSON），测的是装好的工具。
标准输出写按工具分列的汇总：{"tools": {"<tool_id>": {"total": n, "passed": n, "failed": [{"id", "reason"}]}}}；
全过时退出码 0，否则 1。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
ENTRY = ROOT / json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))["runtime"]["process"]["entry"]


def call(tool, payload, workdir):
    env = {"tool": tool, "payload": payload, "budget": {"timeout_ms": 120000}}
    if workdir:
        env["workdir"] = workdir
    p = subprocess.run([sys.executable, str(ENTRY)], input=json.dumps(env).encode("utf-8"),
                       capture_output=True, timeout=180, cwd=str(ROOT))
    if p.returncode != 0:
        raise AssertionError(f"进程退出码 {p.returncode}：{p.stderr.decode('utf-8', 'replace')[-300:]}")
    return json.loads(p.stdout.decode("utf-8"))


def main(check):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool")
    a = ap.parse_args()
    tools = {}
    for case in CASES:
        if a.tool and case["tool"] != a.tool:
            continue
        t = tools.setdefault(case["tool"], {"total": 0, "passed": 0, "failed": []})
        t["total"] += 1
        with tempfile.TemporaryDirectory() as wd:
            try:
                check(case, wd)
                t["passed"] += 1
            except Exception as e:  # 单条失败不影响其余
                t["failed"].append({"id": case["id"], "reason": (str(e) or type(e).__name__)[:400]})
    print(json.dumps({"tools": tools}, ensure_ascii=False))
    return 0 if tools and all(not t["failed"] for t in tools.values()) else 1


def get(obj, path):
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


def check(case, wd):
    r = call(case["tool"], case["payload"], wd)
    exp = dict(case["expect"])
    if any(k.startswith("error.") for k in exp):
        assert not r["ok"], "期望失败，实际成功"
        for k, v in exp.items():
            assert get(r, k) == v, f"{k}={get(r, k)}，期望 {v}"
        return
    assert r["ok"], f"调用失败：{json.dumps(r.get('error'), ensure_ascii=False)[:200]}"
    out = r["output"]
    has, lacks = exp.pop("md_contains", []), exp.pop("md_lacks", [])
    if has or lacks:
        md = next(f for f in out["files"] if f["format"] == "md")
        text = (Path(wd) / md["path"]).read_text(encoding="utf-8")
        for s in has:
            assert s in text, f"Markdown 缺少：{s}"
        for s in lacks:
            assert s not in text, f"Markdown 不应含：{s}"
    structure_checks(out, wd, exp)
    for k, v in exp.items():
        assert get(out, k) == v, f"{k}={get(out, k)}，期望 {v}"


if __name__ == "__main__":
    sys.exit(main(check))
