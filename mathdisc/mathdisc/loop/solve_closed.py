# 承: mathdisc设计文档v1§1 · mathdisc工程文档v1§0 D-5 · 层: 工具·环0 · 版本: mathdisc-loop/v0.1.0
"""solve_closed: 封闭枚举求解 (承设计§1: 化石预言机推广, 零 LLM, 小空间全枚举).

24点形任务的全枚举: V(多重集) × T(算符) 全部二叉组合 → 精确判定可达性。
D-5 双路对照: 枚举判定的 oracle 地位由 check_reach 逐条复核
(找到 ⟹ check_reach 必 established; 找不到 ⟹ 枚举穷尽即"不存在"的证明,
 承设计§5③: "不存在规律"只能来自门(穷尽+阴性对照), 永不消费模型输出)。
"""
# impl: mathdisc-D4 | 承mathdisc设计文档v1§1 solve_closed + §5③
from __future__ import annotations

from fractions import Fraction

from ..check.reach import check_reach

_OPS: dict[str, object] = {
    "+": lambda a, b: a + b, "-": lambda a, b: a - b,
    "*": lambda a, b: a * b, "/": lambda a, b: a / b if b != 0 else None,
}


def _enumerate(values: list[tuple[Fraction, str]], ops: list[str],
               target: Fraction) -> str | None:
    """全枚举 (记忆化按值去重); 命中返回表达式串, 穷尽返回 None."""
    # impl: mathdisc-D4 | 承设计§1 (小空间全枚举)
    if len(values) == 1:
        v, s = values[0]
        return s if v == target else None
    seen: set[tuple] = set()
    for i in range(len(values)):
        for j in range(len(values)):
            if i == j:
                continue
            rest = [values[k] for k in range(len(values)) if k != i and k != j]
            vi, si = values[i]
            vj, sj = values[j]
            for op in ops:
                fn = _OPS[op]
                merged = fn(vi, vj)  # type: ignore
                if merged is None:
                    continue
                key = (merged, tuple(sorted(v for v, _ in rest)), op)
                if key in seen:
                    continue
                seen.add(key)
                hit = _enumerate([*rest, (merged, f"({si}{op}{sj})")], ops, target)
                if hit is not None:
                    return hit
    return None


def solve_closed(V: list[int], T: list[str], target: int) -> dict:
    """封闭枚举求解: 返回 {solvable, expr, proof}.

    solvable=True ⟹ expr 存在且经 check_reach 复核 established (D-5 双路);
    solvable=False ⟹ 枚举穷尽 (proof="exhaustive", 承设计§5③)。
    """
    # impl: mathdisc-D4 | 承工程文档§0 D-5
    unknown = [op for op in T if op not in _OPS]
    if unknown:
        raise ValueError(f"solve_closed 域算符仅 + - * /, 收到: {unknown}")
    tgt = Fraction(target)
    expr = _enumerate([(Fraction(v), str(v)) for v in V], list(T), tgt)
    if expr is None:
        return {"solvable": False, "expr": None, "proof": "exhaustive"}
    # 双路对照 (承 D-5): 枚举命中必须过 check_reach 精确复核
    assert check_reach(expr, tgt).verdict == "established", "D-5 双路违例: 枚举命中过不了门"
    return {"solvable": True, "expr": expr, "proof": "exhaustive+gate"}
