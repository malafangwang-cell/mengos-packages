"""按文件读的测试与金样用的附件夹具：生成合成图纸，用包里带的解析库出完整解析结构，摆成引擎交文件后的样子。

引擎（17 TL-9d）在派单时把原件与解析结构放进工作目录下的只读输入子目录，把 source.file 换成
{path, sha256, bytes, media_type, parsed: {path, sha256, parser}}。这里照这个形状摆，供 tests/ 与 tools/run_golden.py 共用。
图纸全部由 tests/fixtures/dxf_gen/ 的生成器（mengosv2 现成的合成金样生成器的副本）现场生成，不入仓、不含真图。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN = os.path.join(ROOT, "tests", "fixtures", "dxf_gen")
INPUT_DIR = "in"
MEDIA_TYPE = "image/vnd.dxf"


def _env():
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}


def generate(name: str, out_dir: str) -> str:
    """name 以 f_ 开头取 features.py，其余取 cad_fixtures.py（如 d1、rack、ublk）→ dxf 路径。"""
    os.makedirs(out_dir, exist_ok=True)
    script, arg = (("features.py", name) if name.startswith("f_") else ("cad_fixtures.py", name))
    subprocess.run([sys.executable, os.path.join(GEN, script), out_dir, arg], check=True, capture_output=True, env=_env())
    p = os.path.join(out_dir, arg + ".dxf")
    if not os.path.exists(p):
        raise FileNotFoundError(p)
    return p


def parse(dxf: str, out_dir: str, fid: str) -> str:
    """包里带的解析库命令行（与存储服务入库同一调用，--parsed）→ parsed.json 路径。"""
    p = subprocess.run([sys.executable, os.path.join(ROOT, "cadlib", "cadx.py"), dxf, out_dir, "--fid", fid, "--parsed"],
                       capture_output=True, env=_env())
    if p.returncode != 0:
        raise RuntimeError(p.stdout.decode("utf-8", "replace")[-400:])
    return os.path.join(out_dir, "parsed.json")


def parser_of(parsed_path: str) -> str:
    lib = json.load(open(parsed_path, encoding="utf-8"))["library"]
    return f"{lib['name']}@{lib['version']}+sha256:{lib['sha256']}"


def sha256(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def stage(workdir: str, dxf: str, parsed: str | None) -> dict:
    """把原件（与解析结构）放进 workdir/in/，返回替换后的 source.file 对象（path 相对 workdir）。"""
    d = os.path.join(workdir, INPUT_DIR)
    os.makedirs(d, exist_ok=True)
    shutil.copyfile(dxf, os.path.join(d, "1.dxf"))
    f = {"path": f"{INPUT_DIR}/1.dxf", "sha256": sha256(dxf), "bytes": os.path.getsize(dxf), "media_type": MEDIA_TYPE}
    if parsed is not None:
        shutil.copyfile(parsed, os.path.join(d, "1.parsed.json"))
        f["parsed"] = {"path": f"{INPUT_DIR}/1.parsed.json", "sha256": sha256(parsed), "parser": parser_of(parsed)}
    return f


class Fixture:
    """一份夹具：生成并解析一次，可按需摆出“带解析结构 / 只有原件”两种工作目录。"""

    def __init__(self, name: str, base: str | None = None):
        self.name = name
        self.base = base or tempfile.mkdtemp(prefix=f"count-fx-{name}-")
        self.dxf = generate(name, os.path.join(self.base, "gen"))
        self.parsed = parse(self.dxf, os.path.join(self.base, "parsed"), "fx-" + name)

    def workdir(self, with_parsed: bool = True) -> tuple[str, dict]:
        wd = tempfile.mkdtemp(prefix="wd-", dir=self.base)
        return wd, stage(wd, self.dxf, self.parsed if with_parsed else None)

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)
