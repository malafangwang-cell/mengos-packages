#!/usr/bin/env python3
"""cad v2 · process 执行器入口（17 章 TL-8）

协议与 calc v2 相同：stdin 读一行 JSON，stdout 写一行 JSON。
  输入信封：{"tool": "cad.build", "payload": {...}, "budget": {"timeout_ms": 60000}, "workdir": "/abs/dir"}
           也接受裸载荷 + 命令行参数：cad_tool.py cad.build [--workdir DIR]
  输出：{"ok": true, "output": {...}}
       {"ok": false, "error": {"code": "BAD_INPUT|UNSUPPORTED|RESOURCE_LIMIT|TIMEOUT|INTERNAL", "message": "...", "line"?: n, "hint"?: "..."}}

文件产出（W0 探针 P14 的工具侧约定）：
  · 引擎每次调用给一个新建的空目录 workdir；执行体只往这里写，不读写别处。
  · 输出里的 files 列出每个文件：{path(相对 workdir), format, role, media_type, bytes, sha256}。
  · 引擎核对路径不越界、sha256 一致、大小在预算内，再收进 ObjectStore，回执里引用对象。
  · 文件与输出都是逐字节确定的：同一输入两次运行，output 相同，文件也相同（TL-12 ②）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sys

DEFAULT_TIMEOUT_MS = 60_000
MAX_PLAN_CHARS = 20_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TRIANGLES = 2_000_000
DEFAULT_FORMATS = ["step", "glb", "svg"]
ROLES = {"step": "model.exact", "glb": "model.view", "stl": "mesh.print", "3mf": "mesh.print",
         "svg": "drawing", "dxf": "drawing"}


class _Timeout(Exception):
    pass


class BadInput(Exception):
    def __init__(self, message, line=None, hint=None):
        super().__init__(message)
        self.line, self.hint = line, hint


class ResourceLimit(Exception):
    pass


def _on_alarm(signum, frame):
    raise _Timeout


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _fail(code: str, message: str, line=None, hint=None) -> dict:
    e = {"code": code, "message": message}
    if line is not None:
        e["line"] = line
    if hint:
        e["hint"] = hint
    return {"ok": False, "error": e}


# ---------------------------------------------------------------- 入参
def _plan(payload):
    plan = payload.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        raise BadInput("plan 必须是非空字符串（零件计划，一行一个操作）")
    if len(plan) > MAX_PLAN_CHARS:
        raise BadInput(f"plan 超过 {MAX_PLAN_CHARS} 个字符")
    return plan


def _name(payload):
    n = payload.get("name", "part")
    if not isinstance(n, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", n):
        raise BadInput("name 只能由字母、数字、下划线、连字符组成，1–64 个字符")
    return n


def _formats(payload, default):
    import geometry
    fs = payload.get("formats", default)
    if not isinstance(fs, list) or any(not isinstance(f, str) for f in fs):
        raise BadInput("formats 必须是字符串数组")
    bad = [f for f in fs if f not in geometry.FORMATS]
    if bad:
        raise BadInput(f"不支持的格式 {bad[0]}（可用：{', '.join(geometry.FORMATS)}）")
    out = []
    for f in fs:
        if f not in out:
            out.append(f)
    return out


def _allowed(payload, keys):
    extra = set(payload) - set(keys)
    if extra:
        raise BadInput(f"不认识的字段：{', '.join(sorted(extra))}")


def _build(plan):
    import builder
    from cad_dsl import DslError, parse
    try:
        return builder.build(parse(plan))
    except DslError as e:
        raise BadInput(e.message, e.line, e.hint) from None


def _features(res):
    from builder import face_owner
    count = {}
    for f in res.part.faces():
        o = face_owner(f, res.features)
        count[o] = count.get(o, 0) + 1
    return [{"id": f.id, "op": f.op, "line": f.line, "src": f.src, "faces": count.get(f.id, 0)} for f in res.features]


# ---------------------------------------------------------------- 特征表与全行表（2.6.0，局部修改用）
DECLARATION_OPS = ("units", "material", "let")
MODIFIER_OPS = ("fillet", "chamfer", "shell")
COPY_OPS = ("pattern", "mirror")
GLOBAL_EDGES = ("all", "vertical", "top", "bottom", "front", "back", "left", "right")


def _line_kind(op):
    if op in DECLARATION_OPS:
        return "declaration"
    if op in MODIFIER_OPS:
        return "modifier"
    if op in COPY_OPS:
        return "copy"
    return "feature"


def _code_tokens(raw, ln=0):
    """一行的代码部分（去注释、规范化记号）→ (名字, 操作, 其余记号)；空行与注释行返回 None。只在计划已解析通过后调用。"""
    from cad_dsl import _engineering, _normalize, _tokenize
    s = _engineering(_normalize(raw).split("#", 1)[0]).strip()
    if not s:
        return None
    toks = _tokenize(s, ln)
    name = None
    if len(toks) >= 2 and toks[0][0] == "word" and toks[1][1] == ":":
        name, toks = toks[0][1], toks[2:]
    return name, toks[0][1].lower(), toks[1:]


def _scope(f):
    """作用范围（K12）：抽壳、按 all / vertical / 面名选边的圆角与倒角作用到整件，为 global；其余为 local。"""
    if f.op == "shell":
        return "global"
    if f.op in ("fillet", "chamfer") and f.params.get("edges") in GLOBAL_EDGES:
        return "global"
    return "local"


def _refs(f, ids):
    """本行显式引用的特征名（K6）：edges=名、pattern 名、mirror 名。隐式依赖不在内，只是下限。"""
    if f.op in ("fillet", "chamfer"):
        e = f.params.get("edges")
        return [e] if e in ids and e not in GLOBAL_EDGES else []
    if f.op in COPY_OPS:
        return [f.params["of"]]
    return []


def _feature_table(res):
    """特征表：2.5.2 的五个字段照旧，另加 selectable、why_not、face_digest、uncertain_faces、refs、referenced_by、scope、group。"""
    from builder import face_owner, key_is_uncertain, face_key_text, surface_key
    count, digest, uncertain = {}, {}, {}
    for f in res.part.faces():
        o = face_owner(f, res.features)
        count[o] = count.get(o, 0) + 1
        key = surface_key(f)
        digest.setdefault(o, []).append([face_key_text(key), round(f.area, 3) + 0.0])
        if key_is_uncertain(key):
            uncertain[o] = uncertain.get(o, 0) + 1
    ids = {f.id for f in res.features}
    refs = {f.id: _refs(f, ids) for f in res.features}
    out = []
    for f in res.features:
        named = "#" not in f.id
        item = {"id": f.id, "op": f.op, "line": f.line, "src": f.src, "faces": count.get(f.id, 0),
                "selectable": named, "face_digest": sorted(digest.get(f.id, [])),
                "uncertain_faces": uncertain.get(f.id, 0), "refs": refs[f.id],
                "referenced_by": [g.id for g in res.features if f.id in refs[g.id]], "scope": _scope(f)}
        if not named:
            item["why_not"] = "unnamed"
        if f.op in COPY_OPS:
            item["group"] = {"kind": f.op, "source": f.params["of"], "instances": len(f.copies) + 1}
        out.append(item)
    return out


def _lines(plan, features):
    """全行表（K2、K11）：计划里每一行一项，行号与解析器一致。"""
    from cad_dsl import _normalize
    by_line = {f["line"]: f for f in features}
    out = []
    for ln, raw in enumerate(_normalize(plan).splitlines(), 1):
        ct = _code_tokens(raw, ln)
        if ct is None:
            out.append({"line": ln, "kind": "comment", "selectable": False, "why_not": "comment"})
            continue
        name, op, _ = ct
        item = {"line": ln, "kind": _line_kind(op), "op": op}
        if name:
            item["name"] = name
        if item["kind"] == "declaration":
            item.update(selectable=False, why_not="declaration")
        else:
            f = by_line[ln]
            item.update(feature_id=f["id"], selectable=f["selectable"], scope=f["scope"])
            if "why_not" in f:
                item["why_not"] = f["why_not"]
        out.append(item)
    return out


def _unnamed_warnings(features):
    return [{"line": f["line"], "code": "unnamed_feature", "feature": f["id"],
             "message": f"{f['op']} 没有名字（界面上叫 {f['id']}）；特征行都要写名字，"
                        f"例如 {f['op']}1: {f['op']} …，否则以后不能单独改这一行"}
            for f in features if "why_not" in f]


def _write_files(res, formats, name, workdir, meta, mesh):
    import geometry
    if not formats:
        return []
    if not workdir:
        raise BadInput("要产出文件时必须提供 workdir（引擎为每次调用新建的空目录）")
    if not os.path.isabs(workdir) or not os.path.isdir(workdir):
        raise BadInput("workdir 必须是已存在目录的绝对路径")
    files = []
    for fmt in formats:
        data = geometry.export(res, fmt, mesh, meta)
        if len(data) > MAX_FILE_BYTES:
            raise ResourceLimit(f"{fmt} 文件超过 {MAX_FILE_BYTES // 1024 // 1024} MB")
        media, ext = geometry.FORMATS[fmt]
        rel = name + ext
        path = os.path.join(workdir, rel)
        with open(path, "wb") as fh:
            fh.write(data)
        files.append({"path": rel, "format": fmt, "role": ROLES[fmt], "media_type": media,
                      "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    return files


def _mesh_if_needed(res, formats, need):
    import geometry
    if not need and not any(f in ("glb", "stl", "3mf") for f in formats):
        return None
    mesh = geometry.tessellate(res)
    if mesh["n_tri"] > MAX_TRIANGLES:
        raise ResourceLimit(f"网格超过 {MAX_TRIANGLES} 个三角形")
    return mesh


# ---------------------------------------------------------------- 建模三件
def cad_build(payload, workdir=None):
    """计划 → 零件：测量值、特征表、警告，以及请求的文件（缺省 STEP + GLB + SVG 三视图）。"""
    import geometry
    _allowed(payload, ["plan", "name", "formats"])
    plan, name = _plan(payload), _name(payload)
    formats = _formats(payload, DEFAULT_FORMATS)
    res = _build(plan)
    sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    mesh = _mesh_if_needed(res, formats, need=True)
    meas = geometry.measure(res, mesh)
    meta = {"name": name, "plan_sha": sha}
    feats = _feature_table(res)
    return {
        "name": name, "plan_sha256": sha, "measure": meas, "features": feats,
        "warnings": res.warnings + _unnamed_warnings(feats), "files": _write_files(res, formats, name, workdir, meta, mesh),
        "lines": _lines(plan, feats),
        "part": {"material": meas["material"], "density": meas["density_g_cm3"], "mass": meas["mass_g"]},
    }


def cad_check(payload, workdir=None):
    """计划 + 期望清单 → 每条 pass / fail / unknown 与总判定。不产出文件。"""
    import geometry
    from cad_dsl import DslError
    from checker import overall, run_checks
    _allowed(payload, ["plan", "expect"])
    plan = _plan(payload)
    expect = payload.get("expect")
    if not isinstance(expect, str) or not expect.strip():
        raise BadInput("expect 必须是非空字符串（期望清单，一行一条）")
    res = _build(plan)
    need_mesh = bool(re.search(r"(?m)^\s*watertight\b", expect))
    meas = geometry.measure(res, _mesh_if_needed(res, [], need_mesh))
    try:
        checks = run_checks(expect, meas, _features(res))
    except DslError as e:
        raise BadInput("期望清单：" + e.message, e.line, e.hint) from None
    v = overall(checks)
    return {"verdict": v, "covered": v != "unknown", "checks": checks,
            "plan_sha256": hashlib.sha256(plan.encode("utf-8")).hexdigest()}


def _plan_from_object(obj):
    """导出工具的通用入参 object：cad.build 产出的规范对象（产出记录），计划取自其 args.plan。"""
    if not isinstance(obj, dict):
        raise BadInput("object 应当是要导出的三维模型（JSON 对象）")
    if obj.get("tool") not in (None, "cad.build"):
        raise BadInput("object 不是三维模型，导不出零件文件")
    args = obj.get("args")
    if not isinstance(args, dict) or not isinstance(args.get("plan"), str):
        raise BadInput("object 里没有建模计划：只能导出按建模计划建出的零件")
    return args["plan"]


def cad_export(payload, workdir=None):
    """计划（或 cad.build 的产出记录）→ 指定格式的文件。"""
    _allowed(payload, ["plan", "object", "name", "formats", "format"])
    if ("plan" in payload) == ("object" in payload):
        raise BadInput("plan 与 object 二选一：给建模计划，或给要导出的三维模型")
    plan = _plan(payload) if "plan" in payload else _plan({"plan": _plan_from_object(payload["object"])})
    name = _name(payload)
    if "format" in payload:
        if "formats" in payload:
            raise BadInput("format 与 formats 二选一")
        payload = dict(payload, formats=[payload["format"]] if isinstance(payload["format"], str) else payload["format"])
    formats = _formats(payload, [])
    if not formats:
        raise BadInput("formats 不能为空")
    res = _build(plan)
    sha = hashlib.sha256(plan.encode("utf-8")).hexdigest()
    mesh = _mesh_if_needed(res, formats, need=False)
    return {"name": name, "plan_sha256": sha,
            "files": _write_files(res, formats, name, workdir, {"name": name, "plan_sha": sha}, mesh)}


# ---------------------------------------------------------------- 比较（2.6.0，K5、K11、K14）
PART_KEYS = ("material", "density", "mass")
REBUILD_HINT = "先用当前版本的 cad.build 把这份计划重建一次，取新的特征表再比"


def _table(payload, key):
    t = payload.get(key)
    what = "旧" if key == "old" else "新"
    if not isinstance(t, dict) or not isinstance(t.get("features"), list):
        raise BadInput(f"{key} 应当是{what}特征表：cad.build 的产出（含 features 与 part）")
    feats = {}
    for f in t["features"]:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str) or not isinstance(f.get("src"), str):
            raise BadInput(f"{key}.features 的每一项要有 id 与 src")
        if not isinstance(f.get("face_digest"), list):
            raise BadInput(f"{what}特征表里的特征 {f['id']} 没有面摘要（face_digest），是旧版本建的", hint=REBUILD_HINT)
        if f["id"] in feats:
            raise BadInput(f"{key}.features 里特征 {f['id']} 出现了两次")
        feats[f["id"]] = f
    part = t.get("part")
    if not isinstance(part, dict) or any(k not in part for k in PART_KEYS):
        raise BadInput(f"{what}特征表没有零件级属性 part（material、density、mass），是旧版本建的", hint=REBUILD_HINT)
    return feats, part


def _params(src):
    """计划行 → (操作, [(参数名, 原样的值)])。键=值 的参数名为键，位置参数为 arg1、arg2…；值取计划行里的写法，去掉空白。"""
    ct = _code_tokens(src)
    if ct is None:
        return None, []
    _, op, toks = ct
    out, i, npos = [], 0, 0

    def atom(j):
        if toks[j][1] == "(":
            depth = 0
            while j < len(toks):
                depth += {"(": 1, ")": -1}.get(toks[j][1], 0)
                j += 1
                if depth == 0:
                    break
            return j
        return j + 1

    def value(j):
        while j < len(toks) and toks[j][1] in ("+", "-"):
            j += 1
        j = atom(j) if j < len(toks) else j
        while j < len(toks) and toks[j][1] in ("+", "-", "*", "/", "%"):
            j += 1
            while j < len(toks) and toks[j][1] in ("+", "-"):
                j += 1
            j = atom(j) if j < len(toks) else j
        return j

    while i < len(toks):
        if toks[i][0] == "word" and i + 1 < len(toks) and toks[i + 1][1] == "=":
            key, start = toks[i][1].lower(), i + 2
        else:
            npos += 1
            key, start = f"arg{npos}", i
        i = value(start)
        out.append((key, "".join(v for _, v in toks[start:i])))
    return op, out


def _param_diffs(name, a, b):
    (op_a, pa), (op_b, pb) = _params(a), _params(b)
    out = []
    if op_a != op_b:
        out.append({"name": name, "param": "op", "before": op_a, "after": op_b})
    da, db = dict(pa), dict(pb)
    for k in [k for k, _ in pa] + [k for k, _ in pb if k not in da]:
        if da.get(k) != db.get(k):
            out.append({"name": name, "param": k, "before": da.get(k), "after": db.get(k)})
    return out


def _same_line(a, b):
    return _params(a) == _params(b)


def cad_compare(payload, workdir=None):
    """两份特征表 → 改了 / 随动 / 被修剪 / 新增 / 删去，零件级属性的变化与逐行参数差。不建模，不读几何。"""
    _allowed(payload, ["old", "new"])
    old, old_part = _table(payload, "old")
    new, new_part = _table(payload, "new")
    changed, followed, trimmed, diffs = [], [], [], []
    for fid, f in new.items():
        g = old.get(fid)
        if g is None:
            continue
        if not _same_line(g["src"], f["src"]):
            changed.append(fid)
            diffs += _param_diffs(fid, g["src"], f["src"])
        elif {k for k, _ in g["face_digest"]} != {k for k, _ in f["face_digest"]}:
            followed.append(fid)
        elif sorted(map(tuple, g["face_digest"])) != sorted(map(tuple, f["face_digest"])):
            trimmed.append(fid)
    part_changed = [k for k in ("material", "density") if old_part[k] != new_part[k]]
    if old_part["mass"] != new_part["mass"] and (part_changed or (old_part["mass"] is None) != (new_part["mass"] is None)):
        part_changed.append("mass")
    return {"changed": changed, "followed": followed, "trimmed": trimmed,
            "added": [k for k in new if k not in old], "removed": [k for k in old if k not in new],
            "part_changed": part_changed, "param_diffs": diffs}


TOOLS = {"cad.build": cad_build, "cad.check": cad_check, "cad.export": cad_export, "cad.compare": cad_compare}


def run(envelope, tool_from_argv=None, workdir_from_argv=None) -> dict:
    if not isinstance(envelope, dict):
        return _fail("BAD_INPUT", "输入必须是 JSON 对象")
    if "tool" in envelope and "payload" in envelope:
        tool, payload = envelope["tool"], envelope["payload"]
        budget, workdir = envelope.get("budget") or {}, envelope.get("workdir")
    else:
        tool, payload, budget, workdir = tool_from_argv, envelope, {}, workdir_from_argv
    fn = TOOLS.get(tool)
    if fn is None:
        return _fail("BAD_INPUT", f"未知工具 {tool!r}（可用：{', '.join(sorted(TOOLS))}）")
    if not isinstance(payload, dict):
        return _fail("BAD_INPUT", "payload 必须是 JSON 对象")
    timeout_ms = budget.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    try:
        timeout_s = max(0.05, float(timeout_ms) / 1000 * 0.9)
    except (TypeError, ValueError):
        timeout_s = DEFAULT_TIMEOUT_MS / 1000
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return {"ok": True, "output": fn(payload, workdir)}
    except _Timeout:
        return _fail("TIMEOUT", f"超过 {timeout_ms} ms")
    except BadInput as e:
        return _fail("BAD_INPUT", str(e), e.line, e.hint)
    except ResourceLimit as e:
        return _fail("RESOURCE_LIMIT", str(e))
    except RecursionError:
        return _fail("RESOURCE_LIMIT", "嵌套过深")
    except Exception as exc:  # noqa: BLE001 —— 基础设施层异常如实上报
        return _fail("INTERNAL", f"{type(exc).__name__}: {exc}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def _pin_hash_seed() -> None:
    """ezdxf 内部有按字符串哈希排序的容器，DXF 对象顺序随 PYTHONHASHSEED 变化。
    固定种子后重启自身一次（在导入几何库之前，开销约 30 ms），保证文件逐字节确定。"""
    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ, PYTHONHASHSEED="0")
        os.execve(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env)


def main() -> int:
    _pin_hash_seed()
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
