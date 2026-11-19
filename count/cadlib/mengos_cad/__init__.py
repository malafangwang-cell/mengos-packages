"""mengos-cad: 刚性格式 (.dxf) 的解析库。存储服务入库与工具读原件共用这一份代码 (设计-附件按引用由工具读取-2026-11-19 §二十一)。
library() 给出解析库版本 = 名字、规格版本、三段式库版本 (../VERSION) 与内容哈希 (代码加依赖清单); 只用标准库, 不导入解析核。"""
import hashlib
import os

NAME = "mengos-cad"
SPEC = "1"   # 解析规格版本, 同 core.SPEC_VERSION 与 ../SPEC.md 头行 (用例钉三者相同)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 进内容哈希的文件 (相对解析库根目录; 顺序即拼接序): 代码、命令行外壳、版本号、依赖清单。依赖清单照旧放在存储服务目录 (vetc/requirements-cad.txt,
# 镜像与 CI 都按这个路径装), 这里按相对路径读。规格文档不进 (规格变必伴随代码变)
HASHED = ("VERSION", "cadx.py", "mengos_cad/__init__.py", "mengos_cad/core.py", "../requirements-cad.txt")


def library():
    """{"name", "spec", "version", "sha256"}; sha256 = 依次对每个文件取 路径 + NUL + 字节 + NUL 拼接后的哈希。"""
    h = hashlib.sha256()
    for rel in HASHED:
        with open(os.path.join(_ROOT, rel), "rb") as f:
            data = f.read()
        h.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    with open(os.path.join(_ROOT, "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    return {"name": NAME, "spec": SPEC, "version": version, "sha256": h.hexdigest()}
