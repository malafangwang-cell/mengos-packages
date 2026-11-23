"""计算 lock hash（TL-6 version）：覆盖执行体源文件、依赖声明、锁文件、登记资产，以及清单的 norms 与 for。

与引擎 recomputeToolsLock（mengosv2 engine/tools/installer/registry.ts）同构：
  covers 文件按序 ⟨文件名\\0字节\\0⟩ → ⟨registration.json\\0 规范形(自引用置空)\\0⟩ → ⟨(norms)\\0 规范形\\0⟩ → ⟨(for)\\0 规范形\\0⟩。
规范形：键排序、紧凑分隔、不转义非 ASCII。条文与工具同 lock（17 TL-25、TL-31 ①⑩），改任一条条文工具 version 随变。
缺席文件按空字节计会静默算错，所以这里缺文件直接报错。
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCES = ["text.py", "layout.py", "rack_tool.py", "pyproject.toml", "uv.lock"]


def _canon(v) -> bytes:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _registration_bytes() -> bytes:
    reg = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    reg["lock_hash"] = ""
    for unit in reg["units"]:
        unit["version"] = ""
    return _canon(reg)


def lock_hash() -> str:
    manifest = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
    h = hashlib.sha256()
    for name in SOURCES:
        h.update(name.encode() + b"\0" + (ROOT / name).read_bytes() + b"\0")
    h.update(b"registration.json\0" + _registration_bytes() + b"\0")
    if "norms" in manifest:
        h.update(b"(norms)\0" + _canon(manifest["norms"]) + b"\0")
    if "for" in manifest:
        h.update(b"(for)\0" + _canon(manifest["for"]) + b"\0")
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
