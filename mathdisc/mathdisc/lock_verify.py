# 承: mathdisc工程文档v1§0 D-8/§2 · 层: 工具·环0 · 版本: mathdisc-lock/v0.1.0
"""mathdisc.lock 执法 (承工程文档§0 D-8: 四库版本/文法版/prompt版/ρ绑定
任一漂移 → 构造期拒; lock-hash = 工具 version, 承设计§3 S12 纪律)."""
# impl: mathdisc-D7 | 承mathdisc工程文档v1§0 D-8 + §2 mathdisc.lock
from __future__ import annotations

import hashlib
import json
from importlib.metadata import version as _pkg_version
from pathlib import Path

LOCK_PATH = Path(__file__).parent.parent / "mathdisc.lock"

# 实现版 (承裁决呈报v1.0 R1 版本纪律 2026-09-01: 改动入 lock, lock-hash 即工具 version;
# 与 grammar.GRAMMAR_V / rho.PROMPT_VERSION 同款执法形态, 漂移→构造期拒)
IMPL_V = "i-v2"


# impl: mathdisc-D7 | 承工程文档§0 D-8
class LockDriftError(Exception):
    """lock 漂移 → 构造期拒 (承 D-8)."""


def load_lock() -> dict:
    # impl: mathdisc-D7 | 承工程文档§2 mathdisc.lock
    return json.loads(LOCK_PATH.read_text("utf-8"))


def lock_hash() -> str:
    """lock-hash = 工具 version (承设计§3: 锁变即工具升版)."""
    # impl: mathdisc-D7 | 承mathdisc设计文档v1§3
    return hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()[:16]


def verify_lock(_inject_runtime: dict | None = None) -> dict:
    """lock 四键比对: 四库运行时版本 + 文法版 + prompt 版.

    _inject_runtime: 测试缝 (ADP-04 漂移注入); 生产路径不传。
    ρ 绑定校验待 QD1 裁决 (lock 中 model_id 空 = 未绑定, 跳过比对)。
    """
    # impl: mathdisc-D7 | 承工程文档§0 D-8 (任一漂移→构造期拒)
    from .expr import grammar as _grammar
    from .loop import rho as _rho

    lock = load_lock()
    runtime = {pkg: _pkg_version(pkg) for pkg in lock["deps"]}
    if _inject_runtime:
        runtime.update(_inject_runtime)
    drift: list[str] = []
    for pkg, pinned in lock["deps"].items():
        if runtime.get(pkg) != pinned:
            drift.append(f"{pkg}: lock={pinned} runtime={runtime.get(pkg)}")
    if lock["grammar_v"] != _grammar.GRAMMAR_V:
        drift.append(f"grammar_v: lock={lock['grammar_v']} runtime={_grammar.GRAMMAR_V}")
    if lock["prompt_v"] != _rho.PROMPT_VERSION:
        drift.append(f"prompt_v: lock={lock['prompt_v']} runtime={_rho.PROMPT_VERSION}")
    if lock.get("impl_v", "i-v1") != IMPL_V:
        drift.append(f"impl_v: lock={lock.get('impl_v')} runtime={IMPL_V}")
    if lock["rho_model"].get("model_id"):
        # ρ绑定校验 (QD1 已裁 2026-08-18): 一致性由构造保证 ——
        # client_from_lock 是 ρ客户端唯一构造点且直读 lock, 无双源可漂
        pass
    if drift:
        raise LockDriftError(f"mathdisc.lock 漂移 (承 D-8 构造期拒): {'; '.join(drift)}")
    return lock
