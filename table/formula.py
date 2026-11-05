"""公式列：同一行里各列的四则运算，外加 round、abs、min、max。

自己解析，不用 eval。数值一律是 Decimal；有空值参与运算，结果为空；除以零，结果为空并记一条警告。
同一份公式也翻成 Excel 公式写进 xlsx（带算好的缓存值）。
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

FUNCS = {"round": (1, 2), "abs": (1, 1), "min": (2, 8), "max": (2, 8)}
EXCEL_FUNC = {"round": "ROUND", "abs": "ABS", "min": "MIN", "max": "MAX"}
TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<id>[^\W\d][\w]*)|(?P<op>[-+*/(),]))", re.UNICODE)
MAX_LEN = 500
MAX_DEPTH = 40


class FormulaError(Exception):
    pass


class DivZero(Exception):
    pass


def tokenize(src: str):
    if not isinstance(src, str) or not src.strip():
        raise FormulaError("公式不能为空")
    if len(src) > MAX_LEN:
        raise FormulaError(f"公式超过 {MAX_LEN} 个字符")
    s = src.strip()
    if s.startswith("="):
        s = s[1:]
    out, i = [], 0
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        m = TOKEN.match(s, i)
        if not m or m.end() == i:
            raise FormulaError(f"公式里有不认识的字符：{s[i:i + 10]!r}（只能用列名、数字、+ - * / 和括号，函数有 round、abs、min、max）")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
    return out


class _Parser:
    """表达式 := 项 (('+'|'-') 项)*；项 := 因子 (('*'|'/') 因子)*；因子 := ('-'|'+') 因子 | 数 | 列 | 函数(参数…) | (表达式)"""

    def __init__(self, toks, resolve):
        self.t, self.i, self.resolve, self.depth = toks, 0, resolve, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, kind=None, val=None):
        k, v = self.peek()
        if k is None or (kind and k != kind) or (val and v != val):
            want = val or {"num": "数字", "id": "列名", "op": "运算符"}.get(kind, "更多内容")
            raise FormulaError(f"公式不完整：这里应当是 {want}")
        self.i += 1
        return v

    def parse(self):
        node = self.expr()
        if self.i != len(self.t):
            raise FormulaError(f"公式多出了内容：{self.t[self.i][1]}")
        return node

    def expr(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("公式嵌套过深")
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            node = ("bin", self.take(), node, self.term())
        self.depth -= 1
        return node

    def term(self):
        node = self.factor()
        while self.peek() in (("op", "*"), ("op", "/")):
            node = ("bin", self.take(), node, self.factor())
        return node

    def factor(self):
        k, v = self.peek()
        if (k, v) in (("op", "-"), ("op", "+")):
            self.take()
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise FormulaError("公式嵌套过深")
            inner = self.factor()
            self.depth -= 1
            return ("neg", inner) if v == "-" else inner
        if k == "num":
            self.take()
            return ("num", Decimal(v))
        if k == "id":
            self.take()
            if self.peek() == ("op", "("):
                name = v.lower()
                if name not in FUNCS:
                    raise FormulaError(f"不认识的函数 {v}（可用：round、abs、min、max）")
                self.take("op", "(")
                args = [self.expr()]
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
                self.take("op", ")")
                lo, hi = FUNCS[name]
                if not lo <= len(args) <= hi:
                    raise FormulaError(f"{name} 要 {lo}–{hi} 个参数，给了 {len(args)} 个" if lo != hi else f"{name} 要 {lo} 个参数，给了 {len(args)} 个")
                if name == "round" and len(args) == 2 and args[1][0] != "num":
                    raise FormulaError("round 的第二个参数是保留的小数位数，要写数字")
                return ("fn", name, args)
            return ("col", self.resolve(v))
        if (k, v) == ("op", "("):
            self.take()
            node = self.expr()
            self.take("op", ")")
            return node
        raise FormulaError("公式不完整" if k is None else f"公式这里不能是 {v}")


def parse(src: str, resolve):
    """resolve(名字) → 列 key；找不到时抛 FormulaError。"""
    return _Parser(tokenize(src), resolve).parse()


def refs(node, acc=None):
    acc = set() if acc is None else acc
    tag = node[0]
    if tag == "col":
        acc.add(node[1])
    elif tag == "neg":
        refs(node[1], acc)
    elif tag == "bin":
        refs(node[2], acc)
        refs(node[3], acc)
    elif tag == "fn":
        for a in node[2]:
            refs(a, acc)
    return acc


def evaluate(node, row):
    """row: key → Decimal | None。返回 Decimal | None；除以零抛 DivZero。"""
    with localcontext() as ctx:
        ctx.prec = 34
        return _ev(node, row)


def _ev(node, row):
    tag = node[0]
    if tag == "num":
        return node[1]
    if tag == "col":
        return row.get(node[1])
    if tag == "neg":
        v = _ev(node[1], row)
        return None if v is None else -v
    if tag == "bin":
        a, b = _ev(node[2], row), _ev(node[3], row)
        if a is None or b is None:
            return None
        op = node[1]
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise DivZero
        return a / b
    if tag == "fn":
        name, args = node[1], [_ev(x, row) for x in node[2]]
        if any(a is None for a in args):
            return None
        if name == "abs":
            return abs(args[0])
        if name == "min":
            return min(args)
        if name == "max":
            return max(args)
        n = int(args[1]) if len(args) == 2 else 0
        if not -10 <= n <= 10:
            raise FormulaError("round 保留的位数在 -10 到 10 之间")
        try:
            return args[0].quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            return args[0]
    raise AssertionError(tag)


def to_excel(node, cell_of):
    """cell_of(key) → 'B2'。返回不带等号的 Excel 公式。"""
    tag = node[0]
    if tag == "num":
        return format(node[1], "f")
    if tag == "col":
        return cell_of(node[1])
    if tag == "neg":
        return "-" + _paren(node[1], cell_of)
    if tag == "bin":
        return f"{_paren(node[2], cell_of)}{node[1]}{_paren(node[3], cell_of)}"
    if tag == "fn":
        args = [to_excel(a, cell_of) for a in node[2]]
        if node[1] == "round" and len(args) == 1:
            args.append("0")
        return f"{EXCEL_FUNC[node[1]]}({','.join(args)})"
    raise AssertionError(tag)


def _paren(node, cell_of):
    s = to_excel(node, cell_of)
    return f"({s})" if node[0] in ("bin", "neg") else s
