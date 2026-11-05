#!/usr/bin/env python3
"""mathdisc · process 执行器入口（17 章 TL-8；协议与 probe、cad、calc、document 相同）。

stdin 读一行 JSON，stdout 写一行 JSON：
  输入信封：{"tool": "mathdisc.reach", "payload": {...}, "budget": {"timeout_ms": 30000}, "workdir"?: "/abs/dir"}
  输出：{"ok": true, "output": {...}}
       {"ok": false, "error": {"code": "BAD_INPUT|UNSUPPORTED|RESOURCE_LIMIT|TIMEOUT|INTERNAL", "message": "...", "hint"?: "..."}}

前六件工具零模型调用、确定性；mathdisc.discover 是第七件：异步、出网调一个模型（凭据只从环境变量读，主机只有
dashscope.aliyuncs.com）、信任类 T3，产物是候选，不是结论。判定类回执是三值（established / refuted / undetermined，另有 rejected）；
达不到证明级的结论在 output.assumptions 里逐条声明（17 TL-22a），
只在有限范围内核验过的结论另带 output.validity（适用范围，产出台规范 §3）。判定类工具到点未判完，回 undetermined，不报错。
"""
from __future__ import annotations

import json
import signal
import sys
import time
from fractions import Fraction

DEFAULT_TIMEOUT_MS = 30_000
DISCOVER_TIMEOUT_MS = 600_000
TOOLS = ("mathdisc.identity", "mathdisc.formula", "mathdisc.recurrence", "mathdisc.reach",
         "mathdisc.counterexample", "mathdisc.solve_closed", "mathdisc.discover")
CHECKS = {"mathdisc.identity", "mathdisc.formula", "mathdisc.recurrence", "mathdisc.reach",
          "mathdisc.counterexample"}


class _Timeout(BaseException):
    """到点信号。继承 BaseException：发现循环里的模型客户端对 Exception 做重试，不能把到点吞掉。"""


class BadInput(Exception):
    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


def _on_alarm(signum, frame):
    raise _Timeout


def _emit(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _fail(code, message, hint=None) -> dict:
    e = {"code": code, "message": message}
    if hint:
        e["hint"] = hint
    return {"ok": False, "error": e}


def _allowed(payload, keys):
    extra = set(payload) - set(keys)
    if extra:
        raise BadInput(f"不认识的字段：{', '.join(sorted(extra))}")


def _need(payload, key, kind, what):
    if key not in payload:
        raise BadInput(f"缺少 {key}（{what}）")
    v = payload[key]
    if not isinstance(v, kind) or isinstance(v, bool):
        raise BadInput(f"{key} 的类型不对（{what}）")
    return v


def _jsonable(o):
    if isinstance(o, Fraction):
        return str(o)
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (str, int, bool)) or o is None:
        return o
    if isinstance(o, float):
        return o if o == o and o not in (float("inf"), float("-inf")) else str(o)
    return str(o)


# ---------------------------------------------------------------- 适用范围与假设（TL-22a；产出台规范 §3）
# 结论只在有限范围内核验过时，输出带 validity（适用范围），assumptions 把范围写进句子。
# 证明级与精确算术的结论不带 validity：对整个定义域成立。
OUTSIDE_DATA = "范围外是外推，离开数据范围越远，可信度越低"


def _n(v) -> str:
    """数值的紧凑写法：整数照写，其余 6 位有效数字。"""
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) < 1e15):
        return str(int(v))
    return f"{v:.6g}"


def _ranges(rs) -> str:
    return "、".join(f"{r['name']} ∈ [{_n(r['min'])}, {_n(r['max'])}]" for r in rs)


def _formula_validity(train: dict, hold_cols: dict, ev: dict, cut: int, n: int) -> dict:
    names = sorted(k for k in train if k != "y")
    core = [{"name": k, "min": min(train[k]), "max": max(train[k])} for k in names]
    checked = [{"name": k, "min": min(hold_cols[k]), "max": max(hold_cols[k])} for k in names]
    v = {"basis": "data_range", "core": core, "checked": checked,
         "rows": {"train": cut, "holdout": n - cut},
         "error": {k: ev[k] for k in ("train_rel_rmse", "holdout_rel_rmse") if k in ev},
         "outside": OUTSIDE_DATA}
    if len(names) > 1:
        v["note"] = "多个变量时只给逐变量的范围；范围框内没有数据的角落同样未经核验"
    return v


def _formula_assumption(v: dict) -> str:
    return (f"数据级验证：在 {_ranges(v['core'])}（{v['rows']['train']} 行）内拟合，"
            f"保留的 {v['rows']['holdout']} 行（{_ranges(v['checked'])}）核验通过；"
            f"{v['outside']}；未经证明")


def _identity_validity(ev: dict):
    pt = ev.get("sample_point") or {}
    if not pt:
        return None
    return {"basis": "sample_points", "points": [pt], "outside": "只在这些取值上比对过；其他取值未核验"}


def _identity_assumption(ev: dict, v) -> str:
    digits = str(ev.get("grade", ""))[len("verified@"):]
    if v is None:
        return f"数值验证：在 {digits} 位精度上一致，未经符号证明"
    at = "，".join(f"{k} = {x}" for k, x in v["points"][0].items())
    return f"数值验证：在 {at} 处以 {digits} 位精度一致，其他取值未核验，未经符号证明"


def _recurrence_validity(known: list, hold: list) -> dict:
    k, h = len(known), len(hold)
    v = {"basis": "index_range", "core": {"from": 1, "to": k},
         "outside": f"第 {k + h} 项之后未核验"}
    if h:
        v["checked"] = {"from": k + 1, "to": k + h}
    return v


def _recurrence_assumption(v: dict) -> str:
    c = v["core"]
    s = f"序列级验证：在第 {c['from']}–{c['to']} 项上逐项精确复现"
    if "checked" in v:
        s += f"，保留的第 {v['checked']['from']}–{v['checked']['to']} 项盲测一致"
    return s + f"；{v['outside']}，未经证明"


def _receipt(r) -> dict:
    ev = _jsonable(r.evidence)
    return {"verdict": r.verdict, "method_complete": bool(r.method_complete), "evidence": ev,
            "versions": _jsonable(r.versions), "assumptions": []}


def _undetermined(reason: str) -> dict:
    return {"verdict": "undetermined", "method_complete": False,
            "evidence": {"grade": "none", "reason": reason}, "versions": {}, "assumptions": []}


# ---------------------------------------------------------------- 各件
def _identity(p):
    from mathdisc.check.identity import check_identity
    from mathdisc.expr.grammar import parse
    _allowed(p, ("lhs", "rhs", "digits", "try_symbolic"))
    lhs = _need(p, "lhs", str, "左边的表达式")
    rhs = _need(p, "rhs", str, "右边的表达式")
    dps = p.get("digits", 50)
    if not isinstance(dps, int) or isinstance(dps, bool) or not 16 <= dps <= 2000:
        raise BadInput("digits 是 16–2000 的整数（数值比对的十进制位数）")
    ts = p.get("try_symbolic", True)
    if not isinstance(ts, bool):
        raise BadInput("try_symbolic 是布尔值")
    out = _receipt(check_identity(parse(lhs), parse(rhs), declared_dps=dps, try_symbolic=ts))
    ev = out["evidence"]
    if out["verdict"] == "established" and str(ev.get("grade", "")).startswith("verified@"):
        v = _identity_validity(ev)
        if v is not None:
            out["validity"] = v
        out["assumptions"] = [_identity_assumption(ev, v)]
    return out


def _formula(p):
    from mathdisc.check.formula import check_formula
    _allowed(p, ("form", "columns", "holdout_ratio", "k_max", "seed"))
    form = _need(p, "form", str, "含参数 c1, c2… 的候选公式")
    cols = _need(p, "columns", dict, "数据表：变量列与响应列 y")
    for k, v in cols.items():
        if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            raise BadInput(f"列 {k} 是非空的数字数组")
    if "y" not in cols:
        raise BadInput("columns 里要有响应列 y")
    n = len(cols["y"])
    if any(len(v) != n for v in cols.values()):
        raise BadInput("各列长度相同（按行对齐）")
    ratio = p.get("holdout_ratio", 0.25)
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0.1 <= ratio <= 0.5:
        raise BadInput("holdout_ratio 取 0.1–0.5")
    cut = max(1, int(n * (1 - ratio)))
    if cut >= n:
        raise BadInput("数据行太少，留不出保留行", hint="至少 4 行")
    train = {k: [float(x) for x in v[:cut]] for k, v in cols.items()}
    hold = ({k: [float(x) for x in v[cut:]] for k, v in cols.items() if k != "y"}, [float(x) for x in cols["y"][cut:]])
    seed = p.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise BadInput("seed 是整数")
    k_max = p.get("k_max")
    if k_max is not None and (not isinstance(k_max, int) or isinstance(k_max, bool) or k_max < 0):
        raise BadInput("k_max 是非负整数")
    r = _receipt(check_formula(form=form, data=train, holdout=hold, seed=seed, k_max=k_max))
    r["split"] = {"train_rows": cut, "holdout_rows": n - cut}
    if r["verdict"] == "established":
        v = _formula_validity(train, hold[0], r["evidence"], cut, n)
        r["validity"] = v
        r["assumptions"] = [_formula_assumption(v)]
    return r


def _ints(v, key, what, allow_empty=False):
    if not isinstance(v, list) or (not v and not allow_empty) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
        raise BadInput(f"{key} 是{'' if allow_empty else '非空的'}整数数组（{what}）")
    return v


def _recurrence(p):
    from mathdisc.check.recurrence import check_recurrence
    _allowed(p, ("relation", "known", "holdout"))
    rel = _need(p, "relation", str, "用 a[n-1]、a[n-2]… 与 n 写出 a[n]")
    known = _ints(p.get("known"), "known", "已知项 a[1], a[2], …")
    hold = _ints(p.get("holdout", []), "holdout", "紧接已知项之后的保留项", allow_empty=True)
    out = _receipt(check_recurrence(relation=rel, known=known, holdout=hold))
    if out["verdict"] == "established":
        v = _recurrence_validity(known, hold)
        out["validity"] = v
        out["assumptions"] = [_recurrence_assumption(v)]
    return out


def _target(v):
    if isinstance(v, bool):
        raise BadInput("target 是整数或 'p/q' 形式的分数")
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        try:
            return Fraction(v)
        except (ValueError, ZeroDivisionError):
            pass
    raise BadInput("target 是整数或 'p/q' 形式的分数")


def _reach(p):
    from mathdisc.check.reach import check_reach
    _allowed(p, ("expr", "target"))
    expr = _need(p, "expr", str, "只含数字与 + - * / ** 的算式")
    if "target" not in p:
        raise BadInput("缺少 target")
    return _receipt(check_reach(expr, _target(p["target"])))


def _counterexample(p):
    from mathdisc.check.counterex import check_counterexample
    _allowed(p, ("conjecture", "witness"))
    conj = _need(p, "conjecture", str, "形如 isprime(<整数表达式>) 的猜想")
    w = _need(p, "witness", dict, "变量到整数的取值")
    for k, v in w.items():
        if not isinstance(v, int) or isinstance(v, bool):
            raise BadInput(f"witness 的 {k} 是整数")
    return _receipt(check_counterexample(conjecture=conj, witness=w))


def _solve_closed(p):
    from mathdisc.loop.solve_closed import solve_closed
    _allowed(p, ("numbers", "ops", "target"))
    nums = _ints(p.get("numbers"), "numbers", "参与运算的数，每个恰用一次")
    if len(nums) > 6:
        raise BadInput("numbers 至多 6 个")
    ops = p.get("ops", ["+", "-", "*", "/"])
    if not isinstance(ops, list) or not ops or not set(ops) <= {"+", "-", "*", "/"}:
        raise BadInput("ops 取自 + - * /")
    t = p.get("target")
    if not isinstance(t, int) or isinstance(t, bool):
        raise BadInput("target 是整数")
    r = solve_closed(nums, ops, t)
    return {"solvable": bool(r["solvable"]), "expr": r["expr"], "proof": r["proof"]}


def _discover_data(f_task, p):
    """discover 的 data：formula 为列字典（含响应列 y），recurrence 为整数数列或 {known, holdout}。"""
    data = p.get("data")
    if f_task == "formula":
        if not isinstance(data, dict):
            raise BadInput("formula 的 data 是数据表：变量列与响应列 y")
        for k, v in data.items():
            if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
                raise BadInput(f"列 {k} 是非空的数字数组")
        if "y" not in data:
            raise BadInput("data 里要有响应列 y")
        n = len(data["y"])
        if n < 4 or n > 2000 or any(len(v) != n for v in data.values()):
            raise BadInput("各列等长，行数 4–2000")
        if not 2 <= len(data) <= 9:
            raise BadInput("1–8 个变量列加响应列 y")
        return {k: [float(x) for x in v] for k, v in data.items()}
    if isinstance(data, list):
        return {"known": _ints(data, "data", "数列 a[1], a[2], …"), "holdout": []}
    if isinstance(data, dict):
        _allowed(data, ("known", "holdout"))
        return {"known": _ints(data.get("known"), "data.known", "已知项"),
                "holdout": _ints(data.get("holdout", []), "data.holdout", "保留项", allow_empty=True)}
    raise BadInput("recurrence 的 data 是整数数列，或 {known, holdout}")


DISCOVER_OPS = {"+", "-", "*", "/", "**"}


def _discover(p):
    from mathdisc.adapter_projection import project_ta_receipt
    from mathdisc.discover import run_solve
    _allowed(p, ("f_task", "vars", "data", "holdout", "ops", "n_max", "budget"))
    f_task = p.get("f_task")
    if f_task not in ("formula", "recurrence"):
        raise BadInput("f_task 取 formula 或 recurrence")
    names = p.get("vars", [])
    if not isinstance(names, list) or len(names) > 8 or not all(isinstance(x, str) and x for x in names):
        raise BadInput("vars 是变量名数组（至多 8 个）")
    data = _discover_data(f_task, p)
    if f_task == "formula":
        if not names:
            names = sorted(k for k in data if k != "y")
        if set(names) != {k for k in data if k != "y"}:
            raise BadInput("vars 要与 data 里的变量列一一对应")
    ratio = p.get("holdout", 0.25)
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0.1 <= ratio <= 0.5:
        raise BadInput("holdout 取 0.1–0.5")
    ops = p.get("ops", ["+", "-", "*", "/", "**"])
    if not isinstance(ops, list) or not ops or not set(ops) <= DISCOVER_OPS:
        raise BadInput("ops 取自 + - * / **")
    n_max = p.get("n_max", 4)
    budget = p.get("budget", 6)
    for key, val, hi in (("n_max", n_max, 8), ("budget", budget, 24)):
        if not isinstance(val, int) or isinstance(val, bool) or not 1 <= val <= hi:
            raise BadInput(f"{key} 是 1–{hi} 的整数")
    try:
        result, _ = run_solve(f_task, names, ops, data, ratio, budget, n_max)
    except RuntimeError as e:  # 钥匙缺席、模型调用用尽重试：如实报错，不降级、不冒充没找到
        return _fail("INTERNAL", f"RuntimeError: {e}")
    loop_result = {
        "stop": result.stop,
        "relations": [{"expr": r.expr, "receipt": {k: v for k, v in _receipt(r.receipt).items() if k != "assumptions"}}
                      for r in result.relations],
        "metrics": result.metrics,
    }
    # 适用范围：与同步判定工具同一口径，按检查门实际用的拆分与数据算；检查门回执本身不带，这里不改它
    for rel in loop_result["relations"]:
        v = _discover_validity(f_task, data, ratio, rel["receipt"]["evidence"])
        if v is not None:
            rel["validity"] = v
    return {"ok": True, "output": _jsonable(project_ta_receipt(loop_result))}


def _discover_validity(f_task, data, ratio, ev):
    if f_task == "formula":
        n = len(data["y"])
        cut = max(1, int(n * (1 - ratio)))
        train = {k: v[:cut] for k, v in data.items()}
        hold = {k: v[cut:] for k, v in data.items() if k != "y"}
        return _formula_validity(train, hold, ev, cut, n)
    if f_task == "recurrence":
        return _recurrence_validity(data["known"], data["holdout"])
    return None


HANDLERS = {
    "mathdisc.identity": _identity, "mathdisc.formula": _formula, "mathdisc.recurrence": _recurrence,
    "mathdisc.reach": _reach, "mathdisc.counterexample": _counterexample,
    "mathdisc.solve_closed": _solve_closed,
    "mathdisc.discover": _discover,
}


def run(env: dict) -> dict:
    if not isinstance(env, dict):
        return _fail("BAD_INPUT", "信封不是 JSON 对象")
    tool = env.get("tool")
    if tool not in HANDLERS:
        return _fail("UNSUPPORTED", f"不认识的工具：{tool}")
    payload = env.get("payload")
    if not isinstance(payload, dict):
        return _fail("BAD_INPUT", "payload 不是 JSON 对象")
    budget = env.get("budget") or {}
    default_ms = DISCOVER_TIMEOUT_MS if tool == "mathdisc.discover" else DEFAULT_TIMEOUT_MS
    timeout_ms = budget.get("timeout_ms", default_ms) if isinstance(budget, dict) else default_ms
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        timeout_ms = default_ms
    # 判定类工具在预算的八成处停手，回 undetermined；其余到点报 TIMEOUT
    soft = max(0.2, timeout_ms * 0.8 / 1000)
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, soft)
    t0 = time.monotonic()
    try:
        out = HANDLERS[tool](payload)
        if tool == "mathdisc.discover":
            return out  # _discover 自带信封（成功或结构化错误）
        return {"ok": True, "output": out}
    except _Timeout:
        if tool == "mathdisc.discover":
            # 到点未跑完：回 undetermined，不报错、不拿半截结果冒充三态
            return {"ok": True, "output": {
                "stop_reason": "undetermined", "relations": [], "assumptions": [],
                "cost": {"rounds": None, "rho_calls": None}, "relation_receipts": []}}
        if tool in CHECKS:
            return {"ok": True, "output": _undetermined(f"到点未判完（{round(time.monotonic() - t0, 2)} 秒）")}
        return _fail("TIMEOUT", "到点未算完")
    except BadInput as e:
        return _fail("BAD_INPUT", str(e), e.hint)
    except Exception as e:  # noqa: BLE001
        from mathdisc.expr.grammar import GrammarError
        if isinstance(e, (GrammarError, ValueError, KeyError, TypeError, ZeroDivisionError, RecursionError)):
            # mathdisc 内部的文法拒与契约拒
            return _fail("BAD_INPUT", f"{type(e).__name__}: {e}")
        if isinstance(e, MemoryError):
            return _fail("RESOURCE_LIMIT", "内存不足")
        return _fail("INTERNAL", f"{type(e).__name__}: {e}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> int:
    line = sys.stdin.readline()
    try:
        env = json.loads(line)
    except json.JSONDecodeError:
        _emit(_fail("BAD_INPUT", "stdin 第一行不是 JSON"))
        return 0
    _emit(run(env))
    return 0


if __name__ == "__main__":
    sys.exit(main())
