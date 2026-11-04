"""安装包清单自检（WP-W6 §2、§10 的包侧部分）。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
REG = json.loads((ROOT / M["tools"]).read_text(encoding="utf-8"))
TYPES = {t["name"]: t for t in M["types"]}


def _resolve(name, key):
    t = TYPES.get(name)
    while t is not None:
        if key in t:
            return t[key]
        t = TYPES.get(t["parent"])
    return None


def test_types_are_well_formed():
    for t in M["types"]:
        assert t["kind"] in ("deliverable", "value")
        assert t["parent"] is None or t["parent"] in TYPES, t
        if t["kind"] == "deliverable":
            assert _resolve(t["name"], "realizes"), t["name"]
            r = _resolve(t["name"], "renderer")
            assert r and r.get("full") and r.get("embed"), t["name"]
            assert (ROOT / r["full"]).is_file()
        else:
            assert "realizes" not in t and "renderer" not in t, t["name"]


def test_tool_types_are_declared():
    known = set(TYPES) | set(M.get("uses_platform_types", []))
    for u in REG["units"]:
        for k in ("in_types", "out_types"):
            assert set(u["capability"][k]) <= known, (u["tool_id"], k)
    build = next(u for u in REG["units"] if u["tool_id"] == "cad.build")
    assert build["capability"]["out_types"] == ["cad_part"]           # 只做零件：登记在真正支持的类型上（TL-16）


def test_runtime_and_scope():
    pr = M["runtime"]["process"]
    assert M["scope"] == "public" and M["publisher"] == "mengos"
    assert pr["network"] == "none"
    for k in ("project", "lock", "entry"):
        assert (ROOT / pr[k]).is_file()
    assert all(u["executor"]["kind"] == "process" for u in REG["units"])


def test_entry_is_package_relative():
    pr = M["runtime"]["process"]
    for u in REG["units"]:
        assert u["executor"] == {"kind": "process", "entry": pr["entry"], "mode": "sync"}


def test_lock_coverage_matches_lock_script():
    import sys
    sys.path.insert(0, str(ROOT))
    import lock
    assert M["tools_lock"]["covers"] == lock.SOURCES + ["registration.json"]
    assert not any(c.startswith("renderer") for c in M["tools_lock"]["covers"])


def test_content_hash_is_current():
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from make_package import content_hash
    assert M["content_hash"] == content_hash(), "改动后要依次运行 lock.py 与 tools/make_package.py"


TL6 = {"tool_id", "version", "signature", "input_example", "executor", "effect", "cost", "capability",
       "review_coverage", "trust_claim"}


def _ancestors(name):
    out = []
    while name:
        out.append(name)
        name = TYPES[name]["parent"] if name in TYPES else None
    return out


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
        for s in pos:   # 程序过滤：动词有交集，产物类型沿上位链兼容（TL-19）
            assert set(s["ops"]) & set(u["capability"]["ops"])
            assert any(s["required_type"] in _ancestors(t) for t in u["capability"]["out_types"]), s


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
