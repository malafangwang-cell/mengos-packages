#!/usr/bin/env python3
"""count · process 执行器入口（17 章 TL-8）

协议：stdin 读一行 JSON，stdout 写一行 JSON。
  输入信封：{"tool": "count.rows", "payload": {...}, "budget": {...}}；也接受裸载荷 + 命令行参数给出工具名
  输出：{"ok": true, "output": {...}} 或 {"ok": false, "error": {"code": "BAD_INPUT|INTERNAL", "message": "..."}}
输出按键排序、紧凑分隔，同一输入逐字节相同（TL-12 ② 确定性）。不出网、不调模型、不留产出文件。

来源两类：
  - 调用方给出（mode = "inline"）：行数设上限 MAX_INLINE_ROWS，回执带转录假设（17 TL-22a）；
  - 按文件读（mode = "file"，0.2.0）：source.file 由引擎换成附件文件本身（17 TL-9d），放在信封 workdir 下的
    只读输入子目录；默认读入库时存下的完整解析结构，结构里没有的用包里带的同一份解析库回原件读（file_source.py）。
    不设行数上限，不挂转录假设。
清单分页（0.2.0）：count.rows 的 list 一次最多 MAX_LIST_ITEMS 条，超过用 offset、limit 分批取；total_matched 始终给全。
"""
from __future__ import annotations

import json
import sys

from coverage import coverage
from ops import Filter, aggregate, distribution, num_out, parse_aggregate, parse_num
from readers import BadInput, assumptions_of, canonical, read_source, source_hash
from series import chain, product

MAX_INLINE_ROWS = 50          # 与 registration.json 各件 capability.constraints.max_inline_rows 一致（测试钉住）
MAX_LIST_ITEMS = 2000


def _tol(payload, default="0"):
    t = parse_num(payload.get("tol", default))
    if t is None or t < 0:
        raise BadInput("tol 须为非负数")
    return t


def _page(payload, lst):
    """offset、limit（清单分页）：非负整数；limit 1..MAX_LIST_ITEMS；只在 list 为 true 时用。"""
    off, lim = payload.get("offset"), payload.get("limit")
    if off is None and lim is None:
        return None, None
    if not lst:
        raise BadInput("offset、limit 只在 list 为 true 时用")
    if off is not None and (isinstance(off, bool) or not isinstance(off, int) or off < 0):
        raise BadInput("offset 须为非负整数")
    if lim is not None and (isinstance(lim, bool) or not isinstance(lim, int) or not 1 <= lim <= MAX_LIST_ITEMS):
        raise BadInput(f"limit 须为 1 到 {MAX_LIST_ITEMS} 的整数")
    return off, lim


def count_rows(payload, max_rows=MAX_INLINE_ROWS, workdir=None):
    table = read_source(payload.get("source"), max_rows, workdir)
    flt = Filter(payload.get("where"), payload.get("any_of"), table.columns)
    matched, unparsed = flt.apply(table)
    group_by = payload.get("group_by") or []
    if not isinstance(group_by, list) or not all(isinstance(g, str) for g in group_by):
        raise BadInput("group_by 须为列名数组")
    gidx = []
    for g in group_by:
        if g not in table.columns:
            raise BadInput(f"group_by 的列“{g}”不在表头里")
        gidx.append(table.columns.index(g))
    aggs = parse_aggregate(payload.get("aggregate"), table.columns)
    lst = payload.get("list", False)
    if not isinstance(lst, bool):
        raise BadInput("list 须为布尔值")
    off, lim = _page(payload, lst)
    what = {**flt.echo(), "group_by": group_by,
            "aggregate": [{"col": c, "fn": f} for c, _, f in aggs],
            "distribution": payload.get("distribution"), "list": lst}
    if off is not None:
        what["offset"] = off
    if lim is not None:
        what["limit"] = lim
    out = {
        "count": len(matched),
        "what": what,
        "source": {**table.source, "rows_unparsed": len(unparsed)},
        "unparsed": unparsed[:50],
        "checks": table.checks,
        "assumptions": assumptions_of(table),
    }
    if gidx:
        groups: dict[tuple, list] = {}
        for r in matched:
            groups.setdefault(tuple(r[1][i] for i in gidx), []).append(r)
        gl = []
        for key in sorted(groups, key=lambda k: [(0, parse_num(x), x) if parse_num(x) is not None else (1, 0, x) for x in k]):
            g = {"key": dict(zip(group_by, key)), "count": len(groups[key])}
            if aggs:
                g["aggregate"] = aggregate(groups[key], aggs)
            gl.append(g)
        out["groups"] = gl
        out["groups_count"] = len(gl)          # G-3：不同取值（组合）的个数
    if aggs:
        out["aggregate"] = aggregate(matched, aggs)
    if payload.get("distribution") is not None:
        out["distribution"] = distribution(matched, payload["distribution"], table.columns)
    if lst:
        start = off or 0
        page = matched[start:start + lim] if lim is not None else matched[start:]
        if len(page) > MAX_LIST_ITEMS:
            raise BadInput(f"清单 {len(matched)} 条超过 {MAX_LIST_ITEMS}，用 offset、limit 分批取")
        out["items"] = [{"id": rid, "cells": dict(zip(table.columns, cells))} for rid, cells in page]
        out["total_matched"] = len(matched)
    return out


def count_series(payload, max_rows=MAX_INLINE_ROWS, workdir=None):
    mode = payload.get("mode")
    if mode not in ("product", "chain", "both"):
        raise BadInput("mode 须为 product、chain 或 both")
    table = read_source(payload.get("source"), max_rows, workdir)
    flt = Filter(payload.get("where"), payload.get("any_of"), table.columns)
    matched, unparsed = flt.apply(table)
    tol = _tol(payload)
    out = {
        "what": {**flt.echo(), "mode": mode, "tol": num_out(tol)},
        "rows_matched": len(matched),
        "source": {**table.source, "rows_unparsed": len(unparsed)},
        "unparsed": unparsed[:50],
        "checks": table.checks,
        "assumptions": assumptions_of(table),
    }
    if mode in ("product", "both"):
        out["product"] = product(matched, payload.get("product"), table.columns, tol)
    if mode in ("chain", "both"):
        out["chain"] = chain(matched, payload.get("chain"), table.columns, tol)
    return out


def count_coverage(payload, max_rows=MAX_INLINE_ROWS, workdir=None):
    out = coverage(payload, max_rows, workdir)
    if out["source"].get("mode") == "inline":
        out["source"]["source_sha256"] = source_hash({"inventory": payload.get("inventory"), "marks": payload.get("marks", [])})
    return out


RELATIONS = ("eq", "diff")


def count_agree(payload, max_rows=MAX_INLINE_ROWS, workdir=None):
    """G-4 互证：两个数按关系核对（eq：相等；diff：left − right 等于给定差）。数由调用方从计数回执里引用。"""
    sides = {}
    for side in ("left", "right"):
        s = payload.get(side)
        if not isinstance(s, dict):
            raise BadInput(f"{side} 须为对象 {{value, from}}")
        v = parse_num(s.get("value"))
        if v is None:
            raise BadInput(f"{side}.value 须为数")
        f = s.get("from")
        if not isinstance(f, str) or not f.strip():
            raise BadInput(f"{side}.from 须写明这个数取自哪张回执的哪一项")
        sides[side] = (v, f)
    rel = payload.get("relation", "eq")
    if rel not in RELATIONS:
        raise BadInput("relation 须为 eq 或 diff")
    tol = _tol(payload)
    (lv, lf), (rv, rf) = sides["left"], sides["right"]
    expected = parse_num(payload.get("diff", 0)) if rel == "diff" else parse_num(0)
    if expected is None:
        raise BadInput("diff 须为数")
    actual = lv - rv
    holds = abs(actual - expected) <= tol
    return {
        "holds": holds,
        "relation": rel,
        "left": {"value": num_out(lv), "from": lf},
        "right": {"value": num_out(rv), "from": rf},
        "diff_expected": num_out(expected),
        "diff_actual": num_out(actual),
        "tol": num_out(tol),
        "assumptions": ["两边的数由调用方写入，程序未与所引回执核对"],
    }


TOOLS = {
    "count.rows": count_rows,
    "count.series": count_series,
    "count.coverage": count_coverage,
    "count.agree": count_agree,
}


def _fail(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}


def run(envelope, tool_from_argv: str | None = None, max_rows=MAX_INLINE_ROWS) -> dict:
    if not isinstance(envelope, dict):
        return _fail("BAD_INPUT", "输入必须是 JSON 对象")
    workdir = None
    if "tool" in envelope and "payload" in envelope:
        tool, payload = envelope["tool"], envelope["payload"]
        workdir = envelope.get("workdir")
        if isinstance(tool, dict):
            tool = tool.get("signature")
    else:
        tool, payload = tool_from_argv, envelope
    fn = TOOLS.get(tool)
    if fn is None:
        return _fail("BAD_INPUT", f"未知工具 {tool!r}（可用：{', '.join(sorted(TOOLS))}）")
    if not isinstance(payload, dict):
        return _fail("BAD_INPUT", "payload 必须是 JSON 对象")
    try:
        return {"ok": True, "output": fn(payload, max_rows, workdir)}
    except BadInput as exc:
        return _fail("BAD_INPUT", str(exc))
    except RecursionError:
        return _fail("BAD_INPUT", "入参嵌套过深")
    except Exception as exc:  # noqa: BLE001 —— 基础设施层异常如实上报
        return _fail("INTERNAL", f"{type(exc).__name__}: {exc}")


def main() -> int:
    raw = sys.stdin.readline()
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stdout.write(canonical(_fail("BAD_INPUT", f"输入不是合法 JSON：{exc.msg}")) + "\n")
        return 0
    sys.stdout.write(canonical(run(envelope, sys.argv[1] if len(sys.argv) > 1 else None)) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
