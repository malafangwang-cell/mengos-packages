"""0.2.0 按文件读的来源（17 TL-9d；设计-附件按引用由工具读取-2026-11-19 §6.2、§二十一、§十一 验收第 3、4、7 条）。

夹具图纸由 tests/fixtures/dxf_gen/（mengosv2 现成合成金样生成器的副本）现场生成，用包里带的解析库出解析结构，
摆成引擎交文件后的样子（tools/fixture_files.py）。不入真图。
"""
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from count_tool import MAX_LIST_ITEMS, canonical, run  # noqa: E402
from file_source import DETAIL_SECTIONS, own_library, parser_string, unit_key  # noqa: E402
from fixture_files import Fixture  # noqa: E402

NAMES = ("f_seg_exact", "f_nested_owner", "f_unparsed", "rack", "d1", "ublk", "utab")


@pytest.fixture(scope="module")
def fx():
    made = {n: Fixture(n) for n in NAMES}
    yield made
    for f in made.values():
        f.cleanup()


def call(fixture, payload, tool="count.rows", parsed=True):
    wd, f = fixture.workdir(parsed)
    src = dict(payload.pop("source"))
    src["file"] = f
    res = run({"tool": tool, "payload": {"source": src, **payload}, "workdir": wd})
    assert sorted(os.listdir(wd)) == ["in"], "调用后工作目录里不得留文件"
    return res


def ok(res):
    assert res["ok"], res
    return res["output"]


def sections_of(fixture):
    out = ok(call(fixture, {"source": {"section": "文字"}}))
    return out["source"]["sections_available"]


# ── 第 4 条 两条路一致：读解析结构与回原件读得到的行逐字节相同 ──

@pytest.mark.parametrize("name", NAMES)
def test_parsed_and_original_rows_identical(fx, name):
    for section in sections_of(fx[name]):
        a = call(fx[name], {"source": {"section": section}, "list": True}, parsed=True)
        b = call(fx[name], {"source": {"section": section}, "list": True}, parsed=False)
        assert a["ok"] == b["ok"], (name, section, a, b)
        if not a["ok"]:
            assert a == b
            continue
        assert a["output"]["source"]["read_from"] == "parsed" and b["output"]["source"]["read_from"] == "original"
        assert canonical(a["output"]["items"]) == canonical(b["output"]["items"]), (name, section)
        assert a["output"]["source"]["rows_declared"] == b["output"]["source"]["rows_declared"]


def test_not_stored_detail_falls_back_to_original(fx):
    """解析结构里标“未存”的明细节（体量上限）⟹ 用同一份解析库回原件读，行与存了时相同。"""
    f = fx["f_seg_exact"]
    full = ok(call(f, {"source": {"section": "线段明细"}, "list": True}))
    wd, fo = f.workdir(True)
    p = os.path.join(wd, fo["parsed"]["path"])
    d = json.load(open(p, encoding="utf-8"))
    for x in d["details"]:
        if x["section"] == "线段明细":
            x["stored"], x["lines"] = False, []
    data = json.dumps(d, ensure_ascii=False).encode("utf-8")
    open(p, "wb").write(data)
    fo["parsed"]["sha256"] = hashlib.sha256(data).hexdigest()
    out = ok(run({"tool": "count.rows", "payload": {"source": {"file": fo, "section": "线段明细"}, "list": True}, "workdir": wd}))
    assert out["source"]["read_from"] == "original"
    assert out["items"] == full["items"]
    assert sorted(os.listdir(wd)) == ["in"]


# ── 第 3 条 读全、核条数、确定性；文件内容不进回执 ──

def test_whole_file_counts_and_checks(fx):
    out = ok(call(fx["d1"], {"source": {"section": "文字"}}))
    s = out["source"]
    assert s["mode"] == "file" and s["scope"] == "whole" and s["rows_read"] == s["rows_declared"] == out["count"]
    assert s["units_read"] >= 6
    assert {c["name"] for c in out["checks"]} == {"sha256_eq", "parser_eq_ingest", "rows_read_eq_declared"}
    assert all(c["ok"] for c in out["checks"])
    assert out["assumptions"] == []
    assert s["parser"] == own_library()


def test_deterministic_and_no_file_content_in_receipt(fx):
    f = fx["f_seg_exact"]
    wd, fo = f.workdir(True)
    env = {"tool": "count.rows", "payload": {"source": {"file": fo, "section": "线段明细"}, "list": True}, "workdir": wd}
    a, b = canonical(run(env)), canonical(run(env))
    assert a == b
    raw = open(os.path.join(wd, fo["path"]), "rb").read().decode("utf-8", "replace")
    assert "AcDbEntity" in raw and "AcDbEntity" not in a and "SECTION" not in a


def test_unit_scope_and_aliases(fx):
    f = fx["f_nested_owner"]
    for alias in ("区块2", "区块 2"):
        out = ok(call(f, {"source": {"section": "嵌套插入", "unit": alias}}))
        assert out["count"] == 3 and out["source"]["scope"] == "unit" and out["source"]["unit"] == "区块2"
    bad = call(f, {"source": {"section": "嵌套插入", "unit": "区块 9"}})
    assert bad["ok"] is False and "区块1" in bad["error"]["message"]
    assert unit_key("图幅 S3") == unit_key("图幅3") == unit_key("S3")


def test_rows_carry_unit_column(fx):
    out = ok(call(fx["d1"], {"source": {"section": "文字"}, "list": True, "limit": 5}))
    assert out["source"]["columns"][0] == "单元"
    for it in out["items"]:
        assert it["id"].startswith(it["cells"]["单元"] + "/文字/")


def test_wrong_section_lists_sections(fx):
    res = call(fx["f_seg_exact"], {"source": {"section": "没有这一节"}})
    assert res["ok"] is False and res["error"]["code"] == "BAD_INPUT"
    for s in ("文字", "线段明细", "嵌套插入", "未插入图块文字"):
        assert s in res["error"]["message"]


def test_detail_sections_present(fx):
    avail = sections_of(fx["f_seg_exact"])
    assert all(s in avail for s in DETAIL_SECTIONS)
    assert avail["线段明细"] == ["图层", "方向", "长度", "起点", "终点"]
    assert avail["嵌套插入"] == ["名称", "x", "y", "旋转", "嵌套层", "所属直接插入"]
    assert avail["未插入图块文字"] == ["块名", "内容"]


# ── 第 4 条 未解析必须标明：列在回执里；查这一类答“拿不到” ──

def test_unparsed_listed_and_query_refused(fx):
    out = ok(call(fx["f_unparsed"], {"source": {"section": "文字"}}))
    kinds = {u["kind"]: u["count"] for u in out["source"]["unparsed"]}
    assert kinds["POINT"] == 5 and kinds["RAY"] == 1 and kinds["XLINE"] == 1
    res = call(fx["f_unparsed"], {"source": {"section": "POINT"}})
    assert res["ok"] is False and "拿不到" in res["error"]["message"] and "5 处" in res["error"]["message"]


def test_unparsed_scoped_to_unit(fx):
    """按单元读时只列该单元的未解析处数；各单元之和加上不在图面上的（单元为空）= 全文件。"""
    from file_source import Doc
    f = fx["f_unparsed"]
    doc = Doc(json.load(open(f.parsed, encoding="utf-8")))
    whole = ok(call(f, {"source": {"section": "文字"}}))
    per = sum(u["count"] for u in doc.unparsed if not u.get("unit"))
    for unit in doc.unit_names():
        o = call(f, {"source": {"section": "文字", "unit": unit}})
        per += sum(u["count"] for u in o["output"]["source"]["unparsed"]) if o["ok"] else 0
    assert per == sum(u["count"] for u in whole["source"]["unparsed"]) == 8


# ── 第 7 条 损坏：哈希不符、截断 ⟹ 失败、不出数；解析库不同版 ⟹ 失败 ──

def test_sha_mismatch_and_truncation(fx):
    f = fx["f_seg_exact"]
    wd, fo = f.workdir(True)
    bad = dict(fo, sha256="0" * 64)
    r = run({"tool": "count.rows", "payload": {"source": {"file": bad, "section": "文字"}}, "workdir": wd})
    assert r["ok"] is False and "sha256" in r["error"]["message"]
    p = os.path.join(wd, fo["path"])
    data = open(p, "rb").read()
    open(p, "wb").write(data[: len(data) // 2])
    r = run({"tool": "count.rows", "payload": {"source": {"file": fo, "section": "文字"}}, "workdir": wd})
    assert r["ok"] is False and r["error"]["code"] == "BAD_INPUT"
    wd2, fo2 = f.workdir(True)
    pp = os.path.join(wd2, fo2["parsed"]["path"])
    open(pp, "ab").write(b" ")
    r = run({"tool": "count.rows", "payload": {"source": {"file": fo2, "section": "文字"}}, "workdir": wd2})
    assert r["ok"] is False and "解析结构" in r["error"]["message"]


def test_parser_mismatch_refused(fx):
    wd, fo = fx["f_seg_exact"].workdir(True)
    fo["parsed"]["parser"] = "mengos-cad@0.9.0+sha256:" + "1" * 64
    r = run({"tool": "count.rows", "payload": {"source": {"file": fo, "section": "文字"}}, "workdir": wd})
    assert r["ok"] is False and "解析库" in r["error"]["message"]
    assert fo["parsed"]["parser"] != parser_string(own_library())


def test_path_must_stay_in_workdir(fx):
    wd, fo = fx["f_seg_exact"].workdir(True)
    for path in ("../x.dxf", "/etc/hostname"):
        r = run({"tool": "count.rows", "payload": {"source": {"file": dict(fo, path=path), "section": "文字"}}, "workdir": wd})
        assert r["ok"] is False
    os.symlink(os.path.join(wd, fo["path"]), os.path.join(wd, "in", "link.dxf"))
    r = run({"tool": "count.rows", "payload": {"source": {"file": dict(fo, path="in/link.dxf"), "section": "文字"}}, "workdir": wd})
    assert r["ok"] is False and "符号链接" in r["error"]["message"]
    r = run({"tool": "count.rows", "payload": {"source": {"file": {"attachment": "n1"}, "section": "文字"}}, "workdir": wd})
    assert r["ok"] is False and "引擎未交文件" in r["error"]["message"]


# ── 清单分页 ──

def test_pagination(fx):
    f = fx["rack"]
    full = ok(call(f, {"source": {"section": "图块插入"}, "list": True, "limit": MAX_LIST_ITEMS}))
    assert full["total_matched"] == 660 and len(full["items"]) == 660
    pages = []
    for off in range(0, 660, 250):
        o = ok(call(f, {"source": {"section": "图块插入"}, "list": True, "offset": off, "limit": 250}))
        assert o["total_matched"] == 660
        pages += o["items"]
    assert pages == full["items"]
    r = call(f, {"source": {"section": "图块插入"}, "offset": 1})
    assert r["ok"] is False


def test_list_over_cap_without_limit_refused():
    rows = [[str(i)] for i in range(10)]
    import count_tool
    old = count_tool.MAX_LIST_ITEMS
    count_tool.MAX_LIST_ITEMS = 3
    try:
        r = run({"tool": "count.rows", "payload": {"source": {"columns": ["a"], "rows": rows}, "list": True}})
        assert r["ok"] is False and "offset" in r["error"]["message"]
        r = run({"tool": "count.rows", "payload": {"source": {"columns": ["a"], "rows": rows}, "list": True, "offset": 8, "limit": 3}})
        assert r["ok"] and r["output"]["total_matched"] == 10 and [i["id"] for i in r["output"]["items"]] == ["行/9", "行/10"]
    finally:
        count_tool.MAX_LIST_ITEMS = old


# ── count.series、count.coverage 的新取法 ──

def test_series_file_rows_carry_unit(fx):
    out = ok(call(fx["rack"], {"source": {"section": "尺寸标注"}, "mode": "product",
                                "product": {"text": "显示文字", "measure": "测量值"}, "tol": 1}, tool="count.series"))
    hits = out["product"]["hits"]
    assert hits and all(re.match(r"^区块\d+/尺寸标注/\d+$", h["row"]) for h in hits)


def test_coverage_inventory_file_marks_content(fx):
    f = fx["f_nested_owner"]
    inv = ok(call(f, {"source": {"section": "嵌套插入"}, "list": True}))
    ids = [i["id"] for i in inv["items"]]
    content = {"产出": {"表": [{"处理记录": [{"id": i, "status": "done"} for i in ids[:-1]]}]}}
    wd, fo = f.workdir(True)
    r = ok(run({"tool": "count.coverage", "workdir": wd, "payload": {
        "inventory": {"source": {"file": fo, "section": "嵌套插入"}}, "marks": {"content": content, "field": "处理记录"}}}))
    assert r["unmarked_count"] == 1 and r["unmarked"] == [{"id": ids[-1]}] and r["assumptions"] == []
    assert r["source"]["mode"] == "file" and r["source"]["marks"] == {"form": "content", "field": "处理记录", "fields_found": 1, "marks_found": len(ids) - 1}
    empty = ok(run({"tool": "count.coverage", "workdir": wd, "payload": {
        "inventory": {"source": {"file": fo, "section": "嵌套插入"}}, "marks": {"content": {}, "field": "处理记录"}}}))
    assert empty["unmarked_count"] == len(ids) and empty["marked"] == 0


def test_coverage_marks_object_shape():
    r = run({"tool": "count.coverage", "payload": {"inventory": {"items": ["a"]}, "marks": {"content": {}}}})
    assert r["ok"] is False


# ── 解析库按版本带入：带入的字节与登记一致；依赖钉版与解析库的依赖清单一致 ──

def test_vendored_library_matches_lock_and_registration():
    lock = json.loads((ROOT / "cadlib.lock.json").read_text(encoding="utf-8"))
    lib = own_library()
    assert {k: lock[k] for k in ("name", "spec", "version", "sha256")} == lib
    for rel, h in lock["files"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == h, rel
    reg = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    for u in reg["units"]:
        reads = "x-mengos-attachment-file" in json.dumps(u["signature"]["input_schema"])
        assert (u.get("parsers") == [lib]) == reads, u["tool_id"]
        assert ("attachment_file" in u) == reads


def test_dependency_pins_match_parser_requirements():
    req = {}
    for line in (ROOT / "requirements-cad.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", line)
        if m:
            req[m.group(1).lower().replace("_", "-")] = m.group(2)
    py = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps = dict((a.lower().replace("_", "-"), b) for a, b in re.findall(r'"([A-Za-z0-9_.-]+)==([^"]+)"', py))
    assert deps == req
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    for name, ver in req.items():
        assert re.search(rf'name = "{re.escape(name)}"\nversion = "{re.escape(ver)}"', lock), name


def test_manifest_lock_covers_vendored_library():
    man = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
    import lock as lk
    assert set(man["tools_lock"]["covers"]) == set(lk.SOURCES) | {"registration.json"}
    assert man["runtime"]["process"]["workdir"] is True
