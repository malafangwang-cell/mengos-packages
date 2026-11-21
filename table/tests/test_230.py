"""2.3.0 的包内核对（mengosv2 局部追问设计 r10 §3.2、§四、§十 P-1）。只加产出台数据的输出字段，入参不动。
  · 入参契约：三件工具的 input_schema 与 2.2.0 逐键相同（不收新字段，不补 id，不保留前缀，不加报错）；
  · 视图：表 id、行 id（没写的为 null）、入参行序号（分组挪过行时）、单元种类、每格依赖、派生行（row_kind derived、来源键）、
    生成行的键（与 layout 对齐）。宿主与渲染器只读这些，不解析公式；没写 id 的表、行按“#序号”定位。
  · 旧输入的表模型、Markdown、CSV 逐字节不变（test_contribution 的整表金样照旧，产出台数据只多上述字段）。"""
import json
import subprocess
from pathlib import Path

from test_220 import G, files, run

ROOT = Path(__file__).resolve().parents[1]


def build(tmp_path, table, name="b"):
    r, w = run("table.build", {"table": table}, tmp_path, name)
    assert r["ok"], r
    return r["output"], json.loads(files(r, w)["view"])


BOM = {"title": "物料", "columns": [{"key": "name", "title": "名称"}, {"key": "qty", "title": "数量", "type": "integer"},
                                   {"key": "price", "title": "单价", "type": "money"},
                                   {"key": "amt", "title": "金额", "type": "money", "formula": "数量 * 单价"}],
       "rows": [["输入轴", 1, 860], ["齿轮", 2, 1250.5], ["轴承", 4, 95]], "totals": ["金额"]}


# ───────────────────────── 入参契约与 2.2.0 逐键相同 ─────────────────────────
REF_ADD_233 = ["格里的值取自某张回执时，写 {\"$ref\": \"回执id#路径\"} 代替它：回执id 照输入材料里那张回执的 id 原样写；路径从回执顶层起照键名逐层写，每层前面写一个 /，所以路径以 / 开头；数组写序号（从 0 起）。"]


def _strip_232(schema):
    """2.3.2、2.3.3（mengosv2 工单 P4）只改 table 字段说明两处：编号列那句前加“序号、”（P5 B2）；加引用写法一句（P5 B1，2.3.3）。去掉这两处后与 2.2.0 逐键相同。"""
    s = json.loads(json.dumps(schema, ensure_ascii=False))
    t = s.get("properties", {}).get("table")
    if t and "description" in t:
        d = t["description"]
        for a in REF_ADD_233:
            d = d.replace(a, "")
        t["description"] = d.replace("；序号、编号列写 numbering", "；编号列写 numbering")
    return s


def test_input_schemas_equal_2_2_0_key_by_key():
    old = json.loads(subprocess.run(["git", "show", "main:table/registration.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    new = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    o = {u["tool_id"]: _strip_232(u["signature"]["input_schema"]) for u in old["units"]}
    n = {u["tool_id"]: _strip_232(u["signature"]["input_schema"]) for u in new["units"]}
    assert n == o
    assert "local_patch" not in new


def test_output_has_no_normalized_input(tmp_path):
    out, _ = build(tmp_path, BOM)
    assert "normalized" not in out


def test_no_ids_issued_and_no_reserved_prefix(tmp_path):
    _, view = build(tmp_path, BOM)
    s = view["sheets"][0]
    assert "id" not in s and "ids" not in s and "src" not in s                       # 包不补 id；没写 id 的按“#序号”定位
    _, v2 = build(tmp_path, {**BOM, "rows": [{"$id": "_rz", "名称": "a", "数量": 1, "单价": 1}]}, "p")   # _r 开头照收
    assert v2["sheets"][0]["ids"] == ["_rz"]


# ───────────────────────── 视图：单元种类、依赖、行种类与键 ─────────────────────────
def test_cell_kinds_and_dependencies(tmp_path):
    t = {**BOM, "columns": [{"key": "no", "title": "序号", "numbering": "seq"}] + BOM["columns"],
         "rows": [{"$id": "r1", "名称": "输入轴", "数量": 1, "单价": 860}, {"名称": "齿轮", "数量": {"$expr": "@r1.数量*2"}, "单价": 1250.5}]}
    _, view = build(tmp_path, t)
    s = view["sheets"][0]
    assert s["ids"] == ["r1", None]
    assert s["col_kinds"] == ["numbering", "input", "input", "input", "formula"]
    assert s["deps"]["columns"] == {"amt": ["price", "qty"]}
    assert s["deps"]["cells"] == [[1, 2, [[None, "r1", "qty"]], []]]                 # 单表写法没有表 id
    assert s["exprs"][0][:2] == [1, 2] and "totals" in s


def test_sheet_ids_are_published_when_written(tmp_path):
    t = {"title": "两表", "sheets": [{"id": "a", "name": "甲", "columns": ["x"], "rows": [[1]]}, {"id": "b", "name": "乙", "columns": ["y"], "rows": [[2]]}]}
    _, view = build(tmp_path, t)
    assert [s["id"] for s in view["sheets"]] == ["a", "b"]


def test_grouped_rows_publish_their_input_row_index(tmp_path):
    t = {"title": "分组", "columns": [{"key": "g", "title": "组"}, {"key": "v", "title": "值", "type": "integer"}],
         "rows": [["甲", 1], ["乙", 2], ["甲", 3]], "group": {"by": "g"}}
    _, view = build(tmp_path, t)
    s = view["sheets"][0]
    assert s["src"] == [0, 2, 1]                                                     # 组内保持原行序，组按首次出现
    data = [o for o in s["layout"] if o["k"] == "d"]
    assert len(data) == 3



def test_src_is_published_whenever_the_sheet_has_a_layout_even_in_input_order(tmp_path):
    """立法者 2026-11-19 第十一件：渲染器判据“行上没有 src 而表有分组或合并 ⟹ 不能选”；2.3.x 有 layout 就一律给 src，原序也给。"""
    t = {"title": "原序分组", "columns": [{"key": "g", "title": "组"}, {"key": "v", "title": "值", "type": "integer"}],
         "rows": [["甲", 1], ["甲", 3], ["乙", 2]], "group": {"by": "g"}}
    _, view = build(tmp_path, t)
    s = view["sheets"][0]
    assert "layout" in s and s["src"] == [0, 1, 2]
    t2 = {"title": "无分组", "columns": [{"key": "v", "title": "值", "type": "integer"}], "rows": [[1], [2]]}
    _, view2 = build(tmp_path, t2, "c")
    assert "layout" not in view2["sheets"][0] and "src" not in view2["sheets"][0]


def test_generated_rows_carry_kind_and_key(tmp_path):
    _, view = build(tmp_path, G["t3_07_group_subtotal"]["payload"]["table"])
    s = view["sheets"][0]
    assert len(s["layout_keys"]) == len(s["layout"])
    pairs = [(o["k"], k) for o, k in zip(s["layout"], s["layout_keys"]) if o["k"] in ("g", "s")]
    assert ("g", "宏达家具") in pairs and ("s", "宏达家具") in pairs
    assert all(k is None for o, k in zip(s["layout"], s["layout_keys"]) if o["k"] == "d")


def test_merged_rows_key_on_the_merge_key(tmp_path):
    _, view = build(tmp_path, G["t5_03_merge_formula"]["payload"]["table"])
    s = view["sheets"][0]
    ks = [k for o, k in zip(s["layout"], s["layout_keys"]) if o["k"] == "m"]
    assert ks and all(isinstance(k, list) and k for k in ks)


def test_derived_rows_are_kind_derived_keyed_by_their_source_rows(tmp_path):
    _, view = build(tmp_path, G["t6_04_derive_summary"]["payload"]["table"])
    d = next(s for s in view["sheets"] if s.get("row_kind") == "derived")
    assert "ids" not in d and len(d["derived_keys"]) == len(d["rows"])
    assert all(k and all("/" in x for x in k) for k in d["derived_keys"])
