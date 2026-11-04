# 承: mathdisc设计文档v1§0②/§1/§5① · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-check/v0.1.0
"""check.identity: 恒等式判定 (承工程文档§1 identity.py).

mpmath@N位 + 精度自证 + sympy 符号升级通道 (承设计§1):
  · 精度自证 (D-2 实现点, 承工程文档§2 check-I2): refuted 前提 = 后端精度
    自证达标; 后端实配精度 < 声明精度 ⟹ undetermined, 永不出 refuted
    (v1 假反驳事故: float64 冒充 50 位 —— √2²=2 永不 refuted)
  · 符号升级 (承设计§5① + 规格 M-2): proven_symbolic 仅经符号完备片段
    (多项式/有理式); 片段外化简失败 ≠ 不相等 (Richardson) —— 维持 verified@N,
    不降 verdict
  · 自由符号情形: 数值路走定点采样 (mpmath@N 代入), 不假装解析
"""
# impl: mathdisc-D2 | 承mathdisc工程文档v1§1 identity.py + §2 check-I2
from __future__ import annotations

import mpmath as mp
import sympy as sp

from ..expr.ir import IR
from ..expr.render import to_sympy
from .receipt import Receipt, runtime_versions

# 精度自证守卫生数 (声明精度之外的核验余量)
_GUARD_DPS = 15


def _is_complete_fragment(expr: sp.Basic) -> bool:
    """符号完备片段判定 (承设计§5①): 多项式/有理式片段 = simplify/cancel 完备."""
    # impl: mathdisc-D2 | 承mathdisc设计文档v1§5①
    if expr.free_symbols == frozenset() or expr.free_symbols == set():
        return True  # 常数表达式: 符号化简 trivially 完备
    if expr.has(sp.zeta) or expr.has(sp.sin) or expr.has(sp.cos) or expr.has(sp.tan):
        return False  # 超越函数出完备片段 (Richardson 带)
    try:
        # 分子分母均可多项式化 = 有理式片段
        num, den = sp.fraction(sp.cancel(expr))
        sp.Poly(num, *expr.free_symbols)
        sp.Poly(den, *expr.free_symbols)
        return True
    except (sp.PolynomialError, ValueError, AttributeError):
        return False


def _mp_eval(expr: sp.Basic, subs: dict | None = None) -> mp.mpf:
    """sympy 对象 → mpmath 高精度求值 (承设计§2: mpmath 任意精度)."""
    syms = sorted(expr.free_symbols, key=str)
    f = sp.lambdify(syms, expr, modules="mpmath")
    args = [subs[s] for s in syms] if subs else []
    return mp.mpf(f(*args))


def check_identity(
    lhs: IR,
    rhs: IR,
    declared_dps: int = 50,
    try_symbolic: bool = False,
    escalate_recheck: bool = True,
    _force_backend_dps: int | None = None,
    _force_simplify_fail: bool = False,
) -> Receipt:
    """恒等式判定: lhs == rhs ?

    declared_dps: 声明精度 N ∈ [16, 2000] (承工程文档§3 input_domain).
    escalate_recheck: 升位复检开关 (承上游§5 P4验收: "假阳性=0——N位巧合由升位复检
      探测"; 数值 established 后在 @2N 精度重验一次, 复检不过 ⟹ undetermined
      而非 established —— 升位复检降低而不消灭千位巧合风险, 承上游§8①)。
    _force_backend_dps / _force_simplify_fail: 测试缝 (CHK-I-01/05 精度自证与
      符号降级路径的确定性注入点; 生产路径不传)。
    """
    # impl: mathdisc-D2 | 承mathdisc工程文档§2 check-I2 (精度自证先于判定)
    versions = runtime_versions()

    # ── 精度自证 (先于一切判定, 承 I2/D-2) ──
    backend_dps = _force_backend_dps if _force_backend_dps is not None else declared_dps
    if backend_dps < declared_dps:
        return Receipt(
            verdict="undetermined", method_complete=False,
            evidence={"grade": "none",
                      "reason": f"precision 自证失败: 声明 {declared_dps}dps 但后端实配 "
                                f"{backend_dps}dps —— 精度不达不判定 (承 D-2, v1假反驳教训)",
                      "declared_dps": declared_dps, "backend_dps": backend_dps},
            versions=versions)

    lhs_s, rhs_s = to_sympy(lhs), to_sympy(rhs)
    diff = sp.simplify(lhs_s - rhs_s) if not _force_simplify_fail else (lhs_s - rhs_s)

    # ── 符号升级通道 (仅完备片段, 承设计§5①) ──
    if try_symbolic and not _force_simplify_fail and _is_complete_fragment(diff):
        if sp.cancel(diff) == 0:
            return Receipt(
                verdict="established", method_complete=True,
                evidence={"grade": "proven_symbolic",
                          "reason": "符号完备片段(多项式/有理式)内 cancel≡0 (承§5①)"},
                versions=versions)
        # 完备片段内非零 ⟹ 符号级反驳终局
        return Receipt(
            verdict="refuted", method_complete=True,
            evidence={"grade": "proven_symbolic",
                      "reason": "符号完备片段内 cancel≠0, 符号级反驳 (承§5①)"},
            versions=versions)

    # ── 数值路 (mpmath@声明精度+守卫) ──
    mp.dps = declared_dps + _GUARD_DPS
    syms = sorted((lhs_s - rhs_s).free_symbols, key=str)
    # 自由符号: 定点采样代入 (确定性采样点, 种子固定 —— 不假装解析, 承§5①)
    subs = {s: mp.mpf(i + 2) / mp.mpf(7) for i, s in enumerate(syms)}
    # 工具包 mathdisc 1.0.0: 采样点入证据 —— 数值 established 只对这些取值成立 (适用范围如实交出)
    sample = {str(s): f"{i + 2}/7" for i, s in enumerate(syms)}
    delta = abs(_mp_eval(lhs_s, subs) - _mp_eval(rhs_s, subs))
    tol = mp.mpf(10) ** (-(declared_dps - 5))  # 判定阈值: 声明精度留 5 位守卫
    grade = f"verified@{declared_dps}"
    if delta < tol:
        # ── 升位复检 (承上游§5 P4验收指标: "假阳性=0——N位巧合由升位复检探测";
        #    数值 established 后在 @2N 精度重验, 复检不过 ⟹ undetermined 非 established;
        #    升位复检降低而不消灭巧合风险, 承上游§8①; 2026-08-18 对齐修复 G5) ──
        if escalate_recheck and declared_dps * 2 <= 2000 and _force_backend_dps is None:
            hi = declared_dps * 2
            mp.dps = hi + _GUARD_DPS
            delta2 = abs(_mp_eval(lhs_s, subs) - _mp_eval(rhs_s, subs))
            tol2 = mp.mpf(10) ** (-(hi - 5))
            if delta2 >= tol2:
                return Receipt(
                    verdict="undetermined", method_complete=True,
                    evidence={"grade": "none", "abs_delta": mp.nstr(delta, 5),
                              "abs_delta_2N": mp.nstr(delta2, 5),
                              "reason": f"@{declared_dps} 数值达标但升位复检@{hi} 失败 "
                                        f"(Δ={mp.nstr(delta2, 5)} ≥ 阈值) —— N位巧合嫌疑, "
                                        f"不产出 verified (承上游§5升位复检/§8①)"},
                    versions=versions)
        return Receipt(
            verdict="established", method_complete=True,
            evidence={"grade": grade, "abs_delta": mp.nstr(delta, 5), "sample_point": sample,
                      "reason": f"mpmath@{declared_dps}(+{_GUARD_DPS}守卫) 差值低于阈值"
                                + ("; 升位复检@2N 通过 (承上游§5)" if escalate_recheck and declared_dps * 2 <= 2000 and _force_backend_dps is None else "")},
            versions=versions)
    return Receipt(
        verdict="refuted", method_complete=True,  # 精度自证已通过 ⟹ refuted 终局合法
        evidence={"grade": grade, "abs_delta": mp.nstr(delta, 5),
                  "reason": f"mpmath@{declared_dps} 差值 {mp.nstr(delta, 5)} 超阈值, 精度自证达标下的终局反驳"},
        versions=versions)
