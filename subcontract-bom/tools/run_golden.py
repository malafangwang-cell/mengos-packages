"""金样运行入口（TL-12 ③，certification_material.golden_runner）。

certify 在安装区用包环境的解释器运行本文件：
  python tools/run_golden.py [--tool <tool_id>]
本文件不导入包内模块：每条金样都按与引擎相同的进程入口与信封调用工具（stdin 一行 JSON，stdout 一行 JSON），测的是装好的工具。
每条金样标出所对的条文（clause）；条文改动而金样没随改 ⟹ 认证不过（设计稿五“条文与工具的对账”）。
标准输出写按工具分列的汇总：{"tools": {"<tool_id>": {"total": n, "passed": n, "failed": [{"id", "reason"}]}}}；全过退出码 0，否则 1。
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
ENTRY = ROOT / json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))["runtime"]["process"]["entry"]


def call_raw(tool, payload):
    env = {"tool": tool, "payload": payload, "budget": {"timeout_ms": 10000}}
    p = subprocess.run([sys.executable, str(ENTRY)], input=json.dumps(env, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=60, cwd=str(ROOT))
    if p.returncode != 0:
        raise AssertionError(f"进程退出码 {p.returncode}：{p.stderr.decode('utf-8', 'replace')[-300:]}")
    return p.stdout


def check(case):
    raw = call_raw(case["tool"], case["payload"])
    for _ in range(case.get("repeat", 1) - 1):
        assert call_raw(case["tool"], case["payload"]) == raw, "同一入参两次回执不逐字节相同"
    res = json.loads(raw.decode("utf-8"))
    if "expect_error" in case:
        assert res["ok"] is False, "期望失败，实际成功"
        assert res["error"]["code"] == case["expect_error"], f"错误码 {res['error']['code']}，期望 {case['expect_error']}"
        return
    assert res["ok"] is True, f"期望成功，实际失败：{res.get('error')}"
    out = res["output"]
    exp = case["expect"]
    assert out["computed"] == exp["computed"], f"computed {out['computed']}，期望 {exp['computed']}"
    got_nc = {e["item"]: e["needs"] for e in out["not_computed"]}
    assert got_nc == exp["not_computed"], f"not_computed {got_nc}，期望 {exp['not_computed']}"
    if "expect_step_note" in case:
        items = [s for s in out["steps"] if s["item"] == case["expect_step_note"]]
        assert items and "note" in items[0], "steps 里该项没有记下不自洽"
    else:
        assert all("note" not in s for s in out["steps"]), "不该有 note"


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
    print(json.dumps({"tools": tools}, ensure_ascii=False))
    return 0 if tools and all(not t["failed"] for t in tools.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
