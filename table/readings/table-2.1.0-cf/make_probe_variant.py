"""cf-probe-variant.xlsx：补测三种情形（附录 A 之外，只在 LibreOffice 上跑，用来判断不合并的范围）。

V1 B2：甲规则（只设黄底）范围 B2，乙规则（只设蓝字）范围 B2:B3 —— 两条规则在不同的 conditionalFormatting 里
V2 B4：静态浅灰底 + 一条规则只设红字 —— 静态底色与规则字色是否并存（T4-07 的情形）
V3 B5：静态黄底 + 一条规则只设红底 + 一条规则只设粗体 —— 规则压过静态以后，规则之间是否合并
"""
import datetime as _dt
import sys
from pathlib import Path

import xlsxwriter

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("cf-probe-variant.xlsx")
wb = xlsxwriter.Workbook(str(OUT))
wb.set_properties({"title": "cf-probe-variant", "created": _dt.datetime(2026, 11, 12)})
ws = wb.add_worksheet("variant")
base = {"font_name": "Noto Sans CJK SC", "font_size": 14, "align": "center", "valign": "vcenter"}
ws.set_column(0, 0, 46)
ws.set_column(1, 1, 16)
ws.set_default_row(30)
plain, gray, yellow = wb.add_format(base), wb.add_format({**base, "bg_color": "#D9D9D9"}), wb.add_format({**base, "bg_color": "#FFFF00"})
ws.write_row(0, 0, ["情形", "B 列"], wb.add_format({**base, "bold": True}))
for r, (s, f) in enumerate([("V1 甲黄底(B2) 乙蓝字(B2:B3) 不同范围", plain), ("V1 只有乙命中", plain),
                            ("V2 静态浅灰底 + 规则只设红字", gray), ("V3 静态黄底 + 规则红底 + 规则粗体", yellow)], start=1):
    ws.write_string(r, 0, s, plain)
    ws.write_number(r, 1, 150, f)
cond = "=COUNT({c})=1"
ws.conditional_format("B2", {"type": "formula", "criteria": "=B2>100", "format": wb.add_format({"bg_color": "#FFFF00"})})
ws.conditional_format("B2:B3", {"type": "formula", "criteria": "=B2>100", "format": wb.add_format({"font_color": "#0070C0"})})
ws.conditional_format("B4", {"type": "formula", "criteria": "=B4>100", "format": wb.add_format({"font_color": "#FF0000"})})
ws.conditional_format("B5", {"type": "formula", "criteria": "=B5>100", "format": wb.add_format({"bg_color": "#FF0000"})})
ws.conditional_format("B5", {"type": "formula", "criteria": "=B5>100", "format": wb.add_format({"bold": True})})
wb.close()
print(OUT)
