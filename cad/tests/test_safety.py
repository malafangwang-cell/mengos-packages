"""安全与鲁棒：不执行代码；乱输入只得到结构化失败，不得 INTERNAL。"""
import random
import re
from pathlib import Path

import pytest

from cad_tool import run

ROOT = Path(__file__).resolve().parents[1]
SRC = ["cad_dsl.py", "builder.py", "geometry.py", "checker.py", "cad_tool.py"]


def test_no_eval_exec_in_sources():
    for name in SRC:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"(?<![\w.])(eval|exec|compile)\s*\(", text), name
        assert "__import__(\"os\")" not in text and "getattr(" not in text, name


@pytest.mark.parametrize("plan", [
    "__import__('os').system('echo hi')",
    "b: box 10 10 10\nb.__class__",
    "b: box 1e400 1 1",
    "b: box -5 10 10",
    "b: box 10 10 10\nhole d=5 at=(1,2,3) from=top through",
    "b: box 10 10 10\npattern b linear n=100000 dx=1",
    "b: box 10 10 10\nfillet r=1 edges=nosuch",
    "b: box 10 10 10\nb: box 5 5 5",
    "let x = 1/0",
    "b: gear m=1 z=5 width=3",
    "b: box (((((((((1)))))))) 2 3",
    "# 只有注释",
    "b: prism (0,0) (1,1) (2,2) h=3",
    "b: box 10 10 10\nshell t=6 open=top",
    "x" * 401,
    "\n".join(["b%d: box 1 1 1" % i for i in range(301)]),
])
def test_bad_plans_fail_structured(plan):
    res = run({"tool": "cad.build", "payload": {"plan": plan, "formats": []}})
    assert not res["ok"]
    assert res["error"]["code"] in ("BAD_INPUT", "RESOURCE_LIMIT"), res


def test_fuzz_random_lines():
    rnd = random.Random(20261002)
    ops = ["box", "cylinder", "hole", "pocket", "slot", "fillet", "chamfer", "shell", "pattern", "add", "cut", "gear", "prism", "let", "zz"]
    keys = ["d", "h", "w", "l", "r", "c", "t", "n", "at", "from", "depth", "edges", "m", "z", "dx", "axis", "open"]
    vals = ["10", "0", "-3", "1e9", "(1,2)", "(1,2,3)", "top", "front", "through", "all", "vertical", "x", "pi*2", "(", "=", "5/0"]
    internal = []
    for i in range(150):
        lines = ["b: box 40 30 20"]
        for _ in range(rnd.randint(1, 4)):
            parts = [rnd.choice(ops)] + [rnd.choice(vals) if rnd.random() < 0.3 else f"{rnd.choice(keys)}={rnd.choice(vals)}"
                                          for _ in range(rnd.randint(0, 4))]
            lines.append(" ".join(parts))
        res = run({"tool": "cad.build", "payload": {"plan": "\n".join(lines), "formats": []}, "budget": {"timeout_ms": 20000}})
        if not res["ok"] and res["error"]["code"] == "INTERNAL":
            internal.append(("\n".join(lines), res["error"]))
    assert not internal, internal[:3]


def test_workdir_must_be_absolute(tmp_path):
    res = run({"tool": "cad.export", "payload": {"plan": "b: box 10 10 10", "formats": ["stl"]}, "workdir": "rel/dir"})
    assert not res["ok"] and res["error"]["code"] == "BAD_INPUT"


def test_name_cannot_escape_workdir(tmp_path):
    res = run({"tool": "cad.export", "payload": {"plan": "b: box 10 10 10", "formats": ["stl"], "name": "../x"}, "workdir": str(tmp_path)})
    assert not res["ok"] and res["error"]["code"] == "BAD_INPUT"
