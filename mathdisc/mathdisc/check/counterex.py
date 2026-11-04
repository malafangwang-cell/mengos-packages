# 承: mathdisc设计文档v1§1/§2 · mathdisc工程文档v1§1 · 层: 工具·环0 · 版本: mathdisc-check/v0.1.0
"""check.counterex: 反例验证 —— 谓词求值 (承工程文档§1 counterex.py).

数论经 sympy.ntheory (承设计§2 选型定案: isprime/factorint 反例域已实测)。
witness 代入谓词: 谓词假 ⟹ 猜想被反驳 (refuted, 附分解证据);
谓词真 ⟹ 该 witness 非反例 (rejected, 可调参重试非终局, 承 receipt 值域)。
"""
# impl: mathdisc-D2 | 承mathdisc工程文档v1§1 counterex.py
from __future__ import annotations

from sympy import ntheory

from ..expr.grammar import GrammarError, parse
from ..expr.ir import IR
from .receipt import Receipt, runtime_versions


def _eval_int(ir: IR, env: dict[str, int]) -> int:
    """IR → int 精确求值 (反例域全整数, 承§1); 越域 → GrammarError."""
    # impl: mathdisc-D2 | 承工程文档§1 counterex.py
    if ir.kind == "num":
        if not ir.value.lstrip("-").isdigit():
            raise GrammarError(f"非整数字面量出反例域: {ir.value}")
        return int(ir.value)
    if ir.kind == "sym":
        if ir.value not in env:
            raise GrammarError(f"witness 未覆盖符号: {ir.value}")
        return env[ir.value]
    if ir.kind == "neg":
        return -_eval_int(ir.children[0], env)
    if ir.kind == "binop":
        left, right = _eval_int(ir.children[0], env), _eval_int(ir.children[1], env)
        if ir.value == "+":
            return left + right
        if ir.value == "-":
            return left - right
        if ir.value == "*":
            return left * right
        if ir.value == "**":
            if right < 0:
                raise GrammarError("负指数出反例整数域")
            return left ** right
        if ir.value == "/":
            if right == 0 or left % right != 0:
                raise GrammarError("非整除出反例整数域")
            return left // right
        raise GrammarError(f"算符 {ir.value} 不在反例整数域")
    if ir.kind == "call" and ir.value == "factorial":
        import math
        return math.factorial(_eval_int(ir.children[0], env))
    raise GrammarError(f"节点 {ir.kind}:{ir.value} 不在反例整数域")


def check_counterexample(conjecture: str, witness: dict[str, int]) -> Receipt:
    """反例验证: conjecture 是谓词表达式 (如 isprime(2**(2**n)+1)), witness 代入求值。

    谓词形态: isprime(<整数表达式>) (承金样 g-fermat5: F5=641×6700417)。
    """
    # impl: mathdisc-D2 | 承mathdisc工程文档§1 counterex.py + 金样 g-fermat5
    ir = parse(conjecture)
    if ir.kind != "call" or ir.value != "isprime":
        raise GrammarError("counterex 域谓词形态: isprime(<expr>) (承§1)")
    subject = _eval_int(ir.children[0], witness)
    holds = ntheory.isprime(subject)
    if holds:
        return Receipt(
            verdict="rejected", method_complete=True,
            evidence={"grade": "none", "subject": subject,
                      "reason": "witness 代入谓词为真 —— 非反例 (可调参重试, 非终局); "
                                "grade=none: rejected 是无证据等级回执 (承上游§3证据词汇表, 2026-08-18 G6对齐)"},
            versions=runtime_versions())
    factors = sorted(ntheory.factorint(subject).keys())
    return Receipt(
        verdict="refuted", method_complete=True,
        evidence={"grade": "verified_on_data", "subject": subject, "factors": factors,
                  "reason": f"谓词在 witness 处为假, 猜想被反驳; 分解={factors} (ntheory.factorint, 精确数论证据入 verified_on_data 档, 承上游§3证据词汇表, 2026-08-18 G6对齐)"},
        versions=runtime_versions())
