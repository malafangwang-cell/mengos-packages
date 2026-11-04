"""确定性（TL-12 ②）：同一输入在不同进程、不同哈希种子下两次运行，输出与文件逐字节相同。"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BID = json.loads((ROOT / "samples" / "bid_tech.json").read_text(encoding="utf-8"))


def _run(tool, payload, workdir, seed):
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    line = json.dumps({"tool": tool, "payload": payload, "workdir": str(workdir)}, ensure_ascii=False)
    p = subprocess.run([sys.executable, str(ROOT / "doc_tool.py")], input=line, capture_output=True, text=True, env=env, check=True)
    r = json.loads(p.stdout)
    assert r["ok"], r
    return r["output"], {f["path"]: (workdir / f["path"]).read_bytes() for f in r["output"]["files"]}


def test_build_is_byte_identical_across_processes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    oa, fa = _run("doc.build", {"doc": BID, "formats": ["docx", "html"]}, a, 0)
    ob, fb = _run("doc.build", {"doc": BID, "formats": ["docx", "html"]}, b, 4242)
    assert oa == ob
    assert fa == fb
    assert {f["format"] for f in oa["files"]} == {"json", "view", "md", "figure", "docx", "html"}


def test_export_matches_build_and_model_round_trips(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    for d in (a, b, c):
        d.mkdir()
    ob, fb = _run("doc.build", {"doc": BID}, a, 1)
    oe, fe = _run("doc.export", {"doc": BID, "formats": ["docx", "md"]}, b, 2)
    name = ob["name"]
    assert fb[name + ".docx"] == fe[name + ".docx"] and fb[name + ".md"] == fe[name + ".md"]
    model = json.loads(fb[name + ".doc.json"])          # 规范模型再输入一次：同一 doc_sha256、同一文件
    orr, fr = _run("doc.export", {"doc": model, "formats": ["docx", "json"]}, c, 3)
    assert orr["doc_sha256"] == ob["doc_sha256"]
    assert fr[name + ".docx"] == fb[name + ".docx"] and fr[name + ".doc.json"] == fb[name + ".doc.json"]
