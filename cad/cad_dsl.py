r"""CAD 计划语言的解析器（安全：不经 eval，只认白名单）。

一行一个操作：

    # 注释
    units mm
    material 6061-T6
    let w = 80
    base: box w 50 20
    hole1: hole d=20 at=center from=top through
    pocket rect w=30 l=20 depth=5 at=(40,25) from=top
    fillet r=2 edges=vertical
    pattern hole1 linear n=3 dx=20

语法：
    line  := [name ':'] op arg*
    arg   := value | key '=' value
    value := expr | tuple | word
    tuple := '(' expr (',' expr)* ')'
    expr  := 数字、let 变量、pi、+ - * / ( ) 与一元负号

解析结果是 Stmt 列表；数值在解析时求出（let 变量按出现顺序生效）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

MAX_LINES = 300
MAX_LINE_LEN = 400

_TOKEN = re.compile(r"""
    (?P<ws>[ \t]+)
  | (?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)
  | (?P<word>[A-Za-z_一-鿿][A-Za-z0-9_一-鿿.]*)
  | (?P<op>[=:(),+\-*/%])
""", re.X)


class DslError(Exception):
    def __init__(self, line: int, message: str, hint: str = ""):
        super().__init__(message)
        self.line = line
        self.message = message
        self.hint = hint

    def to_dict(self):
        d = {"line": self.line, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        return d


@dataclass
class Stmt:
    line: int
    op: str
    name: str | None
    pos: list = field(default_factory=list)      # 位置参数（已求值）
    kw: dict = field(default_factory=dict)       # 关键字参数（已求值）
    src: str = ""


def _normalize(text: str) -> str:
    rep = {"（": "(", "）": ")", "，": ",", "：": ":", "＝": "=", "×": "*", "÷": "/", "−": "-", "　": " "}
    for a, b in rep.items():
        text = text.replace(a, b)
    return text


# 工程图上的记号（2.4.0）：只作用于代码部分，注释照旧不解析。
#   直径记号 Φ φ Ø ø ⌀ 写在数、名字或括号前 → 去掉（d= 已经说明是直径）；
#   数后的 ° → 去掉（角度一律按度）；数后的 mm → 去掉（长度一律按毫米）。
# 其余记号（R5、M8、±0.1 等）不猜，照常报错并给提示。
_DIA = re.compile(r"[ΦφØø⌀]\s*(?=[0-9.(A-Za-z_一-鿿])")
_DEG = re.compile(r"(?<=[0-9.)])\s*°")
_MM = re.compile(r"(?<=[0-9.])\s*mm\b")


def _engineering(s: str) -> str:
    return _MM.sub("", _DEG.sub("", _DIA.sub("", s)))


_HINTS = {
    "Φ": "直径记号只能写在数前，例如 d=Φ25；或直接写 d=25",
    "°": "角度直接写数，例如 angle=38（按度）",
    "±": "计划里不写公差；公差写进期望清单（cad.check）",
    "R": "圆角半径写 r=，例如 fillet r=5",
}


def _tokenize(s: str, ln: int):
    toks, i = [], 0
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m:
            raise DslError(ln, f"第 {ln} 行第 {i + 1} 个字符“{s[i]}”无法识别", _HINTS.get(s[i], ""))
        kind = m.lastgroup
        if kind != "ws":
            toks.append((kind, m.group()))
        i = m.end()
    return toks


class _Parser:
    def __init__(self, toks, ln, env):
        self.t, self.i, self.ln, self.env = toks, 0, ln, env

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, val):
        k, v = self.take()
        if v != val:
            raise DslError(self.ln, f"第 {self.ln} 行：这里应当是“{val}”，实际是“{v or '行尾'}”")

    # expr := term (('+'|'-') term)*
    def expr(self):
        v = self.term()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            r = self.term()
            v = v + r if op == "+" else v - r
        return v

    def term(self):
        v = self.unary()
        while self.peek()[1] in ("*", "/", "%"):
            op = self.take()[1]
            r = self.unary()
            if op == "*":
                v = v * r
            else:
                if r == 0:
                    raise DslError(self.ln, f"第 {self.ln} 行：除以零")
                v = v / r if op == "/" else v % r
        return v

    def unary(self):
        if self.peek()[1] == "-":
            self.take()
            return -self.unary()
        if self.peek()[1] == "+":
            self.take()
            return self.unary()
        return self.atom()

    def atom(self):
        k, v = self.take()
        if k == "num":
            x = float(v)
            if not math.isfinite(x) or abs(x) > 1e7:
                raise DslError(self.ln, f"第 {self.ln} 行：数值 {v} 超出范围")
            return x
        if v == "(":
            x = self.expr()
            self.expect(")")
            return x
        if k == "word":
            if v == "pi":
                return math.pi
            if v in self.env:
                return self.env[v]
            raise DslError(self.ln, f"第 {self.ln} 行：“{v}”不是数，也不是已定义的变量", "变量先用 let 定义，例如：let w = 80")
        raise DslError(self.ln, f"第 {self.ln} 行：这里应当是一个数，实际是“{v or '行尾'}”")

    def value(self):
        k, v = self.peek()
        if v == "(" and self._is_tuple():
            self.take()
            items = [self.expr()]
            while self.peek()[1] == ",":
                self.take()
                items.append(self.expr())
            self.expect(")")
            return tuple(items)
        if k == "word" and v not in self.env and v != "pi" and self.peek(1)[1] not in ("+", "-", "*", "/", "%"):
            self.take()
            return v
        return self.expr()

    def _is_tuple(self):
        depth, j = 0, self.i
        while j < len(self.t):
            v = self.t[j][1]
            if v == "(":
                depth += 1
            elif v == ")":
                depth -= 1
                if depth == 0:
                    return False
            elif v == "," and depth == 1:
                return True
            j += 1
        return False


def parse(text: str) -> list[Stmt]:
    if not isinstance(text, str) or not text.strip():
        raise DslError(0, "计划为空")
    text = _normalize(text)
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        raise DslError(0, f"计划超过 {MAX_LINES} 行")
    env: dict[str, float] = {}
    out: list[Stmt] = []
    names: set[str] = set()
    for ln, raw in enumerate(lines, 1):
        s = _engineering(raw.split("#", 1)[0]).strip()
        if not s:
            continue
        if len(s) > MAX_LINE_LEN:
            raise DslError(ln, f"第 {ln} 行超过 {MAX_LINE_LEN} 个字符")
        toks = _tokenize(s, ln)
        name = None
        if len(toks) >= 2 and toks[0][0] == "word" and toks[1][1] == ":":
            name = toks[0][1]
            if name in names:
                raise DslError(ln, f"第 {ln} 行：名字“{name}”已经用过")
            names.add(name)
            toks = toks[2:]
        if not toks or toks[0][0] != "word":
            raise DslError(ln, f"第 {ln} 行：缺少操作名")
        op = toks[0][1].lower()
        if op in ("material", "units"):
            rest = s.split(":", 1)[1] if name else s
            rest = rest.strip()[len(toks[0][1]):].strip()
            if not rest:
                raise DslError(ln, f"第 {ln} 行：{op} 后面缺少取值")
            out.append(Stmt(line=ln, op=op, name=name, pos=[rest], src=raw.strip()))
            continue
        p = _Parser(toks[1:], ln, env)
        if op == "let":
            k, var = p.take()
            if k != "word":
                raise DslError(ln, f"第 {ln} 行：let 后面应当是变量名")
            p.expect("=")
            val = p.expr()
            if p.peek()[0] is not None:
                raise DslError(ln, f"第 {ln} 行：表达式后面多了“{p.peek()[1]}”")
            env[var] = val
            continue
        st = Stmt(line=ln, op=op, name=name, src=raw.strip())
        while p.peek()[0] is not None:
            if p.peek()[0] == "word" and p.peek(1)[1] == "=":
                key = p.take()[1].lower()
                p.take()
                if key in st.kw:
                    raise DslError(ln, f"第 {ln} 行：参数“{key}”重复")
                st.kw[key] = p.value()
            else:
                st.pos.append(p.value())
        out.append(st)
    if not out:
        raise DslError(0, "计划里没有任何操作")
    return out
