"""确定性（TL-12 ②）：不同进程、不同哈希种子两次运行，输出与文件逐字节相同。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ALL = ["step", "glb", "stl", "3mf", "svg", "dxf"]


def _run(tool, payload, workdir, seed):
    env = dict(os.environ, PYTHONHASHSEED=str(seed))
    line = json.dumps({"tool": tool, "payload": payload, "workdir": str(workdir)})
    p = subprocess.run([sys.executable, str(ROOT / "cad_tool.py")], input=line, capture_output=True, text=True, env=env, timeout=120)
    return p.stdout


@pytest.mark.parametrize("name", ["base", "flange", "bracket", "box_pocket", "gear"])
def test_double_run_bytes(tmp_path, name):
    plan = (ROOT / "samples" / f"{name}.cad").read_text(encoding="utf-8")
    payload = {"plan": plan, "name": name, "formats": ALL}
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    oa = _run("cad.build", payload, a, 1)
    ob = _run("cad.build", payload, b, 987)
    assert json.loads(oa)["ok"], oa
    assert oa == ob
    for f in sorted(os.listdir(a)):
        assert (a / f).read_bytes() == (b / f).read_bytes(), f


def test_check_deterministic(tmp_path):
    plan = (ROOT / "samples" / "flange.cad").read_text(encoding="utf-8")
    payload = {"plan": plan, "expect": "holes 6 d=10\nmass 1254 g\nwatertight"}
    assert _run("cad.check", payload, tmp_path, 3) == _run("cad.check", payload, tmp_path, 4)
