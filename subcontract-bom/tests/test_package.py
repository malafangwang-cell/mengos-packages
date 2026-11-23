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


def test_norms_unchanged_from_0_4_3():
    """本版不改条文（G 条改句 W5 待定稿后另行落）；条文 sha256 与 0.4.3 相同。"""
    h = hashlib.sha256(("\n".join(M["norms"]) + "\n").encode()).hexdigest()
    assert h == "0c88f5768fba916960127e9cfe96a30bade3ee811f3f2410c1756dc30cd752d0"
    assert M["for"] == ["table"]


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
