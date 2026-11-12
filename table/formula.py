"""公式与条件式：同一行里各列的四则运算与函数，比较与 if，以及看整列的 total、cumsum。

自己解析，不用 eval。数值一律是 Decimal；有空值参与运算，结果为空；除以零，结果为空并记一条警告。
同一份公式也翻成 Excel 公式写进 xlsx（带算好的缓存值）。

2.1.0（执行令 table 包 2.1.0 G2、G4）：
  · 函数加 roundup、rounddown、ceiling、floor（语义照 Excel），and、or、not、if，total(列)、cumsum(列)；
  · 比较 > >= < <= = <>（也认 == 与 !=），数后可带 %（100% 即 1）；字面文字写在双引号里；
  · 不连续的函数（取整四个、比较）先把参数归整到 15 位有效数字（Excel 的显示精度），Excel 一侧写成
    ROUND(x,14-INT(LOG10(ABS(x)+(x=0))))；
  · 另给一个双精度求值（float_eval），build 时用来找“在 Excel 里重算可能不同”的格（只用于告警，不改结果）。
旧函数 round、abs、min、max 的求值与 Excel 写法不变。

2.2.0（执行令 table 包 2.2.0 G10、G17）：
  · 格公式（输入列的格写 {"$expr": 式}）可引用别的格：本表别行 @行id.列，别表 @表id/行id.列（与引擎从式里抽数的写法一致）；
  · 整列跨表汇总：sumif(表id.条件列, 本行的值, 表id.求和列)、countif(表id.条件列, 本行的值)、total(表id.列)；
  · 取整函数的步长、位数可省：roundup(x)、rounddown(x)、round(x) 取到整数，ceiling(x)、floor(x) 取到 1 的倍数；导出 Excel 时补全。
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, ROUND_UP, localcontext

FUNCS = {"round": (1, 2), "abs": (1, 1), "min": (2, 8), "max": (2, 8),
         "roundup": (1, 2), "rounddown": (1, 2), "ceiling": (1, 2), "floor": (1, 2),
         "and": (2, 8), "or": (2, 8), "not": (1, 1), "if": (3, 3)}
AGG = ("total", "cumsum")
XFUNCS = ("sumif", "countif")
EXCEL_FUNC = {"round": "ROUND", "abs": "ABS", "min": "MIN", "max": "MAX", "roundup": "ROUNDUP", "rounddown": "ROUNDDOWN",
              "ceiling": "CEILING", "floor": "FLOOR", "and": "AND", "or": "OR", "not": "NOT", "if": "IF"}
DISCONTINUOUS = ("roundup", "rounddown", "ceiling", "floor")
CMP = (">=", "<=", "<>", "!=", "==", ">", "<", "=")
CMP_NORM = {"!=": "<>", "==": "="}
TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?%?)|(?P<str>\"[^\"]*\"|“[^”]*”)|(?P<ref>@\w+(?:/\w+)?\.\w+)"
                   r"|(?P<qid>[^\W\d]\w*\.\w+)|(?P<id>[^\W\d][\w]*)"
                   r"|(?P<cmp>>=|<=|<>|!=|==|>|<|=)|(?P<op>[-+*/(),]))", re.UNICODE)
DATE_LIT = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
FN_LIST = "round、abs、min、max、roundup、rounddown、ceiling、floor、and、or、not、if、total、cumsum、sumif、countif"
MAX_LEN = 500
MAX_DEPTH = 40
SIG = 15


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
            raise FormulaError(f"公式里有不认识的字符：{s[i:i + 10]!r}（只能用列名、数字、+ - * / 和括号、比较 > >= < <= = <>、"
                               f"双引号里的文字，函数有 {FN_LIST}）")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
    return out


class _Parser:
    """式 := 加减 (比较符 加减)?；加减 := 项 (('+'|'-') 项)*；项 := 因子 (('*'|'/') 因子)*；
    因子 := ('-'|'+') 因子 | 数[%] | "文字" | 列 | 函数(参数…) | (式)"""

    def __init__(self, toks, resolve, resolve_ref=None, resolve_q=None):
        self.t, self.i, self.resolve, self.depth = toks, 0, resolve, 0
        self.resolve_ref, self.resolve_q = resolve_ref, resolve_q

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

    def _deeper(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("公式嵌套过深")

    def expr(self):
        self._deeper()
        node = self.arith()
        if self.peek()[0] == "cmp":
            op = self.take()
            node = ("cmp", CMP_NORM.get(op, op), node, self.arith())
            if self.peek()[0] == "cmp":
                raise FormulaError("比较不能连写（例如 a < b < c）；要两个条件同时成立请写 and(a < b, b < c)")
        self.depth -= 1
        return node

    def arith(self):
        node = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            node = ("bin", self.take(), node, self.term())
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
            self._deeper()
            inner = self.factor()
            self.depth -= 1
            return ("neg", inner) if v == "-" else inner
        if k == "num":
            self.take()
            if v.endswith("%"):
                return ("num", Decimal(v[:-1]) / 100)
            return ("num", Decimal(v))
        if k == "str":
            self.take()
            return ("str", v[1:-1])
        if k == "ref":
            self.take()
            if self.resolve_ref is None:
                raise FormulaError(f"{v}：引用某一格只能写在格公式（{{\"$expr\": 式}}）里；列公式整列同算，引用同一行的列")
            body, _, col = v[1:].rpartition(".")
            sid, _, rid = body.rpartition("/")
            return ("cref", self.resolve_ref(sid or None, rid, col))
        if k == "qid":
            raise FormulaError(f"{v}：表id.列 只能写在 sumif、countif、total 的参数里")
        if k == "id":
            self.take()
            if self.peek() == ("op", "("):
                name = v.lower()
                if name in AGG:
                    self.take("op", "(")
                    kk, vv = self.peek()
                    if kk == "qid" and name == "total":
                        self.take()
                        self.take("op", ")")
                        return ("xagg", "total", self._q(vv))
                    if kk != "id":
                        raise FormulaError(f"{name} 的参数是一列的名字，例如 {name}(金额)" + ("；别的表写 total(表id.列)" if name == "total" else ""))
                    self.take()
                    if self.peek() != ("op", ")"):
                        raise FormulaError(f"{name} 的参数是一列的名字，例如 {name}(金额)")
                    self.take("op", ")")
                    return ("agg", name, self.resolve(vv))
                if name in XFUNCS:
                    self.take("op", "(")
                    cond = self._qarg(name)
                    self.take("op", ",")
                    key = self.expr()
                    if name == "countif":
                        self.take("op", ")")
                        return ("countif", cond, key)
                    self.take("op", ",")
                    tot = self._qarg(name)
                    self.take("op", ")")
                    if tot[0] != cond[0]:
                        raise FormulaError("sumif 的条件列与求和列要在同一张表")
                    return ("sumif", cond, key, tot)
                if name not in FUNCS:
                    raise FormulaError(f"不认识的函数 {v}（可用：{FN_LIST}）")
                self.take("op", "(")
                args = [self.expr()]
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
                self.take("op", ")")
                lo, hi = FUNCS[name]
                if not lo <= len(args) <= hi:
                    raise FormulaError(f"{name} 要 {lo}–{hi} 个参数，给了 {len(args)} 个" if lo != hi else f"{name} 要 {lo} 个参数，给了 {len(args)} 个")
                if name in ("round", "roundup", "rounddown") and len(args) == 2 and args[1][0] != "num":
                    raise FormulaError(f"{name} 的第二个参数是保留的小数位数，要写数字")
                if name in ("ceiling", "floor") and len(args) == 2 and (args[1][0] != "num" or args[1][1] <= 0):
                    raise FormulaError(f"{name} 的第二个参数是取整的倍数，要写大于 0 的数字（缺省 1）")
                return ("fn", name, args)
            return ("col", self.resolve(v))
        if (k, v) == ("op", "("):
            self.take()
            node = self.expr()
            self.take("op", ")")
            return node
        raise FormulaError("公式不完整" if k is None else f"公式这里不能是 {v}")


    def _qarg(self, name):
        kk, vv = self.peek()
        if kk != "qid":
            raise FormulaError(f"{name} 的这个参数写 表id.列，例如 {name}(detail.科目, 科目{', detail.金额' if name == 'sumif' else ''})")
        self.take()
        return self._q(vv)

    def _q(self, v):
        if self.resolve_q is None:
            raise FormulaError(f"{v}：这里不能引用别的表")
        sid, _, col = v.partition(".")
        return self.resolve_q(sid, col)


def parse(src: str, resolve, resolve_ref=None, resolve_q=None):
    """resolve(名字) → 列 key；找不到时抛 FormulaError。
    resolve_ref(表id 或 None, 行id, 列) → 一格的定位（只在格公式里给）；resolve_q(表id, 列) → (表id, 列 key)（跨表汇总用）。"""
    return _Parser(tokenize(src), resolve, resolve_ref, resolve_q).parse()


def cell_refs(node, acc=None):
    """式里引用的格（cref 的定位）。"""
    acc = [] if acc is None else acc
    tag = node[0]
    if tag == "cref":
        acc.append(node[1])
    for k in _kids(node):
        cell_refs(k, acc)
    return acc


def sheet_refs(node, acc=None):
    """式里用到的别的表（跨表汇总）。"""
    acc = set() if acc is None else acc
    tag = node[0]
    if tag == "xagg":
        acc.add(node[2][0])
    elif tag in ("sumif", "countif"):
        acc.add(node[1][0])
    for k in _kids(node):
        sheet_refs(k, acc)
    return acc


def _kids(node):
    tag = node[0]
    if tag == "neg":
        return [node[1]]
    if tag in ("bin", "cmp"):
        return [node[2], node[3]]
    if tag == "fn":
        return list(node[2])
    if tag in ("sumif", "countif"):
        return [node[2]]
    return []


def refs(node, acc=None, rows=None):
    """本式引用的列。rows 给一个集合时另收“同一行里引用的列”（不含 total、cumsum 看的整列）。"""
    acc = set() if acc is None else acc
    tag = node[0]
    if tag == "col":
        acc.add(node[1])
        if rows is not None:
            rows.add(node[1])
    elif tag == "agg":
        acc.add(node[2])
    elif tag == "neg":
        refs(node[1], acc, rows)
    elif tag in ("bin", "cmp"):
        refs(node[2], acc, rows)
        refs(node[3], acc, rows)
    elif tag == "fn":
        for a in node[2]:
            refs(a, acc, rows)
    elif tag in ("sumif", "countif"):
        refs(node[2], acc, rows)
    return acc


def row_refs(node):
    out = set()
    refs(node, None, out)
    return out


def uses(node, names):
    """式里是否用到这些函数（或比较，用 "cmp" 表示；跨行用 "agg"）。"""
    tag = node[0]
    if tag == "fn" and node[1] in names:
        return True
    if tag in names:
        return True
    return any(uses(k, names) for k in _kids(node))


def live_refs(node):
    """化简以后公式还依赖的列（乘以 0 的项不算）：用于告警“公式的结果不依赖任何一列”（17 TL-30 v0.2.99）。"""
    tag = node[0]
    if tag == "col":
        return {node[1]}
    if tag in ("agg",):
        return {node[2]}
    if tag in ("xagg", "sumif", "countif", "cref"):
        return {"<ext>"}
    if tag == "bin" and node[1] == "*" and any(x[0] == "num" and x[1] == 0 for x in (node[2], node[3])):
        return set()
    out = set()
    for k in _kids(node):
        out |= live_refs(k)
    return out


def divides_by_column(node):
    """式里有没有“除以某一列”（比率类）。除以常数（如换算单位的 / 1000）不算。"""
    tag = node[0]
    if tag == "bin" and node[1] == "/" and refs(node[3]):
        return True
    return any(divides_by_column(k) for k in _kids(node))


# ---------------------------------------------------------------- 类型
def kind_of(node, kinds, where="公式"):
    """检查式的类型，返回 num / text / date / bool / empty（""，空）/ textlit / datelit。kinds: key → num|text|date|bool。"""
    tag = node[0]
    if tag == "num":
        return "num"
    if tag == "str":
        if node[1] == "":
            return "empty"
        return "datelit" if _date_lit(node[1]) else "textlit"
    if tag == "col":
        return kinds[node[1]]
    if tag == "agg":
        if kinds[node[2]] != "num":
            raise FormulaError(f"{node[1]} 只能用于数值列")
        return "num"
    if tag == "cref":
        return kinds[node[1]]
    if tag == "xagg":
        if kinds[node[2]] != "num":
            raise FormulaError("total 只能用于数值列")
        return "num"
    if tag in ("sumif", "countif"):
        k = _lit_as(kind_of(node[2], kinds), "text")
        ck = kinds[node[1]]
        if ck == "num" and k != "num" or ck != "num" and k == "num":
            raise FormulaError(f"{tag} 的条件列与本行的值要同一类")
        if tag == "sumif" and kinds[node[3]] != "num":
            raise FormulaError("sumif 的求和列要是数值列")
        return "num"
    if tag == "neg":
        _need_num(kind_of(node[1], kinds), "取负")
        return "num"
    if tag == "bin":
        _need_num(kind_of(node[2], kinds), node[1])
        _need_num(kind_of(node[3], kinds), node[1])
        return "num"
    if tag == "cmp":
        a, b = kind_of(node[2], kinds), kind_of(node[3], kinds)
        a, b = _lit_as(a, b), _lit_as(b, a)
        if a != b or a not in ("num", "text", "date"):
            raise FormulaError(f"比较 {node[1]} 两边要同一类：数与数、日期与日期（日期写 \"YYYY-MM-DD\"）、文字与文字")
        if a == "text" and node[1] not in ("=", "<>"):
            raise FormulaError("文字只能比是否相等（= 或 <>）")
        return "bool"
    if tag == "fn":
        name, args = node[1], node[2]
        ks = [kind_of(x, kinds) for x in args]
        if name in ("and", "or", "not"):
            if any(k != "bool" for k in ks):
                raise FormulaError(f"{name} 的参数要是条件（比较或 and、or、not）")
            return "bool"
        if name == "if":
            if ks[0] != "bool":
                raise FormulaError("if 的第一个参数要是条件，例如 if(执行率 > 100%, \"超支\", \"正常\")")
            out = []
            for x, k in zip(args[1:], ks[1:]):
                if k == "num" and not refs(x) and not cell_refs(x):
                    raise FormulaError("if 的两支不收数字常数（公式不把数据原样带进表）：要数就引用一列，或把数写在输入格里")
                if k not in ("num", "textlit", "datelit", "empty"):
                    raise FormulaError("if 的两支是算式或双引号里的文字")
                out.append("text" if k in ("textlit", "datelit") else k)
            kinds2 = set(out) - {"empty"}
            if len(kinds2) > 1:
                raise FormulaError("if 的两支要同一类：都是算式，或都是文字（\"\" 表示空）")
            return kinds2.pop() if kinds2 else "empty"
        for k in ks:
            _need_num(k, name)
        return "num"
    raise AssertionError(tag)


def _lit_as(a, other):
    if a == "datelit":
        return "date" if other in ("date", "datelit") else "text"
    if a == "textlit":
        return "text"
    return a


def _need_num(k, op):
    if k != "num":
        raise FormulaError(f"{op} 只能用于数（数值列、数字或算式）；文字、日期、条件不能参与计算")


def _date_lit(s):
    m = DATE_LIT.match(s)
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------- 十进制求值
def sig(d: Decimal) -> Decimal:
    """归整到 15 位有效数字（G4）。"""
    if d == 0 or not d.is_finite():
        return d
    with localcontext() as ctx:
        ctx.prec = 60
        return d.quantize(Decimal(1).scaleb(d.adjusted() - (SIG - 1)), rounding=ROUND_HALF_UP)


def evaluate(node, row, cols=None, ri=0, ext=None):
    """row: key → Decimal | str | bool | None。cols: key → 整列的值（total、cumsum 用），ri 为本行序号。
    ext：格公式与跨表汇总的取值——ext.cell(定位) → 那一格的值；ext.column((表id, 列 key)) → 那张表那一列的值。
    返回 Decimal | str | bool | None；除以零抛 DivZero。"""
    with localcontext() as ctx:
        ctx.prec = 34
        return _ev(node, row, cols, ri, ext)


def match_key(v):
    """跨表汇总的等值匹配：文字不分大小写（与 Excel 的 = 相同），数照数比。"""
    if isinstance(v, str):
        return ("s", v.casefold())
    if isinstance(v, Decimal):
        return ("n", v)
    return ("o", v)


def _xsum(ext, cond, key, tot):
    if key is None:
        return None
    want = match_key(key)
    cv = ext.column(cond)
    sv = ext.column(tot) if tot is not None else None
    s, n = Decimal(0), 0
    for i, v in enumerate(cv):
        if v is not None and match_key(v) == want:
            n += 1
            if sv is not None and isinstance(sv[i], Decimal):
                s += sv[i]
    ext.matched(n)
    return s if tot is not None else Decimal(n)


def _ev(node, row, cols, ri, ext=None):
    tag = node[0]
    if tag == "cref":
        return ext.cell(node[1])
    if tag == "xagg":
        return sum((v for v in ext.column(node[2]) if isinstance(v, Decimal)), Decimal(0))
    if tag in ("sumif", "countif"):
        k = _ev(node[2], row, cols, ri, ext)
        return _xsum(ext, node[1], k, node[3] if tag == "sumif" else None)
    if tag == "num":
        return node[1]
    if tag == "str":
        return None if node[1] == "" else node[1]
    if tag == "col":
        return row.get(node[1])
    if tag == "agg":
        vals = [v for v in (cols[node[2]] if node[1] == "total" else cols[node[2]][:ri + 1]) if isinstance(v, Decimal)]
        return sum(vals, Decimal(0))
    if tag == "neg":
        v = _ev(node[1], row, cols, ri, ext)
        return None if v is None else -v
    if tag == "bin":
        a, b = _ev(node[2], row, cols, ri, ext), _ev(node[3], row, cols, ri, ext)
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
    if tag == "cmp":
        a, b = _ev(node[2], row, cols, ri, ext), _ev(node[3], row, cols, ri, ext)
        if a is None or b is None:
            return None
        return _compare(node[1], a, b, sig)
    if tag == "fn":
        name = node[1]
        if name == "if":
            c = _ev(node[2][0], row, cols, ri, ext)
            if c is None:
                return None
            return _ev(node[2][1] if c else node[2][2], row, cols, ri, ext)
        args = [_ev(x, row, cols, ri, ext) for x in node[2]]
        if any(a is None for a in args):
            return None
        if name == "and":
            return all(args)
        if name == "or":
            return any(args)
        if name == "not":
            return not args[0]
        if name == "abs":
            return abs(args[0])
        if name == "min":
            return min(args)
        if name == "max":
            return max(args)
        if name in ("ceiling", "floor"):
            m = args[1] if len(args) == 2 else Decimal(1)
            q = sig(args[0]) / m
            return q.to_integral_value(rounding=ROUND_CEILING if name == "ceiling" else ROUND_FLOOR) * m
        n = int(args[1]) if len(args) == 2 else 0
        if not -10 <= n <= 10:
            raise FormulaError(f"{name} 保留的位数在 -10 到 10 之间")
        x = args[0] if name == "round" else sig(args[0])
        mode = {"round": ROUND_HALF_UP, "roundup": ROUND_UP, "rounddown": ROUND_DOWN}[name]
        try:
            return x.quantize(Decimal(1).scaleb(-n), rounding=mode)
        except InvalidOperation:
            return x
    raise AssertionError(tag)


def _compare(op, a, b, norm):
    if isinstance(a, str) or isinstance(b, str):
        da, db = _as_date(a), _as_date(b)
        if da is not None and db is not None:
            a, b = da, db
        else:
            a, b = str(a).casefold(), str(b).casefold()     # Excel 比文字不分大小写
    elif not isinstance(a, bool):
        a, b = norm(a), norm(b)
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "=": a == b, "<>": a != b}[op]


def _as_date(v):
    if isinstance(v, _dt.date):
        return v
    if isinstance(v, str):
        return _date_lit(v)
    return None


# ---------------------------------------------------------------- 双精度求值（G4 检测）
def float_eval(node, row, cols=None, ri=0, ext=None):
    """照 Excel 的双精度直接算一遍（不做 15 位归整）。返回 (值, 是否经过不连续的函数或比较)。
    别的格、跨表汇总取产出台的值（双精度化），只比本格这一步。"""
    hit = [False]
    try:
        v = _fv(node, {k: _flt(x) for k, x in row.items()}, cols, ri, hit, ext)
    except ZeroDivisionError:
        v = None
    except (OverflowError, ValueError):
        v = None
    return v, hit[0]


def _flt(v):
    return float(v) if isinstance(v, Decimal) else v


def _fv(node, row, cols, ri, hit, ext=None):
    tag = node[0]
    if tag in ("cref", "xagg", "sumif", "countif"):
        with localcontext() as c:
            c.prec = 34
            return _flt(_ev(node, {k: (Decimal(repr(v)) if isinstance(v, float) else v) for k, v in row.items()}, cols, ri, ext))
    if tag == "num":
        return float(node[1])
    if tag == "str":
        return None if node[1] == "" else node[1]
    if tag == "col":
        return row.get(node[1])
    if tag == "agg":
        vals = cols[node[2]] if node[1] == "total" else cols[node[2]][:ri + 1]
        s = 0.0
        for v in vals:
            if isinstance(v, Decimal):
                s += float(v)
        return s
    if tag == "neg":
        v = _fv(node[1], row, cols, ri, hit, ext)
        return None if v is None else -v
    if tag == "bin":
        a, b = _fv(node[2], row, cols, ri, hit, ext), _fv(node[3], row, cols, ri, hit, ext)
        if a is None or b is None:
            return None
        return {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b}[node[1]]()
    if tag == "cmp":
        hit[0] = True
        a, b = _fv(node[2], row, cols, ri, hit, ext), _fv(node[3], row, cols, ri, hit, ext)
        if a is None or b is None:
            return None
        return _compare(node[1], a, b, lambda x: x)
    if tag == "fn":
        name = node[1]
        if name == "if":
            c = _fv(node[2][0], row, cols, ri, hit, ext)
            if c is None:
                return None
            return _fv(node[2][1] if c else node[2][2], row, cols, ri, hit, ext)
        args = [_fv(x, row, cols, ri, hit, ext) for x in node[2]]
        if any(a is None for a in args):
            return None
        if name == "and":
            return all(args)
        if name == "or":
            return any(args)
        if name == "not":
            return not args[0]
        if name == "abs":
            return abs(args[0])
        if name == "min":
            return min(args)
        if name == "max":
            return max(args)
        x = args[0]
        if name in ("ceiling", "floor"):
            hit[0] = True
            m = args[1] if len(args) == 2 else 1.0
            return (math.ceil(x / m) if name == "ceiling" else math.floor(x / m)) * m
        n = int(args[1]) if len(args) == 2 else 0
        p = 10.0 ** n
        if name == "round":
            return float(Decimal(repr(x)).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))
        hit[0] = True
        t = abs(x) * p
        r = (math.ceil(t) if name == "roundup" else math.floor(t)) / p
        return math.copysign(r, x) if r else 0.0
    raise AssertionError(tag)


# ---------------------------------------------------------------- Excel
def to_excel(node, cell_of, kinds=None, agg_of=None):
    """cell_of(key) → 'B2'；agg_of(name, key) → 'SUM($E$2:$E$7)'。返回不带等号的 Excel 公式。
    kinds 给出时，不连续函数的参数与比较的两边按 15 位有效数字归整（G4）。"""
    tag = node[0]
    if tag == "num":
        return format(node[1], "f")
    if tag == "str":
        return '"' + node[1].replace('"', '""') + '"'
    if tag == "col":
        return cell_of(node[1])
    if tag == "agg":
        return agg_of(node[1], node[2])
    if tag == "cref":
        return cell_of(node[1])
    if tag in ("xagg", "sumif", "countif"):
        key = to_excel(node[2], cell_of, kinds, agg_of) if tag != "xagg" else None
        return agg_of(tag, node, key)
        return "-" + _paren(node[1], cell_of, kinds, agg_of)
    if tag == "bin":
        return f"{_paren(node[2], cell_of, kinds, agg_of)}{node[1]}{_paren(node[3], cell_of, kinds, agg_of)}"
    if tag == "cmp":
        a, b = node[2], node[3]
        da = kinds is not None and _is_date_side(a, b, kinds)
        sa = _side(a, cell_of, kinds, agg_of, da)
        sb = _side(b, cell_of, kinds, agg_of, da)
        return f"{sa}{node[1]}{sb}"
    if tag == "fn":
        name = node[1]
        args = [to_excel(a, cell_of, kinds, agg_of) for a in node[2]]
        if name in DISCONTINUOUS:
            if node[2][0][0] != "num":
                args[0] = sig_excel(args[0])
            if len(args) == 1:
                args.append("0" if name in ("roundup", "rounddown") else "1")
        elif name == "round" and len(args) == 1:
            args.append("0")
        return f"{EXCEL_FUNC[name]}({','.join(args)})"
    raise AssertionError(tag)


def _is_date_side(a, b, kinds):
    def k(x):
        try:
            return kind_of(x, kinds)
        except FormulaError:
            return None
    return "date" in (k(a), k(b))


def _side(x, cell_of, kinds, agg_of, date_cmp):
    if x[0] == "str":
        d = _date_lit(x[1])
        if date_cmp and d is not None:
            return f"DATE({d.year},{d.month},{d.day})"
        return '"' + x[1].replace('"', '""') + '"'
    s = to_excel(x, cell_of, kinds, agg_of)
    if kinds is None or date_cmp or x[0] == "num":
        return _wrap(x, s)
    try:
        if kind_of(x, kinds) != "num":
            return _wrap(x, s)
    except FormulaError:
        return _wrap(x, s)
    return sig_excel(s)


def _wrap(x, s):
    return f"({s})" if x[0] in ("bin", "neg", "cmp") else s


def sig_excel(s: str) -> str:
    """Excel 里把 s 归整到 15 位有效数字。x=0 时 LOG10 无定义，加 (x=0) 绕开。"""
    a = s if re.fullmatch(r"\$?[A-Z]+\$?\d+", s) else f"({s})"
    return f"ROUND({a},14-INT(LOG10(ABS({a})+({a}=0))))"


def _paren(node, cell_of, kinds=None, agg_of=None):
    s = to_excel(node, cell_of, kinds, agg_of)
    return f"({s})" if node[0] in ("bin", "neg", "cmp") else s
