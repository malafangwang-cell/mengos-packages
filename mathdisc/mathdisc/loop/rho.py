"""FIND_RELATIONS 编排 ρ.

prompt 渲染 / JSON 解析 / I1 核验 (refs⊆V, ops⊆T, depth, form) ——
本模块是 ρ 唯一调用点; mock 经 LLMClient Protocol 注入,
全循环离线可测。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..llm.client import LLMClient

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "find_relations_v3.txt"
PROMPT_VERSION = "find_relations_v3"  # 版本入 lock
# 提示词版本说明: v3 按 PROGRAM 形式逐段组织(TYPE/INPUT/MAP/INVARIANT/OUTPUT/HALT + I3自律),
#   OUTPUT 为 {"candidates":[{lhs,rhs,form}]}。
#   文本变更=资产升版


def _candidate_to_expr(item: object, f_task: str) -> str | None:
    """设计原生候选对象 → 门消费的表达式串;
    形状缺字段/类型错 → 返回 None (废该条, 违一废该条; 判定仍全归门, 本步只翻译形状)."""
    if not isinstance(item, dict) or not isinstance(item.get("lhs"), str) or not item["lhs"].strip():
        return None
    lhs = item["lhs"]
    # form 声明与任务型不符 → 废该条 (MAP: form(c)=F_task;
    #   F_task 含参形态 reach(target=24) 时, 模型合法地回 form="reach" 或全串, 两者皆收 ——
    #   严格等值判据会把 reach 候选全废)
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
    refs/ops/depth/form 的废单条执法在 solve._i1_check (门侧唯一, 废单条不废轮)。
    """
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
        # 兼容: 部分网关后端的回包以 ```json 围栏包裹
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
