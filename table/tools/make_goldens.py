"""生成 golden_cases.json（TL-12 ③ 金样）。期望值都是手算后写死的，不由工具跑出来再抄。

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
         {"name": "零件/外购", "columns": ["名称", "库存"], "rows": [["轴承", 46]]},
         {"name": "原料", "columns": ["名称", "库存"], "rows": [["圆钢", 12], ["板材", 3]]}]}, "formats": ["xlsx", "csv"]},
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
                                           {"key": "r", "title": "商", "formula": "round(a / b, 2)"}, {"title": "取大", "formula": "max(r, 3)"}],
                "rows": [[7, 3]]}},
     {"model_contains": ['"2.33"', '["7","3","2.33","3"]']})
case("b_count_min_max", "count 可用于文字列；min、max 用于数值列", "table.build",
     {"table": {**STEEL, "totals": [{"column": "牌号", "fn": "count"}, {"column": "屈服强度", "fn": "max"}, {"column": "价格", "fn": "min"}]}},
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
     {"table": {"title": "T", "columns": [{"key": "a", "title": "甲"}, {"title": "乙", "formula": "a * 2"}], "rows": [["x"]]}},
     {"error.code": "BAD_INPUT", "error.where": "table.columns[1].formula"})
case("err_dup_title", "同一张表里列标题重复", "table.build",
     {"table": {"title": "T", "columns": ["甲", "甲"], "rows": []}},
     {"error.code": "BAD_INPUT", "error.where": "table.columns"})

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
     {"verdict": "fail", "checks[2].where": ["钢材!A4"]})
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
         {"name": "甲", "columns": ["名称", "库存"], "rows": [["轴承", 46]]},
         {"name": "乙", "columns": ["名称", "库存"], "rows": [["圆钢", 12], ["板材", 3]]}]}}, "output": {}},
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
     {"object": {"schema": "mengos.table/1", "title": "季度销量", "sheets": [{"name": "季度销量", "columns": [
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
