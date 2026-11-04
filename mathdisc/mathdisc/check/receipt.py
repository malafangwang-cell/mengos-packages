# 承: mathdisc设计文档v1§1 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-check/v0.1.0
"""Receipt: 全套件唯一出口类型 (承工程文档§1 receipt.py).

⟨verdict, method_complete, evidence, versions⟩ (承设计§1 统一纪律):
  verdict ∈ established | refuted | undetermined | rejected
    established   判定成立 (精度/方法达标前提下)
    refuted       终局反驳 —— ★前提=后端精度自证达标 (承设计§0②, D-2)
    undetermined  超时/精度不达/资源限 —— 是回执不是异常 (承 I3)
    rejected      契约违例 (如参数超 k_max) —— 可调参重试, 非终局 (承 CHK-F-04)
  method_complete  方法完备性自证 (承规格 M-1: refuted 的终局性以此为准)
  evidence         证据字典 (含 grade: proven_symbolic | verified@N |
                   verified_on_data | verified_on_seq | none, 承上游§3 证据词汇表
                   + 工程文档§1 recurrence 命名沿用; 表外词禁入, 2026-08-18 G6对齐)
  versions         四库版本+文法版 (承 D-8 lock 治理随行)
"""
# impl: mathdisc-D2 | 承mathdisc工程文档v1§1 receipt.py
from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import version as _pkg_version

# verdict 值域 (封闭枚举, 承设计§1 三值回执 M-1..M-3 + rejected 契约拒)
# impl: mathdisc-D2 | 承mathdisc设计文档v1§1
VERDICTS = frozenset({"established", "refuted", "undetermined", "rejected"})


@dataclass(frozen=True)
class Receipt:
    """判定回执 (不可变; 全套件唯一出口, 承工程文档§1)."""
    verdict: str
    method_complete: bool
    evidence: dict = field(default_factory=dict)
    versions: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # ST1 早失败: verdict 出值域即拒 (封闭枚举执法点)
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict 出值域: {self.verdict} (承 receipt 封闭枚举)")


# impl: mathdisc-D2 | 承mathdisc工程文档§0 D-8 (versions 随行, lock 执法在 verify_lock)
def runtime_versions() -> dict:
    """四库运行时版本 (lock 漂移比对源, 承工程文档§2 mathdisc.lock)."""
    return {pkg: _pkg_version(pkg) for pkg in ("sympy", "mpmath", "scipy", "numpy")}
