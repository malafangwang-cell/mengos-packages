"""安装包清单自检（WP-W6 §2、§10 的包侧部分）。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
REG = json.loads((ROOT / M["tools"]).read_text(encoding="utf-8"))
TYPES = {t["name"]: t for t in M["types"]}


def test_types_are_well_formed():
    for t in M["types"]:
        assert t["kind"] in ("deliverable", "value")
        assert t["parent"] is None or t["parent"] in TYPES, t
        if t["kind"] == "deliverable":
            assert t["realizes"] == ["data_table"]
            r = t["renderer"]
            assert r and r.get("full") and r.get("embed")
            assert (ROOT / r["full"]).is_file()
        else:
            assert "realizes" not in t and "renderer" not in t, t["name"]


def test_tool_types_are_declared():
    known = set(TYPES) | set(M.get("uses_platform_types", []))
    for u in REG["units"]:
        for k in ("in_types", "out_types"):
            assert set(u["capability"][k]) <= known, (u["tool_id"], k)


def test_runtime_and_scope():
    pr = M["runtime"]["process"]
    assert M["scope"] == "public" and M["publisher"] == "mengos"
    assert pr["network"] == "none"
    for k in ("project", "lock", "entry"):
        assert (ROOT / pr[k]).is_file()
    for u in REG["units"]:
        assert u["executor"] == {"kind": "process", "entry": pr["entry"], "mode": "sync"}


def test_lock_covers_match_lock_py():
    import lock
    assert M["tools_lock"]["covers"] == lock.SOURCES + ["registration.json"]
    for f in M["tools_lock"]["covers"]:
        assert (ROOT / f).is_file(), f


def test_content_hash_is_current():
    spec = importlib.util.spec_from_file_location("make_package", ROOT / "tools" / "make_package.py")
    mp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mp)
    assert M["content_hash"] == mp.content_hash(), "改动后要运行 python tools/make_package.py"


def test_certification_material_present():
    cm = M["certification_material"]
    for k in ("golden_cases", "selection_cases", "golden_runner"):
        assert (ROOT / cm[k]).is_file()
    sel = json.loads((ROOT / cm["selection_cases"]).read_text(encoding="utf-8"))
    ids = {u["tool_id"] for u in REG["units"]}
    for tid in ids:
        mine = [c for c in sel if c["tool_id"] == tid]
        assert sum(c["expect_selected"] for c in mine) >= 3 and sum(not c["expect_selected"] for c in mine) >= 3, tid


def test_renderer_is_self_contained():
    html = (ROOT / "renderer" / "index.html").read_text(encoding="utf-8")
    for bad in ("fetch(", "XMLHttpRequest", "WebSocket", "<script src", "@import", "localStorage"):
        assert bad not in html, bad
    assert 'post({ type: "mengos.ready", views: ["full", "embed"] })' in html
