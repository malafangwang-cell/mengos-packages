"""生成 registration.json 与 selection_cases.json（只在改登记内容时运行；version 由 lock.py 写入）。

字段严格按 kernel-spec 17 章 TL-6。给模型看的文字（各层 description、examples、non_goals、constraints）
只写能做出什么、解决什么问题、不做什么，不写实现（TL-16 v0.2.23 澄清）。
"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "doc_tool.py"   # 相对包目录（TL-25）；命令为 ⟨包环境的 python⟩ ⟨包目录⟩/doc_tool.py
EXECUTOR = {"kind": "process", "entry": ENTRY, "mode": "sync"}

DOC_DOMAIN = (
    "doc：一份长文档的内容（报告、方案、标书、手册、论文等）。"
    "title 标题（必填）；sections 按顺序列出各节：heading 节标题（只写标题文字，编号由工具统一加）、"
    "level 层级 1–4（缺省 1，每节最多比上一节深一级）、body 正文（Markdown：段落、加粗、列表、表格、引用、代码块）、"
    "id（可选，供引用和后续修改时定位）、responds_to（这一节响应的要求 id）。"
    "图放进 figures：id、caption、source 为 {svg: 静态矢量图（不含脚本、动画与外部链接）} 或 {media_type: image/png|image/jpeg, base64}；"
    "表放进 tables：id、caption、columns、rows（每行格数与列数相同）、note。"
    "正文里单独一行写 [[fig:id]] 或 [[tab:id]]，图表就放在那里；行内写 [[sec:id]]、[[fig:id]]、[[tab:id]] 引用，"
    "交付时换成“第 2.1 节”“图 3”“表 1”并可点击跳转。"
    "requirements 列出任务书或招标文件提出的要求：id、text、source（出处，如“招标文件 第三章 3.2”）、priority（must 或 should），"
    "交付时列出每条要求由哪些章节响应。"
    "meta：lang（zh-CN 或 en）、author、org、date（YYYY-MM-DD）、version、"
    "numbering（decimal：1 / 1.1；chapter：第一章 / 1.1；zh：一、/（一）/ 1．/（1）；none：不编号）、"
    "figure_numbering（global：图 1、图 2；chapter：图 2-1）、toc（目录，缺省 true）、cover（封面页）、trace_table（文末附要求响应对照表）。"
    "kind=outline 表示提纲，允许各节暂时没有正文。"
    "也接受只有 {title, sections:[{heading, body}]} 的简单写法。"
)
NAME_DESC = "交付文件的名字（不含扩展名）；缺省取标题。"

ID = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,31}$"}
SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
LINE = {"type": "string", "maxLength": 200}
SECTION = {
    "type": "object", "required": ["heading"], "additionalProperties": False,
    "properties": {
        "id": ID, "level": {"type": "integer", "minimum": 1, "maximum": 4},
        "heading": {"type": "string", "minLength": 1, "maxLength": 200},
        "body": {"type": "string", "maxLength": 200000},
        "responds_to": {"type": "array", "items": ID, "uniqueItems": True},
    },
}
FIG_SOURCE = {"oneOf": [
    {"type": "object", "required": ["svg"], "additionalProperties": False,
     "properties": {"svg": {"type": "string", "minLength": 1, "maxLength": 2097152}}},
    {"type": "object", "required": ["media_type", "base64"], "additionalProperties": False,
     "properties": {"media_type": {"enum": ["image/png", "image/jpeg"]}, "base64": {"type": "string", "minLength": 1}}},
]}
FIGURE = {"type": "object", "required": ["id", "caption", "source"], "additionalProperties": False,
          "properties": {"id": ID, "caption": {"type": "string", "minLength": 1, "maxLength": 500},
                         "width": {"type": "number", "minimum": 0.1, "maximum": 1}, "source": FIG_SOURCE}}
CELL = {"type": ["string", "number", "null"]}
TABLE = {"type": "object", "required": ["id", "caption", "columns", "rows"], "additionalProperties": False,
         "properties": {"id": ID, "caption": {"type": "string", "minLength": 1, "maxLength": 500},
                        "columns": {"type": "array", "minItems": 1, "maxItems": 30, "items": {"type": "string"}},
                        "rows": {"type": "array", "items": {"type": "array", "items": CELL}},
                        "align": {"type": ["array", "null"], "items": {"enum": ["left", "center", "right"]}},
                        "note": {"type": "string", "maxLength": 500}}}
REQ = {"type": "object", "required": ["id", "text"], "additionalProperties": False,
       "properties": {"id": ID, "text": {"type": "string", "minLength": 1, "maxLength": 2000},
                      "source": {"type": "string", "maxLength": 300}, "priority": {"enum": ["must", "should"]},
                      "anchor": {"type": "object", "additionalProperties": False,
                                 "properties": {"object": SHA, "page": {"type": "integer", "minimum": 1},
                                                "bbox": {"type": "array", "items": {"type": "number"},
                                                         "minItems": 4, "maxItems": 4}}}}}
META = {"type": "object", "additionalProperties": False, "properties": {
    "lang": {"enum": ["zh-CN", "en"]}, "author": LINE, "org": LINE,
    "date": {"type": "string", "pattern": "^(\\d{4}-\\d{2}-\\d{2})?$"}, "version": {"type": "string", "maxLength": 40},
    "numbering": {"enum": ["decimal", "chapter", "zh", "none"]}, "figure_numbering": {"enum": ["global", "chapter"]},
    "toc": {"type": "boolean"}, "cover": {"type": "boolean"}, "trace_table": {"type": "boolean"}}}
DOC = {"type": "object", "required": ["title", "sections"], "additionalProperties": False,
       "description": DOC_DOMAIN,
       "properties": {
           "schema": {"const": "mengos.document/1"}, "kind": {"enum": ["document", "outline"]},
           "title": {"type": "string", "minLength": 1, "maxLength": 200}, "subtitle": LINE, "meta": META,
           "requirements": {"type": "array", "maxItems": 2000, "items": REQ},
           "sections": {"type": "array", "minItems": 1, "maxItems": 2000, "items": SECTION},
           "figures": {"type": "array", "maxItems": 300, "items": FIGURE},
           "tables": {"type": "array", "maxItems": 500, "items": TABLE}}}
# ---- doc.build 贡献型声明（2.0.0）----
# 只有 doc.build 声明 x-mengos-base 与 x-mengos-merge；doc.check / doc.export 仍用上面不带标注的 DOC，不变。
# 四个 by-id 容器（sections、tables、figures、requirements）的元素 id 恒必填，写在 if/then/else 之外：
# 不带 id 的元素没法被后续增量定位，只会追加出重复项。这是输入契约的收紧（节的 id 原为可选），所以升大版本。
# 元素 id 以外的原必填（heading、caption、columns、rows……）以及顶层、doc 层的必填，搬进 else 分支：
# 不带 base 的整体写法走 else，带 base 的增量只要求 base 与各元素的 id。
BASE_DESC = ("上一版产物的回执节点 id（取输入材料中标 $best:true 的那条）；"
             "给出时只写改动的部分，引擎按标注合并")
BUILD_BY_ID = {   # doc 内各 by-id 容器的标注
    "sections": {"mode": "by-id", "id": "id", "label": "heading", "fill": "body"},
    "tables": {"mode": "by-id", "id": "id", "label": "caption"},
    "figures": {"mode": "by-id", "id": "id", "label": "caption"},
    "requirements": {"mode": "by-id", "id": "id", "label": "text"},
}


def _build_doc_and_branches():
    doc = copy.deepcopy(DOC)
    d = doc["description"]
    assert "id（可选，供引用和后续修改时定位）" in d and d.endswith("也接受只有 {title, sections:[{heading, body}]} 的简单写法。")
    doc["description"] = (d.replace("id（可选，供引用和后续修改时定位）", "id（必填，供引用和后续修改时定位）")
                          .removesuffix("也接受只有 {title, sections:[{heading, body}]} 的简单写法。"))
    else_doc = {"required": doc.pop("required"), "properties": {}}
    for field, ann in BUILD_BY_ID.items():
        arr = doc["properties"][field]
        arr["x-mengos-merge"] = ann
        rest = [k for k in arr["items"].pop("required") if k != "id"]
        arr["items"]["required"] = ["id"]
        if rest:
            else_doc["properties"][field] = {"items": {"required": rest}}
    rows = doc["properties"]["tables"]["items"]["properties"]["rows"]
    rows["x-mengos-merge"] = {"mode": "append"}
    return doc, else_doc


DOC_BUILD, _ELSE_DOC = _build_doc_and_branches()
BUILD_IF = {"required": ["base"]}
BUILD_THEN = {"required": ["base"]}
BUILD_ELSE = {"required": ["doc"], "properties": {"doc": _ELSE_DOC}}
BASE_SLOT = {"type": "string", "x-mengos-base": True, "description": BASE_DESC}

NAME = {"type": "string", "pattern": "^[^/\\\\.:*?\"<>|\\s]{1,64}$", "description": NAME_DESC}

FILE_ITEM = {
    "type": "object", "required": ["path", "format", "role", "media_type", "bytes", "sha256"], "additionalProperties": False,
    "properties": {
        "path": {"type": "string", "pattern": "^(figures/)?[^/\\\\]+$", "description": "相对 workdir 的文件名；位图原图在 figures/ 下一级"},
        "format": {"enum": ["json", "view", "md", "docx", "pdf", "html", "figure"]},
        "role": {"enum": ["document.model", "document.view", "document.text", "document.word", "document.pdf",
                          "document.web", "document.figure", "document.figure_original"]},
        "media_type": {"type": "string"}, "bytes": {"type": "integer", "minimum": 1}, "sha256": SHA,
    },
}
WARN = {"type": "array", "items": {"type": "object", "required": ["where", "code", "message"],
                                   "properties": {"where": {"type": "string"}, "code": {"type": "string"},
                                                  "message": {"type": "string"}, "line": {"type": "integer"},
                                                  "hint": {"type": "string"}}}}
OUTLINE = {"type": "array", "items": {"type": "object", "required": ["id", "level", "number", "heading", "words", "words_total"],
                                      "properties": {"id": {"type": "string"}, "level": {"type": "integer"},
                                                     "number": {"type": "string"}, "heading": {"type": "string"},
                                                     "words": {"type": "integer"}, "words_total": {"type": "integer"}}}}
STATS = {"type": "object", "required": ["sections", "chapters", "words", "chars", "figures", "tables", "requirements",
                                        "must", "must_covered", "warnings"],
         "properties": {k: {"type": "integer"} for k in ["sections", "chapters", "words", "chars", "figures", "tables",
                                                         "requirements", "must", "must_covered", "warnings"]}}
TRACE = {"type": "array", "items": {"type": "object", "required": ["req", "priority", "sections", "covered"],
                                    "properties": {"req": {"type": "string"}, "priority": {"enum": ["must", "should"]},
                                                   "sections": {"type": "array", "items": {"type": "string"}},
                                                   "covered": {"type": "boolean"}}}}
CHECK = {"type": "object", "required": ["line", "src", "kind", "verdict"],
         "properties": {"line": {"type": "integer"}, "src": {"type": "string"}, "kind": {"type": "string"},
                        "verdict": {"enum": ["pass", "fail", "unknown"]}, "expected": {}, "actual": {},
                        "where": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"},
                        "note": {"type": "string"}}}

BLOCKS = {"type": "array", "items": {
    "type": "object", "additionalProperties": False,
    "required": ["id", "kind", "section", "start", "end", "line_start", "line_end", "hash"],
    "properties": {"id": {"type": "string"},
                   "kind": {"enum": ["paragraph", "heading", "list", "quote", "code", "md_table", "hr", "html", "figure", "table"]},
                   "section": ID, "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 0},
                   "line_start": {"type": "integer", "minimum": 0}, "line_end": {"type": "integer", "minimum": 0},
                   "hash": SHA, "figure": ID, "table": ID, "auto": {"const": True}}}}

EXPECT_DESC = (
    "expect：期望清单，一行一条（可省略，省略时只做内置核对）。标题含空格时加引号，也可写 id:节id。"
    "has 标题 [level=N]；order 标题A 标题B …（按此顺序出现）；length 标题|total min=N max=N [unit=words|chars]"
    "（篇幅含子节，words 为字数）；contains 标题|total 短语；figures min=N；tables min=N；pages max=N（页数要排版后才知道，恒为 unknown）；"
    "covered [要求id …]（必须项或所列要求都有章节响应）。"
    "内置核对总会进行：引用都能解析、图表都已放置、没有空节、没有“待补”“TODO”之类占位、标题没有手写编号、图片都能显示、必须项都有章节响应。"
)

units = [
    {
        "tool_id": "doc.build",
        "trust_claim": "T1",
        "effect": "none",
        "executor": EXECUTOR,
        "cost": {"latency": 600, "price": 0, "timeout": 60000},
        "input_example": {"doc": {
            "title": "社区读书角运营方案",
            "meta": {"org": "城东街道", "date": "2026-10-03"},
            "requirements": [{"id": "r1", "text": "给出预算明细", "source": "街道任务书 第 2 条"}],
            "sections": [
                {"id": "bg", "heading": "背景", "body": "居民希望有安静的阅读空间，预算见[[sec:budget]]。"},
                {"id": "budget", "heading": "预算", "body": "一次性投入约 5000 元，明细见[[tab:t1]]。\n\n[[tab:t1]]",
                 "responds_to": ["r1"]}],
            "tables": [{"id": "t1", "caption": "预算明细", "columns": ["项目", "金额（元）"],
                        "rows": [["书架与桌椅", "1,200"], ["首批图书", "3,800"]]}]}},
        "signature": {
            "input_schema": {
                "type": "object", "additionalProperties": False,
                "if": BUILD_IF, "then": BUILD_THEN, "else": BUILD_ELSE,
                "description": "要交付一份长文档时用。你把文档写进 doc：标题、各节正文、图表、要响应的要求；任务只给了题目时，内容由你按题目写。"
                               "本工具统一给章节、图、表编号，生成目录，把交叉引用换成可跳转的“第 2.1 节”“图 3”，列出每条要求由哪些章节响应；"
                               "交付 Word 文件（带目录与页码）、Markdown 原文，以及产出台可看、可按节定位的版本。",
                "properties": {
                    "base": BASE_SLOT,
                    "doc": DOC_BUILD,
                    "name": NAME,
                    "formats": {"type": "array", "uniqueItems": True, "items": {"enum": ["docx", "html"]},
                                "description": "除文档模型、产出台数据与 Markdown 之外，再交哪些文件：docx（Word，缺省）、html（单个网页文件，可打印）。"},
                }},
            "output_schema": {
                "type": "object", "additionalProperties": False,
                "required": ["title", "kind", "doc_sha256", "name", "outline", "stats", "trace", "warnings", "blocks", "files"],
                "properties": {"title": {"type": "string"}, "kind": {"enum": ["document", "outline"]}, "doc_sha256": SHA,
                               "name": {"type": "string"}, "outline": OUTLINE, "stats": STATS, "trace": TRACE,
                               "warnings": WARN, "blocks": BLOCKS, "files": {"type": "array", "items": FILE_ITEM}}},
        },
        "capability": {
            "ops": ["generate"], "in_types": ["doc_plan"], "out_types": ["document", "outline"],
            "constraints": {
                "max_sections": 2000, "max_section_chars": 200000, "max_total_chars": 3000000, "max_figures": 300,
                "max_tables": 500, "max_heading_level": 4, "deterministic_files": True, "page_size": "A4",
                "latency_note": "一份二三十页的方案约 0.3 s；十几万字的长文约 1 s（含 Word）",
            },
            "examples": [
                {"input": "写一份老旧小区加装电梯的可行性报告，约 3000 字（只有题目）",
                 "output": "你按题目写好各节正文填进 doc → Word 与 Markdown，带目录、章节编号"},
                {"input": "按招标文件的要求写投标文件的技术部分，章节按“第一章 / 1.1”编号，附要求响应对照表",
                 "output": "你写好九节内容、填上要求清单，numbering=chapter、trace_table=true → Word 6 页；5 条必须项均有章节响应"},
                {"input": "先列个提纲给我看看", "output": "你写各节标题和要点，kind=outline → 提纲文档"},
                {"input": "把这份季度报告排成带目录的 Word，图表自动编号",
                 "output": "你把报告内容填进 doc → doc.json + .md + .docx；图 1–3、表 1–2，正文里的引用换成可点击的编号"},
            ],
            "non_goals": ["不替你写内容：正文、标题、图表都由调用方给出，工具只组装、编号、排版与追溯",
                          "不判断内容是否满足要求，只列出声明的响应关系",
                          "不出 PDF：PDF 在下载时由导出生成",
                          "不从别处取图：图要随内容一起给出（矢量图或 PNG、JPEG），文档里只有文字、图片和表格",
                          "不做脚注、尾注、参考文献格式与公式排版"],
        },
    },
    {
        "tool_id": "doc.check",
        "trust_claim": "T1",
        "effect": "none",
        "executor": EXECUTOR,
        "cost": {"latency": 200, "price": 0, "timeout": 60000},
        "input_example": {"doc": {"title": "社区读书角运营方案",
                                  "requirements": [{"id": "r1", "text": "给出预算明细"}],
                                  "sections": [{"heading": "背景", "body": "居民希望有安静的阅读空间。"},
                                               {"heading": "预算", "body": "待补", "responds_to": ["r1"]}]},
                          "expect": "has 预算\norder 背景 预算\nlength total min=200\ncovered"},
        "signature": {
            "input_schema": {
                "type": "object", "required": ["doc"], "additionalProperties": False,
                "description": "核对长文档是否达到交付要求：每条要求是否都有章节响应，必需的章节是否齐全、顺序是否正确，篇幅是否在限度内，"
                               "有没有空节、“待补”之类的占位和失效的图表引用。每条给出 pass / fail / unknown 与原因，并给总判定。",
                "properties": {"doc": DOC, "expect": {"type": "string", "maxLength": 20000, "description": EXPECT_DESC}}},
            "output_schema": {
                "type": "object", "additionalProperties": False,
                "required": ["verdict", "covered", "checks", "doc_sha256"],
                "properties": {"verdict": {"enum": ["pass", "fail", "unknown"]},
                               "covered": {"type": "boolean", "description": "verdict 为 unknown 时为 false（TL-22 覆盖范围外）"},
                               "checks": {"type": "array", "items": CHECK}, "doc_sha256": SHA,
                               "assumptions": {"type": "array", "items": {"type": "string"}}}},
        },
        "capability": {
            "ops": ["check"], "in_types": ["document"], "out_types": ["verdict"],
            "constraints": {"three_valued": True, "max_expect_lines": 300,
                            "kinds": ["has", "order", "length", "contains", "figures", "tables", "pages", "covered"],
                            "word_count": "字数口径接近 Word：每个汉字或全角标点算 1，每个西文词或数字串算 1",
                            "latency_note": "约 0.1–0.3 s"},
            "examples": [
                {"input": "核对标书是否逐条响应了招标文件的实质性要求", "output": "covered → fail：r3 未响应"},
                {"input": "技术方案一章不少于 3000 字", "output": "length 技术方案 min=3000 → pass（实际 4210 字）"},
                {"input": "报告里还有没有“待补”和失效的图表引用", "output": "内置核对 placeholder、refs → 列出位置"},
                {"input": "投标文件不超过 60 页", "output": "pages max=60 → unknown（页数要排版后才知道，covered=false）"},
            ],
            "non_goals": ["不判断内容写得好不好、是否真正满足要求", "不改文档，只报告", "不统计页数"],
        },
        "review_coverage": {"by_predicate": ["document_meets_spec"]},
    },
    {
        "tool_id": "doc.export",
        "trust_claim": "T1",
        "effect": "none",
        "executor": EXECUTOR,
        "cost": {"latency": 600, "price": 0, "timeout": 60000},
        "input_example": {"doc": {"title": "社区读书角运营方案",
                                  "sections": [{"heading": "背景", "body": "居民希望有安静的阅读空间。"}]},
                          "formats": ["docx", "html"]},
        "signature": {
            "input_schema": {
                "type": "object", "additionalProperties": False,
                "oneOf": [{"required": ["doc"]}, {"required": ["object"]}],
                "description": "把长文档交成需要的文件：Word（可直接编辑，带目录、页码与可跳转的引用）、PDF（版式固定，带目录页码、书签与可点的引用，适合发送与打印）、单个网页文件、"
                               "Markdown 原文（图片另附文件），以及可以再次编辑的文档模型。",
                "properties": {"doc": DOC,
                               "object": {"type": "object",
                                          "description": "object：要导出的文档（document）；也可以直接给文档内容 doc，二选一。"},
                               "name": NAME,
                               "formats": {"type": "array", "minItems": 1, "uniqueItems": True,
                                           "items": {"enum": ["docx", "pdf", "md", "html", "json"]},
                                           "description": "docx（Word）、pdf（版式固定的 PDF）、md（Markdown 原文）、html（单个网页文件）、json（文档模型）中的一个或多个；"
                                                          "也可写单个 format。"},
                               "format": {"enum": ["docx", "pdf", "md", "html", "json"]}}},
            "output_schema": {
                "type": "object", "additionalProperties": False, "required": ["doc_sha256", "name", "warnings", "files"],
                "properties": {"doc_sha256": SHA, "name": {"type": "string"}, "warnings": WARN,
                               "files": {"type": "array", "items": FILE_ITEM}}},
        },
        "capability": {
            "ops": ["convert"], "in_types": ["document"], "out_types": ["doc_file"],
            "constraints": {"formats": ["docx", "pdf", "md", "html", "json"], "deterministic_files": True, "page_size": "A4",
                            "max_file_mb": 48, "latency_note": "约 0.1–1 s，视篇幅与图片"},
            "examples": [
                {"input": "把投标文件导出成 Word", "output": "formats [docx]"},
                {"input": "要一份能直接发出去、版式固定的 PDF", "output": "formats [pdf]"},
                {"input": "要一个能直接发给甲方、在浏览器里打开的版本", "output": "formats [html]"},
                {"input": "导出 Markdown 原文，放进知识库", "output": "formats [md] → .md 与图片文件"},
            ],
            "non_goals": ["不导出 WPS、ODT、LaTeX 格式",
                          "不读入已有的 Word 文件"],
        },
    },
]

SELECTION = {
    "doc.build": [("写一份社区读书角运营方案", ["generate"], "document", True),
                  ("按招标文件的要求编写投标文件技术部分", ["generate"], "document", True),
                  ("先给这份年度报告列个提纲", ["generate"], "outline", True),
                  ("画一个带孔的铝底座", ["generate"], "cad_model", False),
                  ("求 2^10 + 3^5 的精确值", ["compute"], "number", False),
                  ("核对标书是否逐条响应了招标要求", ["check"], "verdict", False)],
    "doc.check": [("核对标书是否逐条响应了招标文件的要求", ["check"], "verdict", True),
                  ("检查报告里有没有待补的占位和失效的图表引用", ["check"], "verdict", True),
                  ("检查技术方案一章是否不少于 3000 字", ["check"], "verdict", True),
                  ("写一份项目周报", ["generate"], "document", False),
                  ("把报告导出成 Word", ["convert"], "doc_file", False),
                  ("核对这个零件外形是不是 80×50×20", ["check"], "verdict", False, "model")],
    "doc.export": [("把投标文件导出成 Word", ["convert"], "doc_file", True),
                   ("把报告导出成能直接发出去的 PDF", ["convert"], "doc_file", True),
                   ("要一个能在浏览器里打开的报告网页版", ["convert"], "doc_file", True),
                   ("导出报告的 Markdown 原文", ["convert"], "doc_file", True),
                   ("写一份项目周报", ["generate"], "document", False),
                   ("核对报告的图表引用", ["check"], "verdict", False),
                   ("把支架导出成 STL 给 3D 打印", ["convert"], "cad_file", False)],
}
# 第五项 "model"：语义负例。动词与类型过滤会放行，要由选择模型读说明判掉（检查点 H 裁决 §3）；
# 认证 ⑥ 据此单列，不标会被当成登记过宽。tests/test_package.py 按程序过滤复核标注是否齐全。
selection_out = []
for u in units:
    for task, ops, typ, exp, *stage in SELECTION[u["tool_id"]]:
        case = {"tool_id": u["tool_id"], "task": task, "ops": ops, "required_type": typ, "expect_selected": exp}
        if stage:
            case["stage"] = stage[0]
        selection_out.append(case)
(ROOT / "selection_cases.json").write_text(json.dumps(selection_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

reg = {
    "family": "document",
    "family_version": "2.0.0",
    "lock_hash": "",
    "note": "字段严格按 kernel-spec 17 章 TL-6；族名在顶层 family，由引擎下发到各件。cost 的 latency 与 timeout 单位为毫秒，price 为每次调用的平台计价单位。"
            "选择金样（TL-12 ⑥）是认证材料，在 selection_cases.json。类型由本包的 mengos-package.json 声明、经安装器入册（TL-25）；"
            "verdict 为平台类型。文件产出按 TL-9a：结果对象顶层的 files。"
            "本包按安装包交付，仓库现行结构如需额外字段，报工具侧补入，施工方不改包内文件。",
    "units": units,
}
(ROOT / "registration.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("ok")
