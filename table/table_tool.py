#!/usr/bin/env python3
"""table · process 执行器入口（17 章 TL-8）

协议与 document、cad、calc 相同：stdin 读一行 JSON，stdout 写一行 JSON。
  输入信封：{"tool": "table.build", "payload": {...}, "budget": {"timeout_ms": 60000}, "workdir": "/abs/dir"}
           也接受裸载荷 + 命令行参数：table_tool.py table.build [--workdir DIR]
  输出：{"ok": true, "output": {...}}
       {"ok": false, "error": {"code": "BAD_INPUT|RESOURCE_LIMIT|TIMEOUT|INTERNAL", "message": "...", "where"?: "...", "line"?: n, "hint"?: "..."}}

文件产出（TL-9a）：
  · 引擎每次调用给一个新建的空目录 workdir；执行体只往这里写。
  · 结果对象顶层的 files 列出每个文件：{path(相对 workdir), format, role, media_type, bytes, sha256}。
  · 同一输入两次运行，output 相同，文件逐字节相同（TL-12 ②）。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import sys

DEFAULT_TIMEOUT_MS = 60_000
MAX_TIMEOUT_S = 3600
MAX_NAME_BYTES = 100
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 160 * 1024 * 1024
NAME_RE = re.compile(r"[^/\\.:*?\"<>|\s\x00-\x1f]{1,64}")

FORMATS = {
    # format: (扩展名, media_type, role)
    "json": (".table.json", "application/json", "table.model"),
    "view": (".view.json", "application/json", "table.view"),
    "md": (".md", "text/markdown; charset=utf-8", "table.text"),
    "xlsx": (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "table.excel"),
    "csv": (".csv", "text/csv; charset=utf-8", "table.csv"),
}
BUILD_ALWAYS = ["json", "view", "md"]
BUILD_EXTRA = ["xlsx", "csv"]
EXPORT_FORMATS = ["xlsx", "csv", "md", "json"]


class _Timeout(Exception):
    pass


class ResourceLimit(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _fail(code, message, where=None, line=None, hint=None) -> dict:
    e = {"code": code, "message": message}
    if where is not None:
        e["where"] = where
    if line is not None:
        e["line"] = line
    if hint:
        e["hint"] = hint
    return {"ok": False, "error": e}


# ---------------------------------------------------------------- 入参
def _allowed(payload, keys):
    from model import BadInput
    extra = set(payload) - set(keys)
    if extra:
        raise BadInput(f"不认识的字段：{', '.join(sorted(extra))}（可用：{', '.join(keys)}）", sorted(extra)[0])


def _table(payload, build=False):
    from model import BadInput, normalize
    if "table" not in payload:
        raise BadInput("缺少 table（表的内容）", "table")
    return normalize(payload["table"], build)


def slug(title: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", title, flags=re.UNICODE).strip("-")[:40].strip("-")
    return s or "table"


def _name(payload, t):
    from model import BadInput
    n = payload.get("name")
    if n is None:
        return slug(t.title)
    if not isinstance(n, str) or not NAME_RE.fullmatch(n) or len(n.encode("utf-8")) > MAX_NAME_BYTES:
        raise BadInput(f"name 是文件名（不含扩展名）：1–64 个字符、不超过 {MAX_NAME_BYTES} 字节，不能有空白、点、斜杠和 :*?\"<>|", "name")
    return n


def _formats(payload, allowed, default):
    from model import BadInput
    fs = payload.get("formats", default)
    if isinstance(fs, str):
        fs = [fs]
    if not isinstance(fs, list) or any(not isinstance(f, str) for f in fs):
        raise BadInput("formats 必须是字符串数组", "formats")
    bad = [f for f in fs if f not in allowed]
    if bad:
        raise BadInput(f"不支持的格式 {bad[0]}（可用：{', '.join(allowed)}）", "formats")
    out = []
    for f in fs:
        if f not in out:
            out.append(f)
    return out


def _render(t, fmt, name):
    """→ [(文件名, 字节, media_type, format, role)]"""
    import render
    ext, media, role = FORMATS[fmt]
    if fmt == "json":
        return [(name + ext, render.dumps(t.to_json()), media, fmt, role)]
    if fmt == "view":
        return [(name + ext, render.dumps(render.to_view(t)), media, fmt, role)]
    if fmt == "md":
        return [(name + ext, render.to_markdown(t).encode("utf-8"), media, fmt, role)]
    if fmt == "xlsx":
        from xlsx_writer import to_xlsx
        return [(name + ext, to_xlsx(t), media, fmt, role)]
    if fmt == "csv":
        if len(t.sheets) == 1:
            return [(name + ext, render.to_csv(t.sheets[0], t.lang), media, fmt, role)]
        return [(f"{name}-{i + 1}{ext}", render.to_csv(sh, t.lang), media, fmt, role) for i, sh in enumerate(t.sheets)]
    raise AssertionError(fmt)


def _write(t, formats, name, workdir):
    """先全部生成、核对大小，再一次写出；中途出错不留半截文件。"""
    from model import BadInput
    if not workdir:
        raise BadInput("要产出文件时必须提供 workdir（引擎为每次调用新建的空目录）", "workdir")
    if not isinstance(workdir, str) or not os.path.isabs(workdir) or not os.path.isdir(workdir):
        raise BadInput("workdir 必须是已存在目录的绝对路径", "workdir")
    out, total, seen = [], 0, set()
    for fmt in formats:
        for fn, data, media, f, role in _render(t, fmt, name):
            if fn in seen:
                continue
            seen.add(fn)
            if len(data) > MAX_FILE_BYTES:
                raise ResourceLimit(f"{fn} 超过 {MAX_FILE_BYTES // 1024 // 1024} MB")
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise ResourceLimit(f"文件合计超过 {MAX_TOTAL_BYTES // 1024 // 1024} MB")
            out.append((fn, data, media, f, role))
    files = []
    for fn, data, media, f, role in out:
        with open(os.path.join(workdir, fn), "wb") as fh:
            fh.write(data)
        files.append({"path": fn, "format": f, "role": role, "media_type": media,
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return files


def _warnings(t):
    keep = ("where", "code", "message", "line", "hint")
    return [{k: w[k] for k in keep if k in w} for w in t.warnings]


def _sheets(t):
    from model import dec_str
    out = []
    for sh in t.sheets:
        s = {"name": sh.name, "rows": len(sh.rows), "columns": [c.title for c in sh.columns]}
        if sh.totals:
            s["totals"] = [{"column": next(c.title for c in sh.columns if c.key == k), "fn": fn,
                            "value": None if v is None else dec_str(v)} for k, fn, v in sh.totals]
        out.append(s)
    return out


# ---------------------------------------------------------------- 三件工具
def table_build(payload, workdir=None):
    """数据 → 表：规范各列的类型与单位，算公式列和合计；交付表模型、产出台数据、Markdown，以及 Excel（缺省）。"""
    _allowed(payload, ["table", "name", "formats"])
    t = _table(payload, build=True)
    name = _name(payload, t)
    extra = _formats(payload, BUILD_EXTRA, ["xlsx"])
    out = {"title": t.title, "table_sha256": t.sha, "name": name, "sheets": _sheets(t), "stats": t.stats(),
           "warnings": _warnings(t), "files": _write(t, BUILD_ALWAYS + extra, name, workdir)}
    if t.assumptions:
        out["assumptions"] = list(t.assumptions)
    return out


def _from_object(obj):
    """导出工具与核对工具的通用入参 object（17 TL-9b）：交付物的规范对象，即 table.build 的产出记录；表的内容取自其 args.table。"""
    from model import SCHEMA, BadInput
    if not isinstance(obj, dict):
        raise BadInput("object 应当是要导出的表（JSON 对象）", "object")
    if obj.get("schema") == SCHEMA:
        return obj, None
    if obj.get("tool") not in (None, "table.build"):
        raise BadInput("object 不是表，导不出表格文件", "object")
    args = obj.get("args")
    if not isinstance(args, dict) or not isinstance(args.get("table"), dict):
        raise BadInput("object 里没有表的内容：只能导出由 table.build 做出的表", "object")
    return args["table"], args.get("name")


def _resolve_object(payload):
    from model import BadInput
    if ("table" in payload) == ("object" in payload):
        raise BadInput("table 与 object 二选一：给表的内容，或给要处理的表", "table")
    if "object" in payload:
        table, name0 = _from_object(payload["object"])
        payload = {k: v for k, v in payload.items() if k != "object"}
        payload["table"] = table
        if "name" not in payload and isinstance(name0, str):
            payload["name"] = name0
    return payload


def table_check(payload, workdir=None):
    """表 + 期望清单 → 每条 pass / fail / unknown 与总判定。不产出文件。"""
    from checker import ExpectError, overall, run_checks
    from model import BadInput
    _allowed(payload, ["table", "object", "expect"])
    payload = _resolve_object(payload)
    expect = payload.get("expect")
    if expect is not None and (not isinstance(expect, str) or len(expect) > 20000):
        raise BadInput("expect 是期望清单字符串（一行一条，最多 20000 个字符）", "expect")
    t = _table(payload)
    try:
        checks, assumptions = run_checks(t, expect)
    except ExpectError as e:
        raise BadInput("期望清单：" + e.message, "expect", e.hint, line=e.line) from None
    v = overall(checks)
    out = {"verdict": v, "covered": v != "unknown", "checks": checks, "table_sha256": t.sha}
    if assumptions:
        out["assumptions"] = assumptions
    return out


def table_export(payload, workdir=None):
    """表的内容（或要导出的表）→ 指定格式的文件。"""
    from model import BadInput
    _allowed(payload, ["table", "object", "name", "formats", "format"])
    payload = _resolve_object(payload)
    if "format" in payload:
        if "formats" in payload:
            raise BadInput("format 与 formats 二选一", "format")
        f = payload["format"]
        payload = {k: v for k, v in payload.items() if k != "format"}
        payload["formats"] = [f] if isinstance(f, str) else f
    t = _table(payload)
    name = _name(payload, t)
    formats = _formats(payload, EXPORT_FORMATS, [])
    if not formats:
        raise BadInput("formats 不能为空", "formats")
    return {"table_sha256": t.sha, "name": name, "warnings": _warnings(t), "files": _write(t, formats, name, workdir)}


TOOLS = {"table.build": table_build, "table.check": table_check, "table.export": table_export}


def run(envelope, tool_from_argv=None, workdir_from_argv=None) -> dict:
    from model import BadInput
    if not isinstance(envelope, dict):
        return _fail("BAD_INPUT", "输入必须是 JSON 对象")
    if "tool" in envelope and "payload" in envelope:
        tool, payload = envelope["tool"], envelope["payload"]
        budget, workdir = envelope.get("budget") or {}, envelope.get("workdir")
    else:
        tool, payload, budget, workdir = tool_from_argv, envelope, {}, workdir_from_argv
    fn = TOOLS.get(tool) if isinstance(tool, str) else None
    if fn is None:
        return _fail("BAD_INPUT", f"未知工具 {tool!r}（可用：{', '.join(sorted(TOOLS))}）")
    if not isinstance(payload, dict):
        return _fail("BAD_INPUT", "payload 必须是 JSON 对象")
    if not isinstance(budget, dict):
        return _fail("BAD_INPUT", "budget 必须是 JSON 对象", "budget")
    timeout_ms = budget.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, (int, float)):
        return _fail("BAD_INPUT", "budget.timeout_ms 必须是正数（毫秒）", "budget.timeout_ms")
    try:
        t = float(timeout_ms)
    except OverflowError:
        t = float("inf")
    if not math.isfinite(t) or t <= 0:
        return _fail("BAD_INPUT", "budget.timeout_ms 必须是有限的正数（毫秒）", "budget.timeout_ms")
    timeout_s = min(MAX_TIMEOUT_S, max(0.05, t / 1000 * 0.9))
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return {"ok": True, "output": fn(payload, workdir)}
    except _Timeout:
        return _fail("TIMEOUT", f"超过 {timeout_ms} ms")
    except BadInput as e:
        return _fail("BAD_INPUT", str(e), e.where, getattr(e, "line", None), e.hint)
    except ResourceLimit as e:
        return _fail("RESOURCE_LIMIT", str(e))
    except RecursionError:
        return _fail("RESOURCE_LIMIT", "嵌套过深")
    except Exception as exc:  # noqa: BLE001 —— 基础设施层异常如实上报
        return _fail("INTERNAL", f"{type(exc).__name__}: {exc}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> int:
    args = sys.argv[1:]
    workdir = None
    if "--workdir" in args:
        i = args.index("--workdir")
        workdir = os.path.abspath(args[i + 1]) if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    line = sys.stdin.readline()
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError as exc:
        _emit(_fail("BAD_INPUT", f"输入不是合法 JSON：{exc.msg}（第 {exc.pos} 个字符）"))
        return 0
    _emit(run(envelope, args[0] if args else None, workdir))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
