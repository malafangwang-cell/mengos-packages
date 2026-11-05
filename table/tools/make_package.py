"""写入 mengos-package.json 的 content_hash（WP-W6 §2）：覆盖包内全部文件，清单本身按 content_hash 置空计算。

顺序：改源码 → python lock.py → python tools/make_package.py。
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", "__MACOSX"}   # 与安装器同一口径（WP-W6 §2）
SKIP_FILES = {".DS_Store"}
MANIFEST = "mengos-package.json"


def files():
    """包内全部普通文件，去掉运行环境、缓存与系统杂项；按相对路径的 UTF-8 字节序排列。"""
    out = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if (p.is_file() and not (set(rel.parts) & SKIP_DIRS)
                and p.name not in SKIP_FILES and not p.name.endswith(".pyc")):
            out.append(rel)
    return sorted(out, key=lambda r: r.as_posix().encode("utf-8"))


def content_hash() -> str:
    h = hashlib.sha256()
    for rel in files():
        data = (ROOT / rel).read_bytes()
        if rel.as_posix() == MANIFEST:
            m = json.loads(data)
            m["content_hash"] = ""
            data = json.dumps(m, ensure_ascii=False, indent=2).encode() + b"\n"
        h.update(rel.as_posix().encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


if __name__ == "__main__":
    p = ROOT / MANIFEST
    m = json.loads(p.read_text(encoding="utf-8"))
    m["content_hash"] = ""
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    m["content_hash"] = content_hash()
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(m["content_hash"])
