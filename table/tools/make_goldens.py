"""生成 golden_cases.json（TL-12 ③ 金样）。期望值都是手算后写死的，不由工具跑出来再抄。

2.0.0：#7、#28、#35 的各张表补 id（table.build 的 sheet id 必填）；b_round_fn、b_count_min_max、err_formula_text
三条给被公式或合计引用的列补 type（取 1.0.1 原来推断或缺省的类型），期望值不变。

每条：{id, note, tool, payload, expect}。expect 的键是结果里的路径（如 sheets[0].totals[0].value），
另有几个特殊键，由 tools/run_golden.py 解释：
  md_contains / md_lacks       Markdown 文件里有 / 没有这些文字
  csv_contains                 CSV 文件（第一份）解码后含这些文字
  csv_bom                      CSV 是否以 UTF-8 BOM 开头
  xlsx_contains                {"<zip 内路径>": [文字…]}：xlsx 里这一部分含这些文字
  model_contains               表模型 JSON 文件里含这些文字
  twice                        同一输入跑两次，output 与文件逐字节相同
  file_count                   产出文件个数
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = {"title": "减速机物料清单",
       "columns": [{"key": "part", "title": "零件"}, {"key": "qty", "title": "数量", "type": "integer"},
                   {"key": "price", "title": "单价", "type": "money", "unit": "元"},
                   {"key": "amount", "title": "金额", "type": "money", "unit": "元", "formula": "qty * price"}],
       "rows": [["输入轴", 1, 860], ["齿轮", 2, 1250.5], ["轴承 6208", 4, 95]],
       "totals": ["金额"]}
STEEL = {"title": "钢材", "columns": [{"key": "g", "title": "牌号"}, {"key": "ys", "title": "屈服强度", "unit": "MPa", "type": "integer"},
                                      {"key": "p", "title": "价格", "type": "money", "unit": "元/吨"}],
         "rows": [["Q235", 235, 4200], ["Q355", 355, 4550], ["45", 355, 5100], ["304", 205, 15800]]}

C = []


def case(id, note, tool, payload, expect):
    C.append({"id": id, "note": note, "tool": tool, "payload": payload, "expect": expect})


# ---------------------------------------------------------------- table.build
case("b_simple", "最简写法：列只写标题，类型按内容推断", "table.build",
     {"table": {"title": "季度销量", "columns": ["地区", "一季度", "二季度"], "rows": [["华东", 120, 135], ["华南", 98, 110.5]]}},
     {"sheets[0].name": "季度销量", "sheets[0].rows": 2, "sheets[0].columns": ["地区", "一季度", "二季度"],
      "stats.cells": 6, "stats.empty_cells": 0, "file_count": 4,
      "model_contains": ['"type":"integer"', '"type":"number"', '"110.5"'],
      "md_contains": ["| 地区 | 一季度 | 二季度 |", "| 华南 | 98 | 110.5 |"]})
case("b_formula_totals", "公式列（数量 × 单价）与金额合计：860 + 2501 + 380 = 3741", "table.build",
     {"table": BOM},
     {"sheets[0].totals[0].column": "金额", "sheets[0].totals[0].fn": "sum", "sheets[0].totals[0].value": "3741",
      "stats.formula_columns": 1,
      "md_contains": ["| 齿轮 | 2 | 1,250.50 | 2,501.00 |", "| **合计** |  |  | **3,741.00** |", "公式：金额 = 数量 × 单价"]})
case("b_formula_excel", "xlsx 里公式列写成 Excel 公式并带缓存值，合计写成 SUM", "table.build",
     {"table": BOM},
     {"xlsx_contains": {"xl/worksheets/sheet1.xml": ["<f>B3*C3</f><v>2501</v>", "<f>SUM(D2:D4)</f><v>3741</v>"]}})
case("b_percent", "百分比列写百分数：12.5 与 \"8%\" 都按百分数，存为小数；平均 (12.5+8+(-3.25))/3=5.75%，按 1 位小数记为 5.8%", "table.build",
     {"table": {"title": "增长率", "columns": [{"title": "部门"}, {"title": "增长", "type": "percent", "decimals": 1}],
                "rows": [["甲", 12.5], ["乙", "8%"], ["丙", -3.25]], "totals": [{"column": "增长", "fn": "avg"}]}},
     {"sheets[0].totals[0].value": "0.058", "model_contains": ['"0.125"', '"0.08"', '"-0.0325"'],
      "md_contains": ["| 甲 | 12.5% |", "| 丙 | -3.3% |", "| **平均** | **5.8%** |"]})
case("b_money_strings", "金额列认千分位与货币符号：\"¥15,800\" → 15800；平均 (4200+15800)/2 = 10000", "table.build",
     {"table": {"title": "价", "columns": [{"title": "品名"}, {"title": "单价", "type": "money"}],
                "rows": [["甲", "4,200"], ["乙", "¥15,800"]], "totals": [{"column": "单价", "fn": "avg"}]}},
     {"sheets[0].totals[0].value": "10000", "md_contains": ["| 乙 | 15,800.00 |", "| **平均** | **10,000.00** |"]})
case("b_dates", "日期列认 2026/10/5、2026年10月6日，规范成 YYYY-MM-DD", "table.build",
     {"table": {"title": "到货", "columns": [{"title": "批次"}, {"title": "到货日期", "type": "date"}],
                "rows": [["A", "2026-10-04"], ["B", "2026/10/5"], ["C", "2026年10月6日"], ["D", None]]}},
     {"stats.empty_cells": 1, "model_contains": ['"2026-10-05"', '"2026-10-06"'], "md_contains": ["| C | 2026-10-06 |"]})
case("b_bool", "是否列：true / \"是\" / \"否\"；中文显示是、否", "table.build",
     {"table": {"title": "外购", "columns": [{"title": "件"}, {"title": "外购", "type": "bool"}],
                "rows": [["轴承", True], ["油封", "是"], ["箱体", "否"]]}},
     {"md_contains": ["| 油封 | 是 |", "| 箱体 | 否 |"], "model_contains": ['["油封",true]']})
case("b_multisheet", "两张表；表名里的 / 换成 _；CSV 每张一份", "table.build",
     {"table": {"title": "库存", "sheets": [
         {"id": "parts", "name": "零件/外购", "columns": ["名称", "库存"], "rows": [["轴承", 46]]},
         {"id": "raw", "name": "原料", "columns": ["名称", "库存"], "rows": [["圆钢", 12], ["板材", 3]]}]}, "formats": ["xlsx", "csv"]},
     {"sheets[0].name": "零件_外购", "sheets[1].rows": 2, "stats.sheets": 2, "file_count": 6,
      "warnings[0].code": "sheet_name", "md_contains": ["## 零件_外购", "## 原料"]})
case("b_dict_rows", "对象写法的行：按列名取值，缺的格子为空", "table.build",
     {"table": {"title": "人员", "columns": [{"key": "name", "title": "姓名"}, {"key": "dept", "title": "部门"}, {"title": "工号", "type": "integer"}],
                "rows": [{"name": "张敏", "部门": "质检", "工号": 1001}, {"name": "王强", "工号": 1002}]}},
     {"stats.empty_cells": 1, "md_contains": ["| 王强 |  | 1,002 |"]})
case("b_short_rows", "有公式列时行里可以只写非公式列", "table.build",
     {"table": {"title": "面积", "columns": [{"key": "w", "title": "宽", "type": "number"}, {"key": "h", "title": "高", "type": "number"},
                                            {"title": "面积", "formula": "w*h", "decimals": 2}], "rows": [[1.5, 2], [0.3, 0.7]]}},
     {"md_contains": ["| 1.5 | 2 | 3.00 |", "| 0.3 | 0.7 | 0.21 |"]})
case("b_div_zero", "除以零：格子留空并告警，xlsx 用 IFERROR 包住", "table.build",
     {"table": {"title": "单价", "columns": [{"key": "a", "title": "金额", "type": "money"}, {"key": "q", "title": "数量", "type": "integer"},
                                           {"title": "单价", "type": "money", "formula": "a / q"}], "rows": [[100, 4], [50, 0]]}},
     {"warnings[0].code": "div_zero", "stats.empty_cells": 1,
      "xlsx_contains": {"xl/worksheets/sheet1.xml": ['<f>IFERROR(A3/B3,"")</f>', '<f>IFERROR(A2/B2,"")</f><v>25</v>']}, "md_contains": ["| 100.00 | 4 | 25.00 |"]})
case("b_round_fn", "round 与 max：round(7/3, 2) = 2.33；max(2.33, 3) = 3", "table.build",
     {"table": {"title": "函数", "columns": [{"key": "a", "title": "甲", "type": "number"}, {"key": "b", "title": "乙", "type": "number"},
                                           {"key": "r", "title": "商", "type": "number", "formula": "round(a / b, 2)"}, {"title": "取大", "formula": "max(r, 3)"}],
                "rows": [[7, 3]]}},
     {"model_contains": ['"2.33"', '["7","3","2.33","3"]']})
case("b_count_min_max", "count 可用于文字列；min、max 用于数值列", "table.build",
     {"table": {**STEEL, "columns": [{**STEEL["columns"][0], "type": "text"}, *STEEL["columns"][1:]],
                "totals": [{"column": "牌号", "fn": "count"}, {"column": "屈服强度", "fn": "max"}, {"column": "价格", "fn": "min"}]}},
     {"sheets[0].totals[0].value": "4", "sheets[0].totals[1].value": "355", "sheets[0].totals[2].value": "4200",
      "md_contains": ["| **4** | **355** | **4,200.00** |"]})
case("b_twice", "同一输入两次运行，output 与文件逐字节相同（TL-12 ②）", "table.build",
     {"table": {**BOM, "meta": {"date": "2026-10-24", "org": "传动部"}}, "formats": ["xlsx", "csv"]},
     {"twice": True, "file_count": 5})
case("b_assumptions", "assumptions 原样带出（TL-22a）", "table.build",
     {"table": {**STEEL, "assumptions": ["价格为 2026 年 10 月华东市场均价"]}},
     {"assumptions": ["价格为 2026 年 10 月华东市场均价"], "md_contains": ["假设：", "- 价格为 2026 年 10 月华东市场均价"]})
case("err_cell_type", "整数列写了小数：拒收并指明格子", "table.build",
     {"table": {"title": "T", "columns": [{"title": "数量", "type": "integer"}], "rows": [[2.5]]}},
     {"error.code": "BAD_INPUT", "error.where": "table.rows[0][0]"})
case("err_row_len", "格数与列数不符", "table.build",
     {"table": {"title": "T", "columns": ["甲", "乙"], "rows": [["1", "2", "3"]]}},
     {"error.code": "BAD_INPUT", "error.where": "table.rows[0]"})
case("err_formula_ref", "公式引用不存在的列", "table.build",
     {"table": {"title": "T", "columns": [{"key": "a", "title": "甲", "type": "number"}, {"title": "乙", "formula": "a * k"}], "rows": [[1]]}},
     {"error.code": "BAD_INPUT", "error.where": "table.columns[1].formula"})
case("err_formula_text", "公式引用文字列", "table.build",
     {"table": {"title": "T", "columns": [{"key": "a", "title": "甲", "type": "text"}, {"title": "乙", "formula": "a * 2"}], "rows": [["x"]]}},
     {"error.code": "BAD_INPUT", "error.where": "table.columns[1].formula"})
case("err_dup_title", "同一张表里列标题重复", "table.build",
     {"table": {"title": "T", "columns": ["甲", "甲"], "rows": []}},
     {"error.code": "BAD_INPUT", "error.where": "table.columns"})

# ---------------------------------------------------------------- 2.1.0：测试集《表格编辑能力 2026-11-12》由“没有”变“已有”的条目各一例
# 样例表 A（采购清单）、B（分包分解单）、C（月度预算）照测试集第三节原样写；期望值按测试集各条的预期手算。
# 叠加口径按 C2 退路（LibreOffice 实测不按属性合并，见 readings/table-2.1.0-cf/）：条件规则 > 格 > 行 > 列默认。
A_COLS = [{"key": "no", "title": "序号", "type": "integer"}, {"key": "item", "title": "品名"}, {"key": "spec", "title": "规格"},
          {"key": "unit", "title": "单位"}, {"key": "qty", "title": "数量", "type": "integer"},
          {"key": "price", "title": "单价", "type": "money"},
          {"key": "amt", "title": "金额", "type": "money", "formula": "数量 * 单价"}, {"key": "vendor", "title": "供应商"},
          {"key": "date", "title": "到货日期", "type": "date"}]
A_ROWS = [[1, "办公桌", "1400x700", "张", 12, 850, "宏达家具", "2026-11-20"],
          [2, "办公椅", "网布可升降", "把", 12, 320, "宏达家具", "2026-11-20"],
          [3, "文件柜", "1800*900*400", "个", 4, 680, "宏达家具", "2026-11-25"],
          [4, "投影仪", "4K 激光", "台", 1, 12800, "讯联电子", "2026-11-18"],
          [5, "会议桌", "3600×1400", "张", 1, 4600, "宏达家具", "2026-11-25"],
          [6, "网线", "六类 305m", "箱", 3, 560, "讯联电子", "2026-11-15"],
          [7, "插线板", "6 位 3m", "个", 20, 45, "京采办公", "2026-11-15"],
          [8, "白板", "1200×900", "块", 2, 180, "京采办公", "2026-11-15"]]
A_KEYS = ["序号", "品名", "规格", "单位", "数量", "单价", "供应商", "到货日期"]


def A(rows=None, **kw):
    t = {"title": "办公室装修采购清单", "columns": A_COLS, "rows": A_ROWS if rows is None else rows, "totals": ["金额"]}
    t.update(kw)
    return {"table": t}


def a_row(i, style):
    """表 A 第 i 行（从 1 起）写成对象行，带保留键 $style（样式跟着行走）。"""
    return {**dict(zip(A_KEYS, A_ROWS[i - 1])), "$style": style}


def a_rows_with(styles):
    return [a_row(i, styles[i]) if i in styles else r for i, r in enumerate(A_ROWS, start=1)]


B_COLS = [{"key": "code", "title": "编号"}, {"key": "name", "title": "名称"}, {"key": "spec", "title": "规格"},
          {"key": "mat", "title": "材质"}, {"key": "unit", "title": "单位"},
          {"key": "per", "title": "单件数量", "type": "integer"}, {"key": "sets", "title": "套数", "type": "integer"},
          {"key": "total", "title": "总数量", "type": "integer", "formula": "单件数量 * 套数"},
          {"key": "uw", "title": "单重", "type": "number", "unit": "kg"},
          {"key": "tw", "title": "总重", "type": "number", "unit": "kg", "formula": "总数量 * 单重"},
          {"key": "loss", "title": "损耗率", "type": "percent"}]
B_ROWS = [["1", "立柱组件", None, None, "套", None, 24, None, None],
          ["1.1", "立柱", "C100×50×2.0 L=6000", "Q235B", "根", 2, 24, 18.6, 3],
          ["1.2", "底脚板", "150×120×8", "Q235B", "块", 2, 24, 1.13, 2],
          ["1.3", "横斜撑", "C40×25×1.5 L=900", "Q235B", "根", 6, 24, 0.95, 3],
          ["2", "横梁组件", None, None, "套", None, 96, None, None],
          ["2.1", "横梁", "抱焊梁 100×50×1.5 L=2700", "Q235B", "根", 1, 96, 9.8, 3],
          ["2.2", "挂片", "三爪 t=4", "Q235B", "块", 2, 96, 0.32, 2],
          [None, "膨胀螺栓", "M12×100", "8.8 级", "套", 4, 24, 0.12, 5],
          [None, "螺栓", "M10×25", "8.8 级", "套", 8, 24, 0.03, 5],
          [None, "螺栓", "M10×25", "8.8 级", "套", 4, 96, 0.03, 5],
          [None, "安全销", "Φ6", None, "个", 2, 96, 0.01, 5]]


def B(extra_cols, totals=None):
    t = {"title": "钢货架分包分解单（草稿）", "columns": B_COLS + extra_cols, "rows": B_ROWS}
    if totals:
        t["totals"] = totals
    return {"table": t}


C_COLS = [{"key": "subj", "title": "科目"}, {"key": "dept", "title": "部门"},
          {"key": "budget", "title": "预算", "type": "money"}, {"key": "actual", "title": "实际", "type": "money"},
          {"key": "diff", "title": "差额", "type": "money", "formula": "实际 - 预算"},
          {"key": "rate", "title": "执行率", "type": "percent", "decimals": 1, "formula": "实际 / 预算"}]
C_ROWS = [["差旅费", "销售部", 30000, 34500], ["招待费", "销售部", 20000, 12800], ["办公用品", "行政部", 8000, 7650],
          ["房租水电", "行政部", 45000, 45000], ["培训费", "人力部", 15000, 21000], ["软件订阅", "研发部", 26000, 25200]]
C_TOTALS = ["预算", "实际", "差额"]


def C_(extra_cols=(), totals=None, **kw):
    t = {"title": "2026 年 11 月部门费用预算", "sheets": [{"id": "budget", "name": "预算表", "columns": C_COLS + list(extra_cols),
                                                       "rows": C_ROWS, "totals": C_TOTALS if totals is None else totals, **kw}]}
    return {"table": t}


RED_FONT = {"color": "#FF0000", "color_dark": "#FF7B72"}
RED_FILL = {"fill": "#FF0000", "fill_dark": "#8E1B1B"}
YELLOW_FILL = {"fill": "#FFFF00", "fill_dark": "#6B6400"}
LGRAY_FILL = {"fill": "#D9D9D9", "fill_dark": "#33332F"}
S = "xl/worksheets/sheet1.xml"
SIG_G2 = "ROUND($G2,14-INT(LOG10(ABS($G2)+($G2=0))))"
R_AMT = {"when": "金额 > 10000", "style": {"color": "红"}}

case("t1_04_date_format", "T1-04 到货日期显示成“2026年11月20日”：值不变，Excel 里仍是日期型（G5）", "table.build",
     {**A(columns=[*A_COLS[:8], {**A_COLS[8], "date_format": "YYYY年M月D日"}]), "formats": ["xlsx", "csv"]},
     {"md_contains": ["| 宏达家具 | 2026年11月20日 |", "| 讯联电子 | 2026年11月18日 |"],
      "model": {"sheets[0].rows[0][8]": "2026-11-20", "sheets[0].columns[8].date_format": "YYYY年M月D日"},
      "csv_contains": ["宏达家具,2026-11-20"],
      "xlsx_contains": {"xl/styles.xml": ['formatCode="yyyy&quot;年&quot;m&quot;月&quot;d&quot;日&quot;"'], S: ["<c r=\"I2\" s="]}})
case("t3_03_roundup", "T3-03 下料数量 = 总数量 ×（1 + 损耗率）向上取整；组件行留空；Excel 里是 ROUNDUP 公式（G2、G4）", "table.build",
     B([{"key": "cut", "title": "下料数量", "type": "integer", "formula": "roundup(总数量 * (1 + 损耗率))"}]),
     {"model": {"sheets[0].rows[0][11]": None, "sheets[0].rows[4][11]": None,
                "sheets[0].rows[1][11]": "50", "sheets[0].rows[2][11]": "49", "sheets[0].rows[3][11]": "149",
                "sheets[0].rows[5][11]": "99", "sheets[0].rows[6][11]": "196", "sheets[0].rows[7][11]": "101",
                "sheets[0].rows[8][11]": "202", "sheets[0].rows[9][11]": "404", "sheets[0].rows[10][11]": "202"},
      "warning_codes": [],
      "xlsx_contains": {S: ["<f>IF(COUNT(F3,G3)=2,ROUND(F3*G3,0),\"\")</f><v>48</v>",
                            "<f>IF(COUNT(H3,K3)=2,ROUND(ROUNDUP(ROUND((H3*(1+K3)),14-INT(LOG10(ABS((H3*(1+K3)))+((H3*(1+K3))=0)))),0),0),\"\")</f><v>50</v>"]}})
case("t3_04_if_text", "T3-04 状态 = if(执行率 > 100%, 超支, 正常)：文字结果的公式列；正好 100% 是正常（G2）", "table.build",
     C_([{"key": "state", "title": "状态", "type": "text", "formula": "if(执行率 > 100%, \"超支\", \"正常\")"}]),
     {"model": {"sheets[0].rows[0][6]": "超支", "sheets[0].rows[1][6]": "正常", "sheets[0].rows[2][6]": "正常",
                "sheets[0].rows[3][6]": "正常", "sheets[0].rows[4][6]": "超支", "sheets[0].rows[5][6]": "正常",
                "sheets[0].columns[6].type": "text"},
      "md_contains": ["公式：差额 = 实际 - 预算；执行率 = 实际 ÷ 预算；状态 = if(执行率 > 100%, \"超支\", \"正常\")"],
      "xlsx_contains": {S: ["<f>IF(ROUND(F2,14-INT(LOG10(ABS(F2)+(F2=0))))&gt;1,\"超支\",\"正常\")</f><v>超支</v>"]}})
case("t3_05_share", "T3-05 占比 = 实际 ÷ 实际的合计（total），一位小数；六行合计 100.0%（G2）", "table.build",
     C_([{"key": "share", "title": "占比", "type": "percent", "decimals": 1, "formula": "实际 / total(实际)"}],
        totals=C_TOTALS + ["占比"]),
     {"model": {"sheets[0].rows[0][6]": "0.236", "sheets[0].rows[1][6]": "0.088", "sheets[0].rows[2][6]": "0.052",
                "sheets[0].rows[3][6]": "0.308", "sheets[0].rows[4][6]": "0.144", "sheets[0].rows[5][6]": "0.172"},
      "sheets[0].totals[3].value": "1", "md_contains": ["| 差旅费 | 销售部 | 30,000.00 | 34,500.00 | 4,500.00 | 115.0% | 23.6% |",
                                                        "**100.0%** |"],
      "warning_codes": ["ratio_total"],
      "xlsx_contains": {S: ["<f>IFERROR(ROUND(D2/SUM($D$2:$D$7),3),\"\")</f>"]}})
case("t3_06_totals_mixed", "T3-06 合计行：数量求和 55、单价平均 2504.38、金额 37100；产出台标出每格的算法（G3）", "table.build",
     A(totals=["数量", {"column": "单价", "fn": "avg"}, "金额"]),
     {"sheets[0].totals[0].value": "55", "sheets[0].totals[1].value": "2504.38", "sheets[0].totals[2].value": "37100",
      "view": {"sheets[0].totals_fn": [None, None, None, None, "sum", "avg", "sum", None, None]},
      "md_contains": ["| **合计 / 平均** |  |  |  | **55** | **2,504.38** | **37,100.00** |  |  |"],
      "xlsx_contains": {S: ["<f>SUM(E2:E9)</f><v>55</v>", "<f>ROUND(AVERAGE(F2:F9),2)</f><v>2504.38</v>", "<f>SUM(G2:G9)</f><v>37100</v>"]}})
case("t3_09_tons", "T3-09 总重换算成吨、三位小数：精度口径 b 逐行舍入，合计 2.118；另告警先加后舍入为 2.117（G4、C4）", "table.build",
     B([{"key": "tw_t", "title": "总重（吨）", "type": "number", "unit": "t", "decimals": 3, "formula": "总重 / 1000"}],
       totals=["总重", "总重（吨）"]),
     {"model": {"sheets[0].rows[1][11]": "0.893", "sheets[0].rows[2][11]": "0.054", "sheets[0].rows[3][11]": "0.137",
                "sheets[0].rows[5][11]": "0.941", "sheets[0].rows[6][11]": "0.061", "sheets[0].columns[8].unit": "kg"},
      "sheets[0].totals[0].value": "2116.8", "sheets[0].totals[1].value": "2.118",
      "warning_codes": ["rounded_sum"], "warnings_contain": ["合计为 2.118", "相加后再舍入为 2.117"],
      "xlsx_contains": {S: ["<f>IF(COUNT(J3)=1,IFERROR(ROUND(J3/1000,3),\"\"),\"\")</f><v>0.893</v>", "<f>ROUND(SUM(L2:L12),3)</f><v>2.118</v>"]}})
case("t3_10_cumsum", "T3-10 累计实际：从上往下累加，末行等于实际的合计（G2）", "table.build",
     C_([{"key": "cum", "title": "累计实际", "type": "money", "formula": "cumsum(实际)"}]),
     {"model": {"sheets[0].rows[0][6]": "34500", "sheets[0].rows[1][6]": "47300", "sheets[0].rows[2][6]": "54950",
                "sheets[0].rows[3][6]": "99950", "sheets[0].rows[4][6]": "120950", "sheets[0].rows[5][6]": "146150"},
      "sheets[0].totals[1].value": "146150",
      "xlsx_contains": {S: ["<f>SUM($D$2:$D2)</f><v>34500</v>", "<f>SUM($D$2:$D7)</f><v>146150</v>"]}})
case("t3_11_ratio_total", "T3-11 合计行的执行率按公式重算：146150 ÷ 144000 = 101.5%，不是六行平均 101.9%（G3）", "table.build",
     C_(totals=C_TOTALS + [{"column": "执行率", "fn": "formula"}]),
     {"sheets[0].totals[3].fn": "formula", "sheets[0].totals[3].value": "1.015", "warning_codes": [],
      "md_contains": ["| **合计** |  | **144,000.00** | **146,150.00** | **2,150.00** | **101.5%** |"],
      "view": {"sheets[0].totals_fn": [None, None, "sum", "sum", "sum", "formula"]},
      "xlsx_contains": {S: ["<f>IFERROR(ROUND(D8/C8,3),\"\")</f><v>1.015</v>", "<f>IFERROR(ROUND(D2/C2,3),\"\")</f><v>1.15</v>"]}})
case("t4_01_rule_amount", "T4-01 金额超过 1 万标红：挂在金额列上的条件规则，只管数据行；Excel 里是条件格式（G1）", "table.build",
     A(rules=[R_AMT]),
     {"view": {"sheets[0].styles": [RED_FONT], "sheets[0].cell_styles": [[0, 6, 0], [3, 6, 0]],
               "sheets[0].rules": [{"n": 1, "text": "金额 > 10000 → 金额红字"}], "sheets[0].totals_styles": "<缺席>"},
      "model": {"sheets[0].rules": [{"when": "金额 > 10000", "apply_to": ["amt"], "style": {"color": "红"}}]},
      "xlsx_contains": {S: ['<conditionalFormatting sqref="G2:G9">', f"<formula>AND(COUNT($G2)=1,{SIG_G2}&gt;10000)</formula>"],
                        "xl/styles.xml": ['<dxf><font><color rgb="FFFF0000"/></font></dxf>']}})
case("t4_01_rule_follows_value", "T4-01 办公椅数量改成 40（金额 12800）后，该格自动变红：规则不是给两格涂色", "table.build",
     A(rows=[A_ROWS[0], [2, "办公椅", "网布可升降", "把", 40, 320, "宏达家具", "2026-11-20"], *A_ROWS[2:]], rules=[R_AMT]),
     {"view": {"sheets[0].cell_styles": [[0, 6, 0], [1, 6, 0], [3, 6, 0]]}, "sheets[0].totals[0].value": "46060"})
case("t4_02_rule_sign", "T4-02 差额负数标红、正数标绿，0 不着色（G1）", "table.build",
     C_(rules=[{"when": "差额 < 0", "style": {"color": "红"}}, {"when": "差额 > 0", "style": {"color": "绿"}}]),
     {"view": {"sheets[0].styles": [{"color": "#00B050", "color_dark": "#5FD38D"}, RED_FONT],
               "sheets[0].cell_styles": [[0, 4, 0], [1, 4, 1], [2, 4, 1], [4, 4, 0], [5, 4, 1]]}})
case("t4_03_cell_style", "T4-03 这一格标黄（投影仪的单价）：样式写在那一行的 $style 里，值与合计不变（G1、C1）", "table.build",
     A(rows=a_rows_with({4: {"cells": {"单价": {"fill": "黄"}}}})),
     {"view": {"sheets[0].styles": [YELLOW_FILL], "sheets[0].cell_styles": [[3, 5, 0]]},
      "sheets[0].totals[0].value": "37100",
      "model_contains": ['"$style":{"cells":{"price":{"fill":"黄"}}}', '"price":"12800"'],
      "xlsx_contains": {"xl/styles.xml": ['<fgColor rgb="FFFFFF00"/>']}})
case("t4_04_row_gray", "T4-04 第 7、8 行整行置灰：值与合计 37100 都不变（G1、C1）", "table.build",
     A(rows=a_rows_with({7: {"row": {"fill": "浅灰"}}, 8: {"row": {"fill": "浅灰"}}})),
     {"view": {"sheets[0].styles": [LGRAY_FILL], "sheets[0].cell_styles[0]": [6, 0, 0], "sheets[0].cell_styles[6]": [6, 6, 0],
               "sheets[0].cell_styles[17]": [7, 8, 0], "sheets[0].cell_styles[18]": "<缺席>"},
      "sheets[0].totals[0].value": "37100"})
case("t4_06_header_align_width", "T4-06 表头深蓝底白字；品名左对齐、数量单价金额右对齐；规格列宽一点（G1）", "table.build",
     A(columns=[*A_COLS[:2], {**A_COLS[2], "width": 24}, *A_COLS[3:]], header_style={"fill": "深蓝", "color": "白"}),
     {"view": {"sheets[0].header_style": 0,
               "sheets[0].styles": [{"fill": "#1F3864", "fill_dark": "#22385F", "color": "#FFFFFF", "color_dark": "#ECECE8"}],
               "sheets[0].columns[1].align": "left", "sheets[0].columns[4].align": "right", "sheets[0].columns[6].align": "right"},
      "xlsx_contains": {S: ['<col min="3" max="3" width="24.7109375" customWidth="1"/>'],
                        "xl/styles.xml": ['<fgColor rgb="FF1F3864"/>', '<color rgb="FFFFFFFF"/>']}})
case("t4_07_row_and_rule", "T4-07 已有金额红字规则，投影仪整行标黄：那一格黄底 + 红字并存，办公桌金额仍只是红字（G1 叠加）", "table.build",
     A(rows=a_rows_with({4: {"row": {"fill": "黄"}}}), rules=[R_AMT]),
     {"view": {"sheets[0].cell_styles[0]": [0, 6, 0], "sheets[0].cell_styles[1]": [3, 0, 1], "sheets[0].cell_styles[7]": [3, 6, 2],
               "sheets[0].styles": [RED_FONT, YELLOW_FILL, {**YELLOW_FILL, **RED_FONT}]}})
case("t4_08_cell_over_row", "T4-08 第 7、8 行已置灰，第 7 行金额格标黄：那一格黄、同行其余仍灰（格 > 行）；去掉格样式回到灰见 t4_04", "table.build",
     A(rows=a_rows_with({7: {"row": {"fill": "浅灰"}, "cells": {"金额": {"fill": "黄"}}}, 8: {"row": {"fill": "浅灰"}}})),
     {"view": {"sheets[0].styles": [LGRAY_FILL, YELLOW_FILL], "sheets[0].cell_styles[5]": [6, 5, 0],
               "sheets[0].cell_styles[6]": [6, 6, 1], "sheets[0].cell_styles[7]": [6, 7, 0]}})
case("t4_09_rule_over_cell", "T4-09（C2 退路口径）已有金额红底规则，投影仪金额格点名黄底：规则压过静态，该格红底，与 Excel 打开一致", "table.build",
     A(rows=a_rows_with({4: {"cells": {"金额": {"fill": "黄"}}}}), rules=[{"when": "金额 > 10000", "style": {"fill": "红"}}]),
     {"view": {"sheets[0].styles": [RED_FILL], "sheets[0].cell_styles": [[0, 6, 0], [3, 6, 0]]},
      "xlsx_contains": {"xl/styles.xml": ['<fgColor rgb="FFFFFF00"/>', '<dxf><fill><patternFill><bgColor rgb="FFFF0000"/></patternFill></fill></dxf>'],
                        S: ['<conditionalFormatting sqref="G2:G9">']}})
case("t4_10_rule_order", "T4-10 已有“实际超过 3 万标红”，再加“超过 2 万标橙”：先设的优先，34500、45000 红，21000、25200 橙；回显次序（G1）", "table.build",
     C_(rules=[{"when": "实际 > 30000", "style": {"color": "红"}}, {"when": "实际 > 20000", "style": {"color": "橙"}}]),
     {"view": {"sheets[0].styles": [RED_FONT, {"color": "#FFC000", "color_dark": "#FFB547"}],
               "sheets[0].cell_styles": [[0, 3, 0], [3, 3, 0], [4, 3, 1], [5, 3, 1]],
               "sheets[0].rules": [{"n": 1, "text": "实际 > 30000 → 实际红字"}, {"n": 2, "text": "实际 > 20000 → 实际橙字"}]},
      "xlsx_contains": {S: ['type="expression" dxfId="0" priority="1"', 'type="expression" dxfId="1" priority="2"']}})
case("t4_11_color_scale", "T4-11 执行率做成颜色深浅：64.0% 最浅、140.0% 最深，按比例；Excel 里是色阶（G1）", "table.build",
     C_(rules=[{"scale": {"column": "执行率", "from": "白", "to": "蓝"}}]),
     {"view": {"sheets[0].styles[0]": {"fill": "#549FD5", "fill_dark": "#1C3D62"}, "sheets[0].styles[1]": {"fill": "#FFFFFF", "fill_dark": "#191918"},
               "sheets[0].styles[4]": {"fill": "#0070C0", "fill_dark": "#1D4F86"}, "sheets[0].cell_styles[1]": [1, 5, 1],
               "sheets[0].rules": [{"n": 1, "text": "执行率：色阶，最小值白 → 最大值蓝"}]},
      "xlsx_contains": {S: ['<conditionalFormatting sqref="F2:F7">', 'type="colorScale"', '<color rgb="FF0070C0"/>']}})
case("t4_12_rule_row", "T4-12 到货日期晚于 11 月 20 日的整行标浅黄：条件看一列、着色落在整行；20 日当天不算（G1）", "table.build",
     A(rules=[{"when": "到货日期 > \"2026-11-20\"", "apply_to": "row", "style": {"fill": "浅黄"}}]),
     {"view": {"sheets[0].styles": [{"fill": "#FFF2CC", "fill_dark": "#4A4220"}], "sheets[0].cell_styles[0]": [2, 0, 0],
               "sheets[0].cell_styles[8]": [2, 8, 0], "sheets[0].cell_styles[9]": [4, 0, 0], "sheets[0].cell_styles[17]": [4, 8, 0],
               "sheets[0].cell_styles[18]": "<缺席>"},
      "xlsx_contains": {S: ['<conditionalFormatting sqref="A2:I9">', "<formula>AND(COUNT($I2)=1,$I2&gt;DATE(2026,11,20))</formula>"]}})
case("t4_13_rule_cross_column", "T4-13 实际超预算的标红：规则比的是同一行的另一列（G1）", "table.build",
     C_(rules=[{"when": "实际 > 预算", "apply_to": ["实际"], "style": {"color": "红"}}]),
     {"view": {"sheets[0].cell_styles": [[0, 3, 0], [4, 3, 0]]},
      "xlsx_contains": {S: ['<conditionalFormatting sqref="D2:D7">',
                            "<formula>AND(COUNT($C2,$D2)=2,ROUND($D2,14-INT(LOG10(ABS($D2)+($D2=0))))&gt;ROUND($C2,14-INT(LOG10(ABS($C2)+($C2=0)))))</formula>"]}})
_ADJ = [[r[0], r[1], b, r[3]] for r, b in zip(C_ROWS, [33000, 22000, 8800, 49500, 16500, 28600])]
_RULES_SIGN = [{"when": "差额 < 0", "style": {"color": "红"}}, {"when": "差额 > 0", "style": {"color": "绿"}}]
case("t6_08_copy_sheet", "T6-08 预算表复制一份“预算表-调整版”、预算上调 10%：副本重算，原表不动，规则带到副本（G1）", "table.build",
     {"table": {"title": "2026 年 11 月部门费用预算", "sheets": [
         {"id": "budget", "name": "预算表", "columns": C_COLS, "rows": C_ROWS, "totals": C_TOTALS, "rules": _RULES_SIGN},
         {"id": "budget_adj", "name": "预算表-调整版", "columns": C_COLS, "rows": _ADJ, "totals": C_TOTALS, "rules": _RULES_SIGN}]}},
     {"sheets[0].totals[0].value": "144000", "sheets[1].totals[0].value": "158400",
      "model": {"sheets[1].rows[0][5]": "1.045", "sheets[1].rows[0][4]": "1500", "sheets[0].rows[0][5]": "1.15"},
      "view": {"sheets[1].rules[1].text": "差额 > 0 → 差额绿字", "sheets[0].cell_styles": [[0, 4, 0], [1, 4, 1], [2, 4, 1], [4, 4, 0], [5, 4, 1]]}})
case("t7_01_default_look", "T7-01 “让它好看点”给一套保守默认：只动样式（表头、合计行），值、公式、行、列一格不变（G1）", "table.build",
     A(header_style={"fill": "浅灰", "bold": True}, row_styles=[{"kind": "total", "style": {"bold": True, "fill": "浅灰"}}]),
     {"model": {"sheets[0].rows[3]": ["4", "投影仪", "4K 激光", "台", "1", "12800", "12800", "讯联电子", "2026-11-18"],
                "sheets[0].row_styles": [{"kind": "total", "style": {"fill": "浅灰", "bold": True}}]},
      "sheets[0].totals[0].value": "37100",
      "view": {"sheets[0].styles": [{**LGRAY_FILL, "bold": True}], "sheets[0].header_style": 0, "sheets[0].totals_styles[8]": [8, 0],
               "sheets[0].cell_styles": "<缺席>"}})
case("t7_11_rule_default_threshold", "T7-11 “金额大的标红”没给门槛：取明示的默认（高于平均值 4637.5）并回显规则（G1）", "table.build",
     A(rules=[{"when": "金额 > 4637.5", "label": "高于平均值", "style": {"color": "红"}}]),
     {"view": {"sheets[0].cell_styles": [[0, 6, 0], [3, 6, 0]],
               "sheets[0].rules": [{"n": 1, "text": "金额 > 4637.5 → 金额红字", "label": "高于平均值"}]}})
case("t7_14_header_gray", "T7-14 澄清后取“表头灰底”这一支：header_style 只给表头着色（G1）", "table.build",
     A(header_style={"fill": "浅灰"}),
     {"view": {"sheets[0].styles": [LGRAY_FILL], "sheets[0].header_style": 0}})
case("g1_style_follows_row", "C1 样式跟着行走：行的次序倒过来，投影仪那一行的黄底仍在投影仪上（不按行号寻址）", "table.build",
     A(rows=list(reversed(a_rows_with({4: {"row": {"fill": "黄"}}})))),
     {"view": {"sheets[0].cell_styles[0]": [4, 0, 0], "sheets[0].rows[4][1]": "投影仪"}})
case("g4_float_boundary", "G4 大数边界：5335500×1.1、1624290×1.1、6726000×1.08、90×1.1 向上取整，产出台按十进制得整数，逐格告警 Excel 可能多 1", "table.build",
     {"table": {"title": "边界", "columns": [{"key": "n", "title": "基数", "type": "integer"}, {"key": "k", "title": "系数", "type": "number"},
                                           {"title": "取整", "type": "integer", "formula": "roundup(基数 * 系数)"}],
                "rows": [[5335500, 1.1], [1624290, 1.1], [6726000, 1.08], [90, 1.1]]}},
     {"model": {"sheets[0].rows[0][2]": "5869050", "sheets[0].rows[1][2]": "1786719", "sheets[0].rows[2][2]": "7264080",
                "sheets[0].rows[3][2]": "99"},
      "warning_codes": ["excel_float"] * 4,
      "warnings_contain": ["第 1 行（边界!C2）在 Excel 里重算可能得 5869051；产出台按十进制算得 5869050", "可能得 1786720", "可能得 7264081", "可能得 100"]})
case("g2_ceiling_floor", "G2 ceiling、floor 取到倍数（照 Excel：ceiling 朝正无穷、floor 朝负无穷），rounddown 趋向零", "table.build",
     {"table": {"title": "取整", "columns": [{"key": "x", "title": "长度", "type": "number"},
                                           {"title": "上", "type": "number", "formula": "ceiling(长度, 50)"},
                                           {"title": "下", "type": "number", "formula": "floor(长度, 50)"},
                                           {"title": "截", "type": "number", "formula": "rounddown(长度 / 7, 1)"}],
                "rows": [[1234], [1201], [-7]]}},
     {"model": {"sheets[0].rows[0]": ["1234", "1250", "1200", "176.2"], "sheets[0].rows[1]": ["1201", "1250", "1200", "171.5"],
                "sheets[0].rows[2]": ["-7", "0", "-50", "-1"]}})
case("g3_none_and_ratio_warning", "G3 fn none 显式留空；比率类公式列配 sum 告警 ratio_total（只告警，不改结果）", "table.build",
     C_(totals=C_TOTALS + [{"column": "执行率", "fn": "avg"}, {"column": "科目", "fn": "none"}]),
     {"sheets[0].totals[0].fn": "none", "sheets[0].totals[0].value": None, "sheets[0].totals[4].value": "1.019",
      "warning_codes": ["ratio_total"], "md_contains": ["|  |  | **144,000.00** |"]})
case("g5_thousands", "G5 number 列加千分位、integer 列去掉千分位", "table.build",
     {"table": {"title": "千分位", "columns": [{"title": "年份", "type": "integer", "thousands": False},
                                            {"title": "产值", "type": "number", "decimals": 1, "thousands": True}],
                "rows": [[2026, 12345.67], [2025, 987.6]]}},
     {"md_contains": ["| 2026 | 12,345.7 |", "| 2025 | 987.6 |"],
      "xlsx_contains": {"xl/styles.xml": ['formatCode="#,##0.0"', 'numFmtId="1"']}})
case("err_display_column", "$style 的 cells 里写了表里没有的列", "table.build",
     A(rows=a_rows_with({4: {"cells": {"颜色": {"fill": "黄"}}}})),
     {"error.code": "BAD_INPUT", "error.where": "table.rows[3].$style.cells"})
case("err_rule_not_condition", "规则的 when 不是条件", "table.build",
     A(rules=[{"when": "金额 + 1", "style": {"color": "红"}}]),
     {"error.code": "BAD_INPUT", "error.where": "table.rules[0].when"})
case("err_color", "颜色不在色板里", "table.build",
     A(header_style={"fill": "紫"}),
     {"error.code": "BAD_INPUT", "error.where": "table.header_style.fill"})
case("err_row_kind", "row_styles 只按行种类写（2.1.0 只有 total），不收行号", "table.build",
     A(row_styles=[{"rows": [1, 2], "style": {"fill": "黄"}}]),
     {"error.code": "BAD_INPUT", "error.where": "table.row_styles[0].rows"})
case("err_if_constant", "if 的两支暂不收数字常数（#711 §九 第 5 步）", "table.build",
     A(columns=[*A_COLS, {"title": "大件", "type": "integer", "formula": "if(数量 > 10, 1, 0)"}]),
     {"error.code": "BAD_INPUT", "error.where": "table.columns[9].formula"})
case("err_text_formula_type", "结果是文字的公式列要写 type text", "table.build",
     C_([{"title": "状态", "formula": "if(执行率 > 100%, \"超支\", \"正常\")"}]),
     {"error.code": "BAD_INPUT", "error.where": "table.sheets[0].columns[6].type"})

# ---------------------------------------------------------------- 2.2.0：测试集条目（G7–G11、G17），期望值按测试集各条手算
B2_COLS = [{"key": "code", "title": "编号", "numbering": "outline"}, {"key": "cat", "title": "类别", "type": "text"}] + B_COLS[1:] + [
    {"key": "cut", "title": "下料数量", "type": "integer", "formula": "roundup(总数量 * (1 + 损耗率))"}, {"key": "memo", "title": "备注", "type": "text"}]
B_CAT = ["组件", "子件", "子件", "子件", "组件", "子件", "子件", "五金件", "五金件", "五金件", "五金件"]
B_MEMO = ["组件行", None, None, None, "组件行", None, None, "五金件", "五金件，立柱用", "五金件，横梁用", "五金件"]


def B2(sets=(24, 96), **kw):
    """表 B 按 #717 §六 第 1 点加一列“类别”（组件、子件、五金件），编号由工具按层级编。"""
    rows = []
    for k, (cat, r, memo) in enumerate(zip(B_CAT, B_ROWS, B_MEMO)):
        r = list(r[1:])
        if r[5] in (24, 96):
            r[5] = sets[0] if k < 4 or k in (7, 8) else sets[1]
        rows.append([cat] + r + [memo])
    t = {"title": "钢货架分包分解单", "columns": B2_COLS, "rows": rows,
         "outline_from": {"column": "类别", "levels": {"组件": 1, "子件": 2}}}
    t.update(kw)
    return {"table": t}


B_GROUP = {"by": "outline", "rest_label": "五金件"}
B_MERGE = {"by": ["名称", "规格"], "agg": {"总数量": "sum", "总重": "formula", "下料数量": "formula"}, "join": ["备注"]}
SUB_STYLE = {"kind": "subtotal", "style": {"fill": "浅灰", "bold": True}}
DET_ROWS = [["2026-11-03", "差旅费", "销售部", 12000, "张三"], ["2026-11-08", "差旅费", "销售部", 9500, "李四"],
            ["2026-11-20", "差旅费", "销售部", 13000, "张三"], ["2026-11-05", "招待费", "销售部", 7800, "李四"],
            ["2026-11-18", "招待费", "销售部", 5000, "王五"], ["2026-11-02", "办公用品", "行政部", 2650, "赵六"],
            ["2026-11-12", "办公用品", "行政部", 3000, "赵六"], ["2026-11-25", "办公用品", "行政部", 2000, "赵六"],
            ["2026-11-01", "房租水电", "行政部", 45000, "赵六"], ["2026-11-15", "培训费", "人力部", 21000, "孙七"],
            ["2026-11-10", "软件订阅", "研发部", 13200, "周八"], ["2026-11-28", "软件订阅", "研发部", 12000, "周八"]]
DET_COLS = [{"key": "day", "title": "日期", "type": "date"}, {"key": "subj", "title": "科目", "type": "text"},
            {"key": "dept", "title": "部门", "type": "text"}, {"key": "amt", "title": "金额", "type": "money"}, {"key": "who", "title": "经办人"}]
C_SUMIF = [*C_COLS[:3], {**C_COLS[3], "formula": "sumif(detail.科目, 科目, detail.金额)"}, *C_COLS[4:]]
C_BUDGET_ONLY = [[r[0], r[1], r[2]] for r in C_ROWS]


def C2(det_name="费用明细", det_rows=None, extra_sheets=(), order=None, det_rules=None, budget_rules=None):
    det = {"id": "detail", "name": det_name, "columns": DET_COLS, "rows": DET_ROWS if det_rows is None else det_rows, "totals": ["金额"]}
    if det_rules:
        det["rules"] = det_rules
    bud = {"id": "budget", "name": "预算表", "columns": C_SUMIF, "rows": C_BUDGET_ONLY, "totals": C_TOTALS}
    if budget_rules:
        bud["rules"] = budget_rules
    t = {"title": "2026 年 11 月部门费用预算", "sheets": [bud, det, *extra_sheets]}
    if order:
        t["sheet_order"] = order
    return {"table": t}


SUMMARY = {"id": "summary", "name": "汇总", "columns": [{"key": "dept", "title": "部门", "type": "text"},
                                                       {"key": "budget", "title": "预算", "type": "money"},
                                                       {"key": "actual", "title": "实际", "type": "money"}],
           "derive": {"from": ["budget"], "by": ["部门"], "agg": {"预算": "sum", "实际": "sum"}}, "totals": ["预算", "实际"]}
D_COLS = [{"key": "no", "title": "序号", "numbering": "outline"}, {"key": "code", "title": "产品编号"}, {"key": "name", "title": "产品名称", "type": "text"},
          {"key": "dwg", "title": "图纸号"}, {"key": "spec", "title": "规格", "type": "text"}, {"key": "mat", "title": "材质", "type": "text"},
          {"key": "qty", "title": "数量", "type": "integer"}, {"key": "unit", "title": "单位"}, {"key": "color", "title": "颜色1"},
          {"key": "role", "title": "产品角色", "type": "text"}, {"key": "memo", "title": "备注"},
          {"key": "uw", "title": "单重/面积", "type": "number"}, {"key": "tw", "title": "总重", "type": "number"}]
D_OL = {"column": "产品角色", "levels": {"主件": 1, "焊接子件": 2}}


def drow(rid, name, dwg, spec, qty, role, mat="Q235B"):
    o = {"产品名称": name, "图纸号": dwg, "规格": spec, "数量": qty, "产品角色": role, "材质": mat}
    if rid:
        o["$id"] = rid
    return o


def D_s01(hw="ceiling(@r1.数量*{k}*1.005)", extra=None, qty0={"$expr": "6*28"}):
    rows = [drow("r1", "立柱", "GK-LZ-100", "100×70×2.0 L=9000", qty0, "主件"),
            drow("r2", "立柱型材", "GK-LZ-101", "100×70×2.0 L=8990", {"$expr": "@r1.数量"}, "焊接子件"),
            drow("r3", "底板", "GK-LZ-102", "150×150×10", {"$expr": "@r1.数量"}, "焊接子件"),
            drow("r4", "护脚", None, "400×120×5", {"$expr": "6*2"}, "主件"),
            drow("r5", "膨胀螺栓", None, "M12×100", {"$expr": hw.format(k=4)}, "五金", "8.8 级"),
            drow("r6", "螺栓", None, "M10×25", {"$expr": hw.format(k=6)}, "五金", "8.8 级")]
    if extra:
        rows[2:2] = [extra]
    return {"id": "s01", "name": "01立柱", "columns": D_COLS, "outline_from": D_OL, "rows": rows}


def D_s02(hw="ceiling(@r1.数量*{k}*1.005)", mat_r3="Q235B"):
    return {"id": "s02", "name": "02横梁", "columns": D_COLS, "outline_from": D_OL, "rows": [
        drow("r1", "横梁", "GK-HL-2700", "100×50×1.5 L=2700", {"$expr": "6*27*8"}, "主件"),
        drow("r2", "梁管", "GK-HL-2701", "100×50×1.5 L=2690", {"$expr": "@r1.数量"}, "焊接子件"),
        drow("r3", "挂片", "GK-HL-2702", "三爪 t=4", {"$expr": "@r1.数量*2"}, "焊接子件", mat_r3),
        drow("r4", "加强连接板", None, "200×80×6", {"$expr": "6*4"}, "主件"),
        drow("r5", "安全销", None, "Φ6", {"$expr": hw.format(k=2)}, "五金", "8.8 级"),
        drow("r6", "螺栓", None, "M10×25", {"$expr": hw.format(k=4)}, "五金", "8.8 级")]}


def D_s00(qty_hl="@s02/r1.数量"):
    return {"id": "s00", "name": "总清单", "columns": D_COLS, "outline_from": D_OL, "rows": [
        drow(None, "立柱", "GK-LZ-100", "100×70×2.0 L=9000", {"$expr": "@s01/r1.数量"}, "主件"),
        drow(None, "护脚", None, "400×120×5", {"$expr": "@s01/r4.数量"}, "主件"),
        drow(None, "横梁", "GK-HL-2700", "100×50×1.5 L=2700", {"$expr": qty_hl} if isinstance(qty_hl, str) else qty_hl, "主件"),
        drow(None, "加强连接板", None, "200×80×6", {"$expr": "@s02/r4.数量"}, "主件")]}


D_S99 = {"id": "s99", "name": "标准件", "columns": D_COLS, "outline_from": D_OL,
         "derive": {"from": ["s01", "s02"], "where": "产品角色 = \"五金\"", "by": ["产品名称", "规格"], "agg": {"数量": "sum"}}}
D_EMPTY = [{"id": sid, "name": name, "columns": D_COLS, "outline_from": D_OL} for sid, name in
           (("s03", "03背交叉"), ("s04", "04吊梁天轨"), ("s06", "06地轨"), ("s07", "07撞头"))]
D_ORDER = ["s00", "s01", "s02", "s03", "s04", "s05", "s06", "s07", "s99"]


def D(*sheets, order=None):
    t = {"title": "SO260415005 立库分包分解清单", "sheets": list(sheets)}
    if order:
        t["sheet_order"] = order
    return {"table": t}


S1 = "xl/worksheets/sheet1.xml"
S2 = "xl/worksheets/sheet2.xml"
S3 = "xl/worksheets/sheet3.xml"
# —— G7 分组、小计
case("t3_07_group_subtotal", "T3-07 按供应商出小计、最后出总计：同一供应商排在一起；小计 21360、14480、1260；总计 37100 不重复计小计（G7）", "table.build",
     A(group={"by": "供应商"}, subtotals=["金额"]),
     {"model": {"sheets[0].rows[3][1]": "会议桌", "sheets[0].rows[4][1]": "投影仪"},
      "view": {"sheets[0].layout[0]": {"k": "g", "g": 0, "cells": ["", "宏达家具", "", "", "", "", "", "", ""]},
               "sheets[0].layout[5].cells[6]": "21,360.00", "sheets[0].layout[5].cells[1]": "宏达家具 小计",
               "sheets[0].layout[9].cells[6]": "14,480.00", "sheets[0].layout[13].cells[6]": "1,260.00"},
      "sheets[0].totals[0].value": "37100",
      "xlsx_contains": {S: ["<f>SUBTOTAL(9,G3:G6)</f><v>21360</v>", "<f>SUBTOTAL(9,G3:G6,G9:G10,G13:G14)</f><v>37100</v>"]}})
case("t3_07_group_add_row", "T3-07 往讯联电子组加一行（投影幕 1500）：该组小计 15980、总计 38600 跟着变", "table.build",
     A(rows=[*A_ROWS, [9, "投影幕", "120 寸", "块", 1, 1500, "讯联电子", "2026-11-18"]], group={"by": "供应商"}, subtotals=["金额"]),
     {"view": {"sheets[0].layout[10].cells[6]": "15,980.00"}, "sheets[0].totals[0].value": "38600"})
case("t4_05_kind_styles", "T4-05 小计行灰底加粗、总计行更深：样式按行种类写，新出的小计行自动带上（G1+G7）", "table.build",
     A(group={"by": "供应商"}, subtotals=["金额"], row_styles=[SUB_STYLE, {"kind": "total", "style": {"fill": "灰", "bold": True}}]),
     {"view": {"sheets[0].layout[5].st": 1, "sheets[0].layout[9].st": 1, "sheets[0].layout[13].st": 1, "sheets[0].totals_styles[0]": [0, 0],
               "sheets[0].styles[1]": {**LGRAY_FILL, "bold": True}, "sheets[0].styles[0]": {"fill": "#808080", "fill_dark": "#4A4A47", "bold": True}}})
case("t5_01_group_outline", "T5-01 按组件分组：立柱组件 3 行、横梁组件 2 行、五金件 4 行；组件行自己是组头（仍是数据行），五金件另出组头；能折叠（G7）", "table.build",
     B2(group=B_GROUP, totals=["总重"]),
     {"view": {"sheets[0].layout[0]": {"k": "d", "g": 0, "r": 0, "h": True}, "sheets[0].layout[4]": {"k": "d", "g": 1, "r": 4, "h": True},
               "sheets[0].layout[7].k": "g", "sheets[0].layout[7].cells[2]": "五金件", "sheets[0].layout[8]": {"k": "d", "g": 2, "r": 7},
               "sheets[0].layout[11]": {"k": "d", "g": 2, "r": 10}},
      "sheets[0].totals[0].value": "2116.8",
      "xlsx_contains": {S: ['<row r="3" spans="1:14" outlineLevel="1">', '<row r="2" spans="1:14">']}})
# —— G8 编号
case("t5_02_outline_numbering", "T5-02 编号重排：组件 1、2，子件 1.1、1.2…，五金件不编号；编号是文字（G8）", "table.build",
     B2(),
     {"model": {"sheets[0].rows[0][0]": "1", "sheets[0].rows[1][0]": "1.1", "sheets[0].rows[3][0]": "1.3", "sheets[0].rows[4][0]": "2",
                "sheets[0].rows[6][0]": "2.2", "sheets[0].rows[7][0]": None, "sheets[0].rows[10][0]": None},
      "view": {"sheets[0].columns[0].numbering": "outline"}})
case("t5_02_insert_shifts", "T5-02 在 1.1 与 1.2 之间插一行后，后面顺延成 1.3、1.4；第 10 个子件是 1.10（编号每次重算）", "table.build",
     {"table": {"title": "编号", "columns": [{"title": "编号", "numbering": "outline"}, {"title": "类别", "type": "text"}, {"title": "名称"}],
                "outline_from": {"column": "类别", "levels": {"组件": 1, "子件": 2}},
                "rows": [["组件", "甲"]] + [["子件", f"子{i}"] for i in range(1, 11)] + [["组件", "乙"]]}},
     {"model": {"sheets[0].rows[2][0]": "1.2", "sheets[0].rows[10][0]": "1.10", "sheets[0].rows[11][0]": "2"}})
case("t2_02_seq_after_delete", "T2-02 删掉文件柜（整表重写）：序号由工具连续编 1–7，合计 34380（G8 seq）", "table.build",
     A(rows=[r for r in A_ROWS if r[1] != "文件柜"], columns=[{**A_COLS[0], "numbering": "seq"}, *A_COLS[1:]]),
     {"model": {"sheets[0].rows[2][0]": "3", "sheets[0].rows[2][1]": "投影仪", "sheets[0].rows[6][0]": "7"},
      "sheets[0].totals[0].value": "34380", "warning_codes": ["formula_value_ignored"]})
# —— G9 合并
case("t5_03_merge_formula", "T5-03 同名同规格的螺栓合并：总数量 576、总重 17.28、下料合并后再取整 605；总重合计仍 2116.8；口径写进说明（G9）", "table.build",
     {**B2(merge_rows=B_MERGE, totals=["总重"]), "formats": ["xlsx", "csv"]},
     {"view": {"sheets[0].layout[10].k": "m", "sheets[0].layout[10].members": [8, 9], "sheets[0].layout[10].cells[8]": "576",
               "sheets[0].layout[10].cells[10]": "17.28", "sheets[0].layout[10].cells[12]": "605",
               "sheets[0].layout[8]": {"k": "d", "r": 8, "x": 0},
               "sheets[0].merge": "按名称、规格合并同名同规格的行；总数量 = 明细之和；总重 = 合并后按本列公式重算；下料数量 = 合并后按本列公式重算；备注 用“；”连起来"},
      "sheets[0].totals[0].value": "2116.8", "warning_codes": ["merge_blank", "merge_blank"],
      "csv_contains": [",螺栓,M10×25,8.8 级,套,,,576,0.03,17.28,5,605,五金件，立柱用；五金件，横梁用\r\n"],
      "md_contains": ["| 螺栓 | M10×25 | 8.8 级 | 套 |  |  | 576 | 0.03 | 17.28 | 5% | 605 |"]})
case("t8_01_full", "T8-01 分解单正式版：分组编号、五金合并、下料向上取整、每组重量小计与总计、小计行灰底加粗（G7、G8、G9）", "table.build",
     B2(group=B_GROUP, subtotals=["总重"], merge_rows=B_MERGE, totals=["总重"], row_styles=[SUB_STYLE]),
     {"view": {"sheets[0].layout[4].cells[10]": "1083.84", "sheets[0].layout[8].cells[10]": "1002.24", "sheets[0].layout[15].cells[10]": "30.72",
               "sheets[0].layout[13].cells[12]": "605", "sheets[0].layout[4].st": 0, "sheets[0].layout[9]": {"k": "g", "g": 2, "cells": ["", "", "五金件", "", "", "", "", "", "", "", "", "", "", ""]}},
      "model": {"sheets[0].rows[1][12]": "50", "sheets[0].rows[2][12]": "49", "sheets[0].rows[3][12]": "149", "sheets[0].rows[5][12]": "99",
                "sheets[0].rows[6][12]": "196", "sheets[0].rows[7][12]": "101", "sheets[0].rows[10][12]": "202", "sheets[0].rows[0][0]": "1", "sheets[0].rows[6][0]": "2.2"},
      "sheets[0].totals[0].value": "2116.8",
      "xlsx_contains": {S: ["ROUNDUP(", "<f>SUBTOTAL(9,K2:K5)</f><v>1083.84</v>", "<f>SUM(I13,I14)</f><v>576</v>", '<row r="13" spans="1:14" hidden="1" outlineLevel="2">', '<row r="15" spans="1:14" outlineLevel="1" collapsed="1">']}})
case("t8_06_rescale", "T8-06 换规模：立柱组件 36 套、横梁组件 144 套，规则不变，只变了数（G7、G9）", "table.build",
     B2(sets=(36, 144), group=B_GROUP, subtotals=["总重"], merge_rows=B_MERGE, totals=["总重"], row_styles=[SUB_STYLE]),
     {"model": {"sheets[0].rows[1][8]": "72", "sheets[0].rows[3][8]": "216", "sheets[0].rows[5][8]": "144", "sheets[0].rows[6][8]": "288",
                "sheets[0].rows[1][12]": "75", "sheets[0].rows[2][12]": "74", "sheets[0].rows[3][12]": "223", "sheets[0].rows[5][12]": "149",
                "sheets[0].rows[6][12]": "294", "sheets[0].rows[7][12]": "152", "sheets[0].rows[10][12]": "303"},
      "view": {"sheets[0].layout[13].cells[8]": "864", "sheets[0].layout[13].cells[12]": "908", "sheets[0].layout[4].cells[10]": "1625.76",
               "sheets[0].layout[8].cells[10]": "1503.36", "sheets[0].layout[15].cells[10]": "46.08"},
      "sheets[0].totals[0].value": "3175.2"})
# —— G10 跨表
case("t6_02_sumif", "T6-02 预算表的实际从明细按科目加出来：值不变；Excel 里是跨表的等值求和（SUMPRODUCT），改明细预算表跟着变（G10）", "table.build",
     C2(),
     {"model": {"sheets[0].rows[0][3]": "34500", "sheets[0].rows[1][3]": "12800", "sheets[0].rows[2][3]": "7650", "sheets[0].rows[3][3]": "45000",
                "sheets[0].rows[4][3]": "21000", "sheets[0].rows[5][3]": "25200", "sheets[0].rows[0][5]": "1.15"},
      "sheets[0].totals[1].value": "146150", "sheets[0].totals[2].value": "2150", "warning_codes": [],
      "xlsx_contains": {S: ["<f>SUMPRODUCT(--('费用明细'!$B$2:$B$13=A2),'费用明细'!$D$2:$D$13)</f><v>34500</v>"]}})
case("t6_04_derive_summary", "T6-04 加一张按部门的汇总表：4 行，合计 144000 / 146150；每格引用预算表，联动（G10 derive）", "table.build",
     C2(extra_sheets=[SUMMARY]),
     {"model": {"sheets[2].rows": [["销售部", "50000", "47300"], ["行政部", "53000", "52650"], ["人力部", "15000", "21000"], ["研发部", "26000", "25200"]]},
      "sheets[2].totals[0].value": "144000", "sheets[2].totals[1].value": "146150",
      "xlsx_contains": {S3: ["<f>'预算表'!C2+'预算表'!C3</f><v>50000</v>", "<f>'预算表'!D6</f><v>21000</v>"]}})
case("t6_05_rename_reorder", "T6-05 费用明细改名“11月流水”并放到最前：id 不变，引用不断，Excel 公式里是新名（G10 sheet_order）", "table.build",
     C2(det_name="11月流水", order=["detail", "budget"]),
     {"sheets[0].name": "11月流水", "sheets[1].name": "预算表", "model": {"sheets[1].rows[0][3]": "34500"},
      "xlsx_contains": {"xl/workbook.xml": ['<sheet name="11月流水" sheetId="1"', '<sheet name="预算表" sheetId="2"'],
                        S2: ["SUMPRODUCT(--('11月流水'!$B$2:$B$13=A2),'11月流水'!$D$2:$D$13)"]}})
case("t8_03_linked", "T8-03 实际从明细汇过来、执行率超 100% 整行红、低于 70% 整行黄、按部门汇总；Excel 里是原生公式与条件格式（G1+G10）", "table.build",
     C2(extra_sheets=[SUMMARY], budget_rules=[{"when": "执行率 > 100%", "apply_to": "row", "style": {"fill": "浅红"}},
                                              {"when": "执行率 < 70%", "apply_to": "row", "style": {"fill": "浅黄"}}]),
     {"view": {"sheets[0].cell_styles[0]": [0, 0, 0], "sheets[0].cell_styles[6]": [1, 0, 1], "sheets[0].cell_styles[12]": [4, 0, 0],
               "sheets[0].cell_styles[18]": "<缺席>"},
      "model": {"sheets[2].rows[0]": ["销售部", "50000", "47300"]}, "sheets[2].totals[1].value": "146150",
      "xlsx_contains": {S: ['<conditionalFormatting sqref="A2:F7">', "SUMPRODUCT(--('费用明细'!$B$2:$B$13=A2)"]}})
case("t8_03_after_edit", "T8-03 明细的招待费 5000 改成 9000：预算表招待费实际 16800、执行率 84.0%、不再标黄；汇总销售部实际 51300", "table.build",
     C2(det_rows=[r if r[3] != 5000 else [*r[:3], 9000, r[4]] for r in DET_ROWS], extra_sheets=[SUMMARY],
        budget_rules=[{"when": "执行率 > 100%", "apply_to": "row", "style": {"fill": "浅红"}}, {"when": "执行率 < 70%", "apply_to": "row", "style": {"fill": "浅黄"}}]),
     {"model": {"sheets[0].rows[1][3]": "16800", "sheets[0].rows[1][5]": "0.84", "sheets[2].rows[0][2]": "51300"},
      "view": {"sheets[0].cell_styles[6]": [4, 0, 0]}})
_DET312 = DET_ROWS + [["2026-11-30", "差旅费", "销售部", 100, "张三"]] * 300
case("t8_07_append_300", "T8-07 明细追加 300 行（每笔 100 元差旅费）：预算表差旅费实际 64500；规则与汇总范围在 Excel 里含新行（G1+G10）", "table.build",
     C2(det_rows=_DET312, det_rules=[{"when": "金额 > 10000", "style": {"color": "红"}}]),
     {"model": {"sheets[0].rows[0][3]": "64500", "sheets[1].rows[11][3]": "12000"}, "sheets[1].rows": 312,
      "xlsx_contains": {S: ["SUMPRODUCT(--('费用明细'!$B$2:$B$313=A2),'费用明细'!$D$2:$D$313)"],
                        S2: ['<conditionalFormatting sqref="D2:D313">']}})
# —— G17 格公式
case("t9_01_ceiling_cells", "T9-01 五金数量 = 基数 × 1.005 向上取整：676、1014、2605、5210；主件、子件不受影响；Excel 里每格是 CEILING 公式（G17+G2）", "table.build",
     D(D_s01(hw="ceiling({b}*1.005)".replace("{b}", "@r1.数量*{k}")), D_s02()),
     {"view": {"sheets[0].rows[4][6]": "676", "sheets[0].rows[5][6]": "1,014", "sheets[1].rows[4][6]": "2,605", "sheets[1].rows[5][6]": "5,210",
               "sheets[0].rows[0][6]": "168", "sheets[0].rows[1][6]": "168", "sheets[0].rows[4][0]": ""},
      "model": {"sheets[0].rows[4].qty": {"$expr": "ceiling(@r1.数量*4*1.005)"}, "sheets[0].rows[4].$id": "r5", "sheets[0].rows[4].no": None},
      "warning_codes": [],
      "xlsx_contains": {S1: ["<f>CEILING(ROUND(((G2*4)*1.005),14-INT(LOG10(ABS(((G2*4)*1.005))+(((G2*4)*1.005)=0)))),1)</f><v>676</v>"]}})
case("t9_04_sheet_order", "T9-04 加一张“05三脚架”、只要表头：排在 04 与 06 之间；表名以数字开头；整本次序固定（G10 sheet_order）", "table.build",
     D(D_s00(), D_s01(), D_s02(), *D_EMPTY, D_S99, {"id": "s05", "name": "05三脚架", "columns": D_COLS, "outline_from": D_OL}, order=D_ORDER),
     {"sheets[5].name": "05三脚架", "sheets[5].rows": 0, "sheets[0].name": "总清单", "sheets[8].name": "标准件",
      "xlsx_contains": {"xl/workbook.xml": ['<sheet name="04吊梁天轨" sheetId="5" r:id="rId5"/><sheet name="05三脚架" sheetId="6" r:id="rId6"/><sheet name="06地轨"']}})
case("t9_05_insert_ref", "T9-05 立柱下插入焊接子件“加强筋”（每根立柱 2 块）：数量 = 立柱那一格 × 2 = 336；序号 1、1.1、1.2 加强筋、1.3 底板、2；引用按 id 找，不漂（G17+G8）", "table.build",
     D(D_s01(extra=drow("r7", "加强筋", None, "80×60×6", {"$expr": "@r1.数量*2"}, "焊接子件"))),
     {"view": {"sheets[0].rows[2][2]": "加强筋", "sheets[0].rows[2][6]": "336", "sheets[0].rows[2][0]": "1.2", "sheets[0].rows[3][0]": "1.3",
               "sheets[0].rows[4][0]": "2", "sheets[0].rows[5][0]": "", "sheets[0].rows[3][6]": "168", "sheets[0].rows[5][6]": "676"},
      "xlsx_contains": {S1: ["<f>G2*2</f><v>336</v>", "<f>G2</f><v>168</v>"]}})
case("t9_07_cell_exprs", "T9-07 主件写乘式 6×28、6×27×8；子件、五金引用主件那一格；总清单引用各分部主件格；Excel 里都是公式（G17）", "table.build",
     D(D_s00(), D_s01(), D_s02()),
     {"model": {"sheets[1].rows[0].qty": {"$expr": "6*28"}},
      "view": {"sheets[0].rows[0][6]": "168", "sheets[0].rows[2][6]": "1,296", "sheets[2].rows[2][6]": "2,592",
               "sheets[1].exprs[0]": [0, 6, "6 × 28"], "sheets[0].exprs[2]": [2, 6, "@s02/r1.数量"]},
      "xlsx_contains": {S1: ["<f>'01立柱'!G2</f><v>168</v>", "<f>'02横梁'!G5</f><v>24</v>"], S2: ["<f>6*28</f><v>168</v>"],
                        S3: ["<f>(6*27)*8</f><v>1296</v>", "<f>G2*2</f><v>2592</v>"]}})
case("t9_08_derive_std", "T9-08 标准件：各分部五金按名称加规格合并；螺栓 M10×25 = 1014 + 5210 = 6224（取整后相加，不是 6223）；每格是引用分部格的求和（G10 derive）", "table.build",
     D(D_s01(), D_s02(), D_S99),
     {"model": {"sheets[2].rows[0][2]": "膨胀螺栓", "sheets[2].rows[0][6]": "676", "sheets[2].rows[1][6]": "6224", "sheets[2].rows[2][6]": "2605",
                "sheets[2].rows[3]": "<缺席>"},
      "view": {"sheets[2].rows[1][6]": "6,224", "sheets[2].derive": "由表 s01、s02 里符合“产品角色 = \"五金\"”的行按产品名称、规格合并而成；数量 是各来源之和"},
      "warning_codes": [],
      "xlsx_contains": {S3: ["<f>'01立柱'!G7+'02横梁'!G7</f><v>6224</v>"]}})
_S02_NEAR = D_s02()
_S02_NEAR["rows"][5] = {**_S02_NEAR["rows"][5], "规格": "M10x25"}
case("t9_08_near_key", "T9-08 名称、规格写法有细小差别（M10x25 与 M10×25）：不合并，告警点名两种写法（G9 键规则）", "table.build",
     D(D_s01(), _S02_NEAR, D_S99),
     {"warning_codes": ["merge_key_near"], "warnings_contain": ["“螺栓、M10×25”与“螺栓、M10x25”写法相近而不同"], "model": {"sheets[2].rows[3][4]": "M10x25"}})
_T911 = D(D_s00(), D_s01(), D_s02(), *D_EMPTY, D_S99, {"id": "s05", "name": "05三脚架", "columns": D_COLS, "outline_from": D_OL}, order=D_ORDER)
case("t9_11_deliverable", "T9-11 整份分解清单交 Excel：9 张表次序固定，各 13 列；取整、乘式、跨表引用、派生求和都是公式（G10、G17）", "table.build",
     _T911,
     {"stats.sheets": 9, "sheets[8].columns": [c["title"] for c in D_COLS], "file_count": 4,
      "xlsx_contains": {"xl/workbook.xml": ['<sheet name="总清单" sheetId="1"', '<sheet name="标准件" sheetId="9"'],
                        "xl/worksheets/sheet9.xml": ["<f>'01立柱'!G7+'02横梁'!G7</f><v>6224</v>"]}})
# —— G11 核对
_T909 = D(D_s00(qty_hl=1290), D_s01(), D_s02(mat_r3=None), {"id": "s99", "name": "标准件", "columns": D_COLS, "outline_from": D_OL, "rows": [
    drow(None, "膨胀螺栓", None, "M12×100", 676, "五金", "8.8 级"), drow(None, "螺栓", None, "M10×25", 3000, "五金", "8.8 级"),
    drow(None, "螺栓", None, "M10×25", 3223, "五金", "8.8 级"), drow(None, "安全销", None, "Φ6", 2605, "五金", "8.8 级")]})
_EXP909 = "\n".join(["optional 产品编号 图纸号 颜色1 单位 备注 单重/面积 总重 sheet=*",
                     "match 数量 sheet=s00 key=产品名称 against=s01,s02 where=产品角色:主件",
                     "sum_equal 数量 sheet=s99 by=产品名称,规格 from=s01,s02 where=产品角色:五金",
                     "nonempty 材质 sheet=*", "unique 产品名称 规格 sheet=s99"])
case("t9_09_cross_checks", "T9-09 交付前按四条规则核：四处错误各报一条，写明表、行、现值、应值；只核对，不改表（G11）", "table.check",
     {**_T909, "expect": _EXP909},
     {"verdict": "fail", "summary": "4 条核对不通过，共 5 处问题",
      "checks[8].verdict": "pass", "checks[9].problems[0].actual": "1,290", "checks[9].problems[0].expected": "1,296（02横梁 第 1 行）",
      "checks[9].problems[0].cell": "总清单!G4",
      "checks[10].problems[0].actual": "螺栓、M10×25：6223", "checks[10].problems[0].expected": "6224（01立柱、02横梁之和）",
      "checks[11].problems[0].cell": "02横梁!F4", "checks[12].problems[0].sheet": "标准件", "checks[12].problems[0].row": 2,
      "checks[12].problems[1].row": 3})
_T910 = D(D_s00(), D_s01(), D_s02(), {"id": "s99", "name": "标准件", "columns": D_COLS, "outline_from": D_OL, "rows": [
    drow(None, "膨胀螺栓", None, "M12×100", 676, "五金", "8.8 级"), drow(None, "螺栓", None, "M10×25", 6224, "五金", "8.8 级"),
    drow(None, "安全销", None, "Φ6", 2605, "五金", "8.8 级")]})
case("t9_10_all_pass", "T9-10 改正后再核：四条全过，回执写明全部通过，不生成空的问题表（G11）", "table.check",
     {**_T910, "expect": _EXP909},
     {"verdict": "pass", "summary": "全部通过（期望清单 5 条）", "checks[9].verdict": "pass", "checks[10].verdict": "pass",
      "checks[11].verdict": "pass", "checks[12].verdict": "pass"})
case("t8_02_issue_rules", "T8-02 主表标红材质为空与同名同规格未合并的格；核对回执列出 2 条问题（问题表由模型照回执写成普通表）（G11+G1）", "table.check",
     {**B2(rules=[{"when": "材质 = \"—\"", "apply_to": ["材质"], "style": {"color": "红"}}]),
      "expect": "unique 名称 规格\nnonempty 材质"},
     {"verdict": "fail", "checks[2].problems[0].row": 9, "checks[2].problems[1].row": 10, "checks[2].where": ["钢货架分包分解单!C10", "钢货架分包分解单!D10", "钢货架分包分解单!C11", "钢货架分包分解单!D11"]})
case("t2_03_blank_row", "T2-03 插一行空行待填：金额为空不是 0；核对不把空行当错，只提示“有空行”（G11）", "table.check",
     {"table": {"title": "办公室装修采购清单", "columns": A_COLS, "rows": [*A_ROWS[:3], [None] * 8, *A_ROWS[3:]], "totals": ["金额"]}},
     {"verdict": "pass", "checks[2].kind": "empty_row", "checks[2].verdict": "pass", "checks[2].where": ["办公室装修采购清单 第 4 行"],
      "summary": "全部通过"})
case("g11_unique_whole_book", "G11 sheet=* 下 unique 把各表合起来查重（图纸号不重号）", "table.check",
     {**D(D_s01(), D_s02()), "expect": "optional 产品编号 颜色1 单位 备注 单重/面积 总重 sheet=*\nunique 图纸号 sheet=*"},
     {"verdict": "pass"})
# —— 报错
case("err_expr_in_formula_col", "公式列的格不收 $expr（17 TL-30b：工具算出的字段不得收式）", "table.build",
     A(rows=[{**dict(zip(A_KEYS, A_ROWS[0])), "金额": {"$expr": "1+1"}}]),
     {"error.code": "BAD_INPUT", "error.where": "table.rows[0].金额"})
case("err_expr_missing_row", "格公式引用的行 id 不存在", "table.build",
     D({**D_s01(), "rows": [drow("r1", "立柱", None, "x", {"$expr": "@r9.数量"}, "主件")]}),
     {"error.code": "BAD_INPUT", "error.where": "table.sheets[0].rows[0][6]"})
case("err_expr_cycle", "格公式成环", "table.build",
     D({**D_s01(), "rows": [drow("r1", "甲", None, "x", {"$expr": "@r2.数量"}, "主件"), drow("r2", "乙", None, "x", {"$expr": "@r1.数量+1"}, "主件")]}),
     {"error.code": "BAD_INPUT"})
case("err_expr_integer", "整数列的格公式算出小数", "table.build",
     D({**D_s01(), "rows": [drow("r1", "立柱", None, "x", {"$expr": "672*1.005"}, "主件")]}),
     {"error.code": "BAD_INPUT", "error.where": "table.sheets[0].rows[0][6]"})
case("err_merge_round_agg", "含取整的公式列合并时没写口径", "table.build",
     B2(merge_rows={"by": ["名称", "规格"], "agg": {"总数量": "sum", "总重": "formula"}}),
     {"error.code": "BAD_INPUT", "error.where": "table.merge_rows.agg"})
case("err_outline_numeric", "层级来源要是一列文字，不收整数层级列", "table.build",
     {"table": {"title": "T", "columns": [{"title": "层级", "type": "integer"}, {"title": "名称"}], "rows": [[1, "甲"]],
                "outline_from": {"column": "层级", "levels": {"1": 1}}}},
     {"error.code": "BAD_INPUT", "error.where": "table.outline_from.column"})
case("err_sheet_order_id", "sheet_order 里有不存在的表 id", "table.build",
     C2(order=["detail", "nope"]),
     {"error.code": "BAD_INPUT", "error.where": "table.sheet_order"})
case("err_sumif_sheet", "跨表汇总引用了不存在的表", "table.build",
     {"table": {"title": "T", "sheets": [{"id": "a", "columns": [{"key": "k", "title": "科目", "type": "text"},
                                                                {"title": "实际", "type": "money", "formula": "sumif(nope.科目, 科目, nope.金额)"}], "rows": [["x"]]}]}},
     {"error.code": "BAD_INPUT"})

# —— 2.2.0 §二 补：标识符与公式里的数（立法者 11-12，17 TL-30 v0.2.99）
case("err_if_numeric_branches", "补：if 的两支不收数字常数（长期规则）：if(名称=\"立柱\", 168, 1296) 回 BAD_INPUT，提示引用一列", "table.build",
     {"table": {"title": "T", "columns": [{"title": "名称", "type": "text"}, {"title": "数量", "type": "integer", "formula": "if(名称 = \"立柱\", 168, 1296)"}],
                "rows": [["立柱"]]}},
     {"error.code": "BAD_INPUT", "error.where": "table.columns[1].formula"})
case("w_formula_no_column", "补：公式的结果不依赖任何一列（数量*0+168）出告警 formula_no_column，只提示不拒收", "table.build",
     {"table": {"title": "T", "columns": [{"title": "数量", "type": "integer"}, {"title": "单价", "type": "money"},
                                       {"title": "甲", "type": "integer", "formula": "数量*0+168"}, {"title": "金额", "type": "money", "formula": "单价*数量"}],
                "rows": [[2, 5]]}},
     {"warning_codes": ["formula_no_column"], "warnings_contain": ["“甲”的公式“数量*0+168”不依赖任何一列"], "model": {"sheets[0].rows[0][2]": "168"}})
case("w_numeric_as_text", "补：列显式写 text 而值都是数时告警 numeric_as_text；编号列、写了 identifier 的列、标题像编号的列不告警", "table.build",
     {"table": {"title": "T", "columns": [{"title": "编号", "type": "text"}, {"title": "单价", "type": "text"},
                                       {"title": "零件", "type": "text", "identifier": True}],
                "rows": [["1", "12", "100"], ["1.1", "15.5", "200"]]}},
     {"warning_codes": ["numeric_as_text"], "warnings_contain": ["“单价”写成了文字列"], "model": {"sheets[0].columns[2].identifier": True}})

# ---------------------------------------------------------------- table.check
case("c_pass", "列、唯一、非空、合计、行数全过", "table.check",
     {"table": BOM, "expect": "columns 零件 数量 单价 金额\nunique 零件\nnonempty *\ntotal 金额 sum=3741\nrows min=3 max=3"},
     {"verdict": "pass", "covered": True, "checks[5].kind": "total", "checks[5].actual": "3741"})
case("c_total_fail", "合计不符：给 3700，实际 3741", "table.check",
     {"table": BOM, "expect": "total 金额 sum=3700"},
     {"verdict": "fail", "checks[2].verdict": "fail", "checks[2].actual": "3741", "checks[2].expected": "3700"})
case("c_total_tol", "带误差：3741 与 3740 差 1，tol=1 判过", "table.check",
     {"table": BOM, "expect": "total 金额 sum=3740 tol=1"},
     {"verdict": "pass"})
case("c_unique_fail", "主键重复：第 3 行与第 1 行同名，位置 钢材!A4", "table.check",
     {"table": {**STEEL, "rows": [["Q235", 235, 4200], ["Q355", 355, 4550], ["Q235", 240, 4300]]}, "expect": "unique 牌号"},
     {"verdict": "fail", "checks[2].where": ["钢材!A2", "钢材!A4"]})   # 2.2.0 G11：unique 报出每组重复的每一行
case("c_nonempty_fail", "空格子：列出位置", "table.check",
     {"table": {"title": "排班", "columns": ["日期", "早班", "晚班"], "rows": [["10-27", "张敏", None], ["10-28", None, "王强"]]},
      "expect": "nonempty 早班 晚班"},
     {"verdict": "fail", "checks[2].where": ["排班!C2", "排班!B3"]})
case("c_range_sorted", "范围与排序：屈服强度都在 200–400 内；价格升序；屈服强度不是降序", "table.check",
     {"table": STEEL, "expect": "range 屈服强度 min=200 max=400\nsorted 价格 asc\nsorted 屈服强度 desc"},
     {"verdict": "fail", "checks[2].verdict": "pass", "checks[3].verdict": "pass", "checks[4].verdict": "fail", "checks[4].where": ["钢材!B3"]})
case("c_builtin_placeholder", "内置核对：“待补”占位与整列为空", "table.check",
     {"table": {"title": "报价", "columns": ["项目", "报价", "备注"], "rows": [["安装", "待补", None], ["调试", "TBD", None]]}},
     {"verdict": "fail", "checks[0].kind": "empty_column", "checks[0].verdict": "fail", "checks[0].where": ["备注"],
      "checks[1].kind": "placeholder", "checks[1].where": ["报价!B2", "报价!B3"]})
case("c_missing_column", "要的列不在表里", "table.check",
     {"table": STEEL, "expect": "columns 牌号 密度"},
     {"verdict": "fail", "checks[2].where": ["密度"]})
case("c_object", "用 object（table.build 的产出记录）核对，sheet= 指定表（行首行尾都行）", "table.check",
     {"object": {"tool": "table.build", "args": {"table": {"title": "库存", "sheets": [
         {"id": "a", "name": "甲", "columns": ["名称", "库存"], "rows": [["轴承", 46]]},
         {"id": "b", "name": "乙", "columns": ["名称", "库存"], "rows": [["圆钢", 12], ["板材", 3]]}]}}, "output": {}},
      "expect": "rows min=2 sheet=乙\nsheet=乙 total 库存 sum=15\nsheet=乙\nunique 名称"},
     {"verdict": "pass"})
case("err_expect", "期望清单写错：不认识的核对项", "table.check",
     {"table": STEEL, "expect": "has 牌号"},
     {"error.code": "BAD_INPUT", "error.where": "expect", "error.line": 1})

# ---------------------------------------------------------------- table.export
case("e_xlsx", "导出 Excel：冻结首行、筛选、表头", "table.export",
     {"table": STEEL, "formats": ["xlsx"]},
     {"file_count": 1, "files[0].format": "xlsx", "files[0].role": "table.excel",
      "xlsx_contains": {"xl/worksheets/sheet1.xml": ['<pane ySplit="1"', '<autoFilter ref="A1:C5"/>'],
                        "xl/sharedStrings.xml": ["屈服强度（MPa）"]}})
case("e_csv", "CSV：UTF-8 BOM、CRLF、原值不加千分位、表头带单位", "table.export",
     {"table": STEEL, "format": "csv"},
     {"csv_bom": True, "csv_contains": ["牌号,屈服强度（MPa）,价格（元/吨）\r\n", "304,205,15800.00\r\n"]})
case("e_csv_inject", "CSV 注入防护：以 = 开头的文字前加单引号", "table.export",
     {"table": {"title": "T", "columns": ["说明"], "rows": [["=1+1"], ["正常"]]}, "formats": ["csv"]},
     {"csv_contains": ["'=1+1\r\n"]})
case("e_md", "Markdown：竖线转义", "table.export",
     {"table": {"title": "T", "columns": ["a|b"], "rows": [["x|y"]]}, "formats": ["md"]},
     {"md_contains": ["| a\\|b |", "| x\\|y |"]})
case("e_object", "从 object（table.build 的产出记录）导出（17 TL-9b），名字沿用 args.name", "table.export",
     {"object": {"tool": "table.build", "args": {"table": BOM, "name": "bom"}, "output": {}}, "format": "xlsx"},
     {"name": "bom", "files[0].path": "bom.xlsx"})
case("e_model_roundtrip", "表模型再导回：从 json 格式的表模型重新导出，sha 不变", "table.export",
     {"object": {"schema": "mengos.table/1", "title": "季度销量", "sheets": [{"id": "s1", "name": "季度销量", "columns": [
         {"key": "c1", "title": "地区", "type": "text", "align": "left"}, {"key": "c2", "title": "一季度", "type": "integer", "align": "right"}],
         "rows": [["华东", "120"]]}]}, "format": "json"},
     {"file_count": 1, "files[0].role": "table.model", "warnings": []})
case("e_twice", "导出两次逐字节相同", "table.export",
     {"table": {**STEEL, "meta": {"author": "工艺部"}}, "formats": ["xlsx", "csv", "md", "json"]},
     {"twice": True, "file_count": 4})
case("err_both", "table 与 object 同时给", "table.export",
     {"table": STEEL, "object": {}, "formats": ["xlsx"]},
     {"error.code": "BAD_INPUT", "error.where": "table"})
case("err_format", "不支持的格式", "table.export",
     {"table": STEEL, "formats": ["pdf"]},
     {"error.code": "BAD_INPUT", "error.where": "formats"})
case("err_name", "文件名带路径拒收", "table.export",
     {"table": STEEL, "name": "../x", "formats": ["md"]},
     {"error.code": "BAD_INPUT", "error.where": "name"})

if __name__ == "__main__":
    ids = [c["id"] for c in C]
    assert len(ids) == len(set(ids)), "金样 id 重复"
    (ROOT / "golden_cases.json").write_text(json.dumps(C, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    from collections import Counter
    print(len(C), dict(Counter(c["tool"] for c in C)))
