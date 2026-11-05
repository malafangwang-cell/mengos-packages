"""金样经与引擎相同的进程入口与信封全部通过（TL-12 ③）。"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_golden_runner_all_pass():
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "run_golden.py")], capture_output=True, timeout=600)
    out = json.loads(p.stdout.decode("utf-8"))
    failed = {k: v["failed"] for k, v in out["tools"].items() if v["failed"]}
    assert p.returncode == 0 and not failed, failed
    assert set(out["tools"]) == {"table.build", "table.check", "table.export"}
