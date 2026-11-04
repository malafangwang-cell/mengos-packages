"""模糊测试：任意输入都只能得到 ok 或结构化错误，不得出现 INTERNAL（固定种子，可复现）。"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from calc_tool import run  # noqa: E402

ALPHABET = list("0123456789+-*/^()!%.,=| xyneπ√²×÷（）") + ["sqrt", "sin", "log", "frac", "\\frac{", "}", "**", "pi", "e", "mod(", "°"]


def test_fuzz_never_internal():
    rng = random.Random(20261002)
    for _ in range(3000):
        expr = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 25)))
        for tool, payload in (("calc.evaluate", {"expr": expr, "bindings": {"x": 2, "n": 3}}),
                              ("calc.check_equal", {"left": expr, "right": "1"})):
            res = run({"tool": tool, "payload": payload, "budget": {"timeout_ms": 2000}})
            if not res["ok"]:
                assert res["error"]["code"] in ("BAD_INPUT", "RESOURCE_LIMIT", "UNSUPPORTED", "TIMEOUT"), (expr, res)
