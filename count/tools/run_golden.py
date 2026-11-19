"""金样运行入口（TL-12 ③，WP-W6 §2 certification_material.golden_runner）。

certify 在安装区用包环境的解释器运行本文件：
  python tools/run_golden.py [--tool <tool_id>]
不导入包内模块：每条金样都按与引擎相同的进程入口与信封调用工具（stdin 一行 JSON，stdout 一行 JSON），测的是装好的工具。
每条金样的 expect 是 {JSON 指针: 期望值}，指针相对回执 output；expect_error 是期望的失败码。
另跑一遍同一信封，核对两次 stdout 逐字节相同（TL-12 ② 确定性）。
按文件读的金样带 "fixture": {"name": 合成图纸名, "parsed": 是否带解析结构}：现场生成图纸、用包里带的解析库出解析结构，
摆成引擎交文件后的样子（tools/fixture_files.py），把载荷里的 {"$file": true} 换成 source.file 对象，信封带 workdir。
标准输出：{"tools": {"<tool_id>": {"total": n, "passed": n, "failed": [{"id", "reason"}]}}}；全过退出码 0，否则 1。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
ENTRY = ROOT / json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))["runtime"]["process"]["entry"]


def _subst(v, file_obj):
    if v == {"$file": True}:
        return file_obj
    if isinstance(v, dict):
        return {k: _subst(x, file_obj) for k, x in v.items()}
    if isinstance(v, list):
        return [_subst(x, file_obj) for x in v]
    return v


def call(tool, payload, workdir=None):
    envelope = {"tool": tool, "payload": payload, "budget": {"timeout_ms": 10000}}
    if workdir is not None:
        envelope["workdir"] = workdir
    env = json.dumps(envelope).encode("utf-8")
    outs = []
    for seed in ("1", "77"):
        p = subprocess.run([sys.executable, str(ENTRY)], input=env, capture_output=True, timeout=60, cwd=str(ROOT),
                           env={"PYTHONHASHSEED": seed})
        if p.returncode != 0:
            raise AssertionError(f"进程退出码 {p.returncode}：{p.stderr.decode('utf-8', 'replace')[-300:]}")
        outs.append(p.stdout)
    if outs[0] != outs[1]:
        raise AssertionError("两次输出不逐字节相同")
    return json.loads(outs[0].decode("utf-8"))


def pointer(doc, ptr):
    cur = doc
    for raw in ptr.split("/")[1:]:
        key = raw.replace("~1", "/").replace("~0", "~")
        cur = cur[int(key)] if isinstance(cur, list) else cur[key]
    return cur


FIXTURES = {}


def check(case):
    fx = case.get("fixture")
    if fx is None:
        res = call(case["tool"], case["payload"])
    else:
        sys.path.insert(0, str(ROOT / "tools"))
        from fixture_files import Fixture
        if fx["name"] not in FIXTURES:
            FIXTURES[fx["name"]] = Fixture(fx["name"])
        wd, file_obj = FIXTURES[fx["name"]].workdir(fx.get("parsed", True))
        res = call(case["tool"], _subst(case["payload"], file_obj), wd)
        left = sorted(os.listdir(wd))
        assert left == ["in"], f"调用后工作目录里多了文件：{left}"
    if "expect_error" in case:
        assert res["ok"] is False, "期望失败，实际成功"
        assert res["error"]["code"] == case["expect_error"], f"错误码 {res['error']['code']}，期望 {case['expect_error']}"
        return
    assert res["ok"] is True, f"调用失败：{json.dumps(res.get('error'), ensure_ascii=False)[:200]}"
    for ptr, val in case["expect"].items():
        got = pointer(res["output"], ptr)
        assert got == val, f"{ptr}={json.dumps(got, ensure_ascii=False)[:120]}，期望 {json.dumps(val, ensure_ascii=False)}"


def main():
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
    for f in FIXTURES.values():
        f.cleanup()
    print(json.dumps({"tools": tools}, ensure_ascii=False))
    return 0 if tools and all(not t["failed"] for t in tools.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
