# 承: mathdisc设计文档v1§2 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-forensics/v0.1.0
"""法医学签名 Σ_D (承工程文档§1 forensics/signature.py).

差分/比值/loglog斜率/FFT周期/单调 —— 全定性输出 (承工程文档§2 forensics-I1):
  输出枚举词, 禁定量数值 (P3 教训: 数值 hint 诱导 ρ 输出数值而非公式)。
  词表封闭 (VOCAB): 新 hint 词 = 改契约, 先改文档再改码 (承测试README纪律3)。
"""
# impl: mathdisc-D3 | 承mathdisc工程文档v1§1 forensics/signature.py + §2 forensics-I1
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# 封闭定性词表 (承 FRS-01: set(hints) ≤ VOCAB; 新词=改契约)
# impl: mathdisc-D3 | 承mathdisc测试文件README纪律3
VOCAB = frozenset({
    "power_lt_1", "power_near_1", "power_gt_1",  # loglog 斜率档 (定性)
    "ratio_linear_in_n", "ratio_constant",        # 比值表形态 (定性)
    "periodic", "monotonic", "nonmonotonic",      # 周期/单调 (定性)
})


@dataclass(frozen=True)
class Signature:
    """法医签名: 仅定性 hints (承 I1 禁定量数值)."""
    hints: tuple[str, ...]

    VOCAB = VOCAB

    def to_dict(self) -> dict:
        # 只含定性词 —— 任何定量数值不入 dict (承 I1/FRS-01 白盒断言)
        return {"hints": sorted(self.hints)}


def _loglog_slope(x: list[float], y: list[float]) -> float:
    """loglog 斜率 (内部定量计算, 仅用于定性分档与 fitter 初值, 不出现在输出)."""
    lx = [math.log(v) for v in x if v > 0]
    ly = [math.log(abs(v)) for v, xv in zip(y, x) if xv > 0 and v != 0]
    if len(lx) < 2 or len(ly) < 2:
        return 1.0
    return float(np.polyfit(lx, ly[: len(lx)], 1)[0])


def loglog_init(x: list[float], y: list[float]) -> tuple[float, float]:
    """loglog 斜率+截距 → fitter 初值源 (承工程文档§2 check-I4: 法医斜率初值入 evidence).

    返回 (slope, scale): scale = exp(截距) 作系数初值, slope 作幂次初值。
    """
    # impl: mathdisc-D3 | 承mathdisc工程文档v1§2 check-I4 (P3修复定案: 不盲猜1.0)
    lx = [math.log(v) for v in x if v > 0]
    ly = [math.log(abs(v)) for v, xv in zip(y, x) if xv > 0 and v != 0]
    if len(lx) < 2:
        return 1.0, 1.0
    slope, intercept = np.polyfit(lx, ly[: len(lx)], 1)
    return float(slope), float(math.exp(intercept))


def signature(x: list[float] | None = None, y: list[float] | None = None,
              seq: list[float] | None = None) -> Signature:
    """Σ_D 法医签名: 定性 hint 集 (承工程文档§1; 输出枚举词, 承 I1)."""
    # impl: mathdisc-D3 | 承mathdisc工程文档v1§1 forensics/signature.py
    hints: set[str] = set()

    series = list(seq) if seq is not None else (list(y) if y is not None else [])
    if len(series) >= 3:
        # 单调性 (定性)
        diffs = [series[i + 1] - series[i] for i in range(len(series) - 1)]
        if all(d > 0 for d in diffs) or all(d < 0 for d in diffs):
            hints.add("monotonic")
        else:
            hints.add("nonmonotonic")
        # 比值表 (定性): 比值差分≈常数 ⟹ 比值对 n 线性 (阶乘形)
        if all(v != 0 for v in series[:-1]):
            ratios = [series[i + 1] / series[i] for i in range(len(series) - 1)]
            if len(ratios) >= 3:
                d2 = [ratios[i + 1] - ratios[i] for i in range(len(ratios) - 1)]
                spread = max(d2) - min(d2)
                if spread < 1e-9 and abs(d2[0]) > 1e-12:
                    hints.add("ratio_linear_in_n")
                elif all(abs(r - ratios[0]) < 1e-9 for r in ratios):
                    hints.add("ratio_constant")
        # FFT 周期检测 (定性; 承 FRS-03: 法医先说"这是振荡")
        if seq is None and len(series) >= 8:
            centered = np.array(series) - np.mean(series)
            spectrum = np.abs(np.fft.rfft(centered))[1:]
            if spectrum.size > 0 and spectrum.max() > 3 * float(np.median(spectrum) + 1e-12):
                hints.add("periodic")

    if x is not None and y is not None and len(x) >= 2:
        slope = _loglog_slope(list(x), list(y))
        if slope < 0.9:
            hints.add("power_lt_1")
        elif slope > 1.1:
            hints.add("power_gt_1")
        else:
            hints.add("power_near_1")

    return Signature(hints=tuple(sorted(hints)))
