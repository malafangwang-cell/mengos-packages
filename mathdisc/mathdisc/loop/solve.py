# 承: mathdisc设计文档v1§1 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-loop/v0.1.0
"""SOLVE 轮循环 (承工程文档§1 loop/solve.py: 轮循环/dedup/dead累积/三态停机).

不变量 (承工程文档§2 loop):
  I1 I1核验(refs⊆V, ops⊆T, depth, form)废单条不废轮; dead 按方向累积
  I2 三态如实: solved / exhausted(候选全废∧无新方向, 可判定义) / budget
  I3 ρ 调用点唯一 (rho 注入, 本模块不直接碰 LLM); mock 注入全循环可离线测

幻觉经济学 (承设计§0③): 假发现是常态不是异常 —— 废弃桶只增轮数, R 零污染;
  门 (check 阶梯) 是唯一防线, 假阳性经门后 = 0。
"""
# impl: mathdisc-D4 | 承mathdisc工程文档v1§1 loop/solve.py + §2 loop
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable

from ..check.counterex import check_counterexample
from ..check.formula import check_formula
from ..check.identity import check_identity
from ..check.reach import check_reach
from ..check.receipt import Receipt
from ..check.recurrence import check_recurrence
from ..expr.grammar import GrammarError, parse
from ..expr.ir import IR
from ..expr.render import to_readable


def _valuable_subexprs(ir: IR, V: list) -> list[str]:
    """成功关系的子表达式回注素材 (承上游§4: "V ∪= 有价值子表达式" ——
    被计算器验证成立的复合子式, 是后续轮 ρ 的合法新积木; 叶子(字面量/符号)无增量不回注).

    2026-08-18 G8 施工: 语义定案 = "有价值 ⟺ 出门关系的非叶子子式" (门已担保其价值,
    不另立启发式 —— 启发式是新的智慧面, 承上游§8② "配置不是智慧" 同纪律);
    回注为**可读表达式串** (to_readable, 非 canonical —— canonical 带 num:/sym: 类型前缀
    是程序内部形态, 模型不可读; 回注对象要进 ρ 输入, 必须是文法合法表达式, 承 I1 refs⊆V)。
    """
    # impl: mathdisc-D4 | 承数学发现最小闭环-独立设计v1§4 (2026-08-18 G8)
    out: list[str] = []
    def walk(node: IR) -> None:
        if node.kind in ("binop", "call"):  # 复合式 = 有价值积木
            out.append(to_readable(node))
        for c in node.children:
            walk(c)
    walk(ir)
    return [s for s in out if s not in {str(v) for v in V}]


def _description_length(expr: str) -> int:
    """描述长度 (承上游§4/§7: 奥卡姆作呈现排序不作真值; MDL从账本降为呈现一函数)."""
    # impl: mathdisc-D4 | 承数学发现最小闭环-独立设计v1§4 排序/§7 降格
    return len(expr)

# I1 核验的深度档 (承工程文档§2 loop-I1: depth 是 I1 核验维度之一)
_I1_DEPTH_MAX = 32


@dataclass(frozen=True)
class Relation:
    """出门关系 (承 LOP-05: 每条带 Receipt 且 verdict∈verified 族 —— R 零污染)."""
    expr: str
    receipt: Receipt


@dataclass
class SolveResult:
    """SOLVE 循环结果 (三态如实, 承 I2)."""
    stop: str                       # solved | exhausted | budget
    relations: list[Relation] = field(default_factory=list)
    dead: list[str] = field(default_factory=list)        # refuted 方向累积
    metrics: dict = field(default_factory=dict)          # rounds/discarded/discarded_i1/rho_calls
    resume_state: dict | None = None                     # budget 态可续 (承 LOP-01)


# ρ 签名 (承工程文档§1 rho.py 调用形状)
Rho = Callable[[list, list[str], Any, str, list[str], int], list[str]]


def _identifiers(ir: IR) -> tuple[set[str], set[str]]:
    """提取 (数值字面量集, 标识符集) —— I1 refs 核验素材."""
    # impl: mathdisc-D4 | 承工程文档§2 loop-I1 (refs⊆V)
    if ir.kind == "num":
        return {ir.value}, set()
    if ir.kind == "sym":
        return set(), {ir.value}
    if ir.kind == "subscript":
        lits, syms = _identifiers(ir.children[0])
        syms.discard("n")  # n 是递推内建标识符 (承 check-I5 同纪律)
        return lits, syms | {ir.value}
    lits: set[str] = set()
    syms: set[str] = set()
    for c in ir.children:
        cl, cs = _identifiers(c)
        lits |= cl
        syms |= cs
    return lits, syms


def _ops_used(ir: IR) -> set[str]:
    """提取算符+函数名集 —— I1 ops⊆T 核验素材."""
    # impl: mathdisc-D4 | 承工程文档§2 loop-I1 (ops⊆T)
    if ir.kind == "binop":
        return {ir.value} | _ops_used(ir.children[0]) | _ops_used(ir.children[1])
    if ir.kind == "call":
        out = {ir.value}
        for c in ir.children:
            out |= _ops_used(c)
        return out
    if ir.kind in ("neg", "subscript"):
        return _ops_used(ir.children[0]) if ir.kind == "subscript" else _ops_used(ir.children[0]) | {"-"}
    return set()


def _i1_check(cand: str, V: list, T: list[str], f_task: str) -> IR:
    """I1 核验: refs⊆V / ops⊆T / depth / form (废单条, 承 loop-I1); 过则返回 IR.

    reach 域数值字面量须 ∈ V (24点用牌纪律); recurrence/formula 域字面量为
    模板系数/指数, 豁免 refs⊆V (V 是数据非牌面); identity 域符号须 ∈ V∪{pi,e}
    (常数名是文法内建); counterex 域候选是 witness 赋值串, 不走表达式 IR。
    """
    # impl: mathdisc-D4 | 承工程文档§2 loop-I1 + rho.py I1核验(refs⊆V,ops⊆T,depth,form)
    if f_task == "counterex":
        # witness 形态 "n=40" (赋值串): 标识符须 ∈ V, 值须整数
        name, sep, value = cand.partition("=")
        if not sep or name.strip() not in {str(v) for v in V}:
            raise GrammarError(f"I1: witness 形态/标识符违例: {cand}")
        int(value.strip())  # 非整数 → ValueError 上抛 (I1 废)
        return parse(value.strip())  # 返回值侧 IR (depth/form 核验)
    # identity 域: 候选形态 "lhs == rhs", 两侧分别 parse (strip: ast 拒前导空白)
    text = cand.strip()
    if f_task == "identity":
        lhs_s, sep, rhs_s = cand.partition("==")
        if not sep:
            raise GrammarError(f"I1: identity 候选形态须 lhs == rhs: {cand}")
        text = lhs_s.strip()
        parse(rhs_s.strip(), d_max=_I1_DEPTH_MAX)  # 右侧同样过文法 (form 维)
    ir = parse(text, d_max=_I1_DEPTH_MAX)  # GrammarError 上抛 = I1 废 (depth/form 维)
    lits, syms = _identifiers(ir)
    ops = _ops_used(ir)
    if f_task == "identity":
        rhs_ir = parse(cand.partition("==")[2].strip(), d_max=_I1_DEPTH_MAX)
        l2, s2 = _identifiers(rhs_ir)
        lits |= l2
        syms |= s2
        ops |= _ops_used(rhs_ir)
    if not ops <= set(T):
        raise GrammarError(f"I1: ops⊄T ({sorted(ops - set(T))} 未立法)")
    if f_task == "reach":
        v_lits = {str(v) for v in V}
        if not lits <= v_lits:
            raise GrammarError(f"I1: refs⊄V (字面量 {sorted(lits - v_lits)} 不在 V)")
    elif f_task == "identity":
        allowed = {str(v) for v in V} | {"pi", "e"}
        if not syms <= allowed:
            raise GrammarError(f"I1: refs⊄V∪内建常数 ({sorted(syms - allowed)})")
    elif f_task == "formula":
        allowed = {str(v) for v in V} | {f"c{i}" for i in range(1, 10)}
        if not syms <= allowed:
            raise GrammarError(f"I1: refs⊄V∪模板参数 ({sorted(syms - allowed)})")
    else:  # recurrence: 标识符仅限递推基底 (a 等) —— n/字面量豁免 (模板系数)
        pass
    return ir


def _gate(cand_ir: IR, cand: str, f_task: str, target, data, holdout_ratio, V: list) -> Receipt:
    """门: check 阶梯分派 (承设计§0③: 门是唯一防线; ST2 按 f_task 查表)."""
    # impl: mathdisc-D4 | 承mathdisc设计文档v1§0③
    if f_task == "reach":
        return check_reach(cand_ir, Fraction(target))
    if f_task == "recurrence":
        # 序列数据: data={known,holdout} 优先; 缺省以 V 为已知段 (承 LNP-01 调用形态)
        if isinstance(data, dict) and "known" in data:
            return check_recurrence(relation=cand, known=data["known"],
                                    holdout=data.get("holdout", []))
        seq = data if data is not None else V
        return check_recurrence(relation=cand, known=[int(v) for v in seq], holdout=[])
    if f_task == "formula":
        # 数据表承载: 变量列 x₁..xₖ + 响应列 "y" (承 R1-2 多变量, 留出比沿用既有字段)
        table = {k: list(v) for k, v in data.items()}
        if "y" not in table:
            raise ValueError("formula 域 data 缺响应列 'y' (数据表契约)")
        cut = max(1, int(len(table["y"]) * (1 - holdout_ratio)))
        train = {k: v[:cut] for k, v in table.items()}
        holdout = ({k: v[cut:] for k, v in table.items() if k != "y"},
                   table["y"][cut:])
        return check_formula(form=cand, data=train, holdout=holdout, seed=0)
    if f_task == "identity":
        lhs_s, _, rhs_s = cand.partition("==")
        # declared_dps 由 data 携带 (P4 探针 100 位), 缺省 50
        dps = int((data or {}).get("declared_dps", 50))
        return check_identity(parse(lhs_s.strip()), parse(rhs_s.strip()),
                              declared_dps=dps, try_symbolic=True)
    if f_task == "counterex":
        # 猜想由 data.conjecture 携带; 候选是 witness 赋值串 "n=40"
        name, _, value = cand.partition("=")
        return check_counterexample(conjecture=data["conjecture"],
                                    witness={name.strip(): int(value.strip())})
    raise ValueError(f"未知 f_task: {f_task}")


# 成功判据分派 (ST2 查表): counterex 域"发现"= 猜想被反驳 (反例成立, 承上游§3
# CHECK[counterex]); 其余四型 = established
# impl: mathdisc-D4 | 承数学发现最小闭环-独立设计v1§3
_SUCCESS_VERDICT = {"counterex": "refuted"}


def solve(V: list, T: list[str], f_task: str, rho: Rho,
          target: int | None = None, data=None, holdout_ratio: float = 0.25,
          budget: int = 3, n_max: int = 5, sig=None) -> SolveResult:
    """SOLVE 轮循环 (承工程文档§1; 三态如实, 承 I2)."""
    # impl: mathdisc-D4 | 承mathdisc工程文档v1§1 loop/solve.py
    result = SolveResult(stop="budget")
    dead: list[str] = []
    discarded = discarded_i1 = rho_calls = 0
    rounds = 0
    v_live = list(V)  # G8: 有价值子表达式回注的活对象集 (承上游§4 "V ∪= 有价值子表达式")

    # ρ 侧任务描述 (承上游§2: F_task ∈ {…, reach(target), counterex} —— target/conjecture
    #   是任务参数, 必须随 f_task 进 ρ 输入; solve 内部分派仍用基形 f_task)
    # impl: mathdisc-D8 | 承数学发现最小闭环-独立设计v1§2 INPUT
    task_desc = f_task
    if f_task == "reach" and target is not None:
        task_desc = f"reach(target={target})"
    elif f_task == "counterex" and isinstance(data, dict):
        task_desc = f"counterex({data['conjecture']})"

    while rounds < budget:
        cands = rho(v_live, T, sig, task_desc, dead, n_max)
        rho_calls += 1
        # I2 程序侧去重 (承上游§2 I2 "AST-hash去重" + §4 "for c in dedup(C)";
        #   字符串规范化等值: AST-hash 是 canonical 形态的别名, 承 grammar.canonical)
        cands = list(dict.fromkeys(c.strip() for c in cands))[:n_max]
        if not cands:
            result.stop = "exhausted"  # ρ 交空 (承 I2 exhausted 可判定义之半)
            break
        rounds += 1
        round_ok = 0
        round_dead_new = 0   # 本轮新入 dead 的方向数 (含求值废 —— 死结论方向不留痕即"无新方向")
        round_live = 0       # 本轮活方向数 (rejected/undetermined —— 模型收到信号, 非"全废")
        for cand in cands:
            try:
                ir = _i1_check(cand, v_live, T, f_task)
            except (GrammarError, ValueError):
                # 形态/值域违例 = 程序坏候选 (废单条不废轮, 承 I1;
                #   exhausted 语义: 程序坏不产"新方向"信号, 承上游§4 "C全废")
                discarded += 1
                discarded_i1 += 1
                continue
            try:
                receipt = _gate(ir, cand, f_task, target, data, holdout_ratio, v_live)
            except (GrammarError, ValueError, ZeroDivisionError, OverflowError):
                # 求值出精确域 = 死结论方向 (有结论但不合法 ⟹ 不留痕 = "无新方向")
                discarded += 1
                continue
            success = receipt.verdict == _SUCCESS_VERDICT.get(f_task, "established")
            if success:
                round_ok += 1
                result.relations.append(Relation(expr=cand, receipt=receipt))
                # G8 回注: 出门关系的非叶子子式进 v_live, 后续轮 ρ 可见 (承上游§4)
                for sub in _valuable_subexprs(ir, v_live):
                    v_live.append(sub)
            elif receipt.verdict == "refuted" and f_task != "counterex":
                dead.append(cand)  # dead 按方向累积 (承 I1), 进后续轮 ρ 输入
                round_dead_new += 1
                discarded += 1
            else:
                # 活方向 (rejected=可调参重试 / undetermined=方法未尽 / counterex谓词真=非反例):
                #   方向不入 dead (承上游§3), 但模型从"未反驳"收到信号 ⟹ 非"全废" (承§4)
                round_live += 1
                discarded += 1
        # goal 判定在整轮候选过完门之后 (承上游§4 SOLVE: "for c in dedup(C)" 全循环体
        #   后才查 goal —— 同轮其余 refuted 方向须进 dead, 否则下轮 ρ 重复提议已死方向)
        if result.relations:
            result.stop = "solved"  # goal(F_task,R): R 非空即解 (承上游§4)
            break
        # exhausted 真值 (承上游§4/工程文档 loop-I2: "C全废 ∧ 无新方向" ——
        #   全废 := 本轮无成功 ∧ 无活方向 (程序坏与死结论方向不留痕 = "无新方向"仍存活);
        #   rejected/undetermined 让模型收到"未反驳"信号, 不判 exhausted ——
        #   2026-08-18 D8 对齐回归实测: recurrence 域一条 rejected 曾致一轮误停)
        if round_ok == 0 and round_live == 0:
            # ★轮级记忆 (2026-08-18 金样对齐期实测修复): 下轮 ρ 若仍重复已死方向
            #   (dead 零增长) ⟹ "无新方向"跨轮成立, exhausted 即刻可判;
            #   新死方向(dead 增长)给 ρ 一次修正机会, 再交死方向才判穷尽。
            #   不判 exhausted 而直接烧 budget 会把"模型失忆"误报为"预算耗尽" (三态失真)。
            if round_dead_new == 0:
                result.stop = "exhausted"
                break
    else:
        result.stop = "budget"

    # 奥卡姆呈现排序 (承上游§4: "已验关系按描述长度升序呈现——奥卡姆作为呈现顺序,
    #   不作为真值"; §7: MDL账本→呈现排序一函数; 2026-08-18 对齐修复 G7)
    result.relations.sort(key=lambda rel: _description_length(rel.expr))
    if result.stop == "budget":
        result.resume_state = {"rounds_done": rounds, "dead": list(dead)}
    result.dead = dead
    result.metrics = {"rounds": rounds, "discarded": discarded,
                      "discarded_i1": discarded_i1, "rho_calls": rho_calls}
    return result
