"""安装包清单自检（WP-W6 §2；TL-22a 认证核对的包侧部分）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
REG = json.loads((ROOT / M["tools"]).read_text(encoding="utf-8"))
TYPES = {t["name"]: t for t in M["types"]}
CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))


def test_only_value_types():
    for t in M["types"]:
        assert t["kind"] == "value" and "realizes" not in t and "renderer" not in t


def test_tool_types_are_declared():
    known = set(TYPES) | set(M["uses_platform_types"])
    for u in REG["units"]:
        for k in ("in_types", "out_types"):
            assert set(u["capability"][k]) <= known, (u["tool_id"], k)


def test_entry_is_package_relative():
    pr = M["runtime"]["process"]
    assert (ROOT / pr["entry"]).is_file() and pr["network"] == "none"
    for u in REG["units"]:
        assert u["executor"] == {"kind": "process", "entry": pr["entry"], "mode": "sync"}


def test_lock_coverage_matches_lock_script():
    sys.path.insert(0, str(ROOT))
    import lock
    assert M["tools_lock"]["covers"] == lock.SOURCES + ["registration.json"]


def test_assumptions_declared_and_covered_by_goldens():
    """TL-22a：输出 schema 声明了 assumptions 的工具，金样必须含非证明级用例并带出假设。"""
    for u in REG["units"]:
        if "assumptions" in u["signature"]["output_schema"]["properties"]:
            hits = [c for c in CASES if c["tool"] == u["tool_id"] and c.get("expect", {}).get("assumptions")]
            assert hits, u["tool_id"]


def test_replacement_map_targets_exist():
    ids = {u["tool_id"] for u in REG["units"]}
    assert set(M["replaces"]["tool_ids"].values()) <= ids


def test_content_hash_is_current():
    sys.path.insert(0, str(ROOT / "tools"))
    from make_package import content_hash
    assert M["content_hash"] == content_hash(), "改动后要依次运行 lock.py 与 tools/make_package.py"


TL6 = {"tool_id", "version", "signature", "input_example", "executor", "effect", "cost", "capability",
       "review_coverage", "trust_claim"}


def test_units_use_exactly_tl6_fields():
    for u in REG["units"]:
        assert set(u) <= TL6, (u["tool_id"], set(u) - TL6)
        c = u["cost"]
        assert all(isinstance(c[k], (int, float)) for k in ("latency", "price", "timeout")), u["tool_id"]
    assert REG["family"] == M["package"]


def test_selection_cases_three_to_five_each_side():
    sel = json.loads((ROOT / M["certification_material"]["selection_cases"]).read_text(encoding="utf-8"))
    for u in REG["units"]:
        mine = [s for s in sel if s["tool_id"] == u["tool_id"]]
        pos = [s for s in mine if s["expect_selected"]]
        neg = [s for s in mine if not s["expect_selected"]]
        assert 3 <= len(pos) <= 5 and 3 <= len(neg) <= 5, u["tool_id"]
        for s in pos:
            assert set(s["ops"]) & set(u["capability"]["ops"]) and s["required_type"] in u["capability"]["out_types"]


IMPL_WORDS = ["OCCT", "OpenCASCADE", "B-rep", "build123d", "ezdxf", "sympy", "mpmath", "FreeCAD", "Python", "subprocess"]


def test_model_facing_text_states_goals_not_implementation():
    """检查点 F 裁决 §4：给模型看的文字只写目标与用途，不写实现。"""
    def texts(u):
        sch = u["signature"]["input_schema"]
        yield sch.get("description", "")
        for p in sch.get("properties", {}).values():
            yield p.get("description", "")
        cap = u["capability"]
        for e in cap.get("examples", []):
            yield e.get("input", "") + " " + e.get("output", "")
        yield from cap.get("non_goals", [])
        yield from (str(v) for v in cap.get("constraints", {}).values())
    for u in REG["units"]:
        for t in texts(u):
            hit = [w for w in IMPL_WORDS if w.lower() in t.lower()]
            assert not hit, (u["tool_id"], hit, t[:80])


def test_content_hash_skips_env_and_os_files(tmp_path, monkeypatch):
    """content_hash 的文件口径与安装器一致：运行环境、缓存、系统杂项不计入（WP-W6 §2）。"""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import make_package
    for rel in ["keep.txt", "sub/keep.py", ".DS_Store", "sub/.DS_Store", "__MACOSX/x", ".venv/bin/python",
                "__pycache__/a.pyc", "sub/b.pyc", ".pytest_cache/v"]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    monkeypatch.setattr(make_package, "ROOT", tmp_path)
    assert [r.as_posix() for r in make_package.files()] == ["keep.txt", "sub/keep.py"]


def test_model_facing_text_names_no_tool():
    """说明只写自己（工具开发者指南草案 §5.4）：给模型看的文字里不出现工具名。"""
    import re
    for u in REG["units"]:
        sch = u["signature"]["input_schema"]
        texts = [sch.get("description", "")] + [p.get("description", "") for p in sch.get("properties", {}).values()]
        for t in texts:
            assert not re.search(r"\b(calc|mathdisc|doc|cad|probe)\.[a-z_]+", t), (u["tool_id"], t[:80])
