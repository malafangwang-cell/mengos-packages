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
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
ENTRY = ROOT / json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))["runtime"]["process"]["entry"]


def call(tool, payload, workdir):
    env = {"tool": tool, "payload": payload, "budget": {"timeout_ms": 120000}}
    if workdir:
        env["workdir"] = workdir
    p = subprocess.run([sys.executable, str(ENTRY)], input=json.dumps(env, ensure_ascii=False).encode("utf-8"),
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
        try:
            check(case)
            t["passed"] += 1
        except Exception as e:  # 单条失败不影响其余
            t["failed"].append({"id": case["id"], "reason": (str(e) or type(e).__name__)[:400]})
    print(json.dumps({"tools": tools}, ensure_ascii=False))
    return 0 if tools and all(not t["failed"] for t in tools.values()) else 1


def get(obj, path):
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        obj = obj[int(part[1:-1])] if part.startswith("[") else obj[part]
    return obj


def _file(out, wd, fmt):
    f = next((f for f in out["files"] if f["format"] == fmt), None)
    assert f is not None, f"没有 {fmt} 文件"
    return (Path(wd) / f["path"]).read_bytes()


def _digest(out, wd):
    return [(f["path"], hashlib.sha256((Path(wd) / f["path"]).read_bytes()).hexdigest()) for f in out["files"]]


def check(case):
    with tempfile.TemporaryDirectory() as wd:
        r = call(case["tool"], case["payload"], wd)
        exp = dict(case["expect"])
        if any(k.startswith("error.") for k in exp):
            assert not r["ok"], "期望失败，实际成功"
            for k, v in exp.items():
                assert get(r, k) == v, f"{k}={get(r, k)}，期望 {v}"
            return
        assert r["ok"], f"调用失败：{json.dumps(r.get('error'), ensure_ascii=False)[:300]}"
        out = r["output"]
        if exp.pop("twice", False):
            with tempfile.TemporaryDirectory() as wd2:
                r2 = call(case["tool"], case["payload"], wd2)
                assert r2 == r, "两次运行的 output 不同"
                assert _digest(r2["output"], wd2) == _digest(out, wd), "两次运行的文件字节不同"
        if "file_count" in exp:
            n = exp.pop("file_count")
            assert len(out["files"]) == n, f"文件 {len(out['files'])} 个，期望 {n}"
        for key, fmt in (("md_contains", "md"), ("csv_contains", "csv"), ("model_contains", "json")):
            for s in exp.pop(key, []):
                text = _file(out, wd, fmt).decode("utf-8-sig")
                if fmt == "json":   # 表模型按紧凑写法比对（键序固定、无空白）
                    text = json.dumps(json.loads(text), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                assert s in text, f"{fmt} 缺少：{s!r}"
        for s in exp.pop("md_lacks", []):
            assert s not in _file(out, wd, "md").decode("utf-8"), f"Markdown 不应含：{s!r}"
        if "csv_bom" in exp:
            want = exp.pop("csv_bom")
            assert _file(out, wd, "csv").startswith(b"\xef\xbb\xbf") == want, "CSV 的 BOM 不符"
        for part, texts in exp.pop("xlsx_contains", {}).items():
            data = _file(out, wd, "xlsx")
            with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
                xml = z.read(part).decode("utf-8")
            for s in texts:
                assert s in xml, f"xlsx {part} 缺少：{s!r}"
        for k, v in exp.items():
            assert get(out, k) == v, f"{k}={get(out, k)}，期望 {v}"


if __name__ == "__main__":
    sys.exit(main(check))
