"""生成 registration.json（TL-6 登记资产）。登记的单一来源是本文件；改完跑 python lock.py、python tools/make_package.py。

【草案】本文件里进模型上下文的文字（input_schema 各层 description、capability.examples、input_example）
是施工方草案，待立法者定稿（提示词禁触区）。定稿只改这些字符串，结构不动；改后重算 lock、重新认证。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_INLINE_ROWS = 50
OPS = ["eq", "ne", "in", "contains", "regex", "lt", "le", "gt", "ge", "between"]

CELL = {"type": ["string", "number", "null"]}

SOURCE = {
    "type": "object",
    "additionalProperties": False,
    "anyOf": [{"required": ["columns", "rows"]}, {"required": ["text", "reader"]}],
    "description": "要数的行。两种给法二选一：columns 加 rows（列名与逐行单元格）；或 text 加 reader（解析单元或表格的原文，照抄不改）。"
                   f"行数上限 {MAX_INLINE_ROWS}，超过时得到失败回执。",
    "properties": {
        "columns": {"type": "array", "minItems": 1, "maxItems": 40, "items": {"type": "string", "minLength": 1},
                    "description": "列名，照原文表头写，例如 [\"图层\", \"方向\", \"长度≈\", \"根数\", \"总长\"]。"},
        "rows": {"type": "array", "maxItems": MAX_INLINE_ROWS, "x-mengos-data": True,
                 "items": {"type": "array", "items": CELL},
                 "description": "逐行的单元格，每行格数与 columns 相同；数照原文写。"},
        "declared": {"type": "integer", "minimum": 0, "description": "原文写明的总行数（如“共 8 组”里的 8）；给了就核对读到的行数，不符得到失败回执。"},
        "label": {"type": "string", "maxLength": 40, "description": "行序号的前缀，缺省“行”；回执里每行的序号写成 前缀/第几行。"},
        "text": {"type": "array", "minItems": 1, "maxItems": 16, "items": {"type": "string", "minLength": 1, "maxLength": 60000},
                 "description": "原文一段或多段。同一单元被切成多块时，把各块一起给（次序不限）；缺块时读到的行数与声明不符，得到失败回执。"},
        "reader": {"enum": ["mengos-cad-v1", "gfm"],
                   "description": "原文格式：mengos-cad-v1 是首行为 #mengos-cad v1 的图纸解析单元；gfm 是首行表头、次行分隔线的表格。"},
        "section": {"type": "string", "minLength": 1,
                    "description": "mengos-cad-v1 单元里要数的节，写节名（节头“#”与“（”之间的字，如 图块插入、尺寸标注、线段统计、文字）；单元只有一节有行时可省。"},
    },
}

COND = {
    "type": "object", "additionalProperties": False, "required": ["col", "op", "value"],
    "properties": {
        "col": {"type": "string", "minLength": 1, "description": "列名，照表头。"},
        "op": {"enum": OPS, "description": "eq 等于、ne 不等于、in 属于列举的值、contains 含有、regex 正则匹配、lt/le/gt/ge 小于/不大于/大于/不小于、between 落在 [下限, 上限]。"},
        "value": {"type": ["string", "number", "array"], "description": "比较的值。value 写成数时按数比（2760 与 2760.0 相等），写成字符串时逐字比；in 写数组，between 写两个数。"},
        "key": {"type": "string", "minLength": 1, "description": "该列是 k=v;k=v 形式时，取其中键为 key 的值来比。"},
    },
}

WHERE = {"type": "array", "maxItems": 20, "items": COND, "description": "筛选条件，各条同时满足。数值比较时该格不是数的行不计入，列在回执 unparsed 里。"}
ANY_OF = {"type": "array", "maxItems": 10, "items": {"type": "array", "minItems": 1, "maxItems": 20, "items": COND},
          "description": "“或”条件：若干组，组内同时满足、满足任一组即可；与 where 同时给出时两者都要满足。"}
TOL = {"type": "number", "minimum": 0, "description": "数值相等的容差，缺省 0。"}

ROWS_OUT = {
    "type": "object",
    "required": ["count", "what", "source", "checks", "assumptions"],
    "properties": {
        "count": {"type": "integer"},
        "what": {"type": "object"},
        "source": {"type": "object", "required": ["mode", "rows_read"]},
        "groups": {"type": "array"},
        "groups_count": {"type": "integer"},
        "aggregate": {"type": "array"},
        "distribution": {"type": "object"},
        "items": {"type": "array"},
        "unparsed": {"type": "array"},
        "checks": {"type": "array"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}


def unit(tool_id, input_schema, output_schema, capability, example, review=None):
    u = {
        "tool_id": tool_id, "version": "", "trust_claim": "T1", "effect": "none",
        "executor": {"kind": "process", "entry": "count_tool.py", "mode": "sync"},
        "cost": {"latency": 150, "price": 0, "timeout": 10000},
        "input_example": example,
        "signature": {"input_schema": input_schema, "output_schema": output_schema},
        "capability": capability,
    }
    if review is not None:
        u["review_coverage"] = review
    return u


CONSTRAINTS = {"deterministic": True, "network": "none", "model_calls": 0, "max_inline_rows": MAX_INLINE_ROWS,
               "readers": ["rows", "mengos-cad-v1", "gfm"], "source_modes": ["inline"]}

ROWS = unit(
    "count.rows",
    {
        "type": "object", "additionalProperties": False, "required": ["source"],
        "description": "需要知道“有几条、几种、合计多少、排成几列几行”时用：给出要数的行和条件，拿回条数、分组条数、列合计和数值列的分布（不同取值个数、步长、是否等距、网格是否齐全）。",
        "properties": {
            "source": SOURCE, "where": WHERE, "any_of": ANY_OF,
            "group_by": {"type": "array", "maxItems": 5, "items": {"type": "string", "minLength": 1}, "description": "按这些列分组，回执给每组条数与组数 groups_count。"},
            "aggregate": {"type": "array", "maxItems": 10, "items": {"type": "object", "additionalProperties": False, "required": ["col", "fn"],
                          "properties": {"col": {"type": "string", "minLength": 1}, "fn": {"enum": ["sum", "min", "max"]}}},
                          "description": "对满足条件的行求某列的合计（sum）、最小（min）、最大（max）；分组时每组也给。"},
            "distribution": {"type": "object", "additionalProperties": False, "required": ["x"],
                             "properties": {"x": {"type": "string", "minLength": 1}, "y": {"type": "string", "minLength": 1}, "tol": TOL},
                             "description": "取一列（x）或两列（x、y）数值看分布：不同取值个数、相邻间隔、是否等距；两列时给网格的列数、行数与缺位。tol 内的值算同一位置。"},
            "list": {"type": "boolean", "description": "true 时回执带满足条件的逐行清单，每行有稳定序号。"},
        },
    },
    ROWS_OUT,
    {"ops": ["compute"], "in_types": [], "out_types": ["number"], "constraints": {**CONSTRAINTS, "ops": OPS},
     "examples": [
         {"input": "图纸线段统计里，COL_A 图层竖直、长度约 10280 的线有几根", "output": "count 1 组，根数合计 1100"},
         {"input": "同一个图块在这个视图里插了几次、排成几列几行", "output": "count 660；x 向 33 个位置、步长 2760；网格 33×20，无缺位"},
         {"input": "设备台账里状态为在用的设备各车间各有几台", "output": "groups：一车间 12、二车间 7；groups_count 2"},
     ],
     "non_goals": ["不判断一行在业务上是什么", "不读附件，来源行由调用方给出", "不估算"]},
    {"source": {"columns": ["图层", "方向", "长度≈", "根数", "总长"],
                "rows": [["COL_A", "竖直", 10280, 1100, 11302500], ["COL_B", "竖直", 11250, 1100, 12375000]], "declared": 2},
     "where": [{"col": "图层", "op": "eq", "value": "COL_A"}, {"col": "方向", "op": "eq", "value": "竖直"}],
     "aggregate": [{"col": "根数", "fn": "sum"}]},
)

SERIES = unit(
    "count.series",
    {
        "type": "object", "additionalProperties": False, "required": ["source", "mode"],
        "anyOf": [{"properties": {"mode": {"const": "product"}}, "required": ["product"]},
                  {"properties": {"mode": {"const": "chain"}}, "required": ["chain"]},
                  {"properties": {"mode": {"const": "both"}}, "required": ["product", "chain"]}],
        "description": "图上或表里有“个数×间距=总长”式的写法、或首尾相接的一串区间时用：拿回每条乘积串的两个因子与是否自洽，以及每条连续链的段数、各段值、是否等距与总长。",
        "properties": {
            "source": SOURCE, "where": WHERE, "any_of": ANY_OF,
            "mode": {"enum": ["product", "chain", "both"], "description": "product 找乘积串；chain 连链；both 两样都做。"},
            "product": {"type": "object", "additionalProperties": False, "required": ["text"],
                        "properties": {"text": {"type": ["string", "array"], "items": {"type": "string"}},
                                       "measure": {"type": "string", "minLength": 1}},
                        "description": "text：在哪一列（或几列）里找 左*右=合计（* 也可写 × 或 x）；measure：给了就把合计与该列的值比对。两个因子都列出，哪个是个数由你判断。"},
            "chain": {"type": "object", "additionalProperties": False, "required": ["from", "to", "value"],
                      "properties": {"from": {"type": "string", "minLength": 1}, "to": {"type": "string", "minLength": 1},
                                     "value": {"type": "string", "minLength": 1}, "undirected": {"type": "boolean"}},
                      "description": "from、to：起点列与终点列（一个数，或 x,y 形式的坐标）；value：每段的取值列。一段的终点与下一段的起点在 tol 内相同就连成链；undirected 为 true 时不分起止方向。只有一段的不算链。"},
            "tol": TOL,
        },
    },
    {"type": "object", "required": ["what", "source", "checks", "assumptions"],
     "properties": {"product": {"type": "object"}, "chain": {"type": "object"}, "what": {"type": "object"},
                    "source": {"type": "object"}, "checks": {"type": "array"}, "assumptions": {"type": "array", "items": {"type": "string"}}}},
    {"ops": ["compute"], "in_types": [], "out_types": ["number"], "constraints": CONSTRAINTS,
     "examples": [
         {"input": "主视图尺寸写着 33*2760=91080，核一下是否自洽", "output": "left 33、right 2760，product_ok true，与测量值 91080 一致"},
         {"input": "底边那串连续尺寸一共几段、每段多长", "output": "1 条链：12 段，每段 2760，总长 33120"},
         {"input": "工序表里相邻工序是否首尾相接", "output": "2 条链，各 5 段与 3 段；链在第 6 道工序处断开"},
     ],
     "non_goals": ["不判断哪个因子是个数", "不纠正不自洽的乘积串"]},
    {"source": {"columns": ["类型", "测量值", "显示文字", "端点1", "端点2", "图层"],
                "rows": [["线性", 91080, "33*2760=91080", "0,-500", "91080,-500", "DIM"]]},
     "mode": "product", "product": {"text": "显示文字", "measure": "测量值"}, "tol": 1},
)

COVERAGE = unit(
    "count.coverage",
    {
        "type": "object", "additionalProperties": False, "required": ["inventory", "marks"],
        "description": "逐个处理一份清单（分片、条款、构件类）时用：给出清单和已处理的记录，拿回还没处理的有哪些、几条，以及清单外的、重复的记录。",
        "properties": {
            "inventory": {"type": "object", "additionalProperties": False,
                          "anyOf": [{"required": ["items"]}, {"required": ["source"]}],
                          "description": "清单，二选一：items 逐条写 id（可带 label）；或 source 给行（写法同计数），id_col 指定哪列是 id，省略时用每行的稳定序号。",
                          "properties": {
                              "items": {"type": "array", "maxItems": MAX_INLINE_ROWS,
                                        "items": {"anyOf": [{"type": "string", "minLength": 1},
                                                            {"type": "object", "additionalProperties": False, "required": ["id"],
                                                             "properties": {"id": {"type": "string", "minLength": 1}, "label": {"type": "string"}}}]}},
                              "source": SOURCE,
                              "id_col": {"type": "string", "minLength": 1},
                              "label_col": {"type": "string", "minLength": 1},
                          }},
            "expected_total": {"type": "integer", "minimum": 0, "description": "原文写明的清单条数；给了就核对，不符得到失败回执。"},
            "marks": {"type": "array", "maxItems": MAX_INLINE_ROWS * 2,
                      "items": {"type": "object", "additionalProperties": False, "required": ["id", "status"],
                                "properties": {"id": {"type": "string", "minLength": 1}, "status": {"enum": ["done", "empty"]}, "note": {"type": "string", "maxLength": 400}}},
                      "description": "已处理的记录，每条 {id, status, note}；id 照清单原样写；status 为 done（已处理）或 empty（看过、没有相关内容）。"},
        },
    },
    {"type": "object", "required": ["total", "marked", "unmarked_count", "unmarked", "unknown_marks", "duplicate_marks", "source", "assumptions"],
     "properties": {"total": {"type": "integer"}, "marked": {"type": "integer"}, "unmarked_count": {"type": "integer"},
                    "unmarked": {"type": "array"}, "unknown_marks": {"type": "array"}, "duplicate_marks": {"type": "array"},
                    "status_counts": {"type": "object"}, "total_ok": {"type": ["boolean", "null"]}, "expected_total": {},
                    "source": {"type": "object"}, "assumptions": {"type": "array", "items": {"type": "string"}}}},
    {"ops": ["check"], "in_types": [], "out_types": ["verdict"], "constraints": CONSTRAINTS,
     "examples": [
         {"input": "图纸 12 个分片是不是每片都处理过了", "output": "unmarked_count 1，未处理：S7"},
         {"input": "评分办法 47 个评分项是否都有响应", "output": "unmarked_count 0，total_ok true"},
         {"input": "构件类清单里每一类都有数量记录吗", "output": "unmarked_count 2，未处理：横梁、斜撑；清单外记录 1 条"},
     ],
     "non_goals": ["不判断处理得对不对", "不保存状态"]},
    {"inventory": {"items": [{"id": "S1"}, {"id": "S2"}, {"id": "S3"}]}, "expected_total": 3,
     "marks": [{"id": "S1", "status": "done"}, {"id": "S2", "status": "empty", "note": "本片无相关内容"}]},
    review={"by_criterion_pattern": ["每个对象都有处理记录", "没有未处理的清单项"], "by_predicate": ["unmarked_count_eq_0"]},
)

SIDE = {"type": "object", "additionalProperties": False, "required": ["value", "from"],
        "properties": {"value": {"type": "number", "x-mengos-data": True}, "from": {"type": "string", "minLength": 1, "maxLength": 200}},
        "description": "一个数及其出处：value 照回执里的数写；from 写取自哪张回执的哪一项。"}

AGREE = unit(
    "count.agree",
    {
        "type": "object", "additionalProperties": False, "required": ["left", "right"],
        "description": "两种数法应当得到同一个数（或差一个定数）时用：给出两个数和各自出处，拿回是否成立与实际差值。",
        "properties": {
            "left": SIDE, "right": SIDE,
            "relation": {"enum": ["eq", "diff"], "description": "eq：两数相等；diff：left − right 等于 diff。缺省 eq。"},
            "diff": {"type": "number", "description": "relation 为 diff 时的应有差值。"},
            "tol": TOL,
        },
    },
    {"type": "object", "required": ["holds", "relation", "left", "right", "diff_expected", "diff_actual", "assumptions"],
     "properties": {"holds": {"type": "boolean"}, "relation": {"enum": ["eq", "diff"]}, "left": {"type": "object"}, "right": {"type": "object"},
                    "diff_expected": {"type": "number"}, "diff_actual": {"type": "number"}, "tol": {"type": "number"},
                    "assumptions": {"type": "array", "items": {"type": "string"}}}},
    {"ops": ["check"], "in_types": [], "out_types": ["verdict"], "constraints": {"deterministic": True, "network": "none", "model_calls": 0},
     "examples": [
         {"input": "尺寸串的个数因子与图块的列数是否一致", "output": "33 与 33，holds true"},
         {"input": "立柱数是否比列数多一", "output": "34 − 33 = 1，holds true"},
         {"input": "各类别条数之和是否等于评分项总数", "output": "46 与 47，holds false，差 −1"},
     ],
     "non_goals": ["不取回执里的数，数由调用方写入"]},
    {"left": {"value": 33, "from": "乘积串回执 /product/hits/0/left"}, "right": {"value": 33, "from": "图块计数回执 /distribution/x/distinct"}},
    review={"by_criterion_pattern": ["两种数法结果一致"], "by_predicate": ["holds_eq_true"]},
)

REG = {
    "family": "count",
    "family_version": "0.1.0",
    "lock_hash": "",
    "note": "字段严格按 kernel-spec 17 章 TL-6；族名在顶层 family。cost 的 latency 与 timeout 单位为毫秒。第一阶段（零引擎改动）来源只能由调用方给出（source_modes = inline），行数上限 max_inline_rows；回执带假设声明（TL-22a）。input_schema 各层 description、examples、input_example 为草案，待立法者定稿。",
    "units": [ROWS, SERIES, COVERAGE, AGREE],
}

if __name__ == "__main__":
    (ROOT / "registration.json").write_text(json.dumps(REG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("registration.json written (lock 未算：接着跑 python lock.py)")
