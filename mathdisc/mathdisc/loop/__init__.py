# 承: mathdisc工程文档v1§1 · 层: 工具·环0 · 版本: mathdisc-loop/v0.1.0
# 工具包 mathdisc 1.0.0 只带封闭枚举求解；发现循环（solve/rho）随 discover 另行成包。
from .solve_closed import solve_closed

__all__ = ["solve_closed"]
