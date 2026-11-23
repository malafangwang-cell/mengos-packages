#!/usr/bin/env python3
"""subcontract-bom · rack.layout 的 process 执行器入口（17 TL-8）

协议：stdin 读一行 JSON，stdout 写一行 JSON。
  输入信封：{"tool": "rack.layout", "payload": {...}, "budget": {...}}
           也接受裸载荷 + 命令行参数给出工具名：rack_tool.py rack.layout
  输出：{"ok": true, "output": {...}}
       {"ok": false, "error": {"code": "BAD_INPUT|INTERNAL", "message": "..."}}
确定性、不出网、零模型调用；输出按键排序、紧凑分隔，同一输入逐字节相同（TL-12 ②）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import layout  # noqa: E402
import text  # noqa: E402

TOOL_ID = "rack.layout"


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _fail(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def run(envelope, tool_from_argv: str | None = None) -> dict:
    if not isinstance(envelope, dict):
        return _fail("BAD_INPUT", text.W4_SHAPE.format(path="/"))
    if "tool" in envelope and "payload" in envelope:
        tool, payload = envelope["tool"], envelope["payload"]
    else:
        tool, payload = tool_from_argv, envelope
    if tool != TOOL_ID:
        return _fail("BAD_INPUT", f"unknown tool {tool!r}")
    try:
        output, nothing = layout.compute(payload)
    except layout.ShapeError as exc:
        return _fail("BAD_INPUT", text.W4_SHAPE.format(path=str(exc)))
    except Exception as exc:  # noqa: BLE001 —— 如实上报
        return _fail("INTERNAL", f"{type(exc).__name__}: {exc}")
    if nothing:
        details = "；".join(e["reason"] for e in output["not_computed"])
        return _fail("BAD_INPUT", text.W4_NOTHING.format(details=details))
    return {"ok": True, "output": output}


def main() -> int:
    line = sys.stdin.readline()
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError:
        _emit(_fail("BAD_INPUT", text.W4_SHAPE.format(path="/")))
        return 0
    _emit(run(envelope, sys.argv[1] if len(sys.argv) > 1 else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
