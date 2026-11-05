"""T-A 投影参考实现.

evidence.grade → assumptions 逐条透传。
映射表唯一资产真源 = ta_projection.json; 本模块是其 Python 消费方,
TS adapter 读同一 JSON 机械翻译 (双消费方单真源, 映射表显式)。
"""
from __future__ import annotations

import json
from pathlib import Path

_TA_TABLE = json.loads(
    (Path(__file__).parent / "ta_projection.json").read_text("utf-8"))["rules"]


def _grade_to_assumption(grade: str) -> str | None:
    """grade → assumption 文案 (查表; 未命中 = 表缺档, 显式上抛非静默)."""
    for rule in _TA_TABLE:
        if grade == rule["match"] or grade.startswith(rule["match"]):
            tpl = rule.get("template")
            return None if tpl is None else tpl.replace("{grade}", grade)
    raise ValueError(f"ta_projection 表缺档: grade={grade} (丢一条=A8违例, 先补表再用)")


def project_ta_receipt(loop_result: dict) -> dict:
    """discover 循环结果 → T-A 回执:
    relations→output_ref 形状; evidence.grade 逐条→assumptions;
    三态→stop_reason 原样; 轮数与ρ调用数→cost 明细。
    """
    assumptions: list[dict] = []
    relation_receipts: list[dict] = []
    for rel in loop_result.get("relations", []):
        receipt = rel["receipt"]
        grade = receipt["evidence"]["grade"]
        note = _grade_to_assumption(grade)
        mine: list[str] = []
        if note is not None:
            assumptions.append({"statement": note, "source": rel["expr"]})
            mine.append(note)
        # 每条关系的逐条回执, 只增不删; 字段取自该候选的检查门回执原样,
        # validity 回执/调用方带了才带, 不带不伪造; assumptions 与总表 source=expr 的各条一致
        item = {"expr": rel["expr"], "verdict": receipt["verdict"],
                "evidence": receipt["evidence"], "assumptions": mine}
        if rel.get("validity") is not None:
            item["validity"] = rel["validity"]
        relation_receipts.append(item)
    metrics = loop_result.get("metrics", {})
    return {
        "stop_reason": loop_result["stop"],
        "relations": [r["expr"] for r in loop_result.get("relations", [])],
        "assumptions": assumptions,
        "cost": {"rounds": metrics.get("rounds"), "rho_calls": metrics.get("rho_calls")},
        "relation_receipts": relation_receipts,
    }
