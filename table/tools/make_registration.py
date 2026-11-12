"""生成 registration.json（TL-6 登记资产）。说明文字站在调用方的观察点写（TL-16b、TL-19）。

2.0.0：table.build 接入贡献型声明（17 TL-30a），入参与核对、导出分成两份定义：
  · table.build：顶层 base 槽（x-mengos-base）；sheets 标 by-id（id 必填、label=name，不设 fill，与 document 的 doc.tables 同形），各处 rows 标 append；
    必填改为 if {required:[base]} then {required:[base]} else {原必填}，只有 sheet 的 id 必填写在分支之外；
  · table.check、table.export：表的定义照 1.0.1（sheet id 可选），不带贡献词汇——它们收的是表对象，不参与合并。

顺序：改本文件 → python tools/make_registration.py → python lock.py → python tools/make_package.py。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import COLOR_NAMES, DATE_FORMATS, DISPLAY_KEY, MAX_RULES, ROW_KINDS  # noqa: E402  闭集与代码同一处定义
ID = {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]{0,31}$"}
CELL = {"type": ["string", "number", "boolean", "null"]}
NAME = {"type": "string", "pattern": "^[^/\\\\.:*?\"<>|\\s]{1,64}$", "description": "交付文件的名字（不含扩展名）；缺省取标题。"}

# 2.1.0 G1：样式值（四种属性，颜色取命名色板）；都不是数据字段（17 TL-30），不标 x-mengos-data
STYLE = {"type": "object", "additionalProperties": False, "properties": {
    "fill": {"enum": list(COLOR_NAMES)}, "color": {"enum": list(COLOR_NAMES)},
    "bold": {"type": "boolean"}, "italic": {"type": "boolean"}}}
# 行里的保留键：本行、本格的显示设置，跟着这一行走（17 TL-30 v0.2.98，"x-mengos-display": true 声明它不是数据字段）
DISPLAY = {"type": "object", "x-mengos-display": True, "additionalProperties": False,
           "description": "这一行的显示设置：row 整行的样式，cells {列名: 这一格的样式}；排序、插行、删行以后仍属这一行",
           "properties": {"row": STYLE, "cells": {"type": "object", "maxProperties": 200, "additionalProperties": STYLE}}}
RULE = {"oneOf": [
    {"type": "object", "required": ["when", "style"], "additionalProperties": False, "properties": {
        "when": {"type": "string", "minLength": 1, "maxLength": 500},
        "apply_to": {"oneOf": [{"const": "row"}, {"type": "array", "minItems": 1, "maxItems": 200, "items": {"type": "string", "minLength": 1}}]},
        "style": STYLE, "label": {"type": "string", "maxLength": 200}}},
    {"type": "object", "required": ["scale"], "additionalProperties": False, "properties": {
        "scale": {"type": "object", "required": ["column"], "additionalProperties": False, "properties": {
            "column": {"type": "string", "minLength": 1}, "from": {"enum": list(COLOR_NAMES)}, "to": {"enum": list(COLOR_NAMES)}}},
        "label": {"type": "string", "maxLength": 200}}},
]}
ROW_STYLES = {"type": "array", "maxItems": len(ROW_KINDS), "items": {
    "type": "object", "required": ["kind"], "additionalProperties": False,
    "properties": {"kind": {"enum": list(ROW_KINDS)}, "style": STYLE}}}

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
            "style": STYLE,
            "date_format": {"enum": list(DATE_FORMATS)},
            "thousands": {"type": "boolean"},
        }},
    ]
}
ROWS = {"type": "array", "maxItems": 100000, "x-mengos-data": True, "items": {"oneOf": [
    {"type": "array", "maxItems": 200, "items": CELL},
    {"type": "object", "properties": {DISPLAY_KEY: DISPLAY}, "additionalProperties": CELL},
]}}
ROWS_BUILD = {**ROWS, "x-mengos-merge": {"mode": "append"}}
TOTALS = {"type": "array", "maxItems": 200, "items": {"oneOf": [
    {"type": "string", "minLength": 1},
    {"type": "object", "required": ["column"], "additionalProperties": False, "properties": {
        "column": {"type": "string", "minLength": 1},
        "fn": {"enum": ["sum", "avg", "min", "max", "count", "formula", "none"]},
        "value": {}}},
]}}
SHEET_PROPS = {
    "columns": {"type": "array", "minItems": 1, "maxItems": 200, "items": COLUMN},
    "rows": ROWS,
    "totals": TOTALS,
    "caption": {"type": "string", "maxLength": 500},
    "note": {"type": "string", "maxLength": 2000},
    "freeze_cols": {"type": "integer", "minimum": 0, "maximum": 10},
    "header_style": STYLE,
    "rules": {"type": "array", "maxItems": MAX_RULES, "items": RULE},
    "row_styles": ROW_STYLES,
}
TABLE_DESC = (
        "table：一张或几张数据表。title 标题（必填）。单张表直接写 columns 与 rows；几张表写 sheets，"
        "每张 {name 表名（最多 31 个字符）, columns, rows, totals, caption, note}。"
        "columns 按顺序列出各列：title 列标题（必填，只写名称，单位写进 unit）、key（可选，字母、数字、下划线，公式里用它引用这一列）、"
        "type（text 文字 / integer 整数 / number 数 / money 金额 / percent 百分比 / date 日期 / bool 是否；不写时按内容推断）、"
        "unit 单位（如 MPa、元/吨）、decimals 显示几位小数、formula 公式（同一行里数值列的 + - * / 与括号，可用 round、abs、min、max，"
        "用列的 key 或标题引用，例如 \"单价 * 数量\"；公式列的值由工具算，行里不用写）。列也可以只写标题字符串。"
        "公式还可用 roundup、rounddown（向上、向下取整，例如 roundup(总数量 * (1 + 损耗率))）、ceiling(x, 倍数)、floor(x, 倍数)，"
        "比较 > >= < <= = <> 与 and、or、not、if(条件, 甲, 乙)（状态这类文字列写 if，type 写 text，两支写双引号里的文字，不写数字常数），"
        "total(列) 取本列合计、cumsum(列) 从首行累加到本行。百分比列在公式里是小数：12.5% 是 0.125，100% 可直接写成 100%；"
        "百分比公式列算出来的也是小数（实际 / 预算）。"
        "rows 每行一个数组，按列的顺序，每格是字符串、数字、true/false 或 null（空格子）；有公式列时可以只写非公式列。"
        "数值写数字，不带单位；百分比写百分数（12.5 表示 12.5%）；日期写 YYYY-MM-DD。"
        "totals 加末行合计：[{column, fn}]，fn 为 sum / avg / min / max / count，只写列名时按 sum；"
        "fn 写 formula 时合计行按本列公式重算（比率列：实际合计 ÷ 预算合计），写 none 留空。"
        "meta：lang（zh-CN 或 en，也可直接写在 table 顶层）、author、org、date、version。sources 列数据来源，assumptions 列数据成立的前提（如价格的时点）。"
        "2.1.0 起：样式 style 写 {fill 底色, color 字色, bold, italic}，颜色取色板：红、橙、黄、绿、蓝、深蓝、灰、浅灰、白、黑、浅红、浅黄。"
        "列的默认样式写在 columns[].style；表头写 header_style；合计行写 row_styles [{kind: \"total\", style}]。"
        "某一行、某一格的样式写在那一行里：行写成对象，加保留键 \"$style\": {row: 整行样式, cells: {列名: 这一格的样式}}，例如 "
        "{\"品名\": \"投影仪\", \"单价\": 12800, \"$style\": {\"cells\": {\"单价\": {\"fill\": \"黄\"}}}}；样式跟着行走，排序、插行、删行都不用改行号。"
        "条件规则 rules 按次序写 [{when 条件, apply_to, style}]：when 与公式同一种写法，例如 \"金额 > 10000\"、\"实际 > 预算\"、\"执行率 > 100%\"，"
        "日期写在双引号里（到货日期 > 后接双引号括起的 2026-11-20）；"
        "apply_to 缺省给条件里的列着色，写 \"row\" 整行着色，或写列名数组；色阶写 {scale: {column, from, to}}。"
        "规则只管数据行；同一属性先命中的规则先得；规则压过格、行、列上的样式（与 Excel 相同）。rules 给了就整组替换：要加一条，把原有的连同新的按次序一起写出。"
        "日期列可写 date_format（YYYY-MM-DD / YYYY/MM/DD / YYYY年M月D日 / M月D日 / YYYY.MM.DD），只改显示，Excel 里仍是日期；数值列可写 thousands true/false 定千分位。"
)
TABLE_DESC_BUILD = (
    "table：一张或几张数据表。title 标题。单张表直接写 columns 与 rows；几张表写 sheets，"
    "每张 {id, name 表名（最多 31 个字符）, columns, rows, totals, caption, note}，id 必填（字母、数字、下划线，供后续修改时定位这张表）。"
    "columns 按顺序列出各列：title 列标题（必填，只写名称，单位写进 unit）、key（可选，字母、数字、下划线，公式里用它引用这一列）、"
    "type（text 文字 / integer 整数 / number 数 / money 金额 / percent 百分比 / date 日期 / bool 是否；不写时按内容推断，建议都写上；"
    "被公式或合计引用的列必须写 type，只做 count 的列也要写 type（text 即可））、"
    "unit 单位（如 MPa、元/吨）、decimals 显示几位小数、formula 公式（同一行里数值列的 + - * / 与括号，可用 round、abs、min、max，"
    "用列的 key 或标题引用，例如 \"单价 * 数量\"；公式列的值由工具算，行里不用写）。列也可以只写标题字符串。"
    "公式还可用 roundup、rounddown（向上、向下取整，例如 roundup(总数量 * (1 + 损耗率))）、ceiling(x, 倍数)、floor(x, 倍数)，"
    "比较 > >= < <= = <> 与 and、or、not、if(条件, 甲, 乙)（状态这类文字列写 if，type 写 text，两支写双引号里的文字，不写数字常数），"
    "total(列) 取本列合计、cumsum(列) 从首行累加到本行。百分比列在公式里是小数：12.5% 是 0.125，100% 可直接写成 100%；"
    "百分比公式列算出来的也是小数（实际 / 预算）。"
    "rows 每行一个数组，按列的顺序，格数等于列数；有公式列时也可以只写非公式列，格数等于非公式列数；每格是字符串、数字、true/false 或 null（空格子）。"
    "行也可以写成对象（列的 key 或标题 → 值），缺的格子为空；分批追加行时请用对象行，改了列要把已有的数组行按新列重写。"
    "数值写数字，不带单位；百分比写百分数（12.5 表示 12.5%）；日期写 YYYY-MM-DD。"
    "totals 加末行合计：[{column, fn}]，fn 为 sum / avg / min / max / count，只写列名时按 sum；"
    "fn 写 formula 时合计行按本列公式重算（比率列：实际合计 ÷ 预算合计），写 none 留空。"
    "meta：lang（zh-CN 或 en，也可直接写在 table 顶层）、author、org、date、version。sources 列数据来源，assumptions 列数据成立的前提（如价格的时点）。"
    "2.1.0 起：样式 style 写 {fill 底色, color 字色, bold, italic}，颜色取色板：红、橙、黄、绿、蓝、深蓝、灰、浅灰、白、黑、浅红、浅黄。"
    "列的默认样式写在 columns[].style；表头写 header_style；合计行写 row_styles [{kind: \"total\", style}]。"
    "某一行、某一格的样式写在那一行里：行写成对象，加保留键 \"$style\": {row: 整行样式, cells: {列名: 这一格的样式}}，例如 "
    "{\"品名\": \"投影仪\", \"单价\": 12800, \"$style\": {\"cells\": {\"单价\": {\"fill\": \"黄\"}}}}；样式跟着行走，排序、插行、删行都不用改行号。"
    "条件规则 rules 按次序写 [{when 条件, apply_to, style}]：when 与公式同一种写法，例如 \"金额 > 10000\"、\"实际 > 预算\"、\"执行率 > 100%\"，"
    "日期写在双引号里（到货日期 > 后接双引号括起的 2026-11-20）；"
    "apply_to 缺省给条件里的列着色，写 \"row\" 整行着色，或写列名数组；色阶写 {scale: {column, from, to}}。"
    "规则只管数据行；同一属性先命中的规则先得；规则压过格、行、列上的样式（与 Excel 相同）。rules 给了就整组替换：要加一条，把原有的连同新的按次序一起写出。"
    "日期列可写 date_format（YYYY-MM-DD / YYYY/MM/DD / YYYY年M月D日 / M月D日 / YYYY.MM.DD），只改显示，Excel 里仍是日期；数值列可写 thousands true/false 定千分位。"
    "改既有的行（改值、删行、插行、排序、对调）或删表、调表序时，不带 base，整张表重写。"
)


# 2.1.0 新增的说明句（上面两段说明里原样出现；tests/test_contribution.py 按它们剥回 1.0.1 的说明，证明只加不改）
Q = '"'
STYLE_DESC = [
 "2.1.0 起：样式 style 写 {fill 底色, color 字色, bold, italic}，颜色取色板：红、橙、黄、绿、蓝、深蓝、灰、浅灰、白、黑、浅红、浅黄。",
 f"列的默认样式写在 columns[].style；表头写 header_style；合计行写 row_styles [{{kind: {Q}total{Q}, style}}]。",
 f"某一行、某一格的样式写在那一行里：行写成对象，加保留键 {Q}$style{Q}: {{row: 整行样式, cells: {{列名: 这一格的样式}}}}，例如 ",
 f"{{{Q}品名{Q}: {Q}投影仪{Q}, {Q}单价{Q}: 12800, {Q}$style{Q}: {{{Q}cells{Q}: {{{Q}单价{Q}: {{{Q}fill{Q}: {Q}黄{Q}}}}}}}}}；样式跟着行走，排序、插行、删行都不用改行号。",
 f"条件规则 rules 按次序写 [{{when 条件, apply_to, style}}]：when 与公式同一种写法，例如 {Q}金额 > 10000{Q}、{Q}实际 > 预算{Q}、{Q}执行率 > 100%{Q}，",
 "日期写在双引号里（到货日期 > 后接双引号括起的 2026-11-20）；",
 f"apply_to 缺省给条件里的列着色，写 {Q}row{Q} 整行着色，或写列名数组；色阶写 {{scale: {{column, from, to}}}}。",
 "规则只管数据行；同一属性先命中的规则先得；规则压过格、行、列上的样式（与 Excel 相同）。rules 给了就整组替换：要加一条，把原有的连同新的按次序一起写出。",
 "日期列可写 date_format（YYYY-MM-DD / YYYY/MM/DD / YYYY年M月D日 / M月D日 / YYYY.MM.DD），只改显示，Excel 里仍是日期；数值列可写 thousands true/false 定千分位。",
]
FORMULA_ADD = [
 "公式还可用 roundup、rounddown（向上、向下取整，例如 roundup(总数量 * (1 + 损耗率))）、ceiling(x, 倍数)、floor(x, 倍数)，",
 "比较 > >= < <= = <> 与 and、or、not、if(条件, 甲, 乙)（状态这类文字列写 if，type 写 text，两支写双引号里的文字，不写数字常数），",
 "total(列) 取本列合计、cumsum(列) 从首行累加到本行。百分比列在公式里是小数：12.5% 是 0.125，100% 可直接写成 100%；",
 "百分比公式列算出来的也是小数（实际 / 预算）。",
]
TOT_ADD = ["fn 写 formula 时合计行按本列公式重算（比率列：实际合计 ÷ 预算合计），写 none 留空。"]
BUILD_ONLY_ADD = ["改既有的行（改值、删行、插行、排序、对调）或删表、调表序时，不带 base，整张表重写。"]
assert all(x in TABLE_DESC for x in FORMULA_ADD + TOT_ADD + STYLE_DESC)
assert all(x in TABLE_DESC_BUILD for x in FORMULA_ADD + TOT_ADD + STYLE_DESC + BUILD_ONLY_ADD)


def table_def(build=False):
    """build=True：table.build 的贡献型定义；否则核对与导出用的 1.x 定义（逐键同 1.0.1）。"""
    rows = ROWS_BUILD if build else ROWS
    sheet_props = {**SHEET_PROPS, "rows": rows}
    sheet = {"type": "object", "required": ["id"] if build else ["columns"], "additionalProperties": False,
             "properties": {"id": ID, "name": {"type": "string", "maxLength": 200}, **sheet_props,
                            "sources": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000},
                                        "description": "写在这里也行，并入整张表的 sources"},
                            "assumptions": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000},
                                            "description": "写在这里也行，并入整张表的 assumptions"}}}
    sheets = {"type": "array", "minItems": 1, "maxItems": 20, "items": sheet}
    if build:
        sheets = {**sheets, "x-mengos-merge": {"mode": "by-id", "id": "id", "label": "name"}}
    t = {"type": "object"}
    if not build:
        t["required"] = ["title"]
    t["additionalProperties"] = False
    t["description"] = TABLE_DESC_BUILD if build else TABLE_DESC
    t["properties"] = {
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
        "sheets": sheets,
        **sheet_props,
        "sources": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000}},
        "assumptions": {"type": "array", "maxItems": 100, "items": {"type": "string", "maxLength": 1000}},
    }
    return t


TABLE = table_def()
TABLE_BUILD = table_def(build=True)
BASE_SLOT = {"type": "string", "x-mengos-base": True,
             "description": "上一版产物的回执节点 id（取输入材料中标 $best:true 的那条）；给出时只写改动的部分，引擎按标注合并"}
# 不带 base 时的必填（整体写法）：与 1.0.1 相同——table 必填，table.title 必填，每张 sheet 的 columns 必填
WHOLE_REQUIRED = {"required": ["table"], "properties": {"table": {
    "required": ["title"], "properties": {"sheets": {"items": {"required": ["columns"]}}}}}}
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
            "type": "object", "additionalProperties": False,
            "if": {"required": ["base"]}, "then": {"required": ["base"]}, "else": WHOLE_REQUIRED,
            "description": (
                "要交付一张表格时用：清单、台账、明细、对照表、报价单、排班表，或要 Excel、CSV 文件。"
                "你把数据写进 table：各列、各行的值，需要的公式列与合计；任务只给了要求时，数据由你按要求整理。"
                "本工具统一各列的类型、单位与小数位，按公式算出公式列和合计；交付 Excel 文件（表头、冻结首行、筛选、数字格式、能重算的公式、样式与条件格式），"
                "以及产出台上可排序查看的版本和 Markdown 原文。任务要 CSV 时，在与 table 并列的 formats 里写 [\"xlsx\", \"csv\"]。"
                "产出台与 Excel 重算一致；个别取整或比较的边界值可能不一致时会告警，点名到格。"),
            "properties": {
                "base": BASE_SLOT,
                "table": TABLE_BUILD,
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
                        "formula_functions": ["round", "abs", "min", "max", "roundup", "rounddown", "ceiling", "floor",
                                              "and", "or", "not", "if", "total", "cumsum"],
                        "formula_operators": ["+", "-", "*", "/", ">", ">=", "<", "<=", "=", "<>"],
                        "totals": ["sum", "avg", "min", "max", "count", "formula", "none"],
                        "style_properties": ["fill", "color", "bold", "italic"],
                        "palette": list(COLOR_NAMES[:12]),
                        "rule_kinds": ["when", "scale"], "max_rules": MAX_RULES, "row_style_kinds": list(ROW_KINDS),
                        "date_formats": list(DATE_FORMATS),
                        "excel_recalc": "产出台与 Excel 重算一致；取整、比较的参数先归整到 15 位有效数字，个别边界值不一致时告警（excel_float）",
                        "deterministic_files": True,
                        "latency_note": "几百行约 0.1 s；一万行约 1 s（含 Excel）"},
        "examples": [
            {"input": "把 20 种常用钢材的密度、屈服强度和参考价格列成一张 Excel 表", "output": "你整理好 20 行数据填进 table，单位写进各列的 unit → Excel 与产出台表格"},
            {"input": "导出这台减速机的物料清单，带数量、单价和金额合计", "output": "金额列 formula=\"数量 * 单价\"，totals [金额] → 带合计行的 Excel"},
            {"input": "把斐波那契数列前 30 项列成表，另给一份 CSV", "output": "两列 n、F(n)，30 行，formats [xlsx, csv]"},
            {"input": "排一张客服组下周的值班表，七天三班倒", "output": "列：日期、早班、中班、晚班；7 行"},
            {"input": "预算表里执行率超过 100% 的标红，合计行的执行率按公式算", "output": "rules [{when: \"执行率 > 100%\", style: {color: 红}}]，totals 里执行率 fn formula"},
        ],
        "non_goals": [
            "不替你找数据：表里的数据都由调用方给出，工具只整理、计算与排版",
            "不写成文的报告：表只是文章里的一部分时，交给长文工具",
            "不画图表，不做跨表公式与数据透视",
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
    "family_version": "2.1.0",
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
