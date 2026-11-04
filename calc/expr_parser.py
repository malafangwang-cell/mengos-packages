r"""calc v2 · 表达式解析器（安全：不调用 eval/exec，不访问属性，只认白名单）

输入：模型常写的数学记法字符串，例如
    "2^n + n^2"、"2**7+7**2"、"√2·3"、"（3+4）×5"、"sin(30°)"、"x^2 - 4 = 0"
输出：一棵只含白名单节点的语法树（tuple），交给 evaluator 计算。

语法（优先级从低到高）：
    equation := expr ('=' expr)?
    expr     := term (('+'|'-') term)*
    term     := unary (('*'|'/') unary | <隐式乘法> unary)*
    unary    := ('-'|'+') unary | power
    power    := postfix ('^' unary)?           # 右结合；-2^2 = -(2^2)
    postfix  := atom ('!' | '%' | '°')*
    atom     := NUMBER | IDENT | IDENT '(' args ')' | '(' expr ')' | '|' expr '|'

约定（写进登记资产的 input_domain，供模型阅读）：
    · ^ 与 ** 都是乘方；× ÷ · − 和全角括号会被规范化；
    · % 是百分号（50% = 1/2）；取模用 mod(a, b)；
    · ° 是角度（sin(30°)）；
    · ln = 自然对数，lg = 常用对数，log(x) = 自然对数，log(x, b) = 以 b 为底；
    · 常数 pi/π、e、I（虚数单位）、oo/∞（无穷，仅极限用）；
    · 隐式乘法：2x、2(x+1)、(a+b)(a-b)、x(y+1) 都按乘法处理；
    · 接受常见 LaTeX：\frac{a}{b}、\sqrt{x}、2^{10}、\cdot、\times、\pi、\sin 等。
"""

from __future__ import annotations

import re
import unicodedata

MAX_LEN = 4000
MAX_TOKENS = 2000
MAX_DEPTH = 100
MAX_LITERAL_EXP = 10_000

FUNCTIONS = {
    # 名称: (最少参数, 最多参数)
    "sqrt": (1, 1), "cbrt": (1, 1), "root": (2, 2),
    "exp": (1, 1), "ln": (1, 1), "lg": (1, 1), "log": (1, 2), "log2": (1, 1), "log10": (1, 1),
    "sin": (1, 1), "cos": (1, 1), "tan": (1, 1), "cot": (1, 1), "sec": (1, 1), "csc": (1, 1),
    "asin": (1, 1), "acos": (1, 1), "atan": (1, 1), "atan2": (2, 2),
    "arcsin": (1, 1), "arccos": (1, 1), "arctan": (1, 1),
    "sinh": (1, 1), "cosh": (1, 1), "tanh": (1, 1),
    "abs": (1, 1), "sign": (1, 1), "floor": (1, 1), "ceil": (1, 1),
    "factorial": (1, 1), "binomial": (2, 2), "comb": (2, 2), "perm": (2, 2),
    "gcd": (2, 16), "lcm": (2, 16), "mod": (2, 2),
    "max": (1, 64), "min": (1, 64),
    "re": (1, 1), "im": (1, 1),
}
CONSTANTS = {"pi", "e", "I", "oo"}

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


class ParseError(ValueError):
    """输入不合语法；回执 code=BAD_INPUT。"""


def normalize(text: str) -> str:
    if not isinstance(text, str):
        raise ParseError("表达式必须是字符串")
    if len(text) > MAX_LEN:
        raise ParseError(f"表达式超长（>{MAX_LEN} 字符）")
    # 上标先转成 ^n（NFKC 会把 ² 变成 2，丢掉乘方含义）
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+", lambda m: "^" + m.group(0).translate(_SUPERSCRIPT), text)
    # LaTeX 的常见写法（模型常这样输出）：\frac{a}{b}、\sqrt{x}、2^{10}、\cdot、\times、\left( \right)
    text = re.sub(r"\\(left|right)\b", "", text)
    text = re.sub(r"\\(cdot|times)\b", "*", text)
    text = re.sub(r"\\div\b", "/", text)
    text = re.sub(r"\\([A-Za-z]+)", r" \1 ", text)
    text = text.replace("{", "(").replace("}", ")")
    text = text.replace("√", " sqrt ").replace("∞", " oo ").replace("π", " pi ")
    text = text.replace("×", "*").replace("÷", "/").replace("·", "*").replace("⋅", "*")
    text = text.replace("−", "-").replace("–", "-").replace("＝", "=")
    text = unicodedata.normalize("NFKC", text)  # 全角数字、字母、括号转半角
    text = text.replace("**", "^")
    return text


_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
    r"|(?P<id>[A-Za-z][A-Za-z0-9_]*)"
    r"|(?P<op>[-+*/^(),=!%°|])"
    r")"
)


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m or m.end() == pos:
            ch = text[pos:].lstrip()[:1]
            raise ParseError(f"无法识别的字符 {ch!r}（位置 {pos}）")
        pos = m.end()
        if m.group("num") is not None:
            num = m.group("num")
            if "e" in num.lower() and abs(int(re.split("[eE]", num)[1])) > MAX_LITERAL_EXP:
                raise ParseError(f"数字 {num} 的指数过大（上限 {MAX_LITERAL_EXP}）")
            tokens.append(("num", num))
        elif m.group("id") is not None:
            ident = m.group("id")
            if "__" in ident:
                raise ParseError(f"非法标识符 {ident!r}")
            tokens.append(("id", ident))
        else:
            tokens.append(("op", m.group("op")))
        if len(tokens) > MAX_TOKENS:
            raise ParseError(f"表达式过长（>{MAX_TOKENS} 个记号）")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.toks = tokens
        self.i = 0
        self.depth = 0

    # ---- 基础 ----
    def peek(self, k: int = 0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, value: str):
        kind, v = self.take()
        if v != value:
            raise ParseError(f"此处应为 {value!r}，实际是 {v!r}")

    def enter(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ParseError(f"嵌套过深（>{MAX_DEPTH} 层）")

    def leave(self):
        self.depth -= 1

    # ---- 语法 ----
    def equation(self):
        left = self.expr()
        if self.peek()[1] == "=":
            self.take()
            right = self.expr()
            node = ("eq", left, right)
        else:
            node = left
        if self.i != len(self.toks):
            raise ParseError(f"多余的记号 {self.peek()[1]!r}")
        return node

    def expr(self):
        self.enter()
        node = self.term()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            rhs = self.term()
            node = ("add", node, rhs) if op == "+" else ("sub", node, rhs)
        self.leave()
        return node

    def _starts_operand(self) -> bool:
        kind, v = self.peek()
        return kind in ("num", "id") or v in ("(",)

    def term(self):
        node = self.unary()
        while True:
            v = self.peek()[1]
            if v in ("*", "/"):
                self.take()
                rhs = self.unary()
                node = ("mul", node, rhs) if v == "*" else ("div", node, rhs)
            elif self._starts_operand():
                # 隐式乘法：数字后紧跟数字不算（"2 3" 多半是笔误）
                if self.peek()[0] == "num" and self._last_was_number(node):
                    raise ParseError("两个数字之间缺少运算符")
                rhs = self.power_level()
                node = ("mul", node, rhs)
            else:
                return node

    @staticmethod
    def _last_was_number(node) -> bool:
        return isinstance(node, tuple) and node[0] == "num"

    def unary(self):
        v = self.peek()[1]
        if v == "-":
            self.take()
            self.enter()
            node = ("neg", self.unary())
            self.leave()
            return node
        if v == "+":
            self.take()
            return self.unary()
        return self.power_level()

    def power_level(self):
        base = self.postfix()
        if self.peek()[1] == "^":
            self.take()
            self.enter()
            exponent = self.unary()  # 右结合，允许 2^-1
            self.leave()
            return ("pow", base, exponent)
        return base

    def postfix(self):
        node = self.atom()
        while self.peek()[1] in ("!", "%", "°"):
            op = self.take()[1]
            node = {"!": ("fact", node), "%": ("percent", node), "°": ("deg", node)}[op]
        return node

    def atom(self):
        kind, v = self.take()
        if kind is None:
            raise ParseError("表达式不完整")
        if kind == "num":
            return ("num", v)
        if kind == "id":
            if v == "frac" and self.peek()[1] == "(":
                # \frac{a}{b} 经规范化成 frac(a)(b)
                self.take()
                num = self.expr()
                self.expect(")")
                self.expect("(")
                den = self.expr()
                self.expect(")")
                return ("div", num, den)
            if self.peek()[1] == "(" and v in FUNCTIONS:
                self.take()
                args = []
                if self.peek()[1] != ")":
                    args.append(self.expr())
                    while self.peek()[1] == ",":
                        self.take()
                        args.append(self.expr())
                self.expect(")")
                lo, hi = FUNCTIONS[v]
                if not lo <= len(args) <= hi:
                    raise ParseError(f"{v} 需要 {lo}–{hi} 个参数，实际 {len(args)} 个")
                return ("call", v, tuple(args))
            if v in FUNCTIONS and self.peek()[0] in ("num", "id"):
                # sqrt 2、sin x 这类省括号写法：只吃一个 postfix 级操作数
                arg = self.postfix()
                lo, _ = FUNCTIONS[v]
                if lo != 1:
                    raise ParseError(f"{v} 需要括号和 {lo} 个参数")
                return ("call", v, (arg,))
            if v in FUNCTIONS:
                raise ParseError(f"函数 {v} 后缺少参数")
            if v in CONSTANTS:
                return ("const", v)
            return ("sym", v)
        if v == "(":
            node = self.expr()
            self.expect(")")
            return node
        if v == "|":
            node = self.expr()
            self.expect("|")
            return ("call", "abs", (node,))
        raise ParseError(f"此处不能出现 {v!r}")


def parse(text: str):
    """字符串 → 语法树；不合语法抛 ParseError。"""
    tokens = tokenize(normalize(text))
    if not tokens:
        raise ParseError("表达式为空")
    return _Parser(tokens).equation()
