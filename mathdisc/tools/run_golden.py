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


def _get(obj, path):
    """按点号路径取值；数字段按数组下标。"""
    for part in path.split("."):
        if isinstance(obj, list):
            obj = obj[int(part)]
        else:
            if part not in obj:
                raise AssertionError(f"输出缺少 {path}")
            obj = obj[part]
    return obj


def _assert(out, spec):
    """一条断言：{"path", 以及 eq | ne | in | contains | approx(+tol) | nonempty 其一}。"""
    v = _get(out, spec["path"])
    p = spec["path"]
    if "eq" in spec:
        assert v == spec["eq"], f"{p}={v!r}，期望 {spec['eq']!r}"
    if "ne" in spec:
        assert v != spec["ne"], f"{p}={v!r}，不应为 {spec['ne']!r}"
    if "in" in spec:
        assert v in spec["in"], f"{p}={v!r}，期望属于 {spec['in']!r}"
    if "contains" in spec:
        assert spec["contains"] in v, f"{p} 不含 {spec['contains']!r}"
    if "approx" in spec:
        assert abs(float(v) - spec["approx"]) <= spec.get("tol", 1e-6), f"{p}={v}，期望约 {spec['approx']}"
    if "nonempty" in spec:
        assert bool(v) is spec["nonempty"], f"{p}={v!r}，期望{'非空' if spec['nonempty'] else '为空'}"


def check(case, wd):
    res = call(case["tool"], case["payload"], None)
    if "expect_error" in case:
        assert res["ok"] is False, "期望失败，实际成功"
        assert res["error"]["code"] == case["expect_error"], f"错误码 {res['error']['code']}，期望 {case['expect_error']}"
        return
    assert res["ok"] is True, f"调用失败：{json.dumps(res.get('error'), ensure_ascii=False)[:200]}"
    for spec in case["expect"]:
        _assert(res["output"], spec)


if __name__ == "__main__":
    sys.exit(main(check))
