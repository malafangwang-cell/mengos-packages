"""生成 cf-probe.xlsx：恒真条件格式实测样例（执行令 table 包 2.1.0 第 0 步 C2，附录 A）。

只用 XlsxWriter 3.3.0（包锁定的版本），写法与 xlsx_writer.py 导出条件格式时相同：
  · 静态格式写在格上；条件规则按添加次序定优先级（先加的优先）；
  · 恒真规则是公式型条件格式 =TRUE()，排在全部规则之前。
运行：table/.venv/bin/python readings/table-2.1.0-cf/make_probe.py [输出路径]
"""
import datetime as _dt
import sys
from pathlib import Path

import xlsxwriter

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("cf-probe.xlsx")
GRAY, RED, YELLOW, BLUE = "#D9D9D9", "#FF0000", "#FFFF00", "#0070C0"


def build(path):
    wb = xlsxwriter.Workbook(str(path))
    wb.set_properties({"title": "cf-probe", "created": _dt.datetime(2026, 11, 12)})
    ws = wb.add_worksheet("probe")
    base = {"font_name": "Noto Sans CJK SC", "font_size": 14, "align": "center", "valign": "vcenter"}
    f_head = wb.add_format({**base, "bold": True})
    f_plain = wb.add_format(base)
    f_gray = wb.add_format({**base, "bg_color": GRAY})
    ws.set_column(0, 0, 46)
    ws.set_column(1, 2, 16)
    ws.set_default_row(30)
    ws.write_row(0, 0, ["设置（附录 A 编号）", "B 列", "C 列"], f_head)
    notes = {1: "#1 只有静态浅灰底", 2: "#2 静态浅灰底 + 规则 >100 红底 命中", 3: "#3 同 #2，另加恒真规则 浅灰底 排最前",
             4: "#4 两条规则命中：甲只设底色黄、乙只设字色蓝", 5: "#5 两条规则命中：甲黄底在前、乙红底在后"}
    for r, s in notes.items():
        ws.write_string(r, 0, s, f_plain)
    ws.write_number(1, 1, 150, f_gray)     # B2
    ws.write_number(2, 1, 150, f_gray)     # B3
    ws.write_number(3, 1, 150, f_gray)     # B4
    ws.write_number(4, 1, 150, f_plain)    # B5
    ws.write_number(5, 1, 150, f_plain)    # B6
    for r in range(1, 20):                 # C2:C20 静态浅灰 + 命中红底规则 + 一条并段的恒真规则
        ws.write_number(r, 2, 200 + r, f_gray)
    ws.write_string(6, 0, "#6 C2:C20 静态浅灰 + 规则红底命中 + 一条并段恒真 浅灰底", f_plain)
    ws.write_string(7, 0, "#7 把 B3 改成 50 后重算：B3 应回到浅灰底", f_plain)

    fill_red = wb.add_format({"bg_color": RED})
    fill_gray = wb.add_format({"bg_color": GRAY})
    fill_yellow = wb.add_format({"bg_color": YELLOW})
    font_blue = wb.add_format({"font_color": BLUE})
    # 优先级 = 添加次序（XlsxWriter 3.3.0 worksheet.py:3208-3210）。恒真规则先加。
    ws.conditional_format("B4", {"type": "formula", "criteria": "=TRUE()", "format": fill_gray})            # #3 恒真
    ws.conditional_format("C2:C20", {"type": "formula", "criteria": "=TRUE()", "format": fill_gray})        # #6 恒真并成一段
    ws.conditional_format("B3:B4", {"type": "formula", "criteria": "=AND(COUNT(B3)=1,B3>100)", "format": fill_red})   # #2 #3
    ws.conditional_format("C2:C20", {"type": "formula", "criteria": "=AND(COUNT(C2)=1,C2>100)", "format": fill_red})  # #6
    ws.conditional_format("B5", {"type": "formula", "criteria": "=AND(COUNT(B5)=1,B5>100)", "format": fill_yellow})  # #4 甲
    ws.conditional_format("B5", {"type": "formula", "criteria": "=AND(COUNT(B5)=1,B5>100)", "format": font_blue})    # #4 乙
    ws.conditional_format("B6", {"type": "formula", "criteria": "=AND(COUNT(B6)=1,B6>100)", "format": fill_yellow})  # #5 甲
    ws.conditional_format("B6", {"type": "formula", "criteria": "=AND(COUNT(B6)=1,B6>100)", "format": fill_red})     # #5 乙
    wb.close()


if __name__ == "__main__":
    build(OUT)
    print(OUT)
