# 承: mathdisc工程文档v1§1/§3 · 层: 工具·环0 · 版本: mathdisc-discover/v0.1.0
"""discover 作业体 (自主仓库 mathdisc/cli.py 的 run-solve 路径摘出; 其余同步单元走各自入口).

与 run-solve 的差别只在宿主形态: 包内不落盘 (workdir=false), 循环结果直接返回给 md_tool 投影;
ρ 的取得方式在 make_rho_from_env: 缺省真 ρ (lock 绑定, 钥匙只从环境变量取), 仅当环境变量
MATHDISC_RHO_MOCK=1 时为空 ρ, 供管道自检用 (空 ρ 不产能力数据, 发布档由平台拒启该变量)。
入参不决定走不走 mock。
"""
# impl: mathdisc-D7 | 承mathdisc工程文档v1§3 + cli.py run-solve
from __future__ import annotations

import os
import time

MOCK_ENV = "MATHDISC_RHO_MOCK"


def make_rho_from_env():
    """ρ 构造点: 环境变量 MATHDISC_RHO_MOCK=1 → 空ρ; 否则真ρ (经 lock, 钥匙缺席显式上抛, 不降级)."""
    if os.environ.get(MOCK_ENV) == "1":
        def rho(V, T, sig, f_task, dead, n_max):  # noqa: ANN001, ANN202
            return []
        return rho
    from .llm.client import client_from_lock
    from .loop.rho import make_rho
    return make_rho(client_from_lock())


def run_solve(f_task: str, V: list, T: list[str], data, holdout: float,
              budget: int, n_max: int, rho=None) -> tuple:
    """跑 SOLVE 循环, 返回 (SolveResult, elapsed_s). rho 缺省取 make_rho_from_env()."""
    from .loop.solve import solve
    sig = None
    if f_task == "formula" and isinstance(data, dict):
        from .forensics.signature import signature
        sig = signature(y=[float(v) for v in data["y"]])
    if rho is None:
        rho = make_rho_from_env()
    t0 = time.monotonic()
    result = solve(V=V, T=T, f_task=f_task, rho=rho, data=data,
                   holdout_ratio=holdout, budget=budget, n_max=n_max, sig=sig)
    return result, round(time.monotonic() - t0, 2)
