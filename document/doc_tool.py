#!/usr/bin/env python3
"""document · process 执行器入口（17 章 TL-8）

协议与 cad、calc 相同：stdin 读一行 JSON，stdout 写一行 JSON。
  输入信封：{"tool": "doc.build", "payload": {...}, "budget": {"timeout_ms": 60000}, "workdir": "/abs/dir"}
           也接受裸载荷 + 命令行参数：doc_tool.py doc.build [--workdir DIR]
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
MAX_FILE_BYTES = 48 * 1024 * 1024        # 低于对象层单次写入的 50 MiB，留余量
MAX_TOTAL_BYTES = 512 * 1024 * 1024       # 原图 ≤320 MB + .doc.json、网页、产出台数据、Word 各 ≤48 MB + 余量
NAME_RE = re.compile(r"[^/\\.:*?\"<>|\s\x00-\x1f]{1,64}")

FORMATS = {
    # format: (扩展名, media_type, role)
    "json": (".doc.json", "application/json", "document.model"),
    "view": (".view.json", "application/json", "document.view"),
    "md": (".md", "text/markdown; charset=utf-8", "document.text"),
    "docx": (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document.word"),
    "html": (".html", "text/html; charset=utf-8", "document.web"),
    "pdf": (".pdf", "application/pdf", "document.pdf"),
}
BUILD_ALWAYS = ["json", "view", "md"]
BUILD_EXTRA = ["docx", "html"]
EXPORT_FORMATS = ["docx", "pdf", "md", "html", "json"]


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
        raise BadInput(f"不认识的字段：{', '.join(sorted(extra))}（可用：{', '.join(keys)}）")


def _assembled(payload):
    from assemble import assemble
    from model import BadInput, normalize
    if "doc" not in payload:
        raise BadInput("缺少 doc（文档内容）", "doc")
    a = assemble(normalize(payload["doc"]))
    _check_model_size(a)
    return a


def _check_model_size(a):
    """输入阶段就判：规范模型文件（内嵌嵌入副本的 base64）不能超过单文件上限，不留到写文件时才报裸的 RESOURCE_LIMIT。"""
    from model import BadInput
    import render
    if not any(f.orig_path for f in a.doc.figures):
        return
    n = len(render.dumps(a.doc.to_json()))
    if n > MAX_FILE_BYTES:
        raise BadInput(f"文档模型文件将有 {n} 字节（{n / 1024 / 1024:.1f} MB），超过单文件上限 {MAX_FILE_BYTES} 字节"
                       f"（{MAX_FILE_BYTES // 1024 // 1024} MB）：图片嵌入副本与正文合计过大，请减少图片或正文", "doc.figures")


def slug(title: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", title, flags=re.UNICODE).strip("-")[:40].strip("-")
    return s or "document"


def _name(payload, a):
    from model import BadInput
    n = payload.get("name")
    if n is None:
        return slug(a.doc.title)
    if not isinstance(n, str) or not NAME_RE.fullmatch(n) or len(n.encode("utf-8")) > MAX_NAME_BYTES:
        raise BadInput(f"name 是文件名（不含扩展名）：1–64 个字符、不超过 {MAX_NAME_BYTES} 字节，不能有空白、点、斜杠和 :*?\"<>|", "name")
    return n


def _formats(payload, allowed, default):
    from model import BadInput
    fs = payload.get("formats", default)
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


def _render(a, fmt, name):
    """→ [(文件名, 字节, media_type, format, role)]"""
    import render
    ext, media, role = FORMATS[fmt]
    if fmt == "json":
        return [(name + ext, render.dumps(a.doc.to_json()), media, fmt, role)]
    if fmt == "view":
        return [(name + ext, render.dumps(render.to_view(a)), media, fmt, role)]
    if fmt == "md":
        text, figs = render.to_markdown(a, name)
        out = [(name + ext, text.encode("utf-8"), media, fmt, role)]
        out += [(fn, data, mt, "figure", render.ROLE_FIG) for fn, data, mt in figs]
        return out
    if fmt == "html":
        return [(name + ext, render.to_html(a).encode("utf-8"), media, fmt, role)]
    if fmt == "docx":
        from docx_writer import to_docx
        return [(name + ext, to_docx(a), media, fmt, role)]
    if fmt == "pdf":
        from pdf_writer import to_pdf
        data, warns = to_pdf(a)
        a.warnings.extend(warns)            # 排版时才知道的提醒（图画不了、字体缺字）并入本次结果
        return [(name + ext, data, media, fmt, role)]
    raise AssertionError(fmt)


def _originals(a):
    """位图的原图，各成一个产出文件 figures/<id>.<ext>（原字节不改；.doc.json 按哈希引用，Markdown 直接引用）。"""
    import render
    return [(f.orig_path, f.data, f.media_type, "figure", render.ROLE_FIG_ORIG) for f in a.doc.figures if f.orig_path]


def _write(a, formats, name, workdir, with_originals=False):
    """先全部生成、核对大小，再一次写出；中途出错不留半截文件。"""
    from model import BadInput
    if not workdir:
        raise BadInput("要产出文件时必须提供 workdir（引擎为每次调用新建的空目录）", "workdir")
    if not isinstance(workdir, str) or not os.path.isabs(workdir) or not os.path.isdir(workdir):
        raise BadInput("workdir 必须是已存在目录的绝对路径", "workdir")
    out, total, seen = [], 0, set()
    renders = [_render(a, fmt, name) for fmt in formats]
    if with_originals:
        renders.append(_originals(a))
    for batch in renders:
        for fn, data, media, f, role in batch:
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
        os.makedirs(os.path.dirname(os.path.join(workdir, fn)), exist_ok=True)
        with open(os.path.join(workdir, fn), "wb") as fh:
            fh.write(data)
        files.append({"path": fn, "format": f, "role": role, "media_type": media,
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return files


def _warnings(a):
    keep = ("where", "code", "message", "line", "hint")
    return [{k: w[k] for k in keep if k in w} for w in a.warnings]


# ---------------------------------------------------------------- 三件工具
def doc_build(payload, workdir=None):
    """内容 → 文档：编号、目录、引用、要求追溯；交付文档模型、产出台数据、Markdown，以及 Word（缺省）。"""
    _allowed(payload, ["doc", "name", "formats"])
    a = _assembled(payload)
    name = _name(payload, a)
    extra = _formats(payload, BUILD_EXTRA, ["docx"])
    outline = [{"id": o.sec.id, "level": o.sec.level, "number": o.number, "heading": o.sec.heading,
                "words": o.words, "words_total": o.words_total} for o in a.sections]
    return {
        "title": a.doc.title, "kind": a.doc.kind, "doc_sha256": a.sha, "name": name,
        "outline": outline, "stats": a.stats, "trace": a.trace, "warnings": _warnings(a),
        "files": _write(a, BUILD_ALWAYS + extra, name, workdir, with_originals=True),
    }


def doc_check(payload, workdir=None):
    """文档 + 期望清单 → 每条 pass / fail / unknown 与总判定。不产出文件。"""
    from checker import ExpectError, overall, run_checks
    from model import BadInput
    _allowed(payload, ["doc", "expect"])
    expect = payload.get("expect")
    if expect is not None and (not isinstance(expect, str) or len(expect) > 20000):
        raise BadInput("expect 是期望清单字符串（一行一条，最多 20000 个字符）", "expect")
    a = _assembled(payload)
    try:
        checks, assumptions = run_checks(a, expect)
    except ExpectError as e:
        raise BadInput("期望清单：" + e.message, "expect", e.hint, line=e.line) from None
    v = overall(checks)
    out = {"verdict": v, "covered": v != "unknown", "checks": checks, "doc_sha256": a.sha}
    if assumptions:
        out["assumptions"] = assumptions
    return out


def _doc_from_object(obj):
    """导出工具的通用入参 object（17 TL-9b）：交付物的规范对象，即排版那一步的产出记录；文档内容取自其 args.doc。"""
    from model import BadInput
    if not isinstance(obj, dict):
        raise BadInput("object 应当是要导出的文档（JSON 对象）", "object")
    if obj.get("tool") not in (None, "doc.build"):
        raise BadInput("object 不是文档，导不出文档文件", "object")
    args = obj.get("args")
    if not isinstance(args, dict) or not isinstance(args.get("doc"), dict):
        raise BadInput("object 里没有文档内容：只能导出按文档内容排出的文档", "object")
    return args["doc"], args.get("name")


def doc_export(payload, workdir=None):
    """文档内容（或要导出的文档）→ 指定格式的文件。"""
    from model import BadInput
    _allowed(payload, ["doc", "object", "name", "formats", "format"])
    if ("doc" in payload) == ("object" in payload):
        raise BadInput("doc 与 object 二选一：给文档内容，或给要导出的文档", "doc")
    if "object" in payload:
        doc, name0 = _doc_from_object(payload["object"])
        payload = {k: v for k, v in payload.items() if k != "object"}
        payload["doc"] = doc
        if "name" not in payload and isinstance(name0, str):
            payload["name"] = name0
    if "format" in payload:
        if "formats" in payload:
            raise BadInput("format 与 formats 二选一", "format")
        f = payload["format"]
        payload = {k: v for k, v in payload.items() if k != "format"}
        payload["formats"] = [f] if isinstance(f, str) else f
    a = _assembled(payload)
    name = _name(payload, a)
    formats = _formats(payload, EXPORT_FORMATS, [])
    if not formats:
        raise BadInput("formats 不能为空", "formats")
    # Markdown 与规范模型引用原图文件，所以导出它们时随带原图；只导 Word、PDF、网页时不带
    files = _write(a, formats, name, workdir, with_originals=bool({"md", "json"} & set(formats)))   # 先排版再取提醒：PDF 排版时会追加提醒
    return {"doc_sha256": a.sha, "name": name, "warnings": _warnings(a), "files": files}


TOOLS = {"doc.build": doc_build, "doc.check": doc_check, "doc.export": doc_export}


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
