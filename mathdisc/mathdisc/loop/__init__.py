# 承: mathdisc工程文档v1§1 · 层: 工具·环0 · 版本: mathdisc-loop/v0.1.0
# 本包入口按需导入子模块（from mathdisc.loop.solve import solve），不在此处预载，
# 免得同步判定类工具为用不到的发现循环多载数学库。
from .solve_closed import solve_closed

__all__ = ["solve_closed"]
