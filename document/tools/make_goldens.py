"""写出 golden_cases.json：每条的期望值都是手算或按规则手写的，不由工具生成（认证 ③ 的金样材料）。

每条：{id, note, tool, payload, expect}
  expect 的键是输出里的路径（a.b[0].c），值是期望值；
  特殊键：error.code / error.where 期望结构化失败；
          md_contains / md_lacks 对 build 产出的 Markdown 文件做包含与不包含检查。
"""
import json
from pathlib import Path

from synth import b64png

ROOT = Path(__file__).resolve().parents[1]
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 30"><rect width="40" height="30" fill="#ddd"/></svg>'


def sec(h, lv=1, body="正文。", **kw):
    return dict(heading=h, level=lv, body=body, **kw)


def doc(*sections, **kw):
    return dict(title="T", sections=list(sections), **kw)


def fig(i):
    return {"id": i, "caption": f"图题{i}", "source": {"svg": SVG}}


CASES = [
    # ---- 编号 ----
    ("num_decimal", "decimal：1 / 1.1 / 1.2 / 2 / 2.1 / 2.1.1",
     "doc.build", {"doc": doc(sec("A"), sec("B", 2), sec("C", 2), sec("D"), sec("E", 2), sec("F", 3))},
     {"outline[0].number": "1", "outline[1].number": "1.1", "outline[2].number": "1.2", "outline[3].number": "2",
      "outline[4].number": "2.1", "outline[5].number": "2.1.1", "stats.chapters": 2, "stats.sections": 6}),
    ("num_chapter", "chapter：第一章 / 1.1 / 第二章，章标题用全角空格",
     "doc.build", {"doc": doc(sec("总则"), sec("范围", 2), sec("方案"), meta={"numbering": "chapter"})},
     {"outline[0].number": "第一章", "outline[1].number": "1.1", "outline[2].number": "第二章",
      "md_contains": ["## 第一章　总则", "### 1.1 范围", "## 第二章　方案"]}),
    ("num_zh", "zh：一、/（一）/ 1．/（1）/ 二、/（一）（下级在上级变化时重新计数）",
     "doc.build", {"doc": doc(sec("A"), sec("B", 2), sec("C", 3), sec("D", 4), sec("E"), sec("F", 2), meta={"numbering": "zh"})},
     {"outline[0].number": "一、", "outline[1].number": "（一）", "outline[2].number": "1．", "outline[3].number": "（1）",
      "outline[4].number": "二、", "outline[5].number": "（一）", "md_contains": ["## 一、A", "### （一）B"]}),
    ("num_none", "none：不编号",
     "doc.build", {"doc": doc(sec("背景"), sec("预算"), meta={"numbering": "none"})},
     {"outline[0].number": "", "md_contains": ["## 背景", "## 预算"]}),
    ("num_zh_eleven", "第十一章、十一、：中文数字",
     "doc.build", {"doc": doc(*[sec(f"S{i}") for i in range(1, 13)], meta={"numbering": "chapter"})},
     {"outline[9].number": "第十章", "outline[10].number": "第十一章", "outline[11].number": "第十二章"}),
    # ---- 兼容旧契约 ----
    ("compat_old", "旧契约 {title, sections:[{heading, body}]}：缺省 level 1、id s1…，标题前加编号",
     "doc.build", {"doc": {"title": "读书角方案", "sections": [{"heading": "背景", "body": "社区需要。"},
                                                           {"heading": "预算", "body": "五千元。"}]}},
     {"outline[0].id": "s1", "outline[1].id": "s2", "outline[1].level": 1, "name": "读书角方案",
      "md_contains": ["# 读书角方案", "## 1 背景", "社区需要。", "## 2 预算", '<a id="sec-s2"></a>'],
      "warnings": []}),
    # ---- 引用与放置 ----
    ("ref_sec", "[[sec:b]] → 第 1.1 节，并链接到 #sec-b",
     "doc.build", {"doc": doc(sec("A", body="见[[sec:b]]。", id="a"), sec("B", 2, id="b"))},
     {"md_contains": ["见[第 1.1 节](#sec-b)。"], "warnings": []}),
    ("fig_order", "图按放置顺序编号，不按声明顺序：先放 f1 → 图 1，后放 f2 → 图 2",
     "doc.build", {"doc": doc(sec("A", body="[[fig:f1]]\n\n见[[fig:f2]]与[[fig:f1]]。\n\n[[fig:f2]]"),
                             figures=[fig("f2"), fig("f1")])},
     {"stats.figures": 2, "md_contains": ["见[图 2](#fig-f2)与[图 1](#fig-f1)。", "*图 1　图题f1*", "*图 2　图题f2*"]}),
    ("fig_chapter", "figure_numbering=chapter：第 2 章的第 1 张图为 图 2-1",
     "doc.build", {"doc": doc(sec("A"), sec("B", body="[[fig:f1]]"), figures=[fig("f1")],
                             meta={"figure_numbering": "chapter"})},
     {"md_contains": ["*图 2-1　图题f1*"]}),
    ("code_literal", "代码块与行内代码里的记号不解析，也不算放置",
     "doc.build", {"doc": doc(sec("A", body="行内 `[[sec:zz]]`。\n\n```\n[[fig:f1]]\n[[sec:zz]]\n```\n\n[[fig:f1]]"),
                             figures=[fig("f1")])},
     {"md_contains": ["行内 `[[sec:zz]]`。", "```\n[[fig:f1]]\n[[sec:zz]]\n```"], "stats.figures": 1, "warnings": []}),
    ("ref_unknown", "引用不存在的节：显眼标记 + 提醒；核对 refs 为 fail",
     "doc.check", {"doc": doc(sec("A", body="见[[sec:nope]]。"))},
     {"verdict": "fail", "checks[0].kind": "refs", "checks[0].verdict": "fail", "checks[0].actual": 1}),
    ("auto_place", "只被引用、没有放置的图：放在第一次引用它的节末尾；从未出现的图：orphan",
     "doc.check", {"doc": doc(sec("A", body="见[[fig:f1]]。"), figures=[fig("f1"), fig("f2")])},
     {"checks[1].kind": "placement", "checks[1].verdict": "fail", "checks[1].actual": 1, "verdict": "fail"}),
    ("double_place", "同一张图放两次：只用第一次，第二次报提醒",
     "doc.check", {"doc": doc(sec("A", body="[[fig:f1]]"), sec("B", body="[[fig:f1]]"), figures=[fig("f1")])},
     {"checks[1].verdict": "fail", "checks[1].actual": 1}),
    # ---- 字数 ----
    ("words_cjk", "“五千元。”：4 个全角字符 → 字数 4、字符数 4",
     "doc.build", {"doc": doc(sec("A", body="五千元。"))},
     {"outline[0].words": 4, "stats.chars": 4}),
    ("words_mixed", "“共 186 台”：共、台各 1，186 算 1 → 字数 3；字符数 5",
     "doc.build", {"doc": doc(sec("A", body="共 186 台"))},
     {"outline[0].words": 3, "stats.chars": 5}),
    ("words_latin", "“Hello world 2026”：3 个词；字符数 14",
     "doc.build", {"doc": doc(sec("A", body="Hello world 2026"), meta={"lang": "en"})},
     {"outline[0].words": 3, "stats.chars": 14}),
    ("words_total", "words_total 含子节：父 4 + 子 2 = 6",
     "doc.build", {"doc": doc(sec("A", body="一二三四"), sec("B", 2, body="五六"), sec("C", body="七"))},
     {"outline[0].words": 4, "outline[0].words_total": 6, "outline[2].words_total": 1}),
    # ---- 结构核对 ----
    ("empty_leaf", "叶子节没有正文 → empty fail；有子节的父节没有正文不算空",
     "doc.check", {"doc": doc(sec("A", body=""), sec("B", 2, body="有"), sec("C", body=""))},
     {"checks[2].kind": "empty", "checks[2].verdict": "fail", "checks[2].actual": 1}),
    ("outline_kind", "kind=outline：允许空节，不做空节与占位核对",
     "doc.check", {"doc": dict(doc(sec("A", body=""), sec("B", body="待补")), kind="outline")},
     {"verdict": "pass", "checks[2].kind": "numbering"}),
    ("placeholder", "正文里的“待补”“TODO” → placeholder fail，两处",
     "doc.check", {"doc": doc(sec("A", body="预算待补。"), sec("B", body="TODO: 写进度"))},
     {"checks[3].kind": "placeholder", "checks[3].verdict": "fail", "checks[3].actual": 2}),
    ("heading_numbered", "标题自带“1.1 ”而又自动编号 → numbering fail；numbering=none 时不报",
     "doc.check", {"doc": doc(sec("1.1 预算"), sec("第二章 方案"), sec("2024 年回顾"))},
     {"checks[4].kind": "numbering", "checks[4].actual": 2}),
    # ---- 要求追溯 ----
    ("trace", "必须项 r1 有非空节响应；r2 声明了但该节空 → 未响应；should 项未响应只记 note",
     "doc.check", {"doc": doc(sec("A", body="有", responds_to=["r1"]), sec("B", body="", responds_to=["r2"]),
                             requirements=[{"id": "r1", "text": "x"}, {"id": "r2", "text": "y"},
                                           {"id": "r3", "text": "z", "priority": "should"}])},
     {"checks[6].kind": "requirements", "checks[6].verdict": "fail", "checks[6].actual": "1/2 有响应",
      "checks[6].note": "建议项未响应：r3"}),
    # ---- 期望清单 ----
    ("expect_lines", "has / order / length / contains / figures / tables / covered 逐条手判",
     "doc.check", {"doc": doc(sec("背景", body="一二三四五"), sec("方案", body="六七八 [[fig:f1]]", responds_to=["r1"]),
                             figures=[fig("f1")], requirements=[{"id": "r1", "text": "x"}]),
                   "expect": "has 背景\nhas 方案 level=2\norder 方案 背景\nlength 背景 min=5 max=5\nlength total max=8\n"
                             "contains 方案 六七\ncontains total 九\nfigures min=1\ntables min=1\ncovered\ncovered r9"},
     {"checks[7].verdict": "pass", "checks[8].verdict": "fail", "checks[9].verdict": "fail",
      "checks[10].verdict": "pass", "checks[10].actual": 5, "checks[11].verdict": "fail",
      "checks[12].verdict": "pass", "checks[13].verdict": "fail", "checks[14].verdict": "pass",
      "checks[15].verdict": "fail", "checks[16].verdict": "pass", "checks[17].verdict": "fail", "verdict": "fail"}),
    ("expect_pages", "pages 恒为 unknown，covered=false",
     "doc.check", {"doc": doc(sec("A")), "expect": "pages max=60"},
     {"verdict": "unknown", "covered": False, "checks[6].verdict": "unknown"}),
    ("expect_bad", "期望清单写错：按行号报错",
     "doc.check", {"doc": doc(sec("A")), "expect": "has A\nwordcount A min=3"},
     {"error.code": "BAD_INPUT", "error.line": 2}),
    # ---- 表格 ----
    ("table_align", "数字列（含千分位、百分号、数值）自动右对齐，文字列左对齐",
     "doc.build", {"doc": doc(sec("A", body="[[tab:t]]"),
                             tables=[{"id": "t", "caption": "表题", "columns": ["项", "金额", "占比"],
                                      "rows": [["书架", "1,200", "24%"], ["图书", 3800, "76%"]]}])},
     {"md_contains": ["|:--|--:|--:|", "| 图书 | 3800 | 76% |", "**表 1　表题**"]}),
    # ---- 英文 ----
    ("lang_en", "英文：Section 2 / Figure 1. caption",
     "doc.build", {"doc": doc(sec("A", body="See [[sec:b]] and [[fig:f1]].\n\n[[fig:f1]]"), sec("B", id="b"),
                             figures=[fig("f1")], meta={"lang": "en"})},
     {"md_contains": ["See [Section 2](#sec-b) and [Figure 1](#fig-f1).", "*Figure 1. 图题f1*"]}),
    ("trace_table", "trace_table=true：文末附要求响应对照表",
     "doc.build", {"doc": doc(sec("A", body="有", responds_to=["r1"]), requirements=[{"id": "r1", "text": "要求一", "source": "第 2 条"}],
                             meta={"trace_table": True})},
     {"md_contains": ["## 附：要求响应对照表", "| r1 | 要求一 | 第 2 条 | 必须 | 1 A | 已响应 |"]}),
    # ---- 拒收 ----
    ("err_level_jump", "level 跳级拒收",
     "doc.build", {"doc": doc(sec("A"), sec("B", 3))}, {"error.code": "BAD_INPUT", "error.where": "doc.sections[1].level"}),
    ("err_first_level", "第一节不是 level 1 拒收",
     "doc.build", {"doc": doc(sec("A", 2))}, {"error.code": "BAD_INPUT", "error.where": "doc.sections[0].level"}),
    ("err_dup_id", "节 id 重复拒收",
     "doc.build", {"doc": doc(sec("A", id="x"), sec("B", id="x"))}, {"error.code": "BAD_INPUT", "error.where": "doc.sections[1].id"}),
    ("err_default_id_clash", "缺省 id 与显式 id 冲突拒收",
     "doc.build", {"doc": doc(sec("A", id="s2"), sec("B"))}, {"error.code": "BAD_INPUT", "error.where": "doc.sections[1].id"}),
    ("err_row_cells", "表格行的格数与列数不符拒收",
     "doc.build", {"doc": doc(sec("A"), tables=[{"id": "t", "caption": "c", "columns": ["a", "b"], "rows": [["1"]]}])},
     {"error.code": "BAD_INPUT", "error.where": "doc.tables[0].rows[0]"}),
    ("err_svg_script", "SVG 带脚本拒收",
     "doc.build", {"doc": doc(sec("A"), figures=[{"id": "f", "caption": "c", "source": {
         "svg": '<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>'}}])},
     {"error.code": "BAD_INPUT", "error.where": "doc.figures[0].source.svg"}),
    ("err_fig_chapter_none", "figure_numbering=chapter 与 numbering=none 冲突拒收",
     "doc.build", {"doc": doc(sec("A"), meta={"numbering": "none", "figure_numbering": "chapter"})},
     {"error.code": "BAD_INPUT", "error.where": "doc.meta.figure_numbering"}),
    ("err_old_no_title", "旧契约同样拒收：缺 title",
     "doc.build", {"doc": {"sections": [{"heading": "a", "body": "b"}]}}, {"error.code": "BAD_INPUT", "error.where": "doc.title"}),
    ("err_old_empty_heading", "旧契约同样拒收：空标题",
     "doc.build", {"doc": {"title": "t", "sections": [{"heading": "", "body": "b"}]}},
     {"error.code": "BAD_INPUT", "error.where": "doc.sections[0].heading"}),
    ("fig_bitmap_structure", "位图（2.1.0 嵌入副本）：3 节 3 张 PNG，第一节放 2 张；图 1–3 按放置顺序，Word 3 个图形、图题样式 3 条、网页 3 个 <figure>；只比结构",
     "doc.build", {"doc": {"title": "图文", "sections": [
         {"id": "a", "heading": "现场", "body": "[[fig:p1]]\n\n[[fig:p2]]"},
         {"id": "b", "heading": "签到", "body": "见[[fig:p3]]。\n\n[[fig:p3]]"},
         {"id": "c", "heading": "小结", "body": "无图。"}],
         "figures": [{"id": i, "caption": f"图题{i}", "source": {"media_type": "image/png", "base64": b64png(40, 30, k)}}
                     for k, i in enumerate(["p1", "p2", "p3"], 1)]},
         "formats": ["docx", "html"]},
     {"stats.figures": 3, "docx_drawings": 3, "docx_captions": ["图 1　图题p1", "图 2　图题p2", "图 3　图题p3"],
      "html_figures": 3, "md_contains": ["*图 1　图题p1*", "*图 2　图题p2*", "*图 3　图题p3*", "![图 3　图题p3](", '<a id="sec-b"></a>'],
      "md_figure_files": 3}),
    ("err_name", "文件名带路径拒收",
     "doc.export", {"doc": doc(sec("A")), "name": "../x", "formats": ["md"]}, {"error.code": "BAD_INPUT", "error.where": "name"}),
]

NOTES = {   # 2.0.0 补 id 后，这两条的说明随之改写（期望值不变）
    "compat_old": "无 level 的简写 {title, sections:[{id, heading, body}]}：缺省 level 1，标题前加编号",
    "err_default_id_clash": "两节 id 相同拒收（缺省 id 与显式 id 冲突的行为见 tests/test_legacy_default_ids.py）",
}


def fill_ids(payload):
    """2.0.0：doc.build 的节 id 恒必填。缺 id 的节补上工具原来会缺省出的 id（s<序号>），输出与期望值都不变。"""
    for i, s in enumerate(payload.get("doc", {}).get("sections", []), 1):
        s.setdefault("id", f"s{i}")
    return payload


out = [{"id": i, "note": NOTES.get(i, n), "tool": t, "payload": fill_ids(p) if t == "doc.build" else p, "expect": e}
       for i, n, t, p, e in CASES]
(ROOT / "golden_cases.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(len(out), "cases")
