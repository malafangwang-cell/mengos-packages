"""数据图（chart）：把“图表类型 + 数据”确定性地画成 SVG（设计-长文内置图表-2026-11-18 §四–§七）。

模型只给类型和数据；坐标轴、刻度、数值、图例、配色、预测段由本模块按固定规则画。没有随机量，
不读系统字体（文字宽度用随包的 Noto Sans SC 量），同一份数据两次成型逐字节相同。
数据不自洽就退回（BadInput），不画错图。

另给 Word 用的后备位图（raster）：按本模块画出的 SVG 逐元素画成 PNG，新旧 Word 都看得到图。
"""
from __future__ import annotations

import io
import math
import re
from pathlib import Path

from model import BadInput

FONT_FILE = Path(__file__).resolve().parent / "fonts" / "NotoSansSC-Regular.ttf"

# ---------------------------------------------------------------- 固定规则
W = 720
FONT = '"Noto Sans SC","Noto Sans CJK SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif'
INK, INK2, MUTE = "#1a1a19", "#4a4a47", "#7d7d79"
GRID, AXIS, BAND = "#e4e4e1", "#b9b8b2", "#f4f4f2"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]   # 固定顺序，不循环
OTHER = "#a9a7a0"
DARK_LABEL_ON = {"#eda100", OTHER}        # 这些底色上写深色字，其余写白字
MAX_SERIES, MAX_BAR_CATS, MAX_LINE_POINTS, MAX_PIE_IN, PIE_KEEP = 6, 24, 60, 30, 5
TYPES = ("bar", "line", "pie", "combo")
CHART_KEYS = ["type", "categories", "series", "unit", "forecast_from", "decimals", "stacked", "note"]
SERIES_KEYS = ["name", "values", "as", "unit"]
# 写了就退回并提示“由工具统一决定”的字段（颜色、字号、坐标范围、图例位置、图内标题）
STYLE_KEYS = {"color", "colors", "palette", "style", "font", "font_size", "fontsize", "size", "ymin", "ymax",
              "y_min", "y_max", "min", "max", "range", "axis", "legend", "title"}
UNIT_CHARS, NOTE_CHARS = 20, 200



_font = None


def _measure_font():
    global _font
    if _font is None:
        from PIL import ImageFont
        _font = ImageFont.truetype(str(FONT_FILE), 100)
    return _font


def tw(s: str, size: float) -> float:
    """文字宽度（像素），按随包字体 Noto Sans SC 量，不读系统字体。"""
    return _measure_font().getlength(s) * size / 100


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def n2(v: float) -> str:
    """坐标写两位小数，去尾零。"""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def fmt(v: float, dec: int) -> str:
    s = f"{abs(v):,.{dec}f}"
    return ("−" if v < 0 and float(s.replace(",", "")) != 0 else "") + s


def tint(hexc: str, k: float) -> str:
    """与白色混合：k=1 原色，k=0 白。"""
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(255 - (255 - c) * k) for c in (r, g, b))


# ---------------------------------------------------------------- 校验
YEAR = re.compile(r"(\d{4})(年|E)?")
QUARTER = re.compile(r"(\d{4})\s?Q([1-4])")
MONTH = re.compile(r"(\d{4})-(\d{2})")


def _time_index(cats):
    """类别全是年 / 季度 / 月时，返回各自的序号；否则 None。"""
    for rx, f in ((YEAR, lambda m: int(m.group(1))),
                  (QUARTER, lambda m: int(m.group(1)) * 4 + int(m.group(2)) - 1),
                  (MONTH, lambda m: int(m.group(1)) * 12 + int(m.group(2)) - 1)):
        ms = [rx.fullmatch(c) for c in cats]
        if all(ms):
            return [f(m) for m in ms], {YEAR: "年", QUARTER: "季度", MONTH: "月"}[rx]
    return None


def _text(v, where, limit):
    """可选的一行文字（单位、脚注）。"""
    if v is None:
        return
    if not isinstance(v, str):
        raise BadInput(f"{where} 必须是文字", where)
    if "\n" in v or "\r" in v or len(v) > limit:
        raise BadInput(f"{where} 写一行，不超过 {limit} 个字", where)


def validate(c: dict, where="doc.figures[i].source.chart") -> dict:
    if not isinstance(c, dict):
        raise BadInput(f"{where} 必须是对象", where)
    extra = [k for k in c if k not in CHART_KEYS]
    if extra:
        raise BadInput(f"{where} 有不认识的字段：{', '.join(sorted(extra))}（可用：{', '.join(CHART_KEYS)}）", where,
                       "颜色、字号、坐标范围由工具统一决定，不用写" if set(extra) & STYLE_KEYS else None)
    t = c.get("type")
    if t not in TYPES:
        raise BadInput(f"{where}.type 只能是 {' / '.join(TYPES)}（收到 {t!r}）", f"{where}.type")
    cats = c.get("categories")
    if not isinstance(cats, list) or not cats or any(not isinstance(x, str) or not x.strip() for x in cats):
        raise BadInput(f"{where}.categories 是类别名的数组，至少一项，每项是非空文字", f"{where}.categories",
                       "年份写成 \"2024\" 这样的文字")
    cats = [x.strip() for x in cats]
    dup = sorted({x for x in cats if cats.count(x) > 1})
    if dup:
        raise BadInput(f"{where}.categories 有重复的类别：{dup[0]}", f"{where}.categories")
    series = c.get("series")
    if not isinstance(series, list) or not series:
        raise BadInput(f"{where}.series 至少一组数据", f"{where}.series")
    out_s = []
    for i, s in enumerate(series):
        sw = f"{where}.series[{i}]"
        if not isinstance(s, dict) or "name" not in s or "values" not in s:
            raise BadInput(f"{sw} 要有 name 和 values", sw)
        bad = [k for k in s if k not in SERIES_KEYS]
        if bad:
            raise BadInput(f"{sw} 有不认识的字段：{', '.join(sorted(bad))}（可用：{', '.join(SERIES_KEYS)}）", sw)
        name = s["name"]
        if not isinstance(name, str) or not name.strip():
            raise BadInput(f"{sw}.name 不能为空", f"{sw}.name")
        vals = s["values"]
        if not isinstance(vals, list) or len(vals) != len(cats):
            n = len(vals) if isinstance(vals, list) else 0
            raise BadInput(f"“{name}”有 {n} 个数，类别有 {len(cats)} 个（{cats[0]}…{cats[-1]}）", f"{sw}.values",
                           "每组数据的个数要与 categories 相同；某一项没有数据写 null")
        for j, v in enumerate(vals):
            if v is None:
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise BadInput(f"“{name}”的第 {j + 1} 个值（{cats[j]}）不是数：{v!r}", f"{sw}.values[{j}]",
                               "只写数字，不带单位、逗号和百分号；单位写在 unit")
        if all(v is None for v in vals):
            raise BadInput(f"“{name}”没有任何数据", f"{sw}.values")
        out_s.append({"name": name.strip(), "values": [None if v is None else float(v) for v in vals],
                      "as": s.get("as"), "unit": s.get("unit")})
    _text(c.get("unit"), f"{where}.unit", UNIT_CHARS)
    _text(c.get("note"), f"{where}.note", NOTE_CHARS)
    for i, s in enumerate(series):
        _text(s.get("unit"), f"{where}.series[{i}].unit", UNIT_CHARS)
    if c.get("stacked") is not None and not isinstance(c.get("stacked"), bool):
        raise BadInput(f"{where}.stacked 写 true 或 false", f"{where}.stacked")
    if c.get("forecast_from") is not None and not isinstance(c.get("forecast_from"), str):
        raise BadInput(f"{where}.forecast_from 要写 categories 里的一项", f"{where}.forecast_from")
    names = [s["name"] for s in out_s]
    if len(set(names)) != len(names):
        raise BadInput(f"{where}.series 有重名的数据组", f"{where}.series")
    unit = c.get("unit") or ""
    dec = c.get("decimals")
    if dec is not None and (isinstance(dec, bool) or not isinstance(dec, int) or not 0 <= dec <= 4):
        raise BadInput(f"{where}.decimals 取 0–4", f"{where}.decimals")
    warnings = []

    # 类别轴连续性：年、季度、月必须逐期连续（立法者实例①：2024 直接跳到 2027）
    ti = _time_index(cats)
    if ti and t != "pie":
        idx, what = ti
        for a, b, ca, cb in zip(idx, idx[1:], cats, cats[1:]):
            if b <= a:
                raise BadInput(f"类别要按时间先后排：{ca} 之后是 {cb}", f"{where}.categories")
            if b - a != 1:
                raise BadInput(f"横轴按{what}排，{ca} 之后直接是 {cb}，中间缺 {b - a - 1} 个{what}", f"{where}.categories",
                               f"把缺的{what}补进 categories；确实没有数据的，值写 null，图上会留空并标出")
    ff = c.get("forecast_from")
    if ff is not None:
        if t == "pie":
            raise BadInput("饼图没有预测段", f"{where}.forecast_from")
        if ff not in cats:
            raise BadInput(f"{where}.forecast_from 要写 categories 里的一项（收到 {ff!r}）", f"{where}.forecast_from")
        if cats.index(ff) == 0:
            raise BadInput("forecast_from 是第一个类别，等于整张图都是预测；这种情况不要写 forecast_from，在图题里说明", f"{where}.forecast_from")

    if t == "pie":
        if any(x["as"] is not None or x["unit"] is not None for x in out_s):
            raise BadInput("as 和每组各自的 unit 只在组合图（combo）里用", f"{where}.series")
        if len(out_s) != 1:
            raise BadInput("饼图只画一组数据", f"{where}.series", "多组数据的构成对比请用柱状图（stacked: true）")
        vals = out_s[0]["values"]
        if len(cats) > MAX_PIE_IN:
            raise BadInput(f"饼图最多 {MAX_PIE_IN} 项（现有 {len(cats)}）", f"{where}.categories", "项目很多时用表格")
        if any(v is None for v in vals):
            raise BadInput("饼图的每一项都要有数", f"{where}.series[0].values")
        neg = [cats[i] for i, v in enumerate(vals) if v < 0]
        if neg:
            raise BadInput(f"饼图不能有负数（{neg[0]}）", f"{where}.series[0].values", "有正有负的构成用柱状图")
        total = sum(vals)
        if total <= 0:
            raise BadInput("饼图各项合计为 0，画不出占比", f"{where}.series[0].values")
        if len(cats) < 2:
            raise BadInput("饼图至少两项", f"{where}.categories")
        if unit in ("%", "％") and abs(total - 100) > 0.5:
            raise BadInput(f"各项占比合计 {fmt(total, 1)}%，不是 100%", f"{where}.series[0].values",
                           "核对各项数字；如果只列了一部分，把其余的补成一项“其他”")
    else:
        if len(out_s) > MAX_SERIES:
            raise BadInput(f"一张图最多 {MAX_SERIES} 组数据（现有 {len(out_s)}）", f"{where}.series", "拆成两张图，或改用表格")
        lim = MAX_LINE_POINTS if t == "line" else MAX_BAR_CATS
        if len(cats) > lim:
            raise BadInput(f"{'折线图' if t == 'line' else '柱状图'}最多 {lim} 个类别（现有 {len(cats)}）", f"{where}.categories",
                           "拆成两张图，或改用表格")
        for s in out_s:
            if t == "combo":
                if s["as"] not in ("bar", "line"):
                    raise BadInput(f"组合图里“{s['name']}”要写 as：bar（柱）或 line（折线）", f"{where}.series")
            elif s["as"] is not None or s["unit"] is not None:
                raise BadInput(f"as 和每组各自的 unit 只在组合图（combo）里用", f"{where}.series")
        if t == "combo":
            kinds = {s["as"] for s in out_s}
            if kinds != {"bar", "line"}:
                raise BadInput("组合图要同时有柱和折线；只有一种时用 bar 或 line", f"{where}.series")
            for s in out_s:
                s["unit"] = s["unit"] if s["unit"] is not None else unit
            bu = {s["unit"] for s in out_s if s["as"] == "bar"}
            lu = {s["unit"] for s in out_s if s["as"] == "line"}
            if len(bu) > 1 or len(lu) > 1:
                raise BadInput("组合图里所有柱用同一个单位，所有折线用同一个单位", f"{where}.series",
                               "单位超过两种时拆成两张图")
        if t in ("line", "combo"):
            for s in out_s:
                if (t == "line" or s["as"] == "line") and sum(v is not None for v in s["values"]) < 2:
                    raise BadInput(f"折线“{s['name']}”至少要两个点", f"{where}.series")
        if c.get("stacked"):
            if t != "bar":
                raise BadInput("stacked 只用于柱状图", f"{where}.stacked")
            flat = [v for s in out_s for v in s["values"] if v is not None]
            if any(v < 0 for v in flat):
                raise BadInput("堆叠柱状图不能有负数", f"{where}.series", "去掉 stacked，改成并排的柱")
        for s in out_s:
            gaps = [cats[i] for i, v in enumerate(s["values"]) if v is None]
            if gaps:
                warnings.append({"code": "chart_gap", "message": f"“{s['name']}”在 {'、'.join(gaps)} 没有数据，图上留空"})
    if dec is None:
        def nd(v):
            s = repr(v)
            return len(s.split(".")[1]) if "." in s and not s.endswith(".0") and "e" not in s else 0
        dec = min(2, max((nd(v) for s in out_s for v in s["values"] if v is not None), default=0))
    return {"type": t, "categories": cats, "series": out_s, "unit": unit, "forecast_from": ff, "decimals": dec,
            "stacked": bool(c.get("stacked")), "note": c.get("note") or "", "warnings": warnings, "_where": where}


# ---------------------------------------------------------------- 刻度
def nice_scale(lo: float, hi: float, zero: bool, target=5):
    if zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi = lo + 1
    raw = (hi - lo) / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw - 1e-12)
    a, b = math.floor(lo / step + 1e-9) * step, math.ceil(hi / step - 1e-9) * step
    if b - hi < step * 0.45 and hi > 0:        # 数据端给数值标签留出不少于半格
        b += step
    if lo < 0 and lo - a < step * 0.45:
        a -= step
    n = round((b - a) / step)
    ticks = [round(a + i * step, 10) for i in range(n + 1)]
    sdec = max(0, -math.floor(math.log10(step) + 1e-9)) if step < 1 else (1 if abs(step - round(step)) > 1e-9 else 0)
    return a, b, ticks, sdec


# ---------------------------------------------------------------- 画柱 / 线 / 组合
class Svg:
    def __init__(self, h, title):
        self.h, self.title, self.el = h, title, []

    def add(self, s):
        self.el.append(s)

    def text(self, x, y, s, size=12, fill=INK2, anchor="start", weight=None):
        w = f' font-weight="{weight}"' if weight else ""
        self.add(f'<text x="{n2(x)}" y="{n2(y)}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"{w}>{esc(s)}</text>')

    def out(self):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {n2(self.h)}" width="{W}" height="{n2(self.h)}" '
                f'font-family=\'{FONT}\'>\n<title>{esc(self.title)}</title>\n'
                f'<rect x="0" y="0" width="{W}" height="{n2(self.h)}" fill="#ffffff"/>\n' + "\n".join(self.el) + "\n</svg>\n")


def _legend(svg, items, x0, y, x_max):
    """图例：一行排不下就换行。items = [(kind, color, label)]，kind ∈ bar/line/forecast。返回占用的底边 y。"""
    x, row_h = x0, 20
    for kind, color, label in items:
        w = 22 + tw(label, 12) + 18
        if x + w > x_max and x > x0:
            x, y = x0, y + row_h
        if kind == "bar":
            svg.add(f'<rect x="{n2(x)}" y="{n2(y - 9)}" width="12" height="10" rx="2" fill="{color}"/>')
        elif kind == "line":
            svg.add(f'<line x1="{n2(x - 2)}" y1="{n2(y - 4)}" x2="{n2(x + 16)}" y2="{n2(y - 4)}" stroke="{color}" stroke-width="2"/>'
                    f'<circle cx="{n2(x + 7)}" cy="{n2(y - 4)}" r="3.5" fill="{color}" stroke="#ffffff" stroke-width="1.5"/>')
        else:
            svg.add(f'<rect x="{n2(x + 0.5)}" y="{n2(y - 8.5)}" width="11" height="9" rx="2" fill="{BAND}" stroke="{MUTE}" stroke-dasharray="3 2"/>')
        svg.text(x + 20, y, label, 12, INK2)
        x += w
    return y


def _bar_path(x, y0, y1, w, r=3):
    """从基线 y0 长到 y1 的柱：数据端圆角，基线端直角。"""
    r = min(r, w / 2, abs(y1 - y0))
    s = 1 if y1 < y0 else -1          # 向上为 1
    return (f"M{n2(x)} {n2(y0)}L{n2(x)} {n2(y1 + s * r)}Q{n2(x)} {n2(y1)} {n2(x + r)} {n2(y1)}"
            f"L{n2(x + w - r)} {n2(y1)}Q{n2(x + w)} {n2(y1)} {n2(x + w)} {n2(y1 + s * r)}L{n2(x + w)} {n2(y0)}Z")


def _cat_labels(cats, band, is_time, where="chart"):
    """类别标签：排得下就全写；时间类排不下隔 k 个写一个；其他类折成两行。返回 [(序号, [行])] 与行数。"""
    size = 12
    widths = [tw(c, size) for c in cats]
    if max(widths) <= band - 6:
        return [(i, [c]) for i, c in enumerate(cats)], 1
    if is_time:
        k = next(k for k in range(2, len(cats) + 1) if max(widths) <= band * k - 8)
        return [(i, [cats[i]]) for i in range(0, len(cats), k)], 1
    out = []
    for i, c in enumerate(cats):
        h = math.ceil(len(c) / 2)
        a, b = c[:h], c[h:]
        if max(tw(a, size), tw(b, size)) > band - 4:
            raise BadInput(f"类别“{c}”太长，横轴排不下", f"{where}.categories", "类别名缩短到 8 个字以内，或减少类别，或改用表格")
        out.append((i, [a, b]))
    return out, 2


def render_xy(c: dict, title: str) -> str:
    t, cats, dec, unit = c["type"], c["categories"], c["decimals"], c["unit"]
    series = c["series"]
    for s in series:
        s["kind"] = s["as"] if t == "combo" else t
    for i, s in enumerate(series):
        s["color"] = SERIES[i]
    left = [s for s in series if not (t == "combo" and s["kind"] == "line" and s["unit"] != next(x["unit"] for x in series if x["kind"] == "bar"))]
    right = [s for s in series if s not in left]
    lunit = (left[0]["unit"] if t == "combo" else unit) or ""
    runit = right[0]["unit"] if right else ""
    f_i = cats.index(c["forecast_from"]) if c["forecast_from"] else None

    def rng(group, stacked=False):
        if stacked:
            tops = [sum(s["values"][j] or 0 for s in group) for j in range(len(cats))]
            return 0.0, max(tops)
        vs = [v for s in group for v in s["values"] if v is not None]
        return min(vs), max(vs)

    has_bar = any(s["kind"] == "bar" for s in left)
    lo, hi = rng(left, c["stacked"])
    zero = has_bar or (lo >= 0 and (hi - lo) > 0.3 * hi) or lo < 0 < hi
    la, lb, lticks, ldec = nice_scale(lo, hi, zero)
    ldec = min(max(ldec, 0), 4)
    if right:
        lo2, hi2 = rng(right)
        ra, rb, rticks, rdec = nice_scale(lo2, hi2, (lo2 >= 0 and (hi2 - lo2) > 0.3 * hi2) or lo2 < 0 < hi2, target=len(lticks) - 1)
        # 左右轴刻度条数对齐，共用一套横线
        while len(rticks) < len(lticks):
            rb += rticks[1] - rticks[0]
            rticks.append(round(rb, 10))
        while len(lticks) < len(rticks):
            lb += lticks[1] - lticks[0]
            lticks.append(round(lb, 10))

    pct = lambda u: u in ("%", "％")
    ltl = [fmt(v, ldec) + ("%" if pct(lunit) else "") for v in lticks]
    ml = max(44, max(tw(x, 11) for x in ltl) + 14)
    mr = 20
    if right:
        rtl = [fmt(v, rdec) + ("%" if pct(runit) else "") for v in rticks]
        mr = max(44, max(tw(x, 11) for x in rtl) + 14)

    # 图例
    items = []
    multi = len(series) > 1
    if multi:
        for s in series:
            lab = s["name"] + ("（右轴）" if s in right else "")
            items.append((s["kind"], s["color"], lab))
    if f_i is not None:
        items.append(("forecast", "", "预测"))
    svg = Svg(0, title)
    y = 14
    if items:
        y = _legend(svg, items, ml, y + 12, W - mr) + 10
    # 轴标题（单位）
    y += 14

    def axis_title(names, u):
        if pct(u):
            return f"{names}（%）" if names else "%"
        return f"{names}（{u}）" if names and u else (names or (f"单位：{u}" if u else ""))

    if t == "combo" and right:
        ln = "、".join(s["name"] for s in left) if len(left) <= 2 else ""
        rn = "、".join(s["name"] for s in right) if len(right) <= 2 else ""
        svg.text(ml - 4 - max(tw(x, 11) for x in ltl), y, axis_title(ln, lunit), 11, MUTE)
        svg.text(W - mr + 4 + max(tw(x, 11) for x in rtl), y, axis_title(rn, runit), 11, MUTE, "end")
    else:
        lab = axis_title(series[0]["name"] if not multi else "", lunit)
        if lab:
            svg.text(ml - 4 - max(tw(x, 11) for x in ltl), y, lab, 11, MUTE)
    top = y + 12
    ph = c.get("_plot_h", 232)
    bot = top + ph
    pw = W - ml - mr
    band = pw / len(cats)
    Y = lambda v: bot - (v - la) / (lb - la) * ph
    Y2 = (lambda v: bot - (v - ra) / (rb - ra) * ph) if right else None

    # 预测段底色
    if f_i is not None:
        fx = ml + band * f_i
        svg.add(f'<rect x="{n2(fx)}" y="{n2(top)}" width="{n2(W - mr - fx)}" height="{n2(ph)}" fill="{BAND}"/>')
        svg.text(fx + 6, top + 14, "预测", 11, MUTE)
    # 横线与刻度
    for v, lab in zip(lticks, ltl):
        yy = Y(v)
        base = abs(v) < 1e-12
        svg.add(f'<line x1="{n2(ml)}" y1="{n2(yy)}" x2="{n2(W - mr)}" y2="{n2(yy)}" stroke="{AXIS if base else GRID}" stroke-width="1"/>')
        svg.text(ml - 8, yy + 4, lab, 11, MUTE, "end")
    if not any(abs(v) < 1e-12 for v in lticks):
        svg.add(f'<line x1="{n2(ml)}" y1="{n2(bot)}" x2="{n2(W - mr)}" y2="{n2(bot)}" stroke="{AXIS}" stroke-width="1"/>')
    if right:
        for v, lab in zip(rticks, rtl):
            svg.text(W - mr + 8, Y2(v) + 4, lab, 11, MUTE, "start")
    # 类别
    labs, nlines = _cat_labels(cats, band, _time_index(cats) is not None, c["_where"])
    for i, lines in labs:
        for k, ln in enumerate(lines):
            svg.text(ml + band * (i + 0.5), bot + 18 + 15 * k, ln, 12, INK2, "middle")

    boxes = []          # 已放的数值标签，防碰撞

    def place(x, yy, s, pref_up=True, halo=False):
        w, h = tw(s, 11) + 4, 14
        for up in ((True, False) if pref_up else (False, True)):
            by = yy - 7 - h + 3 if up else yy + 8
            box = (x - w / 2, by, x + w / 2, by + h)
            if by < top - 16 or by + h > bot + 4:
                continue
            if all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in boxes):
                boxes.append(box)
                if halo:
                    svg.add(f'<rect x="{n2(box[0])}" y="{n2(box[1])}" width="{n2(w)}" height="{h}" rx="2" fill="#ffffff" fill-opacity="0.85"/>')
                svg.text(x, by + 11, s, 11, INK, "middle")
                return True
        return False

    # 柱
    bars = [s for s in series if s["kind"] == "bar"]
    if bars:
        nb = 1 if c["stacked"] else len(bars)
        bw = min(44 if c["stacked"] else 28, (band * 0.72 - 2 * (nb - 1)) / nb)
        gw = bw * nb + 2 * (nb - 1)
        label_bars = len(cats) * nb <= 16
        z = Y(max(la, 0.0)) if la <= 0 else bot
        for j in range(len(cats)):
            x0 = ml + band * j + (band - gw) / 2
            fc = f_i is not None and j >= f_i
            acc = 0.0
            for k, s in enumerate(bars):
                v = s["values"][j]
                if v is None:
                    if not c["stacked"]:
                        svg.text(x0 + (bw + 2) * k + bw / 2, z - 5, "—", 11, MUTE, "middle")
                    continue
                if c["stacked"]:
                    ya, yb = Y(acc), Y(acc + v)
                    acc += v
                    last = k == max(i for i, b in enumerate(bars) if b["values"][j] is not None)
                    if v > 0:
                        d = _bar_path(x0, ya, yb + (0 if last else 1), bw, 3 if last else 0)
                        svg.add(f'<path d="{d}" fill="{s["color"]}"/>')
                        lab = fmt(v, dec)
                        if ya - yb >= 16 and tw(lab, 11) <= bw + 14 and len(cats) <= 12:
                            svg.text(x0 + bw / 2, (ya + yb) / 2 + 4, lab, 11, INK if s["color"] in DARK_LABEL_ON else "#ffffff", "middle")
                    continue
                x = x0 + (bw + 2) * k
                yv = Y(v)
                if fc:
                    svg.add(f'<path d="{_bar_path(x + 0.5, z, yv + (0.5 if v >= 0 else -0.5), bw - 1)}" fill="{tint(s["color"], 0.28)}" '
                            f'stroke="{s["color"]}" stroke-width="1" stroke-dasharray="4 3"/>')
                else:
                    svg.add(f'<path d="{_bar_path(x, z, yv, bw)}" fill="{s["color"]}"/>')
                if label_bars:
                    lab = fmt(v, dec) + ("%" if pct(lunit) else "")
                    if t == "combo" and v > 0 and z - yv >= 22 and tw(lab, 11) <= bw - 2:
                        boxes.append((x, yv + 3, x + bw, yv + 17))
                        svg.text(x + bw / 2, yv + 14, lab, 11, INK if fc or s["color"] in DARK_LABEL_ON else "#ffffff", "middle")
                    else:
                        place(x + bw / 2, yv, lab, pref_up=v >= 0)
            if c["stacked"] and label_bars and acc:
                place(x0 + bw / 2, Y(acc), fmt(acc, dec))
    # 线
    lines = [s for s in series if s["kind"] == "line"]
    for s in lines:
        yf = Y2 if s in right else Y
        pts = [(ml + band * (j + 0.5), yf(v), j) if v is not None else None for j, v in enumerate(s["values"])]
        seg, segs = [], []
        for p in pts:
            if p is None:
                if seg:
                    segs.append(seg)
                seg = []
            else:
                seg.append(p)
        if seg:
            segs.append(seg)
        for sg in segs:
            solid = [p for p in sg if f_i is None or p[2] < f_i]
            dash = [p for p in sg if f_i is not None and p[2] >= f_i - 1] if f_i is not None else []
            if len(solid) > 1:
                svg.add(f'<polyline points="{" ".join(n2(p[0]) + "," + n2(p[1]) for p in solid)}" fill="none" stroke="{s["color"]}" '
                        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            if len(dash) > 1 and any(p[2] >= f_i for p in dash):
                svg.add(f'<polyline points="{" ".join(n2(p[0]) + "," + n2(p[1]) for p in dash)}" fill="none" stroke="{s["color"]}" '
                        f'stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>')
    for s in lines:
        yf = Y2 if s in right else Y
        u = runit if s in right else lunit
        npts = sum(v is not None for v in s["values"])
        label_all = npts <= 8 and len(lines) <= 2
        last = max(j for j, v in enumerate(s["values"]) if v is not None)
        show_marker = npts <= 24
        for j, v in enumerate(s["values"]):
            if v is None:
                continue
            x, yy = ml + band * (j + 0.5), yf(v)
            fc = f_i is not None and j >= f_i
            if show_marker or j == last:
                svg.add(f'<circle cx="{n2(x)}" cy="{n2(yy)}" r="4" fill="{"#ffffff" if fc else s["color"]}" '
                        f'stroke="{s["color"] if fc else "#ffffff"}" stroke-width="{2 if fc else 1.5}"/>')
            if label_all or j == last:
                place(x, yy - 3, fmt(v, dec if s not in right else max(dec, 1) if pct(u) else dec) + ("%" if pct(u) else ""), halo=bool(bars))
    svg.h = bot + 18 + 15 * nlines - 4 + 12
    if c["note"]:
        svg.text(ml, svg.h + 4, c["note"], 11, MUTE)
        svg.h += 18
    return svg.out()


# ---------------------------------------------------------------- 饼
def round_pct(vals, dec=1):
    """占比按最大余数法凑整，显示出来的各项合计恰为 100。"""
    total, k = sum(vals), 10 ** dec
    raw = [v / total * 100 * k for v in vals]
    base = [math.floor(r) for r in raw]
    rest = round(100 * k - sum(base))
    order = sorted(range(len(vals)), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order[:rest]:
        base[i] += 1
    return [b / k for b in base]


def render_pie(c: dict, title: str) -> str:
    cats, vals, dec, unit = c["categories"], c["series"][0]["values"], c["decimals"], c["unit"]
    rows = list(zip(cats, vals))
    merged = []
    other_names = ("其他", "其它", "Other", "Others")
    own_other = [r for r in rows if r[0] in other_names]
    rest = [r for r in rows if r[0] not in other_names]
    if len(rows) > PIE_KEEP + 1:
        ranked = sorted(range(len(rest)), key=lambda i: (-rest[i][1], i))
        keep = sorted(ranked[:PIE_KEEP])
        merged = [rest[i] for i in sorted(ranked[PIE_KEEP:])]
        rest = [rest[i] for i in keep]
        c["warnings"].append({"code": "chart_pie_merged",
                              "message": f"饼图有 {len(rows)} 项，最小的 {len(merged)} 项（{'、'.join(m[0] for m in merged)}）并入“其他”"})
    other_v = sum(r[1] for r in own_other) + sum(m[1] for m in merged)
    slices = [(n, v, SERIES[i]) for i, (n, v) in enumerate(rest)]
    if own_other or merged:
        slices.append(("其他", other_v, OTHER))
    total = sum(v for _, v, _ in slices)
    pcts = round_pct([v for _, v, _ in slices])
    is_pct = unit in ("%", "％")

    cx, cy, r = 168, 150, 118
    lx = 318
    row_h = 26
    n = len(slices)
    table_h = 24 + row_h * (n + 1)
    extra = 20 if merged else 0
    H = max(2 * cy, 40 + table_h + extra) + (18 if c["note"] else 0)
    cy = (H - (18 if c["note"] else 0)) / 2
    svg = Svg(H, title)
    ang = -math.pi / 2
    for (name, v, col), p in zip(slices, pcts):
        if v <= 0:
            continue
        a2 = ang + v / total * 2 * math.pi
        if v >= total:
            svg.add(f'<circle cx="{cx}" cy="{n2(cy)}" r="{r}" fill="{col}"/>')
        else:
            x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            big = 1 if a2 - ang > math.pi else 0
            svg.add(f'<path d="M{cx} {n2(cy)}L{n2(x1)} {n2(y1)}A{r} {r} 0 {big} 1 {n2(x2)} {n2(y2)}Z" fill="{col}" '
                    f'stroke="#ffffff" stroke-width="2" stroke-linejoin="round"/>')
        if p >= 6:
            mid = (ang + a2) / 2
            rr = r * (0.62 if p < 40 else 0.5)
            svg.text(cx + rr * math.cos(mid), cy + rr * math.sin(mid) + 4, f"{p:.1f}%", 12,
                     INK if col in DARK_LABEL_ON else "#ffffff", "middle", 500)
        ang = a2
    # 右侧清单：名称、数值、占比
    y = cy - (table_h + extra) / 2 + 14
    vx, px = 596, 692
    svg.text(lx + 20, y, "项目", 11, MUTE)
    if not is_pct:
        svg.text(vx, y, f"数值（{unit}）" if unit else "数值", 11, MUTE, "end")
    svg.text(px, y, "占比", 11, MUTE, "end")
    y += 8
    svg.add(f'<line x1="{lx}" y1="{n2(y)}" x2="{px}" y2="{n2(y)}" stroke="{GRID}" stroke-width="1"/>')
    for (name, v, col), p in zip(slices, pcts):
        y += row_h
        svg.add(f'<rect x="{lx}" y="{n2(y - 15)}" width="12" height="12" rx="2" fill="{col}"/>')
        svg.text(lx + 20, y - 5, name, 12.5, INK)
        if not is_pct:
            svg.text(vx, y - 5, fmt(v, dec), 12.5, INK2, "end")
        svg.text(px, y - 5, f"{p:.1f}%", 12.5, INK, "end")
    y += 6
    svg.add(f'<line x1="{lx}" y1="{n2(y)}" x2="{px}" y2="{n2(y)}" stroke="{GRID}" stroke-width="1"/>')
    y += row_h - 6
    svg.text(lx + 20, y - 3, "合计", 12.5, INK2)
    if not is_pct:
        svg.text(vx, y - 3, fmt(total, dec), 12.5, INK2, "end")
    svg.text(px, y - 3, "100.0%", 12.5, INK2, "end")
    if merged:
        y += 20
        s = "其他含：" + "、".join(f"{m[0]} {fmt(m[1], dec)}" for m in merged)
        svg.text(lx, y, s, 11, MUTE)
    if c["note"]:
        svg.text(24, H - 8, c["note"], 11, MUTE)
    return svg.out()


def canonical(raw: dict, c: dict) -> dict:
    """写回文档模型的图表数据：只留给出的字段，键序固定；类别名、组名去首尾空白；数原样（整数仍是整数）。
    再交一次得到同一张图（幂等）。"""
    out = {"type": c["type"], "categories": c["categories"], "series": []}
    for s_raw, s in zip(raw["series"], c["series"]):
        d = {"name": s["name"], "values": list(s_raw["values"])}
        if s_raw.get("as") is not None:
            d["as"] = s_raw["as"]
        if s_raw.get("unit") is not None:
            d["unit"] = s_raw["unit"]
        out["series"].append(d)
    for k in ("unit", "forecast_from", "decimals", "stacked", "note"):
        if raw.get(k) is not None:
            out[k] = raw[k]
    return out


def render(chart: dict, title: str, where: str = "doc.figures[i].source.chart") -> tuple[str, list, dict]:
    """校验并出图 → (SVG 文字, 提醒, 写回模型的图表数据)。数据不自洽 ⟹ BadInput，什么都不画。"""
    c = validate(chart, where)
    svg = render_pie(c, title) if c["type"] == "pie" else render_xy(c, title)
    return svg, c["warnings"], canonical(chart, c)




# ---------------------------------------------------------------- Word 的后备位图
# 只认本模块自己画出的那几种元素与属性（rect、line、polyline、circle、path 的 M/L/Q/A/Z、text），
# 不是通用 SVG 渲染器。先按 SS 倍画，再缩到 scale 倍，边缘平滑；全过程确定，同一 SVG 出同一 PNG。
SS = 4
_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_FONT_BOLD = Path(__file__).resolve().parent / "fonts" / "NotoSansSC-Bold.ttf"


def _rgba(c: str | None, opacity: float = 1.0):
    if not c or c == "none":
        return None
    r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
    return (r, g, b, round(255 * opacity))


def _quad(p0, p1, p2, n=8):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (k / n for k in range(1, n + 1))]


def _arc(p0, r, large, sweep, p1):
    """圆弧（rx = ry，无旋转）按端点式求圆心后折成折线（SVG 1.1 附录 F.6）。"""
    (x1, y1), (x2, y2) = p0, p1
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    d2 = dx * dx + dy * dy
    r = max(r, math.sqrt(d2))
    k = math.sqrt(max(0.0, (r * r - d2) / d2)) if d2 else 0.0
    if large == sweep:
        k = -k
    cx, cy = (x1 + x2) / 2 + k * dy, (y1 + y2) / 2 - k * dx
    a1, a2 = math.atan2(y1 - cy, x1 - cx), math.atan2(y2 - cy, x2 - cx)
    if sweep and a2 < a1:
        a2 += 2 * math.pi
    if not sweep and a2 > a1:
        a2 -= 2 * math.pi
    n = max(4, int(abs(a2 - a1) / (math.pi / 90)))
    return [(cx + r * math.cos(a1 + (a2 - a1) * i / n), cy + r * math.sin(a1 + (a2 - a1) * i / n)) for i in range(1, n + 1)]


def _path_points(d: str):
    toks = re.findall(r"[MLQAZ]|-?\d+(?:\.\d+)?", d)
    pts, cur, i = [], None, 0
    while i < len(toks):
        op = toks[i]
        i += 1
        if op in ("M", "L"):
            cur = (float(toks[i]), float(toks[i + 1]))
            i += 2
            pts.append(cur)
        elif op == "Q":
            c1, e = (float(toks[i]), float(toks[i + 1])), (float(toks[i + 2]), float(toks[i + 3]))
            i += 4
            pts += _quad(cur, c1, e)
            cur = e
        elif op == "A":
            r, large, sweep = float(toks[i]), int(toks[i + 3]), int(toks[i + 4])
            e = (float(toks[i + 5]), float(toks[i + 6]))
            i += 7
            pts += _arc(cur, r, large, sweep, e)
            cur = e
    return pts


def _dashed(draw, pts, dash, fill, width, closed=False):
    if closed:
        pts = pts + pts[:1]
    on, off = dash
    pos, drawing, left = 0.0, True, on
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while seg - t > 1e-9:
            step = min(left, seg - t)
            if drawing:
                a, b = t / seg, (t + step) / seg
                draw.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
                          fill=fill, width=width)
            t += step
            left -= step
            if left <= 1e-9:
                drawing = not drawing
                left = on if drawing else off
        pos += seg


def raster(svg: str, scale: float = 2.0) -> bytes:
    """本模块画出的 SVG → PNG（Word 后备位图）。"""
    import xml.etree.ElementTree as ET
    from PIL import Image, ImageDraw, ImageFont
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    W_, H_ = float(root.get("width")), float(root.get("height"))
    k = scale * SS
    img = Image.new("RGBA", (round(W_ * k), round(H_ * k)), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img, "RGBA")
    fonts = {}

    def font(size, bold):
        key = (round(size * k * 4), bold)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(str(_FONT_BOLD if bold else FONT_FILE), size * k)
        return fonts[key]

    def P(pts):
        return [(x * k, y * k) for x, y in pts]

    def dash_of(el):
        v = el.get("stroke-dasharray")
        return tuple(float(x) * k for x in v.split()) if v else None

    def outline(pts, el, closed):
        col, w = _rgba(el.get("stroke")), max(1, round(float(el.get("stroke-width", "1")) * k))
        if col is None:
            return
        dash = dash_of(el)
        if dash:
            _dashed(draw, pts, dash, col, w, closed)
        else:
            draw.line(pts + (pts[:1] if closed else []), fill=col, width=w, joint="curve")

    for el in root.iter():
        tag = el.tag.replace(ns, "")
        g = lambda a, d="0": float(el.get(a, d))
        if tag == "rect":
            x, y, w, h = g("x"), g("y"), g("width"), g("height")
            fill = _rgba(el.get("fill"), float(el.get("fill-opacity", "1")))
            box = [x * k, y * k, (x + w) * k, (y + h) * k]
            if fill:
                draw.rounded_rectangle(box, radius=g("rx") * k, fill=fill)
            if el.get("stroke"):
                outline(P([(x, y), (x + w, y), (x + w, y + h), (x, y + h)]), el, True)
        elif tag == "line":
            outline(P([(g("x1"), g("y1")), (g("x2"), g("y2"))]), el, False)
        elif tag == "polyline":
            nums = [float(v) for v in _NUM.findall(el.get("points"))]
            outline(P(list(zip(nums[::2], nums[1::2]))), el, False)
        elif tag == "circle":
            cx, cy, r = g("cx") * k, g("cy") * k, g("r") * k
            fill = _rgba(el.get("fill"))
            st = _rgba(el.get("stroke"))
            sw = float(el.get("stroke-width", "0")) * k if st else 0
            if st:
                draw.ellipse([cx - r - sw / 2, cy - r - sw / 2, cx + r + sw / 2, cy + r + sw / 2], fill=st)
            if fill:
                rr = r - sw / 2
                draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=fill)
        elif tag == "path":
            pts = P(_path_points(el.get("d")))
            fill = _rgba(el.get("fill"))
            if fill:
                draw.polygon(pts, fill=fill)
            if el.get("stroke"):
                outline(pts, el, True)
        elif tag == "text":
            size = g("font-size", "12")
            anchor = {"start": "ls", "middle": "ms", "end": "rs"}[el.get("text-anchor", "start")]
            bold = (el.get("font-weight") or "400") >= "600"
            draw.text((g("x") * k, g("y") * k), el.text or "", font=font(size, bold), fill=_rgba(el.get("fill")), anchor=anchor)
    out = img.convert("RGB").resize((round(W_ * scale), round(H_ * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=False, compress_level=9)
    return buf.getvalue()
