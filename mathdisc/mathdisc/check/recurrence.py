# 承: mathdisc设计文档v1§1 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-check/v0.1.0
"""check.recurrence: 递推验证 —— 精确复现 + 保留项盲测 (承工程文档§1 recurrence.py).

不变量 (承工程文档§2 check):
  I5 禁浮点 (fractions 全径); ★n 作独立标识符经 IR 节点消费 ——
     字符串替换路径结构性不存在 (v1 阶乘 bug "n在串尾replace不匹配" 的永久防线,
     金样 g-factorial)
  流程: 已知段精确复现 (种子外每项由 relation 推出) + 保留项盲测,
        任一不齐 → refuted (精确算术, method_complete=True)
"""
# impl: mathdisc-D2 | 承mathdisc工程文档v1§1 recurrence.py + §2 check-I5
from __future__ import annotations

from fractions import Fraction

from ..expr.grammar import parse
from ..expr.ir import IR
from .receipt import Receipt, runtime_versions


def _index_offset(idx: IR, n: int) -> int:
    """下标表达式 → 绝对下标 (仅允许 n / n-k 形态, 其余显式拒, 承 ST1 早失败)."""
    # impl: mathdisc-D2 | 承工程文档§2 check-I5
    if idx.kind == "sym" and idx.value == "n":
        return n
    if idx.kind == "binop" and idx.value == "-" and idx.children[0].kind == "sym" \
            and idx.children[0].value == "n" and idx.children[1].kind == "num" \
            and idx.children[1].value.lstrip("-").isdigit():
        return n - int(idx.children[1].value)
    raise ValueError(f"递推下标仅允许 a[n] / a[n-k] 形态 (k 为整数字面量), 实收: {idx.canonical}")


def _max_lookback(ir: IR) -> int:
    """relation 中最大回看步长 k (a[n-k]); 无下标 → 0; 非 n/n-k 下标 → 显式拒."""
    # impl: mathdisc-D2 | 承工程文档§1 recurrence.py
    if ir.kind == "subscript":
        idx = ir.children[0]
        if idx.kind == "sym" and idx.value == "n":
            return 0  # a[n] 自引用下标, 回看 0
        # n-k 形态 (非此形态由 _index_offset 在求值时显式拒; 此处同形态提取 k)
        _index_offset(idx, 10**6)  # 形态校验 (大 n 不越界, 仅验形)
        return int(idx.children[1].value)
    return max((_max_lookback(c) for c in ir.children), default=0)


def _eval_at(ir: IR, seq: list[Fraction], n: int) -> Fraction:
    """relation 在索引 n 处求值 (a[n-k] 查已精确算出的序列前缀; n 为 IR sym 节点, 非字符串)."""
    # impl: mathdisc-D2 | 承工程文档§2 check-I5 (n 独立标识符, 阶乘bug永久防线)
    if ir.kind == "num":
        if not ir.value.lstrip("-").isdigit():
            raise ValueError(f"浮点字面量禁入递推精确域: {ir.value} (承 I5)")
        return Fraction(int(ir.value))
    if ir.kind == "sym":
        if ir.value == "n":
            return Fraction(n)
        raise ValueError(f"递推域未知符号: {ir.value}")
    if ir.kind == "subscript":
        off = _index_offset(ir.children[0], n)
        if off < 1 or off > len(seq):
            raise ValueError(f"下标越界 a[{off}] (已精确算出前缀长 {len(seq)}, 承 ST1 早失败)")
        return seq[off - 1]
    if ir.kind == "neg":
        return -_eval_at(ir.children[0], seq, n)
    if ir.kind == "binop":
        left, right = _eval_at(ir.children[0], seq, n), _eval_at(ir.children[1], seq, n)
        if ir.value == "+":
            return left + right
        if ir.value == "-":
            return left - right
        if ir.value == "*":
            return left * right
        if ir.value == "/":
            if right == 0:
                raise ValueError("除零 (递推精确域显式拒)")
            return left / right
        raise ValueError(f"算符 {ir.value} 不在递推精确域")
    raise ValueError(f"节点 {ir.kind} 不在递推精确域")


def check_recurrence(relation: str, known: list[int], holdout: list[int]) -> Receipt:
    """递推验证: relation 精确复现 known 种子外各项 + 盲测 holdout.

    known: 已知序列 a[1..len(known)] (1-based, 承金样 g-factorial);
    holdout: 紧接的保留项 a[len+1..len+len(holdout)]。
    """
    # impl: mathdisc-D2 | 承mathdisc工程文档§1 recurrence.py
    ir = parse(relation)
    k = _max_lookback(ir)
    seq = [Fraction(v) for v in known]
    # 精确复现: 种子 (前 k 项) 之外逐项推出比对 (承§1: 精确复现)
    for n in range(k + 1, len(seq) + 1):
        if _eval_at(ir, seq, n) != seq[n - 1]:
            return Receipt(
                verdict="refuted", method_complete=True,
                evidence={"grade": "exact", "failed_at": n,
                          "reason": f"已知段第 {n} 项精确复现不齐 (承§1)"},
                versions=runtime_versions())
    # 保留项盲测 (承§1: 盲测不齐→refuted)
    for j, expect in enumerate(holdout):
        n = len(seq) + 1
        got = _eval_at(ir, seq, n)
        if got != Fraction(expect):
            return Receipt(
                verdict="refuted", method_complete=True,
                evidence={"grade": "exact", "failed_at": n, "got": str(got),
                          "expected": str(expect), "reason": "保留项盲测不齐"},
                versions=runtime_versions())
        seq.append(got)
    return Receipt(
        verdict="established", method_complete=True,
        evidence={"grade": "exact", "lookback": k,
                  "reason": "已知段精确复现 + 保留项盲测全齐 (fractions 全径)"},
        versions=runtime_versions())
