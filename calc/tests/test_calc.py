"""calc v2 金样与性质测试。运行：python -m pytest tests -q"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calc_tool import run  # noqa: E402

CASES = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_golden(case):
    res = run({"tool": case["tool"], "payload": case["payload"]})
    if "expect_error" in case:
        assert res["ok"] is False, res
        assert res["error"]["code"] == case["expect_error"], res
        return
    assert res["ok"] is True, res
    for key, val in case["expect"].items():
        assert res["output"].get(key) == val, (key, res["output"])


def _spawn(line: str, *argv: str) -> bytes:
    p = subprocess.run([sys.executable, str(ROOT / "calc_tool.py"), *argv], input=line.encode(),
                       capture_output=True, timeout=60, env={**os.environ, "PYTHONHASHSEED": "random"})
    assert p.returncode == 0, p.stderr
    return p.stdout


@pytest.mark.parametrize("case", [c for c in CASES if c["id"] in
                                  ("t1-smoke", "sqrt-surd", "solve-system", "integrate-definite", "eq-identity")])
def test_determinism_across_processes(case):
    line = json.dumps({"tool": case["tool"], "payload": case["payload"]})
    assert _spawn(line) == _spawn(line)


def test_bare_payload_with_argv():
    out = json.loads(_spawn(json.dumps({"expr": "6*7"}), "calc.evaluate"))
    assert out == {"ok": True, "output": {"approx": "42", "exact": True, "kind": "integer", "path": "rational", "value": "42"}}


def test_invalid_json_is_structured_failure():
    out = json.loads(_spawn("{not json"))
    assert out["ok"] is False and out["error"]["code"] == "BAD_INPUT"


def test_unknown_tool():
    res = run({"tool": "calc.nope", "payload": {}})
    assert res["error"]["code"] == "BAD_INPUT"


def test_timeout_is_structured():
    res = run({"tool": "calc.algebra",
               "payload": {"op": "integrate", "expr": "exp(x^5)*sin(x^3)*log(x^2+1)", "var": "x"},
               "budget": {"timeout_ms": 300}})
    assert res["ok"] is False and res["error"]["code"] == "TIMEOUT"


def test_no_eval_anywhere():
    src = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in ("expr_parser.py", "evaluator.py", "calc_tool.py"))
    for banned in ("eval(", "exec(", "sympify(", "parse_expr(", "__import__", "getattr("):
        assert banned not in src, banned
