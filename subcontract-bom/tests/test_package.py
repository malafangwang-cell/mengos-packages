"""安装包清单自检（WP-W6 §2；TL-22a、TL-25、TL-31）。"""
import hashlib
import json
import re
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
REG = json.loads((ROOT / M["tools"]).read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
UNIT = REG["units"][0]


def test_norms_0_5_0():
    """0.5.0 条文（调度 2026-11-23 定稿）：在 0.4.3 上改 R1.1、R1.6、R2.2、R3.1、R6.1、R6.6、D13、G1、G5、T9，新增 R7.0，
    G2、G3、G5、G6 末尾加 W5 句、D13 加 W5 插句；共 94 条。核对值钉住，改一字须改这里。"""
    import re
    h = hashlib.sha256(("\n".join(M["norms"]) + "\n").encode()).hexdigest()
    assert h == "ffba6a1fe4d3b9dba9b383d3bfdbf20d97451ee272827cd27b8bd9f05ac9a914"   # 0.5.3 实验版：D13 取实验员 0.5.2 全文并加 $count 两处、R7.0 换成 $count 写法（逐字稿草案，未定稿）
    assert len(M["norms"]) == 94 and M["for"] == ["table"]
    codes = [re.search(r"（([A-Z]\d+(?:\.\d+)?)）", n).group(1) for n in M["norms"]]
    assert codes.index("R7.0") + 1 == codes.index("R7.1")
    w5 = "本条算出的量由排布计算工具算出，事实表里引它的回执"
    assert [c for c, n in zip(codes, M["norms"]) if w5 in n] == ["G2", "G3", "G5", "G6"]
    assert "由排布计算工具算出；主件数量再由这些事实按 T 开头的推算规则算出" in M["norms"][codes.index("D13")]
    assert M["norms"][codes.index("D13")].count("写进这一行的 $count") == 2
    assert "总清单的数量格写进这一行的 $count" in M["norms"][codes.index("R7.0")]


def test_manifest_w6_from_text():
    import text
    assert M["tool_titles"] == {"rack.layout": text.W6_TOOL_TITLE}
    assert M["types"][0]["note"] == text.W6_TYPE_NOTE


def test_no_placeholder_text_left():
    import text
    for k, v in vars(text).items():
        if not k.startswith("W"):
            continue
        for s in (v if isinstance(v, (list, dict)) else [v]):
            assert "待定稿" not in json.dumps(s, ensure_ascii=False)


def test_only_value_types_and_declared():
    assert [t["name"] for t in M["types"]] == ["rack_layout_receipt"]
    assert all(t["kind"] == "value" for t in M["types"])
    assert set(UNIT["capability"]["out_types"]) <= {t["name"] for t in M["types"]}


def test_entry_and_executor():
    pr = M["runtime"]["process"]
    assert (ROOT / pr["entry"]).is_file() and pr["network"] == "none"
    assert UNIT["executor"] == {"kind": "process", "entry": pr["entry"], "mode": "sync"}
    assert UNIT["trust_claim"] == "T1" and UNIT["effect"] == "none" and UNIT["capability"]["ops"] == ["compute"]


def test_lock_covers_and_current():
    import lock
    assert M["tools_lock"]["covers"] == lock.SOURCES + ["registration.json"]
    v = lock.lock_hash()
    assert REG["lock_hash"] == v and UNIT["version"] == v, "改动后要依次运行 tools/make_registration.py、lock.py、tools/make_package.py"


def test_registration_matches_generator():
    import make_registration
    gen = json.loads(json.dumps(make_registration.REGISTRATION))
    gen["lock_hash"] = REG["lock_hash"]
    for u in gen["units"]:
        u["version"] = REG["lock_hash"]
    assert gen == REG


def test_content_hash_is_current():
    from make_package import content_hash
    assert M["content_hash"] == content_hash()


def test_input_is_count_position_with_safe_zone_names():
    fd = UNIT["signature"]["input_schema"]["properties"]["from_drawing"]
    assert fd["x-mengos-count"] is True
    zones = fd["properties"]["zones"]
    assert zones["propertyNames"] == {"pattern": "^[^/~#]{1,32}$"} and zones["maxProperties"] == 20
    assert UNIT["signature"]["input_schema"]["required"] == ["from_drawing"]
    for name, p in fd["properties"].items():
        if name != "zones":
            assert "type" not in p, name   # 数量位置写引用，替换前不是数


def test_only_computed_integers_are_referable():
    out = UNIT["signature"]["output_schema"]

    def marks(node, path):
        if isinstance(node, dict):
            if node.get("x-mengos-ref") is True:
                yield path
            for k, v in node.items():
                yield from marks(v, f"{path}/{k}")
    paths = list(marks(out, ""))
    assert paths and all(p.startswith("/properties/computed/") for p in paths)


def test_golden_outputs_validate_against_output_schema():
    import rack_tool
    schema = UNIT["signature"]["output_schema"]
    for c in CASES:
        r = rack_tool.run({"tool": c["tool"], "payload": c["payload"]})
        if r["ok"]:
            jsonschema.validate(r["output"], schema)


def test_golden_payloads_validate_against_input_schema_unless_shape_error():
    schema = UNIT["signature"]["input_schema"]
    v = jsonschema.Draft202012Validator(schema)
    for c in CASES:
        ok = v.is_valid(c["payload"])
        assert ok == (c["id"][0] != "S"), c["id"]


def test_goldens_cover_each_clause():
    clauses = " ".join(c["clause"] for c in CASES)
    for g in ("G2", "G3", "G5", "G6"):
        assert g in clauses


def test_selection_cases_three_to_five_each_side():
    sel = json.loads((ROOT / M["certification_material"]["selection_cases"]).read_text(encoding="utf-8"))
    pos = [s for s in sel if s["expect_selected"]]
    neg = [s for s in sel if not s["expect_selected"]]
    assert 3 <= len(pos) <= 5 and 3 <= len(neg) <= 5
    for s in pos:
        if s.get("via") == "assist":   # 配套接入并入（MF-1j 草案）：按 assist.for 判，不按本工具的 ops/out_types
            assert s["required_type"] in UNIT["assist"]["for"]
        else:
            assert set(s["ops"]) & set(UNIT["capability"]["ops"]) and s["required_type"] in UNIT["capability"]["out_types"]


def test_model_facing_text_single_source():
    """进模型的文字只从 text.py 来：layout、rack_tool、登记脚本里不写中文句子（注释与 docstring 除外）。"""
    import ast
    for f in ("layout.py", "rack_tool.py"):
        tree = ast.parse((ROOT / f).read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                assert not re.search(r"[一-鿿]", n.value), (f, n.value[:40])


def test_input_example_runs_like_certify():
    """certify（mengosv2 engine/tools/certify.ts ④）没有 determinismPayload 时取登记 input_example 原样执行、不做证件替换：
    示例必须是具体数，经进程入口执行成功、两次逐字节相同、回执合 output_schema。"""
    import subprocess
    env = json.dumps({"tool": UNIT["tool_id"], "payload": UNIT["input_example"]}, ensure_ascii=False).encode()
    outs = [subprocess.run([sys.executable, str(ROOT / M["runtime"]["process"]["entry"])], input=env, capture_output=True, cwd=str(ROOT)).stdout
            for _ in range(2)]
    assert outs[0] == outs[1]
    res = json.loads(outs[0])
    assert res["ok"] is True, res
    assert res["output"]["not_computed"] == []
    jsonschema.validate(res["output"], UNIT["signature"]["output_schema"])
    jsonschema.validate(UNIT["input_example"], UNIT["signature"]["input_schema"])


def test_assist_declaration():
    """0.5.1：配套接入声明 assist.for = ["table"]（本包规范声明的产物类型，与清单 for 相同）；不改 out_types、不挂 data_table。"""
    assert UNIT["assist"] == {"for": ["table"]}
    assert UNIT["assist"]["for"] == M["for"]
    assert UNIT["capability"]["out_types"] == ["rack_layout_receipt"]
