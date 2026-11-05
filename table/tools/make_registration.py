"""生成 registration.json（TL-6 登记资产）。说明文字站在调用方的观察点写（TL-16b、TL-19）。

顺序：改本文件 → python tools/make_registration.py → python lock.py → python tools/make_package.py。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]{0,31}$"}
CELL = {"type": ["string", "number", "boolean", "null"]}
NAME = {"type": "string", "pattern": "^[^/\\\\.:*?\"<>|\\s]{1,64}$", "description": "交付文件的名字（不含扩展名）；缺省取标题。"}

COLUMN = {
    "oneOf": [
        {"type": "string", "minLength": 1, "maxLength": 200},
        {"type": "object", "required": ["title"], "additionalProperties": False, "properties": {
            "key": ID,
            "title": {"type": "string", "minLength": 1, "maxLength": 200},
            "type": {"enum": ["text", "integer", "number", "money", "percent", "date", "bool"]},
            "unit": {"type": "string", "maxLength": 40},
            "decimals": {"type": "integer", "minimum": 0, "maximum": 10},
            "formula": {"type": "string", "minLength": 1, "maxLength": 500},
            "width": {"type": "integer", "minimum": 4, "maximum": 100},
            "align": {"enum": ["left", "center", "right"]},
        }},
    ]
}
ROWS = {"type": "array", "maxItems": 100000, "x-mengos-data": True, "items": {"oneOf": [
    {"type": "array", "maxItems": 200, "items": CELL},
    {"type": "object", "additionalProperties": CELL},
]}}
TOTALS = {"type": "array", "maxItems": 200, "items": {"oneOf": [
    {"type": "string", "minLength": 1},
    {"type": "object", "required": ["column"], "additionalProperties": False, "properties": {
        "column": {"type": "string", "minLength": 1},
        "fn": {"enum": ["sum", "avg", "min", "max", "count"]},
        "value": {}}},
]}}
SHEET_PROPS = {
    "columns": {"type": "array", "minItems": 1, "maxItems": 200, "items": COLUMN},
    "rows": ROWS,
    "totals": TOTALS,
    "caption": {"type": "string", "maxLength": 500},
    "note": {"type": "string", "maxLength": 2000},
    "freeze_cols": {"type": "integer", "minimum": 0, "maximum": 10},
}
TABLE = {
    "type": "object",
    "required": ["title"],
    "additionalProperties": False,
    "description": (
        "table：一张或几张数据表。title 标题（必填）。单张表直接写 columns 与 rows；几张表写 sheets，"
        "每张 {name 表名（最多 31 个字符）, columns, rows, totals, caption, note}。"
        "columns 按顺序列出各列：title 列标题（必填，只写名称，单位写进 unit）、key（可选，字母、数字、下划线，公式里用它引用这一列）、"
        "type（text 文字 / integer 整数 / number 数 / money 金额 / percent 百分比 / date 日期 / bool 是否；不写时按内容推断）、"
        "unit 单位（如 MPa、元/吨）、decimals 显示几位小数、formula 公式（同一行里数值列的 + - * / 与括号，可用 round、abs、min、max，"
        "用列的 key 或标题引用，例如 \"单价 * 数量\"；公式列的值由工具算，行里不用写）。列也可以只写标题字符串。"
        "rows 每行一个数组，按列的顺序，每格是字符串、数字、true/false 或 null（空格子）；有公式列时可以只写非公式列。"
        "数值写数字，不带单位；百分比写百分数（12.5 表示 12.5%）；日期写 YYYY-MM-DD。"
        "totals 加末行合计：[{column, fn}]，fn 为 sum / avg / min / max / count，只写列名时按 sum。"
        "meta：lang（zh-CN 或 en，也可直接写在 table 顶层）、author、org、date、version。sources 列数据来源，assumptions 列数据成立的前提（如价格的时点）。"
    ),
    "properties": {
        "schema": {"const": "mengos.table/1"},
        "title": {"type": "string", "minLength": 1, "maxLength": 200},
        "subtitle": {"type": "string", "maxLength": 200},
        "name": {"type": "string", "maxLength": 200, "description": "单张表写法里的表名；缺省取标题"},
        "lang": {"enum": ["zh-CN", "en"], "description": "meta.lang 的简写"},
        "meta": {"type": "object", "additionalProperties": False, "properties": {
            "lang": {"enum": ["zh-CN", "en"]},
            "author": {"type": "string", "maxLength": 200},
            "org": {"type": "string", "maxLength": 200},
            "date": {"type": "string", "pattern": "^(\\d{4}-\\d{2}-\\d{2})?$"},
            "version": {"type": "string", "maxLength": 200}}},
        "sheets": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
            "type": "object", "required": ["columns"], "additionalProperties": False,
            "properties": {"id": ID, "name": {"type": "string", "maxLength": 200}, **SHEET_PROPS,
                           "sources": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000},
                                       "description": "写在这里也行，并入整张表的 sources"},
                           "assumptions": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000},
                                           "description": "写在这里也行，并入整张表的 assumptions"}}}},
        **SHEET_PROPS,
        "sources": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000}},
        "assumptions": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000}},
    },
}
SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
WARN = {"type": "array", "items": {"type": "object", "required": ["where", "code", "message"], "properties": {
    "where": {"type": "string"}, "code": {"type": "string"}, "message": {"type": "string"},
    "line": {"type": "integer"}, "hint": {"type": "string"}}}}
FILES = {"type": "array", "items": {"type": "object", "required": ["path", "format", "role", "media_type", "bytes", "sha256"],
                                    "additionalProperties": False, "properties": {
    "path": {"type": "string", "pattern": "^[^/\\\\]+$", "description": "相对 workdir 的文件名"},
    "format": {"enum": ["json", "view", "md", "xlsx", "csv"]},
    "role": {"enum": ["table.model", "table.view", "table.text", "table.excel", "table.csv"]},
    "media_type": {"type": "string"},
    "bytes": {"type": "integer", "minimum": 1},
    "sha256": SHA}}}
OBJECT = {"type": "object", "description": "object：要处理的表（table）；也可以直接给表的内容 table，二选一。"}
EXEC = {"kind": "process", "entry": "table_tool.py", "mode": "sync"}
EXPORT_FORMATS = ["xlsx", "csv", "md", "json"]

BUILD = {
    "tool_id": "table.build",
    "trust_claim": "T1",
    "effect": "none",
    "executor": EXEC,
    "cost": {"latency": 300, "price": 0, "timeout": 60000},
    "input_example": {"table": {
        "title": "减速机物料清单",
        "columns": [{"key": "part", "title": "零件"}, {"key": "qty", "title": "数量", "type": "integer"},
                    {"key": "price", "title": "单价", "type": "money", "unit": "元"},
                    {"key": "amount", "title": "金额", "type": "money", "unit": "元", "formula": "qty * price"}],
        "rows": [["输入轴", 1, 860], ["齿轮", 2, 1250.5], ["轴承 6208", 4, 95]],
        "totals": ["金额"]}},
    "signature": {
        "input_schema": {
            "type": "object", "required": ["table"], "additionalProperties": False,
            "description": (
                "要交付一张表格时用：清单、台账、明细、对照表、报价单、排班表，或要 Excel、CSV 文件。"
                "你把数据写进 table：各列、各行的值，需要的公式列与合计；任务只给了要求时，数据由你按要求整理。"
                "本工具统一各列的类型、单位与小数位，按公式算出公式列和合计；交付 Excel 文件（表头、冻结首行、筛选、数字格式、能重算的公式），"
                "以及产出台上可排序查看的版本和 Markdown 原文。任务要 CSV 时，在与 table 并列的 formats 里写 [\"xlsx\", \"csv\"]。"),
            "properties": {
                "table": TABLE,
                "name": NAME,
                "formats": {"type": "array", "uniqueItems": True, "items": {"enum": ["xlsx", "csv"]},
                            "description": "除表模型、产出台数据与 Markdown 外还要哪些文件：xlsx（Excel，缺省）、csv。写在 table 外面、与 table 并列，例如 {\"table\": {…}, \"formats\": [\"xlsx\", \"csv\"]}。"},
            },
        },
        "output_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "table_sha256", "name", "sheets", "stats", "warnings", "files"],
            "properties": {
                "title": {"type": "string"},
                "table_sha256": SHA,
                "name": {"type": "string"},
                "sheets": {"type": "array", "items": {"type": "object", "required": ["name", "rows", "columns"], "properties": {
                    "name": {"type": "string"}, "rows": {"type": "integer"},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "totals": {"type": "array", "items": {"type": "object", "required": ["column", "fn", "value"], "properties": {
                        "column": {"type": "string"}, "fn": {"type": "string"}, "value": {"type": ["string", "null"]}}}}}}},
                "stats": {"type": "object", "required": ["sheets", "rows", "columns", "cells", "empty_cells", "formula_columns", "warnings"],
                          "properties": {k: {"type": "integer"} for k in ("sheets", "rows", "columns", "cells", "empty_cells", "formula_columns", "warnings")}},
                "warnings": WARN,
                "files": FILES,
                "assumptions": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "capability": {
        "ops": ["generate"],
        "in_types": ["table_plan"],
        "out_types": ["table"],
        "constraints": {"max_sheets": 20, "max_columns": 200, "max_rows": 100000, "max_cells": 1000000,
                        "column_types": ["text", "integer", "number", "money", "percent", "date", "bool"],
                        "formula_functions": ["round", "abs", "min", "max"], "totals": ["sum", "avg", "min", "max", "count"],
                        "deterministic_files": True,
                        "latency_note": "几百行约 0.1 s；一万行约 1 s（含 Excel）"},
        "examples": [
            {"input": "把 20 种常用钢材的密度、屈服强度和参考价格列成一张 Excel 表", "output": "你整理好 20 行数据填进 table，单位写进各列的 unit → Excel 与产出台表格"},
            {"input": "导出这台减速机的物料清单，带数量、单价和金额合计", "output": "金额列 formula=\"数量 * 单价\"，totals [金额] → 带合计行的 Excel"},
            {"input": "把斐波那契数列前 30 项列成表，另给一份 CSV", "output": "两列 n、F(n)，30 行，formats [xlsx, csv]"},
            {"input": "排一张客服组下周的值班表，七天三班倒", "output": "列：日期、早班、中班、晚班；7 行"},
        ],
        "non_goals": [
            "不替你找数据：表里的数据都由调用方给出，工具只整理、计算与排版",
            "不写成文的报告：表只是文章里的一部分时，交给长文工具",
            "不画图表，不做条件格式、跨表公式与数据透视",
            "不读入已有的 Excel 文件",
            "不直接交 PDF",
        ],
    },
}

CHECK = {
    "tool_id": "table.check",
    "trust_claim": "T1",
    "effect": "none",
    "executor": EXEC,
    "cost": {"latency": 200, "price": 0, "timeout": 60000},
    "input_example": {"table": BUILD["input_example"]["table"], "expect": "columns 零件 数量 单价 金额\nunique 零件\nnonempty *\ntotal 金额 sum=3741"},
    "signature": {
        "input_schema": {
            "type": "object", "additionalProperties": False, "oneOf": [{"required": ["table"]}, {"required": ["object"]}],
            "description": (
                "核对表格是否达到交付要求：要的列是否都在、顺序是否对，行数是否在范围内，主键有没有重复，必填的格子有没有空，"
                "数值是否在合理范围，合计是否等于给定值，是否按某一列排好序；内置核对公式有没有除以零、有没有整列为空、有没有“待补”之类占位。"
                "每条给出 pass / fail / unknown 与原因（附出问题的单元格位置），并给总判定。"),
            "properties": {
                "table": TABLE,
                "object": OBJECT,
                "expect": {"type": "string", "maxLength": 20000, "description": (
                    "expect：期望清单，一行一条（可省略，省略时只做内置核对）。列名用列标题或 key，含空格时加引号；每条都可以加 sheet=表名（行首行尾都行），也可单独一行写 sheet=表名、管到下一个这样的行；都不写时核对第一张表。"
                    "columns 列A 列B …（这些列都在）；order 列A 列B …（按此顺序）；rows min=N max=N（行数）；unique 列A [列B …]（合起来不重复）；"
                    "nonempty 列A … 或 nonempty *（没有空格子）；range 列 min=X max=Y（数值范围，百分比列写百分数）；"
                    "total 列 sum=V（或 avg= / min= / max= / count=，可加 tol=误差）；sorted 列 asc|desc（已排序）。")},
            },
        },
        "output_schema": {
            "type": "object", "additionalProperties": False, "required": ["verdict", "covered", "checks", "table_sha256"],
            "properties": {
                "verdict": {"enum": ["pass", "fail", "unknown"]},
                "covered": {"type": "boolean", "description": "verdict 为 unknown 时为 false（TL-22 覆盖范围外）"},
                "checks": {"type": "array", "items": {"type": "object", "required": ["line", "src", "kind", "verdict"], "properties": {
                    "line": {"type": "integer"}, "src": {"type": "string"}, "kind": {"type": "string"},
                    "verdict": {"enum": ["pass", "fail", "unknown"]}, "expected": {}, "actual": {},
                    "where": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}}},
                "table_sha256": SHA,
                "assumptions": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "capability": {
        "ops": ["check"],
        "in_types": ["table"],
        "out_types": ["verdict"],
        "constraints": {"three_valued": True, "max_expect_lines": 300,
                        "kinds": ["columns", "order", "rows", "unique", "nonempty", "range", "total", "sorted"],
                        "latency_note": "约 0.1 s"},
        "examples": [
            {"input": "核对物料清单的金额合计是不是 128,600 元", "output": "total 金额 sum=128600 → pass"},
            {"input": "检查员工表的工号有没有重复", "output": "unique 工号 → fail：员工!A7 与前面的行重复"},
            {"input": "排班表每天三个班都要有人", "output": "nonempty 早班 中班 晚班 → pass"},
            {"input": "报价单里还有没有没填的格子和“待补”", "output": "nonempty * 与内置占位核对 → 列出单元格位置"},
        ],
        "non_goals": ["不判断数据本身是否属实（例如价格对不对）", "不改表，只报告"],
    },
    "review_coverage": {"by_predicate": ["table_meets_spec"]},
}

EXPORT = {
    "tool_id": "table.export",
    "trust_claim": "T1",
    "effect": "none",
    "executor": EXEC,
    "cost": {"latency": 300, "price": 0, "timeout": 60000},
    "input_example": {"table": {"title": "季度销量", "columns": ["地区", "一季度", "二季度"], "rows": [["华东", 120, 135], ["华南", 98, 110]]},
                      "formats": ["xlsx", "csv"]},
    "signature": {
        "input_schema": {
            "type": "object", "additionalProperties": False, "oneOf": [{"required": ["table"]}, {"required": ["object"]}],
            "description": (
                "把表格交成需要的文件：Excel（可直接编辑，带表头、筛选、数字格式与能重算的公式）、"
                "CSV（每张表一个文件，UTF-8，Excel 直接打开不乱码）、Markdown 原文，以及可以再次编辑的表模型。"),
            "properties": {
                "table": TABLE,
                "object": OBJECT,
                "name": NAME,
                "formats": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": EXPORT_FORMATS},
                            "description": "xlsx（Excel）、csv、md（Markdown）、json（表模型）中的一个或多个；也可写单个 format。"},
                "format": {"enum": EXPORT_FORMATS},
            },
        },
        "output_schema": {
            "type": "object", "additionalProperties": False, "required": ["table_sha256", "name", "warnings", "files"],
            "properties": {"table_sha256": SHA, "name": {"type": "string"}, "warnings": WARN, "files": FILES},
        },
    },
    "capability": {
        "ops": ["convert"],
        "in_types": ["table"],
        "out_types": ["table_file"],
        "constraints": {"formats": EXPORT_FORMATS, "deterministic_files": True, "max_file_mb": 64,
                        "csv": "UTF-8 带 BOM、CRLF；每张表一个文件；不含合计行；数值不加千分位，百分比写百分数",
                        "latency_note": "约 0.1–1 s，视行数"},
        "examples": [
            {"input": "把报价表导出成 Excel", "output": "formats [xlsx]"},
            {"input": "要一份 CSV 导进 ERP", "output": "formats [csv]"},
            {"input": "给我 Markdown 版本贴进文档", "output": "formats [md]"},
        ],
        "non_goals": ["不交 PDF、WPS、ODS 格式", "不读入已有的 Excel 文件"],
    },
}

REG = {
    "family": "table",
    "family_version": "1.0.1",
    "lock_hash": "",
    "note": ("字段严格按 kernel-spec 17 章 TL-6；族名在顶层 family，由引擎下发到各件。cost 的 latency 与 timeout 单位为毫秒，price 为每次调用的平台计价单位。"
             "选择金样（TL-12 ⑥）是认证材料，在 selection_cases.json。类型由本包的 mengos-package.json 声明、经安装器入册（TL-25）；verdict 为平台类型。"
             "文件产出按 TL-9a：结果对象顶层的 files。本包按安装包交付，仓库现行结构如需额外字段，报工具侧补入，施工方不改包内文件。"),
    "units": [BUILD, CHECK, EXPORT],
}

if __name__ == "__main__":
    p = ROOT / "registration.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    if old:
        REG["lock_hash"] = old.get("lock_hash", "")
        for u, o in zip(REG["units"], old.get("units", [])):
            if o.get("tool_id") == u["tool_id"]:
                u["version"] = o.get("version", "")
    for u in REG["units"]:
        u.setdefault("version", "")
    p.write_text(json.dumps(REG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("registration.json", len(REG["units"]), "units")
