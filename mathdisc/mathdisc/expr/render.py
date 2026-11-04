# 承: mathdisc设计文档v1§2 · mathdisc工程文档v1§1 · 层: 工具·环0 · 版本: mathdisc-expr/v0.1.0
"""IR → sympy 对象 (程序化构造) / 可读串 (承工程文档§1 render.py).

安全 (承设计§2 选型定案): 禁 sympify 字符串路径 (已知注入面) ——
sympy 对象由 IR 节点逐类型程序化构造, 字符串死于 parse 一处。
"""
# impl: mathdisc-D1 | 承mathdisc设计文档v1§2 + 工程文档§1 render.py
from __future__ import annotations

import sympy as sp

from .grammar import GrammarError
from .ir import IR

# sympy 函数映射表 (ST2 查表; isprime 是谓词非表达式函数, 由 counterex 特殊消费, 不在此表)
# impl: mathdisc-D1 | 承mathdisc设计文档v1§2 (SymPy=符号验证唯一通道)
_SYMPY_FUNCS = {
    "sqrt": sp.sqrt, "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "exp": sp.exp, "log": sp.log, "abs": sp.Abs, "zeta": sp.zeta,
    "factorial": sp.factorial,
}
_SYMPY_CONSTS = {"pi": sp.pi, "e": sp.E}


def to_sympy(ir: IR) -> sp.Basic:
    """IR → sympy 对象 (程序化构造, 承设计§2).

    subscript (递推下标) 不属 sympy 表达式域 —— 显式拒, 由 check/recurrence
    的 fractions 独立求值器消费 (承工程文档§2 check-I5 禁浮点)。
    """
    # impl: mathdisc-D1 | 承工程文档§1 render.py
    if ir.kind == "num":
        # 整数字面量走 Integer (精确), 浮点字面量走 Float (check 层各自执法)
        return sp.Integer(int(ir.value)) if ir.value.lstrip("-").isdigit() else sp.Float(ir.value)
    if ir.kind == "sym":
        const = _SYMPY_CONSTS.get(ir.value)
        return const if const is not None else sp.Symbol(ir.value)
    if ir.kind == "neg":
        return -to_sympy(ir.children[0])
    if ir.kind == "binop":
        left, right = to_sympy(ir.children[0]), to_sympy(ir.children[1])
        # 算符分派 (ST2 查表)
        return {
            "+": lambda: left + right, "-": lambda: left - right,
            "*": lambda: left * right, "/": lambda: left / right,
            "**": lambda: left ** right, "%": lambda: left % right,
        }[ir.value]()
    if ir.kind == "call":
        fn = _SYMPY_FUNCS.get(ir.value)
        if fn is None:
            raise GrammarError(f"函数 {ir.value} 不在 sympy 映射表 (谓词归 counterex 域)")
        return fn(*[to_sympy(c) for c in ir.children])
    raise GrammarError("subscript 下标语法仅递推域可渲染 (承工程文档§2 check-I5)")


def to_readable(ir: IR) -> str:
    """IR → 可读串 (回执/日志用)."""
    # impl: mathdisc-D1 | 承工程文档§1 render.py
    if ir.kind in ("num", "sym"):
        return ir.value
    if ir.kind == "neg":
        return f"(-{to_readable(ir.children[0])})"
    if ir.kind == "subscript":
        return f"{ir.value}[{to_readable(ir.children[0])}]"
    if ir.kind == "call":
        return f"{ir.value}({', '.join(to_readable(c) for c in ir.children)})"
    return f"({to_readable(ir.children[0])} {ir.value} {to_readable(ir.children[1])})"
