# 承: mathdisc设计文档v1§1/§2 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-check/v0.1.0
"""check.formula: 公式验证 —— 拟合 + 四查 (承工程文档§1 formula.py).

  拟合: scipy least_squares (承设计§2 选型定案); ★seed 显式入回执可复现,
        初值取法医斜率 (P3 修复定案: 不盲猜 1.0, 承工程文档§2 check-I4)
  四查: 留出残差 / 参数上限 / 奇点扫描 / 量纲(可选 pint, 未装则记 skipped)
  证据等级 verified_on_data: 数据级验证 ≠ 证明 (承设计§5: A8 跨界不洗白)

2026-09-01 R1 施工 (承《mathdisc-formula域多变量支持缺口-裁决呈报v1.0》R1-1):
  数据契约单变量 x/y → 数据表 dict(变量列 x₁..xₖ + 响应列 "y", 行对齐),
  变量集 = 数据表列 − {"y"} (承上游设计 y=f(x₁..xₖ) §1 L47);
  lambdify 绑变量全集; 四查语义/阈值一字不动; I4 (seed 与初值来源入 evidence) 不变;
  多变量法医初值 basis = 排序后首变量列 (收敛退化则按裁决 R1 附带决定补金样标定)。
"""
# impl: mathdisc-D3 | 承mathdisc工程文档v1§1 formula.py + §2 check-I4
# impl: mathdisc-R1 | 承裁决呈报v1.0 R1-1 (2026-09-01 多变量数据表)
from __future__ import annotations

import hashlib
import re

import numpy as np
import sympy as sp
from scipy.optimize import least_squares

from ..expr.grammar import GrammarError, parse
from ..expr.render import to_sympy
from ..forensics.signature import loglog_init
from .receipt import Receipt, runtime_versions

_PARAM_RE = re.compile(r"^c\d+$")
# 四查阈值 (承工程文档§1 四查定义; 数值为本实现定案, 漂移走版本事件)
_HOLDOUT_REL_TOL = 0.05   # 留出相对 RMSE 上限
_PARAM_ABS_MAX = 1e6      # 参数幅值上限
_GRID = 200               # 奇点扫描网格数
# 多变量奇点扫描求值预算 (R1-1 施工): 单维网格 = min(_GRID, max(8, 预算**(1/k)))
# 总量钉 2e6 — k=1 路径不变 (200 点), k=2 → 200²/维≤40万, k=3 → 125³≈195万
_SING_EVAL_BUDGET = 2_000_000


def _data_fingerprint(data: dict[str, list[float]],
                      holdout: tuple[dict[str, list[float]], list[float]]) -> str:
    """训练+留出数据指纹 (承上游§3 verified_on_data⟨D指纹,…⟩; repr 精确序列 sha256)."""
    # impl: mathdisc-D3 | 承数学发现最小闭环-独立设计v1§3 (2026-08-18 G4对齐)
    # impl: mathdisc-R1 | 多变量: 指纹覆盖整张数据表 (同式不同数据 ⟹ 不同指纹)
    payload = repr((dict(data), holdout)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _exponent_params(expr: sp.Basic, var: sp.Symbol, params: list[str]) -> set[str]:
    """出现在 var 指数位的参数集 (初值分档依据: 幂次参数 ← 法医斜率)."""
    # impl: mathdisc-D3 | 承工程文档§2 check-I4
    # impl: mathdisc-R1 | 多变量: var = basis 变量 (仅该列的指数位入档)
    out: set[str] = set()
    for p in params:
        if expr.has(sp.Pow(var, sp.Symbol(p))) or any(
            a.is_Pow and a.exp.has(sp.Symbol(p)) for a in expr.atoms(sp.Pow)
        ):
            out.add(p)
    return out


def check_formula(
    form: str,
    data: dict[str, list[float]],
    holdout: tuple[dict[str, list[float]], list[float]],
    seed: int,
    k_max: int | None = None,
) -> Receipt:
    """公式验证: form(含参数 c1..ck 与变量 x₁..xₖ) 对数据表拟合 + 四查.

    data: 数据表 — 变量列(可多个, k≥1) + 响应列 "y", 行对齐
          (承上游设计 §1 L47 y=f(x₁..xₖ));
    holdout: (留出变量列 dict, 留出响应 list).
    """
    # impl: mathdisc-D3 | 承mathdisc工程文档v1§1 formula.py
    # impl: mathdisc-R1 | 承裁决呈报v1.0 R1-1 (数据表多变量)
    versions = runtime_versions()
    expr = to_sympy(parse(form))
    params = sorted((str(s) for s in expr.free_symbols if _PARAM_RE.match(str(s))),
                    key=lambda s: int(s[1:]))

    # ── 数据表契约边界校验 (R1-1; 程序侧显式拒, refs⊆V 的 I1 兜底之外) ──
    if "y" not in data:
        raise GrammarError("数据表缺响应列 'y'")
    vars_ = sorted(k for k in data if k != "y")
    if not vars_:
        raise GrammarError("数据表缺变量列 (仅 'y')")
    n_rows = len(data["y"])
    if any(len(col) != n_rows for col in data.values()):
        raise GrammarError("数据表列长不齐 (行对齐违例)")
    refs = {str(s) for s in expr.free_symbols} - set(params)
    if not refs <= set(vars_):
        raise GrammarError(f"form 引用变量不在数据表中: {sorted(refs - set(vars_))}")

    # 参数上限查之契约段: 自由参数超 k_max → rejected (可调参重试, 非终局, 承 CHK-F-04)
    if k_max is not None and len(params) > k_max:
        return Receipt(
            verdict="rejected", method_complete=False,
            evidence={"grade": "none", "k": len(params), "k_max": k_max,
                      "reason": f"自由参数 {len(params)} 超 k_max={k_max} (承§1 参数上限查)"},
            versions=versions)

    # ── 拟合: 初值取法医斜率 (承 I4: seed 与初值来源入 evidence) ──
    # R1-1: 多变量 basis = 排序后首变量列 (单变量路径逐字不变)
    basis = vars_[0]
    slope, scale = loglog_init(list(data[basis]), list(data["y"]))
    exp_params = _exponent_params(expr, sp.Symbol(basis), params)
    p0 = [slope if p in exp_params else (scale if p == params[0] else 1.0) for p in params]
    f = sp.lambdify([*vars_, *params], expr, modules="numpy")

    def _cols(table: dict[str, list[float]]) -> list[np.ndarray]:
        return [np.asarray(table[v], dtype=float) for v in vars_]

    def resid(p: np.ndarray) -> np.ndarray:
        return np.asarray(f(*_cols(data), *p), dtype=float) - np.asarray(data["y"], dtype=float)

    fit = least_squares(resid, p0, method="lm" if n_rows >= len(params) else "trf")
    fitted = {p: float(v) for p, v in zip(params, fit.x)}
    evidence = {
        "grade": "verified_on_data", "params": fitted, "seed": seed,
        # D指纹 (承上游§3: verified_on_data⟨D指纹, 留出残差, 参数⟩ —— 数据指纹入回执,
        #   同式不同数据 ⟹ 不同 verified_on_data 证据; 2026-08-18 对齐修复 G4)
        "data_fingerprint": _data_fingerprint(data, holdout),
        "fitter_init_source": "forensics_slope",  # 承 I4/P3: 初值来源入回执
        "p0_source": {"slope": slope, "scale": scale, "basis_var": basis},
    }

    # ── 四查 (承§1) ──
    # 查0 训练残差 (2026-08-18 D8实测事故修复: "x+x"(零自由参数)冒充开普勒定律,
    #   恰在留出区与真律相交致假阳性出门 —— 训练残差与留出残差双查, 缺一不穿;
    #   阈值标定权归 P3 探针集, 承上游§8② "ε_val是配置不是智慧")
    pred_train = np.asarray(f(*_cols(data), *fit.x), dtype=float)
    rel_rmse_train = float(np.sqrt(np.mean((pred_train - np.asarray(data["y"], dtype=float)) ** 2))
                           / (np.mean(np.abs(data["y"])) + 1e-300))
    evidence["train_rel_rmse"] = rel_rmse_train
    if rel_rmse_train > _HOLDOUT_REL_TOL:
        return Receipt(verdict="refuted", method_complete=True,
                       evidence={**evidence, "failed_check": "train_residual",
                                 "reason": f"训练相对RMSE {rel_rmse_train:.4g} 超 {_HOLDOUT_REL_TOL} (零拟合能力候选显式拒)"},
                       versions=versions)
    # 查2 参数上限
    if any(abs(v) > _PARAM_ABS_MAX for v in fitted.values()):
        return Receipt(verdict="refuted", method_complete=True,
                       evidence={**evidence, "failed_check": "param_bound",
                                 "reason": "拟合参数幅值超上限"}, versions=versions)
    # 查3 奇点扫描 (数据区间内网格求值出现非有限值; R1-1: k>1 为张量网格)
    if len(vars_) == 1:
        grid = np.linspace(min(data[vars_[0]]), max(data[vars_[0]]), _GRID)
        scan = np.asarray(f(grid, *fit.x), dtype=float)
    else:
        per_dim = min(_GRID, max(8, int(_SING_EVAL_BUDGET ** (1 / len(vars_)))))
        axes = [np.linspace(min(data[v]), max(data[v]), per_dim) for v in vars_]
        mesh = np.meshgrid(*axes, indexing="ij")
        scan = np.asarray(f(*mesh, *fit.x), dtype=float)
    if not np.all(np.isfinite(scan)):
        return Receipt(verdict="refuted", method_complete=True,
                       evidence={**evidence, "failed_check": "singularity",
                                 "reason": "数据区间内存在奇点 (扫描网格非有限值)"}, versions=versions)
    # 查1 留出残差 (过拟合由数据判, 承 CHK-F-03)
    hcols, hy = holdout
    hy = np.asarray(hy, dtype=float)
    missing = [v for v in vars_ if v not in hcols]
    if missing:
        raise GrammarError(f"留出集缺变量列: {missing}")
    pred = np.asarray(f(*_cols(hcols), *fit.x), dtype=float)
    rel_rmse = float(np.sqrt(np.mean((pred - hy) ** 2)) / (np.mean(np.abs(hy)) + 1e-300))
    evidence["holdout_rel_rmse"] = rel_rmse
    if rel_rmse > _HOLDOUT_REL_TOL:
        return Receipt(verdict="refuted", method_complete=True,
                       evidence={**evidence, "failed_check": "holdout",
                                 "reason": f"留出相对RMSE {rel_rmse:.4g} 超 {_HOLDOUT_REL_TOL}"},
                       versions=versions)
    # 查4 量纲 (可选 extra: mathdisc[units]; 未安装记 skipped, 不静默省查)
    evidence["units_check"] = "skipped (pint 未安装, extra: mathdisc[units])"

    return Receipt(verdict="established", method_complete=True, evidence=evidence,
                   versions=versions)
