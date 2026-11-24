"""r21（本地实验，立法者 2026-11-24 批）：table 的三处改动的单元验收——
① $count 的说明句各处换成批准的逐字句；② 自检类核对项（算式里含被核的那一格）未过时一律不说“把这一格改成它”，
被核的格是读出格时用批准的句子点出一起被核的格（后接作者提示）；③ 找行时目标行缺席就说没有，不再按“前三列里含这段文字”对到别的行。"""
import json
from pathlib import Path

import table_tool

ROOT = Path(__file__).resolve().parent.parent
COUNT_DESC = '这一行的数量格：{列名: 值}。值写格公式 {"$expr": "表名/行名/列名 的算式"}、回执引用 {"$ref": "<回执id>#<指针>"}，或图上照写的数。'
OLD_DESC = "这一行里取自回执的格：{列名: 回执引用，或量全由引用给出的算式}。"

FACTS = {"id": "facts", "name": "排布事实", "columns": [{"title": "项名", "type": "text"}, {"title": "取数/算式", "type": "text"},
                                                    {"title": "值", "type": "number", "required": True, "count": True}]}
TIER = ("cell 排布事实/层段数/值 = min(排布事实/层段数/值, floor((排布事实/下立柱高/值 + 排布事实/上立柱高/值) / 排布事实/层间距/值))")
TIER_HINT = ("层段数 × 层间距不超过立柱总高（下立柱高 + 上立柱高）。超过了，是层间距或层段数读错了：层间距是同一条竖向尺寸链上重复次数最多的那一段的长度，"
             "层段数是它重复的次数，两个都从数串回执的 most 里取（G3），只数一条链。")


def _facts(rows):
    return {"title": "T", "sheets": [{**FACTS, "rows": rows}]}


def _tier_rows(n, pitch, lower=6000, upper=5000):
    return [{"$id": "a1", "项名": "层段数", "值": n}, {"$id": "a2", "项名": "层间距", "值": pitch},
            {"$id": "a3", "项名": "下立柱高", "值": lower}, {"$id": "a4", "项名": "上立柱高", "值": upper}]


def check(table, expect):
    r = table_tool.run({"tool": "table.check", "payload": {"table": table, "expect": expect}})
    assert r["ok"], r
    return r["output"]


def line1(out):
    return [x for x in out["checks"] if x["line"] == 1][0]


# ---------------------------------------------------------------- ① $count 说明
def _descs(o, acc):
    if isinstance(o, dict):
        if "$count" in o and isinstance(o["$count"], dict):
            acc.append(o["$count"].get("description"))
        for v in o.values():
            _descs(v, acc)
    elif isinstance(o, list):
        for v in o:
            _descs(v, acc)
    return acc


def test_count_description_everywhere_verbatim():
    reg = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    descs = _descs(reg, [])
    assert len(descs) == 6 and all(d == COUNT_DESC for d in descs)   # 三个工具 × 单张表与 sheets 两处
    assert OLD_DESC not in (ROOT / "registration.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------- ② 自检类
def test_tier_check_passes_when_consistent():
    assert line1(check(_facts(_tier_rows(9, 1200)), TIER))["verdict"] == "pass"     # 9 段 × 1200 ≤ 11000


def test_tier_check_fails_when_inconsistent_with_read_cell_sentence():
    out = check(_facts(_tier_rows(10, 1500)), TIER + " # 提示：" + TIER_HINT)           # 10 段 × 1500 > 11000
    c = line1(out)
    assert c["verdict"] == "fail" and c.get("self") is True
    assert c["message"] == ("排布事实/层段数/值 现为 10，核对项‘" + TIER + "’不过；重新读这一格和它一起被核的格："
                            "排布事实/下立柱高/值、排布事实/上立柱高/值、排布事实/层间距/值。提示：" + TIER_HINT)
    assert "把这一格改成它" not in c["message"] and out["failed"][0] == c["message"]


def test_tier_check_not_evaluable_without_upper_upright():
    rows = [r for r in _tier_rows(9, 1200) if r["项名"] != "上立柱高"]                # 一体立柱：没有上立柱高这一行
    c = line1(check(_facts(rows), TIER))
    assert c["verdict"] == "fail" and "没有名为“上立柱高”的行" in c["message"] and "把这一格改成它" not in c["message"]


def test_self_check_on_read_cell_alone():
    rows = [{"$id": "p", "项名": "排数", "值": 14.5}]
    src = "cell 排布事实/排数/值 = floor(排布事实/排数/值)"
    c = line1(check(_facts(rows), src))
    assert c["message"] == "排布事实/排数/值 现为 14.5，核对项‘" + src + "’不过；重新读这一格"


def test_self_check_on_formula_cell_keeps_d3_sentence():
    rows = [{"$id": "a", "项名": "托盘数", "值": 100}, {"$id": "b", "项名": "列数", "值": 3},
            {"$id": "c", "项名": "排数", "值": {"$expr": "排布事实/托盘数/值 / 排布事实/列数/值"}}]
    src = "cell 排布事实/排数/值 = floor(排布事实/排数/值)"
    c = line1(check(_facts(rows), src))
    assert c["message"].endswith("这一格是算出来的，不要直接改它，重新读它用到的读出量：排布事实/托盘数/值、排布事实/列数/值")


def test_self_check_never_says_change_this_cell():
    srcs = ["cell 排布事实/x/值 = floor(排布事实/x/值)", "cell 排布事实/x/值 = min(排布事实/x/值, 排布事实/y/值)",
            "cell 排布事实/x/值 = 排布事实/x/值 + 1", "cell 排布事实/没有的行/值 = floor(排布事实/没有的行/值)"]
    fails = 0
    for rows in ([{"$id": "a", "项名": "x", "值": 2.5}, {"$id": "b", "项名": "y", "值": 1}],
                 [{"$id": "a", "项名": "x", "值": "两个"}, {"$id": "b", "项名": "y", "值": 1}],
                 [{"$id": "a", "项名": "x", "值": {"$expr": "排布事实/y/值 / 2"}}, {"$id": "b", "项名": "y", "值": 5}],
                 [{"$id": "a", "项名": "x"}, {"$id": "b", "项名": "y", "值": 1}]):
        for src in srcs:
            c = line1(check(_facts(rows), src))
            assert c.get("self") is True, (rows, src, c)
            fails += c["verdict"] == "fail"
            assert "把这一格改成它" not in c.get("message", ""), (rows, src, c["message"])
    assert fails == 15          # 16 种里只有“格公式 2.5 = min(2.5, 5)”通过
    # 不是自检类的照旧
    c = line1(check(_facts([{"$id": "a", "项名": "x", "值": 2}]), "cell 排布事实/x/值 = 3"))
    assert "self" not in c and c["message"].endswith("按规范它应等于 3，把这一格改成它")


def test_text_self_check_no_change_phrase():
    rows = [{"$id": "a", "项名": "规格", "取数/算式": "H"}]
    t = {"title": "T", "sheets": [{**FACTS, "rows": rows}]}
    src = 'text 排布事实/规格/项名 = "*{排布事实/规格/项名}*"'
    c = line1(check(t, src))
    assert c["verdict"] == "fail" and c.get("self") is True and "改成含它的写法" not in c["message"]
    assert c["message"] == "排布事实/规格/项名 现为 “规格”，核对项‘" + src + "’不过；重新读这一格"


# ---------------------------------------------------------------- ③ 目标行缺席
R20A_LIKE = [
    {"$id": "f1", "项名": "横梁净长CE", "值": 2660},
    {"$id": "f2", "项名": "托盘区二托盘平面尺寸甲", "值": 1200},
    {"$id": "f3", "项名": "托盘区二托盘平面尺寸乙", "值": 1000},
    {"$id": "f4", "项名": "托盘区二排数", "取数/算式": "托盘区二托盘数 / (列数 * 横梁层数 * 托盘区二每格每层托盘数)", "值": 8},
    {"$id": "f5", "项名": "合计巷道数", "取数/算式": "托盘区一巷道数 + 托盘区二巷道数", "值": 24},
]
PER = ("cell 排布事实/托盘区二每格每层托盘数/值 = floor(排布事实/横梁净长CE/值 / min(排布事实/托盘区二托盘平面尺寸甲/值, "
       "排布事实/托盘区二托盘平面尺寸乙/值))")


def test_absent_row_reported_absent_not_matched_to_other_row():
    # r20a 回归：“托盘区二每格每层托盘数”这一行不在，“托盘区二排数”那一行的取数/算式里含这几个字——以前对到了排数那一行
    c = line1(check(_facts(R20A_LIKE), PER))
    assert c["verdict"] == "fail"
    assert c["message"].startswith("表 排布事实 里没有名为“托盘区二每格每层托盘数”的行")
    assert "托盘区二排数" not in c["message"] and "target" not in c["cells"]
    c2 = line1(check(_facts(R20A_LIKE), "cell 排布事实/托盘区一巷道数/值 = 12"))
    assert c2["message"].startswith("表 排布事实 里没有名为“托盘区一巷道数”的行") and "合计巷道数" not in c2["message"]


def test_absent_row_in_formula_cell_not_matched_either():
    rows = R20A_LIKE + [{"$id": "f6", "项名": "x", "值": {"$expr": "排布事实/托盘区二每格每层托盘数/值 * 2"}}]
    r = table_tool.run({"tool": "table.check", "payload": {"table": _facts(rows), "expect": "cell 排布事实/x/值 = 2"}})
    out = r["output"] if r["ok"] else r["error"]
    assert "16" not in json.dumps(out, ensure_ascii=False).replace("2660", "")   # 没有拿排数 8 去算 8 × 2


def test_name_that_only_contains_the_wanted_name_is_not_the_row():
    c = line1(check(_facts([{"$id": "a", "项名": "托盘区一排数（双深）", "值": 16}]), "cell 排布事实/托盘区一排数/值 = 16"))
    assert c["verdict"] == "fail" and c["message"].startswith("表 排布事实 里没有名为“托盘区一排数”的行")
    # 逐字同名（去空白）与行 $id 照认
    assert line1(check(_facts([{"$id": "a", "项名": "托盘区一 排数", "值": 16}]), "cell 排布事实/托盘区一排数/值 = 16"))["verdict"] == "pass"
    assert line1(check(_facts([{"$id": "rows1", "项名": "别的名字", "值": 16}]), "cell 排布事实/rows1/值 = 16"))["verdict"] == "pass"
