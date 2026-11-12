"""块清单（局部追问设计 r9.1 §三、r8 §3.1；施工项 A1 / 读数令 X8 P1）。

doc.build 的产出带 blocks：块 id、种类、所在节、在规范化 body 里的起止（码点，左闭右开）、块哈希（body 源文字的 sha256）；
图块带 doc.figures 的 id。先红：
  · 同一份文档两次 build 的块清单逐字节相同；
  · 段内改字只改一块的哈希；
  · 起止切回 body 得到的就是块的源文字，哈希与之相符；
  · 放置行成图块 / 表块，带 id；只被引用的图表补在节末，标 auto。
"""
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BID = json.loads((ROOT / "samples" / "bid_tech.json").read_text(encoding="utf-8"))

DOC = {
    "title": "块清单样例",
    "sections": [
        {"id": "s1", "heading": "概述",
         "body": "第一段，含图引用 [[fig:a]]。\n\n第二段有两行\n续行。\n\n[[fig:a]]\n\n- 列表一\n- 列表二\n\n### 小标题\n\n> 引用\n\n```\ncode [[fig:a]]\n```"},
        {"id": "s2", "heading": "细节", "body": "只引用表 [[tab:t]]，不放置。\n\n| a | b |\n|---|---|\n| 1 | 2 |"},
        {"id": "s3", "heading": "空节"},
    ],
    "figures": [{"id": "a", "caption": "示意", "source": {"svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\"><rect width=\"10\" height=\"10\"/></svg>"}}],
    "tables": [{"id": "t", "caption": "表", "columns": ["x"], "rows": [["1"]]}],
}


def _build(doc, workdir, seed=0):
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    line = json.dumps({"tool": "doc.build", "payload": {"doc": doc, "formats": []}, "workdir": str(workdir)}, ensure_ascii=False)
    p = subprocess.run([sys.executable, str(ROOT / "doc_tool.py")], input=line, capture_output=True, text=True, env=env, check=True)
    r = json.loads(p.stdout)
    assert r["ok"], r
    return r["output"]


def _wd(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    return d


def test_blocks_byte_identical_across_builds(tmp_path):
    a = _build(BID, _wd(tmp_path, "a"), 0)
    b = _build(BID, _wd(tmp_path, "b"), 4242)
    assert "blocks" in a and len(a["blocks"]) > 0
    assert json.dumps(a["blocks"], ensure_ascii=False, sort_keys=True) == json.dumps(b["blocks"], ensure_ascii=False, sort_keys=True)


def test_edit_inside_paragraph_changes_one_hash(tmp_path):
    a = _build(DOC, _wd(tmp_path, "a"))["blocks"]
    doc2 = copy.deepcopy(DOC)
    doc2["sections"][0]["body"] = doc2["sections"][0]["body"].replace("第二段有两行", "第二段改了几个字有两行")
    b = _build(doc2, _wd(tmp_path, "b"))["blocks"]
    assert [x["id"] for x in a] == [x["id"] for x in b]
    diff = [x["id"] for x, y in zip(a, b) if x["hash"] != y["hash"]]
    assert diff == ["s1.b2"]


def test_ranges_slice_back_to_source(tmp_path):
    out = _build(DOC, _wd(tmp_path, "a"))
    bodies = {s["id"]: s.get("body", "") for s in DOC["sections"]}
    for blk in out["blocks"]:
        src = bodies[blk["section"]][blk["start"]:blk["end"]]
        assert hashlib.sha256(src.encode("utf-8")).hexdigest() == blk["hash"], blk
        if not blk.get("auto"):
            assert src.strip() != "", blk
    s1 = [b for b in out["blocks"] if b["section"] == "s1"]
    assert [b["kind"] for b in s1] == ["paragraph", "paragraph", "figure", "list", "heading", "quote", "code"]
    assert s1[1]["start"] == bodies["s1"].index("第二段") and bodies["s1"][s1[1]["start"]:s1[1]["end"]] == "第二段有两行\n续行。"
    assert s1[2]["figure"] == "a"


def test_auto_placed_table_and_md_table(tmp_path):
    out = _build(DOC, _wd(tmp_path, "a"))
    s2 = [b for b in out["blocks"] if b["section"] == "s2"]
    assert [b["kind"] for b in s2] == ["paragraph", "md_table", "table"]
    assert s2[2]["table"] == "t" and s2[2]["auto"] is True
    assert not [b for b in out["blocks"] if b["section"] == "s3"]
