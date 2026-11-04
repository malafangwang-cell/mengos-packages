"""引擎贡献合并代数的参照实现（Python 对照，只供包内预检用，不在工具运行路径上，不属 lock 覆盖范围）。

对应 mengosv2 `engine/projection/shapes/contribution.ts`（@4f708d6）的 validateAnnotations、contributionInfo、
merge、touchedKeys、emptySlots、skeleton；语义依据 kernel-spec 17 TL-30a 与设计稿 r8 §三.2/§三.3。
本文件由包侧逐段对照 TS 手写；它是否忠实，靠 tests/fixtures/contribution 里照抄自引擎的金样验：
金样全过才说明本参照实现与引擎在这些用例上一致，之后才拿它去核 doc.build 的 schema。
正则：JS 的 \\w 只含 ASCII，这里用 re.ASCII 对齐（\\s 在 JS 里含 Unicode 空白，Python 的 ASCII 模式只含 ASCII 空白；
doc.build 不用 named-lines，金样卡的 plan 正则只涉及 ASCII）。
"""
from __future__ import annotations

import json
import re
from typing import Any

_MODES = ("by-id", "append", "named-lines")
_MISSING = object()   # TS 的 undefined（与 JSON null 区分）


def is_obj(v: Any) -> bool:
    return isinstance(v, dict)


def canonical_json(v: Any) -> str:
    """键按 UTF-16 码元升序、无空白（对齐引擎 canonicalJson 在本用例涉及的值型上的输出）。"""
    def norm(x):
        if isinstance(x, dict):
            return {k: norm(x[k]) for k in sorted(x, key=lambda k: k.encode("utf-16-be"))}
        if isinstance(x, list):
            return [norm(i) for i in x]
        return x
    return json.dumps(norm(v), ensure_ascii=False, separators=(",", ":"))


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


# ───────── 声明与标注 ─────────
def reachable_annotations(schema: Any) -> list[dict]:
    """从根沿 properties 与 items 递归，不进 $ref、oneOf/anyOf/allOf/if/then/else。"""
    out: list[dict] = []

    def walk(node, path):
        if not is_obj(node):
            return
        if "x-mengos-merge" in node:
            out.append({"path": path, "schema": node, "raw": node["x-mengos-merge"]})
        props = node.get("properties")
        if is_obj(props):
            for name, sub in props.items():
                walk(sub, name if path == "" else f"{path}.{name}")
        if "items" in node:
            walk(node["items"], f"{path}[]")

    walk(schema, "")
    return out


def contribution_info(schema: Any):
    """贡献型判别：顶层 properties 恰一个带 x-mengos-base:true 且类型为 string，且至少一个可达标注。否则 None。"""
    if not is_obj(schema):
        return None
    props = schema.get("properties")
    if not is_obj(props):
        return None
    keys = [k for k, p in props.items() if is_obj(p) and p.get("x-mengos-base") is True]
    if len(keys) != 1 or props[keys[0]].get("type") != "string":
        return None
    return {"baseKey": keys[0]} if reachable_annotations(schema) else None


def base_slot_keys(schema: Any) -> list[str]:
    props = schema.get("properties") if is_obj(schema) else None
    if not is_obj(props):
        return []
    return [k for k, p in props.items() if is_obj(p) and p.get("x-mengos-base") is True]


def validate_annotations(schema: Any) -> dict:
    """标注合法性（TL-30a）。返回 {"ok": True} 或 {"ok": False, "path", "reason"}。"""
    for a in reachable_annotations(schema):
        p = "(根)" if a["path"] == "" else a["path"]
        raw = a["raw"]
        if not is_obj(raw):
            return {"ok": False, "path": p, "reason": "同一节点出现多个标注" if isinstance(raw, list) else "标注不是对象"}
        mode = raw.get("mode")
        if mode not in _MODES:
            return {"ok": False, "path": p, "reason": f"mode 非法: {mode}"}
        sch = a["schema"]
        is_arr = sch.get("type") == "array" or "items" in sch
        if mode in ("by-id", "append") and not is_arr:
            return {"ok": False, "path": p, "reason": f"{mode} 只能标在数组节点"}
        if mode == "named-lines":
            if sch.get("type") != "string":
                return {"ok": False, "path": p, "reason": "named-lines 只能标在字符串节点"}
            name = raw.get("name")
            if not isinstance(name, str):
                return {"ok": False, "path": p, "reason": "named-lines 缺 name"}
            try:
                groups = re.compile(name + "|", re.ASCII).groups
            except re.error:
                return {"ok": False, "path": p, "reason": "name 不是合法正则"}
            if groups != 1:
                return {"ok": False, "path": p, "reason": f"name 须恰一个捕获组 (实 {groups})"}
    return {"ok": True}


def _ann(schema: Any):
    if not is_obj(schema):
        return None
    raw = schema.get("x-mengos-merge")
    if not is_obj(raw) or raw.get("mode") not in _MODES:
        return None
    a = {"mode": raw["mode"]}
    if isinstance(raw.get("id"), str):
        a["id"] = raw["id"]
    if isinstance(raw.get("label"), str):
        a["label"] = raw["label"]
    if raw.get("fill") is True or isinstance(raw.get("fill"), str):
        a["fill"] = raw["fill"]
    if isinstance(raw.get("name"), str):
        a["name"] = raw["name"]
    return a


def _sub(schema: Any, key: str):
    if is_obj(schema) and is_obj(schema.get("properties")):
        return schema["properties"].get(key)
    return None


def _items(schema: Any):
    return schema.get("items") if is_obj(schema) else None


def _name_of(rx, line):
    m = rx.search(line)
    return None if m is None else (m.group(1) or "")


# ───────── 合并 ─────────
class MergeError(Exception):
    def __init__(self, instance_path: str, message: str):
        super().__init__(f"{instance_path} {message}")
        self.instance_path, self.message = instance_path, message


def _merge_annotated(schema, ann, P, D, path):
    if ann["mode"] == "named-lines":
        if not isinstance(D, str):
            raise MergeError(path, "合并类型不符: 增量不是字符串")
        if P is not _MISSING and not isinstance(P, str):
            raise MergeError(path, "合并类型不符: best 里不是字符串")
        rx = re.compile(ann.get("name", ""), re.ASCII)
        lines = [] if P is _MISSING or P == "" else P.split("\n")
        for line in ([] if D == "" else D.split("\n")):
            name = _name_of(rx, line)
            at = -1 if name is None else next((i for i, l in enumerate(lines) if _name_of(rx, l) == name), -1)
            if at >= 0:
                lines[at] = line
            else:
                lines.append(line)
        return "\n".join(lines)
    if not isinstance(D, list):
        raise MergeError(path, "合并类型不符: 增量不是数组")
    if P is not _MISSING and not isinstance(P, list):
        raise MergeError(path, "合并类型不符: best 里不是数组")
    out = [] if P is _MISSING else list(P)
    if ann["mode"] == "append":
        return out + list(D)
    id_key = ann.get("id", "id")
    for el in D:
        if not is_obj(el) or not isinstance(el.get(id_key), str):
            raise MergeError(path, "by-id 元素缺 id")
        at = next((i for i, x in enumerate(out) if is_obj(x) and x.get(id_key) == el[id_key]), -1)
        if at < 0:
            out.append(el)
            continue
        out[at] = _merge_object(_items(schema), out[at], el, f"{path}/{at}")
    return out


def _merge_object(schema, P, D, path):
    if not is_obj(P) or not is_obj(D):
        return D
    out = dict(P)
    for k, dv in D.items():
        if dv is None:
            out.pop(k, None)
            continue
        out[k] = _merge_node(_sub(schema, k), P[k] if k in P else _MISSING, dv, f"{path}/{k}")
    return out


def _merge_node(schema, P, D, path):
    ann = _ann(schema)
    if ann is not None:
        return _merge_annotated(schema, ann, P, D, path)
    if P is _MISSING:
        return _merge_object(schema, {}, D, path) if is_obj(D) else D
    return _merge_object(schema, P, D, path)


def merge(schema: Any, P: Any, delta: Any) -> Any:
    """合并错误抛 MergeError（引擎里是 {ok:false, instancePath, message}，调用方判 TOOL_FAILED）。入参不被改。"""
    import copy
    return _merge_object(schema, copy.deepcopy(P), copy.deepcopy(delta), "")


# ───────── 触及键 ─────────
def touched_keys(schema: Any, delta: Any) -> set[str]:
    out: set[str] = set()

    def walk(sch, v, prefix):
        ann = _ann(sch)
        if ann is None:
            if is_obj(v):
                for k, x in v.items():
                    walk(_sub(sch, k), x, k if prefix == "" else f"{prefix}.{k}")
            elif prefix != "":
                out.add(prefix)
            return
        if v is None:
            out.add(prefix)
            return
        if ann["mode"] == "append":
            out.add(f"{prefix}+" if isinstance(v, list) else prefix)
            return
        if ann["mode"] == "named-lines":
            if not isinstance(v, str) or "name" not in ann:
                out.add(prefix)
                return
            rx = re.compile(ann["name"], re.ASCII)
            for line in ([] if v == "" else v.split("\n")):
                name = _name_of(rx, line)
                out.add(f"{prefix}@{name}" if name is not None else f"{prefix}@+")
            return
        if not isinstance(v, list):
            out.add(prefix)
            return
        id_key = ann.get("id", "id")
        for el in v:
            if not is_obj(el) or not isinstance(el.get(id_key), str):
                continue
            pre = f"{prefix}#{el[id_key]}."
            others = [(k, x) for k, x in el.items() if k != id_key]
            if not others:
                out.add(pre)
            for k, x in others:
                walk(_sub(_items(sch), k), x, f"{pre}{k}")

    walk(schema, delta, "")
    return out


# ───────── 空槽与骨架 ─────────
def _is_empty(ann, el, id_key):
    if ann["fill"] is True:
        return all(k == id_key or k == ann.get("label") for k in el)
    return ann["fill"] not in el or el[ann["fill"]] == ""   # JSON null 不是"缺席"（TS: === undefined）


def empty_slots(schema: Any, args: Any) -> list[str]:
    out: list[str] = []

    def walk(sch, v, prefix):
        ann = _ann(sch)
        join = lambda k: k if prefix == "" else f"{prefix}.{k}"
        if ann is None:
            if is_obj(v):
                for k, x in v.items():
                    walk(_sub(sch, k), x, join(k))
            return
        if ann["mode"] == "by-id" and isinstance(v, list):
            id_key = ann.get("id", "id")
            for el in v:
                if not is_obj(el) or not isinstance(el.get(id_key), str):
                    continue
                here = f"{prefix}#{el[id_key]}"
                if "fill" in ann and _is_empty(ann, el, id_key):
                    out.append(here)
                for k, x in el.items():
                    if k in (id_key, ann.get("label"), ann.get("fill")):
                        continue
                    child = _sub(_items(sch), k)
                    if _ann(child) is not None:
                        walk(child, x, f"{here}.{k}")
        elif ann["mode"] == "named-lines" and isinstance(v, str) and "name" in ann:
            rx = re.compile(ann["name"], re.ASCII)
            for line in v.split("\n"):
                m = rx.search(line)
                if m is not None and line[m.end():].strip() == "":
                    out.append(f"{prefix}@{m.group(1) or ''}")

    walk(schema, args, "")
    return out


def _leaf(v):
    return {"$size": _utf8_len(canonical_json(v))}


def _skeleton_node(schema, value):
    ann = _ann(schema)
    if ann is not None and is_obj(schema):
        if ann["mode"] == "by-id":
            if not isinstance(value, list):
                return _leaf(value)
            id_key = ann.get("id", "id")
            rows = []
            for el in value:
                if not is_obj(el):
                    rows.append(_leaf(el))
                    continue
                row = {}
                if id_key in el:
                    row[id_key] = el[id_key]
                if "label" in ann and ann["label"] in el:
                    row["label"] = el[ann["label"]]
                if "fill" in ann:
                    row["empty"] = _is_empty(ann, el, id_key)
                for k, v in el.items():
                    if k in (id_key, ann.get("label"), ann.get("fill")):
                        continue
                    child = _sub(_items(schema), k)
                    if _ann(child) is not None:
                        row[k] = _skeleton_node(child, v)
                rows.append(row)
            return rows
        if ann["mode"] == "append":
            return {"$count": len(value)} if isinstance(value, list) else _leaf(value)
        if not isinstance(value, str) or "name" not in ann:
            return _leaf(value)
        rx = re.compile(ann["name"], re.ASCII)
        rows = []
        for line in value.split("\n"):
            m = rx.search(line)
            if m is None:
                continue
            rows.append({"empty": line[m.end():].strip() == "", "name": m.group(1) or ""})
        return rows
    if is_obj(value):
        return {k: _skeleton_node(_sub(schema, k), v) for k, v in value.items()}
    return _leaf(value)


def skeleton(schema: Any, args: Any, is_best: bool) -> str:
    body = _skeleton_node(schema, args)
    root = {**body, "$best": is_best} if is_obj(body) else {"$best": is_best, "value": body}
    return canonical_json(root)
