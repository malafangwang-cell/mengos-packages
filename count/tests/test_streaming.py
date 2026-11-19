"""0.2.3 回原件读的耗时与内存（架构线第十六件；设计-附件按引用由工具读取-2026-11-19 §十四 风险 3）。

甲：明细节不建行表，count.rows 一遍读完、边读边算；结果与 0.2.2（建行表）逐项一致——
    期望值 tests/fixtures/stream_equiv.json 由 0.2.2 跑出（用例矩阵 tools/stream_equiv_cases.py），比每条回执的规范化 sha256。
丙：回原件读设内存上限（地址空间），超了干净失败（解析库的 CAD_RESOURCE_EXCEEDED），不截断；读完复原上限。
"""
import hashlib
import json
import os
import resource
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import file_source  # noqa: E402
from count_tool import canonical, run  # noqa: E402
from fixture_files import Fixture  # noqa: E402
from readers import read_source  # noqa: E402
from stream_equiv_cases import FIXTURES, cases  # noqa: E402

EXPECT = json.loads((ROOT / "tests" / "fixtures" / "stream_equiv.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fx():
    made = {n: Fixture(n) for n in FIXTURES}
    yield made
    for f in made.values():
        f.cleanup()


def test_matrix_covers_expectations():
    assert sorted(c[0] for c in cases()) == sorted(EXPECT)


def test_same_as_materialized_implementation(fx):
    diff = []
    for cid, name, section, q, parsed in cases():
        wd, f = fx[name].workdir(parsed)
        r = run({"tool": "count.rows", "payload": {"source": {"file": f, "section": section}, **json.loads(json.dumps(q))}, "workdir": wd})
        got = {"ok": r["ok"], "count": r["output"]["count"] if r["ok"] else None,
               "sha256": hashlib.sha256(canonical(r).encode()).hexdigest()}
        if got != EXPECT[cid]:
            diff.append(cid)
    assert diff == []


def test_detail_rows_not_materialized(fx):
    wd, f = fx["rack"].workdir(True)
    t = read_source({"file": f, "section": "线段明细"}, None, wd)
    assert not isinstance(t.rows, list) and len(t.rows) == t.source["rows_read"] == 4905
    assert list(t.rows)[:3] == list(t.rows)[:3] and sum(1 for _ in t.rows) == 4905   # 可再读，序号与切格同前


def _vm_mb() -> int:
    return int([l for l in open("/proc/self/status") if l.startswith("VmSize")][0].split()[1]) // 1024


def test_original_read_over_memory_cap_fails_cleanly(fx, monkeypatch):
    """med（展开约 60 万线段，同 vetc 的 RLIMIT_AS 干净失败用例）在本进程现有地址空间之上只给 100 MB：回原件读必超。"""
    med = Fixture("med")
    try:
        before = resource.getrlimit(resource.RLIMIT_AS)
        wd, f = med.workdir(False)
        monkeypatch.setattr(file_source, "ORIGINAL_AS_LIMIT_MB", _vm_mb() + 100)
        r = run({"tool": "count.rows", "payload": {"source": {"file": f, "section": "线段明细"}}, "workdir": wd})
        assert r == {"ok": False, "error": {"code": "BAD_INPUT", "message": file_source.RESOURCE_EXCEEDED}}
        assert sorted(os.listdir(wd)) == ["in"], "失败不留产出"
        assert resource.getrlimit(resource.RLIMIT_AS) == before, "读完复原上限"
    finally:
        med.cleanup()
    wd, f = fx["rack"].workdir(False)
    r = run({"tool": "count.rows", "payload": {"source": {"file": f, "section": "线段明细"}}, "workdir": wd})
    assert r["ok"] and r["output"]["count"] == 4905


def test_parsed_read_not_capped(fx, monkeypatch):
    """读解析结构不重新解析，不设这道上限。"""
    wd, f = fx["rack"].workdir(True)
    monkeypatch.setattr(file_source, "ORIGINAL_AS_LIMIT_MB", 1)
    r = run({"tool": "count.rows", "payload": {"source": {"file": f, "section": "图块插入"}}, "workdir": wd})
    assert r["ok"] and r["output"]["source"]["read_from"] == "parsed"
