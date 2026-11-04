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
    for k in path.split("."):
        obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj


def check(case, wd):
    res = call(case["tool"], case["payload"], wd if case.get("workdir") else None)
    exp = case["expect"]
    assert res["ok"] is exp["ok"], f"ok={res['ok']}，期望 {exp['ok']}：{json.dumps(res, ensure_ascii=False)[:200]}"
    if not exp["ok"]:
        assert res["error"]["code"] == exp["code"], f"错误码 {res['error']['code']}，期望 {exp['code']}"
        if "line" in exp:
            assert res["error"].get("line") == exp["line"], f"行号 {res['error'].get('line')}，期望 {exp['line']}"
        if "hint_contains" in exp:
            assert exp["hint_contains"] in res["error"].get("hint", ""), "提示不含期望内容"
        return
    out = res["output"]
    for v in exp.get("values", []):
        got = get(out, v["path"])
        assert abs(got - v["value"]) <= abs(v["value"]) * v["rtol"], f"{v['path']}={got}，期望 {v['value']}±{v['rtol']}"
    for e in exp.get("equals", []):
        assert get(out, e["path"]) == e["value"], f"{e['path']}={get(out, e['path'])}，期望 {e['value']}"
    for c in exp.get("count", []):
        n = len([h for h in get(out, c["path"]) if all(h.get(k) == w for k, w in c["where"].items())])
        assert n == c["value"], f"{c['path']} 计数 {n}，期望 {c['value']}"
    if exp.get("files_verified"):
        for f in out["files"]:
            data = (Path(wd) / f["path"]).read_bytes()
            assert len(data) == f["bytes"] and hashlib.sha256(data).hexdigest() == f["sha256"], f"文件 {f['path']} 与清单不符"
        assert sorted(os.listdir(wd)) == sorted(f["path"] for f in out["files"]), "workdir 里有未声明的文件"


if __name__ == "__main__":
    sys.exit(main(check))
