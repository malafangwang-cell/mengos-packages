# 承: mathdisc设计文档v1§1 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-check/v0.1.0
"""check.reach: 表达式达标判定 —— 精确求值 == target (承工程文档§1 reach.py).

不变量 (承工程文档§2 check-I5): 禁浮点, fractions 全径 ——
  浮点字面量/非整数指数/非完全平方开方 一律显式拒 (GrammarError),
  精确域不存在的运算不降级为浮点近似 (承 GR-R7 禁静默降级)。
"""
# impl: mathdisc-D2 | 承mathdisc工程文档v1§1 reach.py + §2 check-I5
from __future__ import annotations

from fractions import Fraction

from ..expr.grammar import GrammarError, parse
from ..expr.ir import IR
from .receipt import Receipt, runtime_versions


def _eval_exact(ir: IR) -> Fraction:
    """IR → Fraction 精确求值 (禁浮点, 承 I5); 精确域外运算 → GrammarError."""
    # impl: mathdisc-D2 | 承工程文档§2 check-I5
    if ir.kind == "num":
        if not ir.value.lstrip("-").isdigit():
            raise GrammarError(f"浮点字面量禁入精确域: {ir.value} (承 I5)")
        return Fraction(int(ir.value))
    if ir.kind == "sym":
        raise GrammarError(f"reach 域无自由符号: {ir.value}")
    if ir.kind == "neg":
        return -_eval_exact(ir.children[0])
    if ir.kind == "binop":
        left, right = _eval_exact(ir.children[0]), _eval_exact(ir.children[1])
        if ir.value == "+":
            return left + right
        if ir.value == "-":
            return left - right
        if ir.value == "*":
            return left * right
        if ir.value == "/":
            if right == 0:
                raise GrammarError("除零 (精确域显式拒)")
            return left / right
        if ir.value == "**":
            if right.denominator != 1:
                raise GrammarError("非整数指数出精确域 (承 I5)")
            e = int(right)
            if e < 0:
                return Fraction(1) / (left ** (-e))
            return left ** e
        raise GrammarError(f"算符 {ir.value} 不在 reach 精确域")
    if ir.kind == "call":
        args = [_eval_exact(c) for c in ir.children]
        if ir.value == "factorial":
            if args[0].denominator != 1 or args[0] < 0:
                raise GrammarError("factorial 仅定义于非负整数 (精确域)")
            import math
            return Fraction(math.factorial(int(args[0])))
        if ir.value == "sqrt":
            import math
            v = args[0]
            if v < 0:
                raise GrammarError("sqrt 负数出精确域 (承 I5)")
            n, d = math.isqrt(v.numerator), math.isqrt(v.denominator)
            if n * n != v.numerator or d * d != v.denominator:
                raise GrammarError("非完全平方开方出精确域 (不降级浮点, 承 GR-R7)")
            return Fraction(n, d)
        raise GrammarError(f"函数 {ir.value} 不在 reach 精确域")
    raise GrammarError(f"节点 {ir.kind} 不在 reach 精确域")


def check_reach(expr: str | IR, target: int | Fraction) -> Receipt:
    """表达式精确求值 == target ? (承 §1: reach=精确求值, exact 级证据)."""
    # impl: mathdisc-D2 | 承mathdisc工程文档§1 reach.py
    ir = parse(expr) if isinstance(expr, str) else expr
    value = _eval_exact(ir)
    tgt = Fraction(target)
    hit = value == tgt
    return Receipt(
        verdict="established" if hit else "refuted",
        method_complete=True,  # 精确算术 ⟹ 判定完备 (承 evidence.grade=exact)
        evidence={"grade": "exact", "value": str(value), "target": str(tgt),
                  "reason": "fractions 全径精确求值 (承 I5)"},
        versions=runtime_versions())
