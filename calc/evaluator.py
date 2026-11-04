"""calc v2 · 求值器

两条路：
  1. 有理数快路：只用 Python 的 int / Fraction，不导入 sympy。覆盖 + - * / ^（整数指数）、
     ! % mod gcd lcm abs floor ceil max min binomial perm，以及完全平方数的 sqrt。
     绝大多数"算一个数"的请求走这条路，单次进程约几十毫秒。
  2. sympy 路：遇到无理数、常数、三角、对数、符号运算时才导入 sympy（约 0.3 秒）。

两条路都是精确计算：小数字面量按十进制精确转成有理数（0.1 = 1/10），不经过浮点。
"""

from __future__ import annotations

import math
from decimal import Decimal, localcontext
from fractions import Fraction

from expr_parser import ParseError, parse

MAX_DIGITS = 100_000      # 结果位数上限
MAX_FACTORIAL = 5_000


class ResourceLimit(ValueError):
    """结果规模超限；回执 code=RESOURCE_LIMIT。"""


class Unsupported(ValueError):
    """超出本工具能力；回执 code=UNSUPPORTED。"""


class _NeedSympy(Exception):
    pass


# --------------------------------------------------------------------------
# 有理数快路
# --------------------------------------------------------------------------

def _digits(q: Fraction) -> float:
    n = max(abs(q.numerator), abs(q.denominator), 1)
    return n.bit_length() * 0.30103


def _as_int(q: Fraction, what: str) -> int:
    if q.denominator != 1:
        raise ParseError(f"{what} 需要整数，实际是 {q}")
    return q.numerator


def _exact(node, bindings: dict[str, Fraction]) -> Fraction:
    tag = node[0]
    if tag == "num":
        return Fraction(node[1])
    if tag == "sym":
        if node[1] in bindings:
            return bindings[node[1]]
        raise _NeedSympy
    if tag == "const":
        if node[1] in bindings:
            return bindings[node[1]]
        raise _NeedSympy
    if tag == "neg":
        return -_exact(node[1], bindings)
    if tag in ("add", "sub", "mul", "div"):
        a = _exact(node[1], bindings)
        b = _exact(node[2], bindings)
        if tag == "add":
            return a + b
        if tag == "sub":
            return a - b
        if tag == "mul":
            return a * b
        if b == 0:
            raise ParseError("除以零")
        return a / b
    if tag == "pow":
        base = _exact(node[1], bindings)
        exp = _exact(node[2], bindings)
        if exp.denominator != 1:
            raise _NeedSympy
        n = exp.numerator
        if base == 0 and n < 0:
            raise ParseError("0 的负数次幂无定义")
        if abs(base) not in (0, 1) and abs(n) * _digits(base) > MAX_DIGITS:
            raise ResourceLimit(f"结果超过 {MAX_DIGITS} 位")
        return base ** n
    if tag == "fact":
        n = _as_int(_exact(node[1], bindings), "阶乘")
        if n < 0:
            raise ParseError("负数没有阶乘")
        if n > MAX_FACTORIAL:
            raise ResourceLimit(f"阶乘参数超过 {MAX_FACTORIAL}")
        return Fraction(math.factorial(n))
    if tag == "percent":
        return _exact(node[1], bindings) / 100
    if tag == "deg":
        raise _NeedSympy
    if tag == "call":
        return _exact_call(node[1], [_exact(a, bindings) for a in node[2]])
    if tag == "eq":
        raise ParseError("此处不接受等式（'='）")
    raise ParseError(f"未知节点 {tag}")


def _exact_call(name: str, args: list[Fraction]) -> Fraction:
    if name == "abs":
        return abs(args[0])
    if name == "sign":
        return Fraction((args[0] > 0) - (args[0] < 0))
    if name == "floor":
        return Fraction(math.floor(args[0]))
    if name == "ceil":
        return Fraction(math.ceil(args[0]))
    if name == "max":
        return max(args)
    if name == "min":
        return min(args)
    if name == "mod":
        if args[1] == 0:
            raise ParseError("mod 的除数为零")
        return args[0] - args[1] * math.floor(args[0] / args[1])
    if name in ("gcd", "lcm"):
        ints = [_as_int(a, name) for a in args]
        fn = math.gcd if name == "gcd" else math.lcm
        return Fraction(fn(*ints))
    if name == "factorial":
        n = _as_int(args[0], "阶乘")
        if n < 0:
            raise ParseError("负数没有阶乘")
        if n > MAX_FACTORIAL:
            raise ResourceLimit(f"阶乘参数超过 {MAX_FACTORIAL}")
        return Fraction(math.factorial(n))
    if name in ("binomial", "comb", "perm"):
        n, k = _as_int(args[0], name), _as_int(args[1], name)
        if n > MAX_FACTORIAL:
            raise ResourceLimit(f"{name} 参数超过 {MAX_FACTORIAL}")
        if n < 0 or k < 0:
            raise ParseError(f"{name} 需要非负整数")
        return Fraction(math.comb(n, k) if name != "perm" else math.perm(n, k))
    if name == "sqrt":
        q = args[0]
        if q >= 0:
            rn, rd = math.isqrt(q.numerator), math.isqrt(q.denominator)
            if rn * rn == q.numerator and rd * rd == q.denominator:
                return Fraction(rn, rd)
        raise _NeedSympy
    raise _NeedSympy


def _fraction_approx(q: Fraction, digits: int) -> str:
    if q.denominator == 1 and len(str(abs(q.numerator))) <= digits:
        return str(q.numerator)
    with localcontext() as ctx:
        ctx.prec = digits
        d = Decimal(q.numerator) / Decimal(q.denominator)
        return format(d.normalize(), "g") if d != 0 else "0"


def _fraction_result(q: Fraction, digits: int) -> dict:
    kind = "integer" if q.denominator == 1 else "rational"
    value = str(q.numerator) if kind == "integer" else f"{q.numerator}/{q.denominator}"
    return {"value": value, "exact": True, "approx": _fraction_approx(q, digits), "kind": kind}


# --------------------------------------------------------------------------
# sympy 路
# --------------------------------------------------------------------------

_sp = None


def sympy():
    global _sp
    if _sp is None:
        import sympy as sp  # 延迟导入：只在需要时付出 ~0.3 秒
        _sp = sp
    return _sp


def _sym_call(name: str, args: list):
    sp = sympy()
    table = {
        "sqrt": lambda a: sp.sqrt(a[0]),
        "cbrt": lambda a: sp.real_root(a[0], 3),
        "root": lambda a: sp.real_root(a[0], a[1]),
        "exp": lambda a: sp.exp(a[0]),
        "ln": lambda a: sp.log(a[0]),
        "lg": lambda a: sp.log(a[0], 10),
        "log": lambda a: sp.log(a[0]) if len(a) == 1 else sp.log(a[0], a[1]),
        "log2": lambda a: sp.log(a[0], 2),
        "log10": lambda a: sp.log(a[0], 10),
        "sin": lambda a: sp.sin(a[0]), "cos": lambda a: sp.cos(a[0]), "tan": lambda a: sp.tan(a[0]),
        "cot": lambda a: sp.cot(a[0]), "sec": lambda a: sp.sec(a[0]), "csc": lambda a: sp.csc(a[0]),
        "asin": lambda a: sp.asin(a[0]), "acos": lambda a: sp.acos(a[0]), "atan": lambda a: sp.atan(a[0]),
        "arcsin": lambda a: sp.asin(a[0]), "arccos": lambda a: sp.acos(a[0]), "arctan": lambda a: sp.atan(a[0]),
        "atan2": lambda a: sp.atan2(a[0], a[1]),
        "sinh": lambda a: sp.sinh(a[0]), "cosh": lambda a: sp.cosh(a[0]), "tanh": lambda a: sp.tanh(a[0]),
        "abs": lambda a: sp.Abs(a[0]), "sign": lambda a: sp.sign(a[0]),
        "floor": lambda a: sp.floor(a[0]), "ceil": lambda a: sp.ceiling(a[0]),
        "factorial": lambda a: _guard_factorial(a[0]),
        "binomial": lambda a: sp.binomial(a[0], a[1]), "comb": lambda a: sp.binomial(a[0], a[1]),
        "perm": lambda a: sp.ff(a[0], a[1]),
        "gcd": lambda a: sp.gcd(list(a)) if len(a) > 2 else sp.gcd(a[0], a[1]),
        "lcm": lambda a: sp.lcm(list(a)) if len(a) > 2 else sp.lcm(a[0], a[1]),
        "mod": lambda a: sp.Mod(a[0], a[1]),
        "max": lambda a: sp.Max(*a), "min": lambda a: sp.Min(*a),
        "re": lambda a: sp.re(a[0]), "im": lambda a: sp.im(a[0]),
    }
    return table[name](args)


def _guard_factorial(x):
    sp = sympy()
    if x.is_Integer and x > MAX_FACTORIAL:
        raise ResourceLimit(f"阶乘参数超过 {MAX_FACTORIAL}")
    return sp.factorial(x)


def _guard_pow(base, exp):
    sp = sympy()
    if exp.is_Integer and base.is_number and base.is_Rational and abs(base) not in (0, 1):
        q = Fraction(int(base.p), int(base.q))
        if abs(int(exp)) * _digits(q) > MAX_DIGITS:
            raise ResourceLimit(f"结果超过 {MAX_DIGITS} 位")
    if exp.is_Integer and base.is_number and not base.is_Rational:
        if abs(int(exp)) > 100_000:
            raise ResourceLimit("指数过大")
    return sp.Pow(base, exp)


def to_sympy(node, bindings: dict):
    sp = sympy()
    tag = node[0]
    if tag == "num":
        return sp.Rational(node[1])
    if tag == "sym":
        name = node[1]
        return bindings[name] if name in bindings else sp.Symbol(name)
    if tag == "const":
        name = node[1]
        if name in bindings:
            return bindings[name]
        return {"pi": sp.pi, "e": sp.E, "I": sp.I, "oo": sp.oo}[name]
    if tag == "neg":
        return -to_sympy(node[1], bindings)
    if tag in ("add", "sub", "mul", "div"):
        a, b = to_sympy(node[1], bindings), to_sympy(node[2], bindings)
        if tag == "add":
            return a + b
        if tag == "sub":
            return a - b
        if tag == "mul":
            return a * b
        if b == 0:
            raise ParseError("除以零")
        return a / b
    if tag == "pow":
        return _guard_pow(to_sympy(node[1], bindings), to_sympy(node[2], bindings))
    if tag == "fact":
        return _guard_factorial(to_sympy(node[1], bindings))
    if tag == "percent":
        return to_sympy(node[1], bindings) / 100
    if tag == "deg":
        return to_sympy(node[1], bindings) * sp.pi / 180
    if tag == "call":
        return _sym_call(node[1], [to_sympy(a, bindings) for a in node[2]])
    if tag == "eq":
        return sp.Eq(to_sympy(node[1], bindings), to_sympy(node[2], bindings), evaluate=False)
    raise ParseError(f"未知节点 {tag}")


def _kind(v) -> str:
    if v.is_Integer:
        return "integer"
    if v.is_Rational:
        return "rational"
    if v.is_real is True:
        return "real"
    if v.is_number:
        return "complex" if v.is_real is False else "number"
    return "expression"


def _approx(v, digits: int):
    sp = sympy()
    if not v.is_number:
        return None
    if v.has(sp.oo, -sp.oo, sp.zoo, sp.nan):
        return str(v)
    n = sp.N(v, digits)
    return str(n)


def sympy_result(v, digits: int) -> dict:
    sp = sympy()
    if v.is_Rational:
        return _fraction_result(Fraction(int(v.p), int(v.q)), digits)
    return {
        "value": sp.sstr(v),
        "exact": not v.has(sp.Float),
        "approx": _approx(v, digits),
        "kind": _kind(v),
    }


# --------------------------------------------------------------------------
# 绑定
# --------------------------------------------------------------------------

def _binding_nodes(bindings) -> dict:
    if bindings is None:
        return {}
    if not isinstance(bindings, dict):
        raise ParseError("bindings 必须是对象，例如 {\"n\": 7}")
    out = {}
    for name, val in bindings.items():
        if not isinstance(name, str) or not name.isidentifier() or "__" in name:
            raise ParseError(f"非法变量名 {name!r}")
        if isinstance(val, bool) or val is None:
            raise ParseError(f"变量 {name} 的值必须是数或表达式")
        if isinstance(val, (int, float)):
            val = repr(val) if isinstance(val, float) else str(val)
        if not isinstance(val, str):
            raise ParseError(f"变量 {name} 的值必须是数或表达式")
        out[name] = parse(val)
    return out


def exact_bindings(nodes: dict) -> dict:
    return {k: _exact(v, {}) for k, v in nodes.items()}


def sympy_bindings(nodes: dict) -> dict:
    return {k: to_sympy(v, {}) for k, v in nodes.items()}


# --------------------------------------------------------------------------
# 对外：三件工具
# --------------------------------------------------------------------------

def evaluate(payload: dict) -> dict:
    expr = payload.get("expr")
    digits = int(payload.get("digits", 30))
    if not 1 <= digits <= 1000:
        raise ParseError("digits 取值 1–1000")
    bnodes = _binding_nodes(payload.get("bindings"))
    tree = parse(expr)
    if tree[0] == "eq":
        # 'y = 2^7 + 7^2' 这类带标签的写法：左边是单个未绑定变量时，只算右边
        if tree[1][0] == "sym" and tree[1][1] not in bnodes:
            tree = tree[2]
        else:
            raise ParseError("求值不接受等式；解方程请用 calc.algebra 的 solve")
    try:
        q = _exact(tree, exact_bindings(bnodes))
        out = _fraction_result(q, digits)
        out["path"] = "rational"
        return out
    except _NeedSympy:
        pass
    v = to_sympy(tree, sympy_bindings(bnodes))
    free = sorted(str(s) for s in v.free_symbols)
    if free:
        raise ParseError(f"有未绑定的变量：{', '.join(free)}（请在 bindings 中给出，或改用 calc.algebra）")
    v = v if v.is_Rational else sympy().simplify(v)
    sp = sympy()
    if v.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
        raise ParseError(f"结果无定义或为无穷（{sp.sstr(v)}），例如 log(0)、tan(90°)、1/0")
    out = sympy_result(v, digits)
    out["path"] = "symbolic"
    return out


def _strip_answer_label(text: str) -> str:
    """'y = 177' → '177'；只剥一个形如 '<变量> =' 的前缀。"""
    if isinstance(text, str) and text.count("=") == 1:
        left, right = text.split("=", 1)
        if left.strip().isidentifier():
            return right
    return text


def check_equal(payload: dict) -> dict:
    left_text = payload.get("left")
    right_text = _strip_answer_label(payload.get("right"))
    lt, rt = parse(left_text), parse(right_text)
    if lt[0] == "eq" or rt[0] == "eq":
        raise ParseError("left/right 应是表达式，不是等式")
    bnodes = _binding_nodes(payload.get("bindings"))
    try:
        eb = exact_bindings(bnodes)
        a, b = _exact(lt, eb), _exact(rt, eb)
        return {"equal": a == b, "covered": True, "method": "exact-rational",
                "left": _fraction_result(a, 30)["value"], "right": _fraction_result(b, 30)["value"]}
    except _NeedSympy:
        pass
    sp = sympy()
    sb = sympy_bindings(bnodes)
    a, b = to_sympy(lt, sb), to_sympy(rt, sb)
    d = sp.simplify(a - b)
    base = {"left": sp.sstr(a), "right": sp.sstr(b)}
    if d == 0:
        return {"equal": True, "covered": True, "method": "symbolic", **base}
    if d.is_number:
        n = sp.N(d, 60)
        if n.is_zero is False and n != 0:
            return {"equal": False, "covered": True, "method": "numeric-nonzero", **base,
                    "assumptions": ["数值判定：两式之差在 60 位有效数字下不为零，未经符号证明"]}
        return {"equal": None, "covered": False, "method": "undetermined", **base}
    z = d.equals(0)
    if z is False:
        # sympy 的 equals 在化简不能定论时会在随机点做数值检验；不把它当作符号证明（TL-22a）
        return {"equal": False, "covered": True, "method": "sympy-equals", **base,
                "assumptions": ["不等由 sympy.equals 判定，可能依据随机点上的数值检验，未经符号证明"]}
    return {"equal": None, "covered": False, "method": "undetermined", **base}


def _sym(name: str):
    if not isinstance(name, str) or not name.isidentifier() or "__" in name:
        raise ParseError(f"非法变量名 {name!r}")
    return sympy().Symbol(name)


def _sorted_strs(values) -> list[str]:
    sp = sympy()
    return [sp.sstr(v) for v in sorted(values, key=sp.default_sort_key)]


def algebra(payload: dict) -> dict:
    sp = sympy()
    op = payload.get("op")
    digits = int(payload.get("digits", 30))
    sb = sympy_bindings(_binding_nodes(payload.get("bindings")))

    def ex(key="expr", allow_eq=False):
        tree = parse(payload.get(key))
        if tree[0] == "eq" and not allow_eq:
            raise ParseError(f"{op} 不接受等式")
        return to_sympy(tree, sb)

    def var(default_from=None):
        if payload.get("var") is not None:
            return _sym(payload["var"])
        if default_from is not None:
            free = sorted(default_from.free_symbols, key=sp.default_sort_key)
            if len(free) == 1:
                return free[0]
            raise ParseError("请用 var 指明变量" + (f"（候选：{', '.join(map(str, free))}）" if free else ""))
        raise ParseError("缺少 var")

    def done(v):
        out = sympy_result(v, digits)
        out["op"] = op
        return out

    if op in ("simplify", "expand", "factor", "subs"):
        v = ex()
        fn = {"simplify": sp.simplify, "expand": sp.expand, "factor": sp.factor, "subs": sp.simplify}[op]
        return done(fn(v))
    if op == "diff":
        v = ex()
        order = int(payload.get("order", 1))
        if not 1 <= order <= 20:
            raise ParseError("order 取值 1–20")
        return done(sp.diff(v, var(v), order))
    if op == "integrate":
        v = ex()
        x = var(v)
        lo, hi = payload.get("lower"), payload.get("upper")
        if (lo is None) != (hi is None):
            raise ParseError("定积分需要同时给出 lower 和 upper")
        if lo is None:
            r = sp.integrate(v, x)
        else:
            r = sp.integrate(v, (x, to_sympy(parse(str(lo)), sb), to_sympy(parse(str(hi)), sb)))
        out = done(r)
        out["evaluated"] = not r.has(sp.Integral)
        return out
    if op == "limit":
        v = ex()
        x = var(v)
        at = payload.get("at")
        if at is None:
            raise ParseError("limit 需要 at")
        direction = payload.get("dir", "+-")
        if direction not in ("+", "-", "+-"):
            raise ParseError("dir 取 '+'、'-' 或 '+-'")
        return done(sp.limit(v, x, to_sympy(parse(str(at)), sb), direction))
    if op == "solve":
        exprs = payload.get("exprs")
        if exprs is None:
            exprs = [payload.get("expr")]
        if not isinstance(exprs, list) or not exprs or len(exprs) > 20:
            raise ParseError("exprs 应为 1–20 个等式")
        eqs = []
        for e in exprs:
            t = to_sympy(parse(e), sb)
            eqs.append(t if isinstance(t, sp.Equality) else sp.Eq(t, 0))
        names = payload.get("vars") or ([payload["var"]] if payload.get("var") else None)
        if names:
            syms = [_sym(n) for n in names]
        else:
            free = set().union(*(e.free_symbols for e in eqs))
            syms = sorted(free, key=sp.default_sort_key)
            if not syms:
                raise ParseError("方程里没有未知数")
        domain = payload.get("domain", "complex")
        if domain not in ("complex", "real"):
            raise ParseError("domain 取 complex 或 real")
        try:
            sols = sp.solve(eqs, syms, dict=True)
        except NotImplementedError as exc:
            raise Unsupported(f"sympy 无法求解：{exc}") from exc
        rows, real_unknown = [], False
        for s in sols:
            if domain == "real" and any(val.is_real is False for val in s.values()):
                continue
            if domain == "real" and any(val.is_real is None for val in s.values()):
                real_unknown = True
            rows.append({str(k): sp.sstr(val) for k, val in sorted(s.items(), key=lambda kv: str(kv[0]))})
        rows.sort(key=lambda r: [r[k] for k in sorted(r)])
        # 多项式方程组的解集由 sympy 完整给出；非多项式（三角、指数、对数等）只给它能求出的解，
        # 周期解只给主值，因此如实声明"可能不完备"（TL-22a）
        complete = all((e.lhs - e.rhs).as_poly(*syms) is not None for e in eqs)
        out = {"op": op, "vars": [str(s) for s in syms], "solutions": rows, "count": len(rows),
               "domain": domain, "complete": complete}
        assumptions = []
        if not complete:
            assumptions.append("解集可能不完备：方程不是多项式，sympy 只返回它能求出的解（例如周期解只给主值）")
        if real_unknown:
            assumptions.append("部分解是否为实数无法判定，已保留在实数解中")
        if assumptions:
            out["assumptions"] = assumptions
        if len(syms) == 1:
            out["values"] = [r[str(syms[0])] for r in rows if str(syms[0]) in r]
        return out
    raise ParseError(f"不支持的 op：{op!r}（可用：simplify、expand、factor、subs、diff、integrate、limit、solve）")
