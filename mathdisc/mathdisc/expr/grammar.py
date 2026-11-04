# 承: mathdisc设计文档v1§4 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-expr/v0.1.0
"""ast 白名单访问器 (承工程文档§1 grammar.py: parse(str)→IR|GrammarError 显式拒).

安全 (承设计文档§4 注入面): 表达式字符串是唯一注入面, ast 白名单是唯一入口;
eval 路径结构性不存在 (选型定案§2: 落选 sympify 字符串路径=已知注入面).

不变量 (承工程文档§2 expr):
  I1 白名单外节点/函数名 → GrammarError 显式拒 (回执, 非异常穿透)
"""
# impl: mathdisc-D1 | 承mathdisc设计文档v1§4 + 工程文档§2 expr-I1
from __future__ import annotations

import ast

from .ir import IR

# impl: mathdisc-D1 | 承工程文档§2 expr-I1
class GrammarError(Exception):
    """白名单外节点/函数/超深 → 显式拒 (承 I1; 消费方转回执, 非异常穿透)."""


# ── 白名单 (承设计文档§2: ast白名单访问器, 允许节点表+函数表; ST2 查表) ──
# impl: mathdisc-D1 | 承mathdisc设计文档v1§2
ALLOWED_FUNCS: frozenset[str] = frozenset({
    "sqrt", "sin", "cos", "tan", "exp", "log", "abs", "zeta", "factorial",
    "isprime",  # 谓词 (counterex 域消费, sympy.ntheory)
})
ALLOWED_CONST_NAMES: frozenset[str] = frozenset({"pi", "e"})
ALLOWED_BINOPS: dict[type, str] = {
    ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
    ast.Pow: "**", ast.Mod: "%",
}
# 默认深度限 (工程文档未钉默认值, 取 EXP-03 实测口径 32; 调用方可显式覆盖)
# impl: mathdisc-D1 | 承mathdisc测试文件 EXP-03
DEFAULT_D_MAX = 32

# 文法版本 (承工程文档§2 mathdisc.lock: 白名单/节点集变更=文法升版, 入 lock 治理)
# impl: mathdisc-D7 | 承mathdisc工程文档v1§2
GRAMMAR_V = "g-v1"


def parse(src: str, d_max: int = DEFAULT_D_MAX) -> IR:
    """解析表达式字符串为 IR; 白名单外/超深 → GrammarError (承 I1).

    d_max: 深度限 (承工程文档§4 EXP 深度限执法).
    """
    # impl: mathdisc-D1 | 承工程文档§1 grammar.py
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise GrammarError(f"语法错误: {e}") from e
    return _visit(tree.body, d_max)


def _visit(node: ast.AST, d_max: int, depth: int = 1) -> IR:
    # impl: mathdisc-D1 | 承EXP-03 深度限执法
    if depth > d_max:
        raise GrammarError(f"超深度限 d_max={d_max} (承 EXP-03)")

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise GrammarError(f"非常量数值: {node.value!r} (白名单仅 int/float)")
        # 整数字面量规范化为 int 串 (1.0 与 1 同形不同义——浮点字面量保留原样,
        # 精确域(reach/recurrence)禁浮点由 check 层执法, 不在文法层)
        v = repr(node.value)
        return IR(kind="num", value=v, depth=depth)

    if isinstance(node, ast.Name):
        return IR(kind="sym", value=node.id, depth=depth)

    if isinstance(node, ast.BinOp):
        op = ALLOWED_BINOPS.get(type(node.op))
        if op is None:
            raise GrammarError(f"白名单外算符: {type(node.op).__name__}")
        left = _visit(node.left, d_max, depth + 1)
        right = _visit(node.right, d_max, depth + 1)
        return IR(kind="binop", value=op, children=(left, right), depth=depth)

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return IR(kind="neg", children=(_visit(node.operand, d_max, depth + 1),), depth=depth)
        if isinstance(node.op, ast.UAdd):
            return _visit(node.operand, d_max, depth + 1)
        raise GrammarError(f"白名单外一元算符: {type(node.op).__name__}")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise GrammarError("函数调用仅允许白名单名直接调用 (禁属性/返回函数调用)")
        if node.func.id not in ALLOWED_FUNCS:
            raise GrammarError(f"白名单外函数: {node.func.id}")
        if node.keywords:
            raise GrammarError("禁关键字实参 (注入面最小化)")
        args = tuple(_visit(a, d_max, depth + 1) for a in node.args)
        return IR(kind="call", value=node.func.id, children=args, depth=depth)

    if isinstance(node, ast.Subscript):
        # 递推下标 a[n-1] 仅此形态: base 必须为标识符, 下标为白名单表达式
        if not isinstance(node.value, ast.Name):
            raise GrammarError("下标基底仅允许标识符 (递推域 a[...] 形态)")
        index = _visit(node.slice, d_max, depth + 1)
        return IR(kind="subscript", value=node.value.id, children=(index,), depth=depth)

    raise GrammarError(f"白名单外节点: {type(node).__name__} (承 I1 显式拒)")
