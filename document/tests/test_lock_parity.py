"""lock 跨语言一致（17 TL-25a）：安装器用 JS 规范化 JSON 重算 lock，包侧 lock.py 用 Python。
两边对数字的写法只在两处不同：整数值的浮点数（Python 1.0，JS 1）与指数写法（Python 1e-06，JS 0.000001）。
登记资产里不出现这两种数，两边算出的 lock 就逐字节相同。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _floats(o, path="$"):
    if isinstance(o, float):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from _floats(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _floats(v, f"{path}[{i}]")


def test_registration_numbers_are_language_neutral():
    m = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
    reg = json.loads((ROOT / m["tools"]).read_text(encoding="utf-8"))
    bad = [(p, v) for p, v in _floats(reg) if v.is_integer() or "e" in repr(v).lower()]
    assert not bad, f"整数值或指数写法的浮点数会让安装器重算的 lock 与 lock.py 不同：{bad}"
