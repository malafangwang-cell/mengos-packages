# 承: mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-expr/v0.1.0
"""表达式内部表示 IR (承工程文档§1 ir.py: 节点类型/content_hash/规范形).

不变量 (承工程文档§2 expr):
  I2 同表达式同 content_hash (去重键); 规范形仅语法级 (交换律参数排序),
     语义等价不归并 —— 等价判定归 check 阶梯
"""
# impl: mathdisc-D1 | 承mathdisc工程文档v1§1 ir.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IR:
    """表达式内部表示 (不可变).

    kind: num(数值字面量) | sym(标识符/常量名) | call(白名单函数)
        | binop(二元算符) | neg(一元负) | subscript(递推下标 a[...], 仅递推域)
    """
    kind: str
    value: str = ""
    children: tuple["IR", ...] = field(default_factory=tuple)
    depth: int = 1

    @property
    def canonical(self) -> str:
        """规范形序列化 (承 I2: 交换律 +/* 参数排序, 仅语法级)."""
        # impl: mathdisc-D1 | 承工程文档§2 expr-I2
        if self.kind in ("num", "sym"):
            return f"{self.kind}:{self.value}"
        if self.kind == "neg":
            return f"neg({self.children[0].canonical})"
        if self.kind == "subscript":
            return f"{self.value}[{self.children[0].canonical}]"
        children = self.children
        if self.kind == "binop" and self.value in ("+", "*"):
            children = tuple(sorted(children, key=lambda c: c.canonical))
        inner = ",".join(c.canonical for c in children)
        if self.kind == "call":
            return f"{self.value}({inner})"
        return f"({children[0].canonical}{self.value}{children[1].canonical})"

    @property
    def content_hash(self) -> str:
        """去重键 (承 I2: 同表达式同 hash)."""
        return hashlib.sha256(self.canonical.encode("utf-8")).hexdigest()
