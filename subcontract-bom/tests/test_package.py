"""安装包清单自检（WP-W6 §2；TL-31）。r19（本地实验，功能清单 A3、A5）：rack.layout 拆掉，排布推算写成事实表里的格公式。

A3/A5 的回放用例要用到表格包（model.normalize、table.check）：按 MENGOS_TABLE_SRC 或 ../table（包仓布局，须为 table 2.6.0 及以上）找，找不到就跳过。
"""
import hashlib
import json
import re
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
CODES = [re.search(r"（([A-Z]\d+(?:\.\d+)?)）", n).group(1) for n in M["norms"]]
NORM = dict(zip(CODES, M["norms"]))
CHECKS = M["checks"][0]["expect"]
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "rack_layout_golden.json").read_text(encoding="utf-8"))

_TABLE = next((p for p in ([Path(os.environ["MENGOS_TABLE_SRC"])] if os.environ.get("MENGOS_TABLE_SRC") else []) + [ROOT.parent / "table"] if (p / "model.py").is_file()), None)
needs_table = pytest.mark.skipif(_TABLE is None, reason="没有表格包源码")
if _TABLE is not None:
    sys.path.insert(0, str(_TABLE))


def test_norms_r19():
    """r19：D13、G2、G3、G5、G6 改写（推算量写成格公式），R7.0 的数量格改写成格公式；共 94 条，条文里不再有排布计算工具与 $calc。"""
    assert len(M["norms"]) == 93 and M["for"] == ["table"]            # r22：去掉 R9.2、T0，加生成的 F1
    assert CODES.index("R7.0") + 1 == CODES.index("R7.1")
    for n in M["norms"]:
        assert "排布计算" not in n and "rack.layout" not in n and "$calc" not in n
    w = "本条算出的量在事实表里写成格公式"
    assert [c for c, n in zip(CODES, M["norms"]) if n.endswith(w)] == []     # r22：写法归表格工具，四条的尾句去掉
    d = NORM["D13"]
    assert "推算量（算式见 F1）" in d and "层段数" in d and "总长" in d and "F1" in CODES
    assert "count: true" not in d and "count: true" not in NORM["R1.1"]      # r22：包里不写表格工具的写法
    assert "$" not in "".join(M["norms"]) and "R9.2" not in CODES and "T0" not in CODES
    assert "count.series 的 chain" in NORM["G3"]                     # 读图规则一字不动
    assert "不为整数的列入问题表" in NORM["G5"]


def test_no_tools_no_types():
    assert M["tools"] == [] and M["types"] == [] and M["tools_lock"] == {"covers": []}
    assert "runtime" not in M and "tool_titles" not in M and "certification_material" not in M
    assert not (ROOT / "registration.json").exists() and not (ROOT / "rack_tool.py").exists()


def test_content_hash_is_current():
    from make_package import content_hash
    assert M["content_hash"] == content_hash()


def test_checks_r19():
    assert len(CHECKS) == 79                       # r22：83 − 10（口径待客户定的数量行不生成）+ 2（G8 读数自检）+ 4（T0 的算式进算式表）
    for row in ("列数", "横梁层数", "托盘区一每格每层托盘数", "托盘区二排数", "托盘区一双深位组数", "托盘区二巷道数", "合计排数", "合计双深位组数", "合计巷道数"):
        assert any(c.startswith(f"cell 排布事实/{row}/值 = ") for c in CHECKS), row
    assert any(c.startswith("cell 排布事实/托盘区一排数/值 = floor(排布事实/托盘区一排数/值)") for c in CHECKS)
    assert not any("rack" in c for c in CHECKS)


# r20（功能清单补一 D3）：原 rack.layout 的那句提示（W3，逐字）作为作者提示放回“各区排数是整数”两条核对项的行尾
HINT_R20 = "排数应为整数；层间距的段数只数一条竖向尺寸链上的（G3），主视图上的那条链最可靠。层段数取数串回执里层间距那个值出现的次数，它比横梁层数少 1。"   # r22g 加了后一句


def test_d3_integer_rows_hint_r20():
    for zz in ("托盘区一", "托盘区二"):
        line = f"cell 排布事实/{zz}排数/值 = floor(排布事实/{zz}排数/值) # 提示：{HINT_R20}"
        assert line in CHECKS, zz
    assert sum(1 for c in CHECKS if "# 提示：" in c) == 5          # r22：再加 G8 两条读数自检的提示


@needs_table
def test_d3_hint_shown_when_rows_not_integer():
    import model
    from checker import run_checks
    line = next(c for c in CHECKS if c.startswith("cell 排布事实/托盘区一排数/值 = floor("))
    t = model.normalize({"title": "T", "sheets": [{"id": "facts", "name": "排布事实", "columns": [{"title": "项名", "type": "text"}, {"title": "值", "type": "number"}],
                                                   "rows": [{"项名": "托盘区一托盘数", "值": 100}, {"项名": "列数", "值": 3}, {"项名": "横梁层数", "值": 11},
                                                            {"项名": "托盘区一排数", "值": {"$expr": "排布事实/托盘区一托盘数/值 / (排布事实/列数/值 * 排布事实/横梁层数/值)"}}]}]})
    res, _ = run_checks(t, line)
    c = [x for x in res if x["line"] > 0][0]
    assert c["verdict"] == "fail" and c["message"].endswith("。提示：" + HINT_R20)
    assert "重新读它用到的读出量：排布事实/托盘区一托盘数/值、排布事实/列数/值、排布事实/横梁层数/值" in c["message"]


def _row_names():
    """D13 与 R7.0 写明的项名、行名（引号里的名字）。"""
    t = json.loads((ROOT / "design" / "tables.json").read_text(encoding="utf-8"))   # r22：名字在名册里定义一次
    return set(t["facts_read"]) | set(t["facts_derived"]) | set(t["master_rows"])


def test_check_rows_are_named_in_norms():
    """按条文写出的表，核对项全部找得到行：核对项左右两边用到的每个行名，D13（事实）或 R7.0（总清单）里都写明了。"""
    names = _row_names()
    missing = set()
    for c in CHECKS:
        for sheet, row in re.findall(r"(排布事实|总清单)/([^/\s{}]+)/", c):
            if row not in names and row.replace("托盘区二", "托盘区一") not in names:   # “托盘区一……这样”：托盘区二照此类推
                missing.add(f"{sheet}/{row}")
    assert not missing, sorted(missing)


# ───────────── A3、A5 验收 3：拿 rack.layout 的金样回放 ─────────────
ZONE = {"甲": "托盘区一", "乙": "托盘区二"}


def _fact_rows(fd):
    """按条文写一张事实表：读出量填数，算出量写核对项里的那些式子（区按金样里给了的写）。"""
    zones = [z for z in ("甲", "乙") if z in fd.get("zones", {})]
    R = lambda name: f"排布事实/{name}/值"
    rows = []

    def put(name, value):
        if value is not None:
            rows.append({"项名": name, "$count": {"值": value}})
    put("总长", fd.get("run_length"))
    put("列距", fd.get("column_pitch"))
    put("层段数", fd.get("level_segments"))
    put("横梁净长CE", fd.get("beam_clear"))
    if "columns_read" in fd:
        put("列数", fd["columns_read"])
    else:
        put("列数", {"$expr": f"{R('总长')} / {R('列距')}"})
    put("每排立柱片数", {"$expr": f"{R('列数')} + 1"})
    put("横梁层数", {"$expr": f"{R('层段数')} + 1"})
    for z in zones:
        zz, p = ZONE[z], fd["zones"][z]
        put(f"{zz}托盘数", p.get("pallets"))
        put(f"{zz}托盘平面尺寸甲", p.get("pallet_plan_a"))
        put(f"{zz}托盘平面尺寸乙", p.get("pallet_plan_b"))
        put(f"{zz}每格每层托盘数", {"$expr": f"floor({R('横梁净长CE')} / min({R(zz + '托盘平面尺寸甲')}, {R(zz + '托盘平面尺寸乙')}))"})
        put(f"{zz}排数", {"$expr": f"{R(zz + '托盘数')} / ({R('列数')} * {R('横梁层数')} * {R(zz + '每格每层托盘数')})"})
        put(f"{zz}双深位组数", {"$expr": f"{R(zz + '排数')} / 2"})
        put(f"{zz}巷道数", {"$expr": f"{R(zz + '双深位组数')} / 2"})
    for tot, item in (("合计排数", "排数"), ("合计双深位组数", "双深位组数"), ("合计巷道数", "巷道数")):
        put(tot, {"$expr": " + ".join(R(ZONE[z] + item) for z in zones)} if zones else None)
    return rows


def _table(fd):
    return {"title": "排布", "sheets": [{"id": "facts", "name": "排布事实", "columns": [
        {"title": "项名", "type": "text"}, {"title": "取数/算式", "type": "text"}, {"title": "值", "type": "number", "required": True, "count": True}],
        "rows": _fact_rows(fd)}]}


def _flat_expected(computed):
    out = {}
    for k, name in (("columns", "列数"), ("frames_per_row", "每排立柱片数"), ("levels", "横梁层数")):
        if k in computed:
            out[name] = computed[k]
    for z, d in computed.get("zones", {}).items():
        for k, name in (("pallets_per_cell", "每格每层托盘数"), ("rows", "排数"), ("groups", "双深位组数"), ("aisles", "巷道数")):
            if k in d:
                out[ZONE[z] + name] = d[k]
    for k, name in (("rows", "合计排数"), ("groups", "合计双深位组数"), ("aisles", "合计巷道数")):
        if k in computed.get("total", {}):
            out[name] = computed["total"][k]
    return out


@needs_table
@pytest.mark.parametrize("case", [c for c in GOLDEN if "expect" in c and "computed" in c.get("expect", {})], ids=lambda c: c["id"])
def test_a3_formula_table_equals_rack_layout_golden(case):
    import model
    fd = case["payload"]["from_drawing"]
    if not all(isinstance(v, (int, float)) for k, v in fd.items() if k != "zones"):
        pytest.skip("数以字符串送达的用例只考工具的入参校验")
    t = model.normalize(_table(fd))
    sh = t.sheets[0]
    got = {r[0]: r[2] for r in sh.rows}
    want = _flat_expected(case["expect"]["computed"])
    assert want, case["id"]
    for name, v in want.items():
        assert got.get(name) == Decimal(v), (case["id"], name, got.get(name), v)


@needs_table
def test_a5_new_fact_checks_pass_on_golden_table():
    import model
    from checker import run_checks
    case = next(c for c in GOLDEN if c["id"] == "P0-正例")
    t = model.normalize(_table(case["payload"]["from_drawing"]))
    # r21 的层段数读数核对要层间距、立柱高，rack.layout 的金样里没有这几项（它的验收见 test_r21_*）
    fact_checks = [c for c in CHECKS if c.startswith("cell 排布事实/") and "架深" not in c and "立柱总高" not in c and "设水平交叉拉杆" not in c
                   and not c.startswith(("cell 排布事实/立柱片总数/", "cell 排布事实/托盘区一立柱片数/", "cell 排布事实/托盘区二立柱片数/"))]   # r22 新进算式表的几项不是原 rack.layout 的输出，金样里没有
    res, _ = run_checks(t, "\n".join(fact_checks))
    bad = [c for c in res if c["line"] > 0 and c["verdict"] != "pass"]
    assert not bad, bad


# ───────────── A1 验收 2：核对项清单里每一条 cell 算式写成格公式建表，再用原核对项核，全过 ─────────────
@needs_table
def test_a1_round_trip_every_cell_check():
    import model
    from checker import run_checks
    cell_checks = [c for c in CHECKS if c.startswith("cell ")]
    addr = re.compile(r"(排布事实|总清单)/([^/\s(),]+)/(值|数量)")
    done = 0
    for c in cell_checks:
        left, right = (x.strip() for x in c[5:].split("=", 1))
        if left in right:
            continue                                   # “是整数”这类自指的核对（排数 = floor(排数)）不是式子，不往返
        cells = {left} | {"/".join(m) for m in addr.findall(right)}
        sheets = {"排布事实": [], "总清单": []}
        for i, a in enumerate(sorted(cells)):
            sname, row, col = a.split("/")
            val = {"$expr": right} if a == left else 2 + i % 5   # 读到的格填非零的数
            sheets[sname].append({"名": row, col: val})
        t = {"title": "往返", "sheets": [
            {"id": "facts", "name": "排布事实", "columns": [{"title": "名", "type": "text"}, {"title": "值", "type": "number"}], "rows": sheets["排布事实"] or [{"名": "空"}]},
            {"id": "bom", "name": "总清单", "columns": [{"title": "名", "type": "text"}, {"title": "数量", "type": "number"}], "rows": sheets["总清单"] or [{"名": "空"}]}]}
        tm = model.normalize(t)
        assert not tm.expr_fail, (c, tm.expr_fail)
        res, _ = run_checks(tm, c)
        assert [x["verdict"] for x in res if x["line"] > 0] == ["pass"], (c, res)
        done += 1
    assert done == len(cell_checks) - 5           # 两条“排数是整数”、层段数读数核对、G8 两条读数自检（都自指）不往返


# ───────────── r21（立法者 2026-11-24 批）─────────────
TIER_R21 = ("cell 排布事实/层段数/值 = min(排布事实/层段数/值, floor(排布事实/立柱总高/值 / 排布事实/层间距/值)) "
            "# 提示：层段数 × 层间距不超过立柱总高（下立柱高 + 上立柱高）。超过了，是层间距或层段数读错了：层间距是同一条竖向尺寸链上重复次数最多的那一段的长度，"
            "层段数是它重复的次数，两个都从数串回执的 most 里取（G3），只数一条链。")


def test_r22_norm_texts():
    assert NORM["R6.4"] == "[约束] （R6.4）主件数量是推算量，每个因子都是一项排布事实，定值只用 T9 与 R6.6 的；立库货架的按本规范 T 开头的推算规则"
    assert "计算器" not in "".join(M["norms"]) and "不心算" not in NORM["D13"]
    f1 = NORM["F1"]
    for piece in ("列数 = 总长 ÷ 列距", "立柱片总数 = 合计排数 × 每排立柱片数", "托盘区一立柱片数 = 托盘区一排数 × 每排立柱片数", "立柱总高 = 下立柱高 + 上立柱高"):
        assert piece in f1, piece


def test_r21_tier_check_present_after_beam_levels():
    assert TIER_R21 in CHECKS
    i = CHECKS.index(TIER_R21)
    assert CHECKS[i - 1].startswith("cell 排布事实/横梁层数/值 = ")


def _tier_table(n, pitch, upper=5000):
    import model
    rows = [{"项名": "层段数", "值": n}, {"项名": "层间距", "值": pitch}, {"项名": "下立柱高", "值": 6000}]
    if upper is not None:
        rows.append({"项名": "上立柱高", "值": upper})
    rows.append({"项名": "立柱总高", "值": {"$expr": "排布事实/下立柱高/值 + 排布事实/上立柱高/值"}})   # r22：立柱总高是事实表里的算式格
    return model.normalize({"title": "T", "sheets": [{"id": "facts", "name": "排布事实", "columns": [{"title": "项名", "type": "text"}, {"title": "值", "type": "number"}], "rows": rows}]})


@needs_table
def test_r21_tier_check_r19a_passes_r20a_fails():
    from checker import run_checks
    ok = [x for x in run_checks(_tier_table(9, 1200), TIER_R21)[0] if x["line"] > 0][0]       # 9 段 × 1200 ≤ 立柱总高 11000
    assert ok["verdict"] == "pass"
    bad = [x for x in run_checks(_tier_table(10, 1500), TIER_R21)[0] if x["line"] > 0][0]     # 10 段 × 1500 > 11000
    assert bad["verdict"] == "fail" and "把这一格改成它" not in bad["message"]
    assert "重新读这一格和它一起被核的格：排布事实/立柱总高/值、排布事实/层间距/值。提示：层段数 × 层间距不超过立柱总高" in bad["message"]


@needs_table
def test_r21_tier_check_one_piece_upright_not_evaluable():
    from checker import run_checks
    c = [x for x in run_checks(_tier_table(9, 1200, upper=None), TIER_R21)[0] if x["line"] > 0][0]
    assert c["verdict"] == "fail" and "排布事实/立柱总高/值 还是空的" in c["message"]      # r22：立柱总高是算式格，缺上立柱高时它算不出
