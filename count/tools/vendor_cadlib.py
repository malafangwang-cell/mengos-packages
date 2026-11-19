#!/usr/bin/env python3
"""按“版本加哈希”带入解析库 mengos-cad（设计-附件按引用由工具读取-2026-11-19 §21.3、§21.6）。

用法：python tools/vendor_cadlib.py <mengosv2 仓>/vetc/cadlib --version 1.0.0 --sha256 <内容哈希>
  从存储服务的解析库目录逐字节拷入 cadlib/（VERSION、cadx.py、mengos_cad/__init__.py、mengos_cad/core.py）
  与 requirements-cad.txt（解析库内容哈希按 ../requirements-cad.txt 计入，故放在 cadlib/ 的上一级），
  再用带入的那一份解析库重算 library()，版本与哈希须与命令行给的相同，否则不写、退出 1。
  写 cadlib.lock.json：解析库的名字、规格版本、库版本、内容哈希与逐文件 sha256。
只带入代码与依赖清单，不带金样与规格文档（不进内容哈希）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("VERSION", "cadx.py", "mengos_cad/__init__.py", "mengos_cad/core.py")


def library_of(root: str) -> dict:
    """在子进程里导入 root/mengos_cad 取 library()（只用标准库，不导入解析核）。"""
    code = "import json,sys; sys.path.insert(0, sys.argv[1]); from mengos_cad import library; print(json.dumps(library()))"
    out = subprocess.run([sys.executable, "-I", "-B", "-c", code, root], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--version", required=True)
    ap.add_argument("--sha256", required=True)
    a = ap.parse_args(argv)
    src = os.path.abspath(a.src)
    with tempfile.TemporaryDirectory() as tmp:
        stage = os.path.join(tmp, "count")
        for rel in FILES:
            os.makedirs(os.path.dirname(os.path.join(stage, "cadlib", rel)), exist_ok=True)
            shutil.copyfile(os.path.join(src, rel), os.path.join(stage, "cadlib", rel))
        shutil.copyfile(os.path.join(src, "..", "requirements-cad.txt"), os.path.join(stage, "requirements-cad.txt"))
        lib = library_of(os.path.join(stage, "cadlib"))
        if lib["version"] != a.version or lib["sha256"] != a.sha256:
            print(f"带入的解析库是 {lib['version']} {lib['sha256']}，与要求的 {a.version} {a.sha256} 不同，不写", file=sys.stderr)
            return 1
        dst = os.path.join(HERE, "cadlib")
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(os.path.join(stage, "cadlib"), dst)
        shutil.copyfile(os.path.join(stage, "requirements-cad.txt"), os.path.join(HERE, "requirements-cad.txt"))
    files = {f"cadlib/{rel}": hashlib.sha256(open(os.path.join(HERE, "cadlib", rel), "rb").read()).hexdigest() for rel in FILES}
    files["requirements-cad.txt"] = hashlib.sha256(open(os.path.join(HERE, "requirements-cad.txt"), "rb").read()).hexdigest()
    lock = {**lib, "files": files}
    with open(os.path.join(HERE, "cadlib.lock.json"), "w", encoding="utf-8") as f:
        json.dump(lock, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(lib, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
