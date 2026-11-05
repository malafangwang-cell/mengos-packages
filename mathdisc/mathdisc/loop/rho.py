# 承: mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-loop/v0.1.0
"""FIND_RELATIONS 编排 ρ (承工程文档§1 loop/rho.py).

prompt 渲染 / JSON 解析 / I1 核验 (refs⊆V, ops⊆T, depth, form) ——
本模块是 ρ 唯一调用点 (承工程文档§2 loop-I3); mock 经 LLMClient Protocol 注入,
全循环离线可测 (承 §2 llm/loop 纪律)。
"""
# impl: mathdisc-D4 | 承mathdisc工程文档v1§1 loop/rho.py
from __future__ import annotations

import json
from pathlib import Path

from ..llm.client import LLMClient

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "find_relations_v3.txt"
PROMPT_VERSION = "find_relations_v3"  # 版本入 lock (承工程文档§2 mathdisc.lock)
# v1→v2 (2026-08-18, 承D8实测): 补五型候选形状段 —— 实测 P4 模型用单"="(I1形态全废)、
#   P5 未给赋值形态(裸"n"); v2 逐型钉死候选形状。
# v2→v3 (2026-08-18, 承立法者指令"严谨对齐设计文档prompt"):
#   v2 是 D8 期自造散文形 —— 恰为上游§2明文废除的形态("废除GEN_EQ/GEN_CONJ两件散文形prompt");
#   v3 逐段对齐上游§2 PROGRAM FIND_RELATIONS 原文(TYPE/INPUT/MAP/INVARIANT/OUTPUT/HALT + I3自律),
#   OUTPUT 回设计原生形状 {"candidates":[{lhs,rhs,form}]}, v2 的归一桥接拆除(承ST3不留workaround)。
#   文本变更=资产升版(承工程文档§2 lock治理)


def _candidate_to_expr(item: object, f_task: str) -> str | None:
    """设计原生候选对象 → 门消费的表达式串 (承上游§2 OUTPUT {"candidates":[{lhs,rhs,form}]});
    形状缺字段/类型错 → 返回 None (废该条, 承 I1 违一废该条精神; 判定仍全归门, 本步只翻译形状)."""
    # impl: mathdisc-D4 | 承数学发现最小闭环-独立设计v1§2 OUTPUT
    if not isinstance(item, dict) or not isinstance(item.get("lhs"), str) or not item["lhs"].strip():
        return None
    lhs = item["lhs"]
    # form 声明与任务型不符 → 废该条 (承上游§2 MAP: form(c)=F_task;
    #   F_task 含参形态 reach(target=24) 时, 模型合法地回 form="reach" 或全串, 两者皆收 ——
    #   2026-08-18 D8-v3实测: 严格等值判据把 reach 候选全废, P1 崩至 1-2/12)
    base = f_task.split("(")[0]
    if "form" in item and item["form"] not in (base, f_task):
        return None
    if f_task.startswith("identity"):
        rhs = item.get("rhs")
        return f"{lhs} == {rhs}" if isinstance(rhs, str) and rhs.strip() else None
    if f_task.startswith("counterex"):
        rhs = item.get("rhs")
        return f"{lhs}={rhs}" if isinstance(rhs, str) and rhs.strip() else None
    return lhs  # formula/recurrence/reach: rel = ⟨lhs⟩ (rhs∅)


def make_rho(client: LLMClient, prompt_path: Path = PROMPT_PATH):
    """构造真 ρ: (V, T, sig, f_task, dead, n_max) → 候选表达式串列表.

    I1 形状核验在此层只做设计 OUTPUT 契约形状 ({"candidates":[...]});
    refs/ops/depth/form 的废单条执法在 solve._i1_check (门侧唯一, 承 loop-I1 废单条不废轮)。
    """
    # impl: mathdisc-D4 | 承工程文档§2 loop-I3 (ρ调用点唯一)
    template = prompt_path.read_text("utf-8")

    def rho(V: list, T: list[str], sig, f_task: str, dead: list[str],
            n_max: int) -> list[str]:
        prompt = (template
                  .replace("{F_TASK}", f_task)
                  .replace("{N_MAX}", str(n_max))
                  .replace("{V_JSON}", json.dumps(V, ensure_ascii=False))
                  .replace("{T_JSON}", json.dumps(T, ensure_ascii=False))
                  .replace("{SIG_JSON}", json.dumps(sig.to_dict() if sig else {}, ensure_ascii=False))
                  .replace("{DEAD_JSON}", json.dumps(dead, ensure_ascii=False)))
        raw = client.complete(prompt)
        # ★2026-09-01 实测修复 (真ρ能力测试发现): 万擎网关后端回包以 ```json 围栏包裹
        #   设计原生形状 —— 契约形状本身合法, 剥围栏/提取首个{...}后解析;
        #   契约消费侧鲁棒化, prompt 模板文本不动 (文法/prompt 版本不变)。
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return []
            try:
                obj = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return []
        if not isinstance(obj, dict) or not isinstance(obj.get("candidates"), list):
            return []
        out: list[str] = []
        for c in obj["candidates"]:
            expr = _candidate_to_expr(c, f_task)
            if expr is not None:
                out.append(expr)
        return out[:n_max]

    return rho
