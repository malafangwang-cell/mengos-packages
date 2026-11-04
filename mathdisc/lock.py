"""计算 lock hash（TL-6 version）：覆盖执行体源文件、依赖声明、锁文件与登记资产；任一变化即升版。

登记资产里本身写着 version 与 lock_hash，计算时把这两处置空，避免自引用。
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = [
    "md_tool.py",
    "mathdisc/__init__.py",
    "mathdisc/check/__init__.py",
    "mathdisc/check/counterex.py",
    "mathdisc/check/formula.py",
    "mathdisc/check/identity.py",
    "mathdisc/check/reach.py",
    "mathdisc/check/receipt.py",
    "mathdisc/check/recurrence.py",
    "mathdisc/expr/__init__.py",
    "mathdisc/expr/grammar.py",
    "mathdisc/expr/ir.py",
    "mathdisc/expr/render.py",
    "mathdisc/forensics/__init__.py",
    "mathdisc/forensics/signature.py",
    "mathdisc/loop/__init__.py",
    "mathdisc/loop/solve_closed.py",
    "pyproject.toml",
    "uv.lock",
]


def _registration_bytes() -> bytes:
    reg = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    reg["lock_hash"] = ""
    for unit in reg["units"]:
        unit["version"] = ""
    return json.dumps(reg, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def lock_hash() -> str:
    h = hashlib.sha256()
    for name in SOURCES:
        p = ROOT / name
        h.update(name.encode() + b"\0" + (p.read_bytes() if p.exists() else b"") + b"\0")
    h.update(b"registration.json\0" + _registration_bytes() + b"\0")
    return h.hexdigest()[:16]


if __name__ == "__main__":
    reg_path = ROOT / "registration.json"
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    v = lock_hash()
    reg["lock_hash"] = v
    for unit in reg["units"]:
        unit["version"] = v
    reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(v)
