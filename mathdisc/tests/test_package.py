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
    assert (ROOT / pr["entry"]).is_file() and pr["network"] == "dashscope.aliyuncs.com"
    for u in REG["units"]:
        if u["tool_id"] == "mathdisc.discover":  # 异步、出网、带凭据名：专项见 test_discover.py
            assert u["executor"] == {"kind": "process", "entry": pr["entry"], "mode": "async", "credential_ref": "DASHSCOPE_API_KEY",
                                     "async_ops": {"submit": "POST /api/v1/jobs", "status": "GET /api/v1/jobs/{job_id}"}}
        else:
            assert u["executor"] == {"kind": "process", "entry": pr["entry"], "mode": "sync"}


def test_manifest_requires_matches_pyproject():
    """包清单的解释器要求与 pyproject 的 requires-python 相同，不再漂移。"""
    import tomllib
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    assert M["runtime"]["process"]["requires"] == py == ">=3.12"


def test_lock_coverage_matches_lock_script():
    sys.path.insert(0, str(ROOT))
    import lock
    assert M["tools_lock"]["covers"] == lock.SOURCES + ["registration.json"]


NON_PROOF = {"mathdisc.identity", "mathdisc.formula", "mathdisc.recurrence"}


def _asserts_assumptions(c, nonempty):
    return any(e.get("path") == "assumptions" and e.get("nonempty") is nonempty for e in c.get("expect", []))


def test_assumptions_declared_and_covered_by_goldens():
    """TL-22a：输出声明 assumptions 的工具，金样核对它；会出非证明级结论的工具，金样必须带出假设。"""
    for u in REG["units"]:
        if "assumptions" not in u["signature"]["output_schema"]["properties"]:
            continue
        if u["tool_id"] == "mathdisc.discover":
            continue  # 回执形状不同（T-A 投影），假设逐条在场由 test_discover.py 的回放金样核对
        mine = [c for c in CASES if c["tool"] == u["tool_id"]]
        if u["tool_id"] in NON_PROOF:
            assert any(_asserts_assumptions(c, True) for c in mine), u["tool_id"]
        else:
            assert any(_asserts_assumptions(c, False) for c in mine), u["tool_id"]


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


IMPL_WORDS = ["OCCT", "OpenCASCADE", "B-rep", "build123d", "ezdxf", "sympy", "mpmath", "FreeCAD", "Python", "subprocess", "scipy", "numpy", "least_squares", "fractions"]


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


# ---------------------------------------------------------------- mathdisc 专项（静态，不需要数学库）
def test_every_unit_has_goldens_and_error_cases():
    for u in REG["units"]:
        mine = [c for c in CASES if c["tool"] == u["tool_id"]]
        assert len(mine) >= 3, u["tool_id"]
        assert any("expect_error" in c for c in mine), u["tool_id"]


def test_d2_permanent_golden_present():
    """D-2：√2²=2 永不 refuted 的金样必须在册（v1 假反驳事故）。"""
    ids = {c["id"] for c in CASES}
    assert {"id-sqrt2-never-refuted", "id-sqrt2-2000", "fm-x-plus-x", "rc-factorial", "cx-fermat5"} <= ids


def test_check_units_declare_assumptions_output():
    for u in REG["units"]:
        if u["capability"]["ops"] == ["check"]:
            props = u["signature"]["output_schema"]["properties"]
            assert {"verdict", "method_complete", "evidence", "assumptions"} <= set(props), u["tool_id"]


def test_network_path_only_in_llm_client():
    """出网只有一个出口：llm/client.py（stdlib urllib）。其余执行体源码没有出网模块；
    出网主机只有 dashscope.aliyuncs.com（包清单的 runtime.process.network 同此）。"""
    import re
    bad = ["urllib", "socket", "http.client", "requests", "httpx"]
    for rel in M["tools_lock"]["covers"]:
        if rel.endswith(".py") and rel != "mathdisc/llm/client.py":
            src = (ROOT / rel).read_text(encoding="utf-8")
            for w in bad:
                assert f"import {w}" not in src and f"from {w}" not in src and f".{w} import" not in src, (rel, w)
    hosts = set()
    for rel in M["tools_lock"]["covers"]:
        if rel.endswith((".py", ".lock", ".json")) and rel != "uv.lock":
            hosts |= set(re.findall(r"https?://([A-Za-z0-9.-]+)", (ROOT / rel).read_text(encoding="utf-8")))
    assert hosts == {"dashscope.aliyuncs.com"}, hosts


def test_old_ids_not_reused():
    """TL-24：新 tool_id 不与旧 id 同名。"""
    ids = {u["tool_id"] for u in REG["units"]}
    assert not (ids & set(M["replaces"]["tool_ids"])), ids


def test_envelope_rejects_without_math_libs():
    """信封层的拒绝不依赖数学库，本地即可跑。"""
    import subprocess
    def call(env):
        p = subprocess.run([sys.executable, str(ROOT / "md_tool.py")], input=(json.dumps(env) + "\n").encode(),
                           capture_output=True, timeout=30, cwd=str(ROOT))
        return json.loads(p.stdout)
    assert call({"tool": "mathdisc.nope", "payload": {}})["error"]["code"] == "UNSUPPORTED"
    assert call({"tool": "mathdisc.reach", "payload": []})["error"]["code"] == "BAD_INPUT"
    assert call({"tool": "eval.evaluate", "payload": {}})["error"]["code"] == "UNSUPPORTED"


def test_bounded_conclusions_have_validity_goldens():
    """产出台规范 §3：有限范围内核验的结论带 validity，金样逐类核对。"""
    need = {"mathdisc.formula": "data_range", "mathdisc.identity": "sample_points", "mathdisc.recurrence": "index_range"}
    for tool, basis in need.items():
        assert any(c["tool"] == tool and {"path": "validity.basis", "eq": basis} in c.get("expect", []) for c in CASES), tool


def test_validity_helpers_offline():
    sys.path.insert(0, str(ROOT))
    import md_tool as m
    v = m._formula_validity({"x": [0.5, 3.0], "y": [1, 2]}, {"x": [3.5, 4.0]}, {}, 6, 8)
    assert v["core"] == [{"name": "x", "min": 0.5, "max": 3.0}] and "外推" in m._formula_assumption(v)
    ev = {"grade": "verified@50", "sample_point": {"x": "2/7"}}
    assert "x = 2/7" in m._identity_assumption(ev, m._identity_validity(ev))
    assert "第 10 项之后未核验" in m._recurrence_assumption(m._recurrence_validity([1] * 8, [1, 2]))


def test_model_facing_text_names_no_tool():
    """说明只写自己（工具开发者指南草案 §5.4）：给模型看的文字里不出现工具名。"""
    import json as _json, re
    from pathlib import Path as _P
    reg = _json.loads((_P(__file__).resolve().parents[1] / "registration.json").read_text(encoding="utf-8"))
    for u in reg["units"]:
        sch = u["signature"]["input_schema"]
        texts = [sch.get("description", "")] + [p.get("description", "") for p in sch.get("properties", {}).values()]
        texts += [e["input"] + " " + e["output"] for e in u["capability"]["examples"]]
        for t in texts:
            assert not re.search(r"\b(calc|mathdisc|doc|cad|probe)\.[a-z_]+", t), (u["tool_id"], t[:80])
