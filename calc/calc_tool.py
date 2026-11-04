#!/usr/bin/env python3
"""calc v2 · process 执行器入口（17 章 TL-8）

协议：stdin 读一行 JSON，stdout 写一行 JSON。
  输入信封：{"tool": "calc.evaluate", "payload": {...}, "budget": {"timeout_ms": 10000}}
           也接受裸载荷 + 命令行参数给出工具名：calc_tool.py calc.evaluate
  输出：{"ok": true, "output": {...}}
       {"ok": false, "error": {"code": "BAD_INPUT|UNSUPPORTED|RESOURCE_LIMIT|TIMEOUT|INTERNAL", "message": "..."}}
输出按键排序、紧凑分隔，同一输入逐字节相同（TL-12 ② 确定性）。
"""

from __future__ import annotations

import json
import signal
import sys

from evaluator import ResourceLimit, Unsupported, algebra, check_equal, evaluate
from expr_parser import ParseError

TOOLS = {
    "calc.evaluate": evaluate,
    "calc.algebra": algebra,
    "calc.check_equal": check_equal,
}
DEFAULT_TIMEOUT_MS = 10_000


class _Timeout(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _fail(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def run(envelope, tool_from_argv: str | None = None) -> dict:
    if not isinstance(envelope, dict):
        return _fail("BAD_INPUT", "输入必须是 JSON 对象")
    if "tool" in envelope and "payload" in envelope:
        tool, payload, budget = envelope["tool"], envelope["payload"], envelope.get("budget") or {}
    else:
        tool, payload, budget = tool_from_argv, envelope, {}
    fn = TOOLS.get(tool)
    if fn is None:
        return _fail("BAD_INPUT", f"未知工具 {tool!r}（可用：{', '.join(sorted(TOOLS))}）")
    if not isinstance(payload, dict):
        return _fail("BAD_INPUT", "payload 必须是 JSON 对象")
    timeout_ms = budget.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    try:
        timeout_s = max(0.05, float(timeout_ms) / 1000 * 0.9)  # 留一成余量，先于引擎计时返回结构化 TIMEOUT
    except (TypeError, ValueError):
        timeout_s = DEFAULT_TIMEOUT_MS / 1000
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return {"ok": True, "output": fn(payload)}
    except _Timeout:
        return _fail("TIMEOUT", f"计算超过 {timeout_ms} ms")
    except ParseError as exc:
        return _fail("BAD_INPUT", str(exc))
    except ResourceLimit as exc:
        return _fail("RESOURCE_LIMIT", str(exc))
    except Unsupported as exc:
        return _fail("UNSUPPORTED", str(exc))
    except RecursionError:
        return _fail("RESOURCE_LIMIT", "表达式嵌套过深")
    except Exception as exc:  # noqa: BLE001 —— 基础设施层异常如实上报
        return _fail("INTERNAL", f"{type(exc).__name__}: {exc}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> int:
    line = sys.stdin.readline()
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError as exc:
        _emit(_fail("BAD_INPUT", f"输入不是合法 JSON：{exc.msg}（第 {exc.pos} 个字符）"))
        return 0
    _emit(run(envelope, sys.argv[1] if len(sys.argv) > 1 else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
