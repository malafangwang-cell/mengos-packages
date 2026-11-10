"""带私有提示词的包的构建与测试入口（立法者 2026-11-10：提示词不公开）。

写给模型的提示词放在私有仓库 malafangwang-cell/mengos-package-prompts，不在本仓库。
本脚本从环境变量 MENGOS_PACKAGE_PROMPTS_DIR 指向的私有仓库本地副本取提示词，按
prompts.lock.json 核对 sha256，把包拷到工作区之外的临时目录、放入提示词，在那里调用
包自带的脚本（lock.py、tools/make_package.py、tools/make_archive.py、tools/run_golden.py、
tests/）。跑完不论成败都把临时目录整个删掉，工作区里不留提示词副本。包内文件一个不改，
所以 content_hash、lock hash 与改造前相同。

缺提示词、sha 不符、工作区里残留提示词副本，一律报错退出（退出码 2），不跳过，也不放占位。
本脚本不打印提示词原文。

用法（在仓库根目录）：
  export MENGOS_PACKAGE_PROMPTS_DIR=/path/to/mengos-package-prompts
  python tools/pkgbuild.py verify  mathdisc            # 核对 content_hash 与 lock_hash 和登记值一致
  python tools/pkgbuild.py test    mathdisc            # uv sync --frozen 后跑 pytest tests（pytest 不在包依赖里，用 --with 临时带上）与 tools/run_golden.py
  python tools/pkgbuild.py archive mathdisc <输出目录>  # 确定性归档；输出目录不得在本仓库内
  python tools/pkgbuild.py regen   mathdisc            # 改源码后重生成登记与清单，写回 registration.json、mengos-package.json

不要在工作区直接跑包内的 lock.py 或 tools/make_package.py：包内 lock.py 遇到缺文件时按空内容计算，
会静默写出错误的 lock hash。
"""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCK = json.loads((REPO / "prompts.lock.json").read_text(encoding="utf-8"))
ENV = LOCK["env"]
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", "__MACOSX"}   # 与包内 make_package.py 同一口径
SKIP_FILES = {".DS_Store"}


class BuildError(Exception):
    pass


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _entries(pkg: str):
    if pkg not in LOCK["packages"]:
        raise BuildError(f"{pkg} 在 prompts.lock.json 里没有登记提示词；不带提示词的包直接用包内脚本")
    return LOCK["packages"][pkg]


def _prompts_dir() -> Path:
    raw = os.environ.get(ENV, "").strip()
    if not raw:
        raise BuildError(f"未设置 {ENV}。提示词不公开，构建需要私有仓库 "
                         "malafangwang-cell/mengos-package-prompts 的本地副本，并把该变量指向它")
    d = Path(raw).expanduser().resolve()
    if not d.is_dir():
        raise BuildError(f"{ENV} 指向的目录不存在：{d}")
    return d


def _check_workspace_clean(pkg: str):
    for e in _entries(pkg):
        p = REPO / pkg / e["path"]
        if p.exists():
            raise BuildError(f"工作区里有提示词副本 {p.relative_to(REPO)}，提示词不得留在公开仓库，请先删除")


def _ignore(_dir, names):
    return [n for n in names if n in SKIP_DIRS or n in SKIP_FILES or n.endswith(".pyc")]


class Staged:
    """把包拷进工作区之外的临时目录并放入提示词；退出时整个删掉。"""

    def __init__(self, pkg: str):
        self.pkg = pkg

    def __enter__(self) -> Path:
        entries = _entries(self.pkg)
        src_dir = _prompts_dir()
        _check_workspace_clean(self.pkg)
        sources = []
        for e in entries:
            src = src_dir / e["private"]
            if not src.is_file():
                raise BuildError(f"私有提示词仓库里缺 {e['private']}（{ENV}={src_dir}）")
            got = _sha256(src)
            if got != e["sha256"]:
                raise BuildError(f"{e['private']} 的 sha256 是 {got}，"
                                 f"与 prompts.lock.json 登记的 {e['sha256']} 不符")
            sources.append((src, e))
        self.tmp = Path(tempfile.mkdtemp(prefix="mengos-pkgbuild-"))
        root = self.tmp / self.pkg
        shutil.copytree(REPO / self.pkg, root, ignore=_ignore)
        for src, e in sources:
            dst = root / e["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            if _sha256(dst) != e["sha256"]:
                raise BuildError(f"放入临时目录后 {e['path']} 的 sha256 不符")
        return root

    def __exit__(self, *exc):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.tmp.exists():
            print(f"警告：临时目录 {self.tmp} 未能删净，内含提示词，请手动删除", file=sys.stderr)
        return False


def _run(cmd, cwd: Path, env=None):
    p = subprocess.run(cmd, cwd=str(cwd), env=env)
    if p.returncode != 0:
        raise BuildError(f"命令失败（退出码 {p.returncode}）：{' '.join(map(str, cmd))}")


_HASHES = (
    "import json, sys; sys.path[:0] = ['tools', '.']\n"
    "import make_package, lock\n"
    "print(json.dumps({'content_hash': make_package.content_hash(), 'lock_hash': lock.lock_hash()}))\n"
)


def _hashes(root: Path) -> dict:
    out = subprocess.run([sys.executable, "-I", "-c", _HASHES], cwd=str(root), capture_output=True, text=True)
    if out.returncode != 0:
        raise BuildError("计算 hash 失败：\n" + out.stderr[-2000:])
    return json.loads(out.stdout)


def _verify(root: Path) -> dict:
    got = _hashes(root)
    want = {
        "content_hash": json.loads((root / "mengos-package.json").read_text(encoding="utf-8"))["content_hash"],
        "lock_hash": json.loads((root / "registration.json").read_text(encoding="utf-8"))["lock_hash"],
    }
    for k in ("content_hash", "lock_hash"):
        mark = "一致" if got[k] == want[k] else "不一致"
        print(f"{k}: 实测 {got[k]} / 登记 {want[k]} → {mark}")
    if got != want:
        raise BuildError("hash 与登记值不一致")
    return got


def cmd_verify(a):
    with Staged(a.pkg) as root:
        _verify(root)


def cmd_test(a):
    with Staged(a.pkg) as root:
        _verify(root)
        env = dict(os.environ)
        env.pop("UV_PROJECT_ENVIRONMENT", None)   # 环境建在临时目录里，随之删除
        _run(["uv", "sync", "--frozen", "--quiet"], root, env)
        _run(["uv", "run", "--frozen", "--with", "pytest", "python", "-m", "pytest", "tests", "-q", "--tb=line",
              "-p", "no:cacheprovider"], root, env)
        _run(["uv", "run", "--frozen", "python", "tools/run_golden.py"], root, env)


def cmd_archive(a):
    out = Path(a.out_dir).expanduser().resolve()
    if out == REPO or REPO in out.parents:
        raise BuildError(f"输出目录 {out} 在本仓库内；归档含提示词原文，不得放进公开仓库工作区")
    with Staged(a.pkg) as root:
        _verify(root)
        _run([sys.executable, "-I", "tools/make_archive.py", str(out)], root)


def cmd_regen(a):
    with Staged(a.pkg) as root:
        for script in ("tools/make_registration.py", "lock.py", "tools/make_package.py"):
            if (root / script).is_file():
                _run([sys.executable, "-I", script], root)
        _verify(root)
        for name in ("registration.json", "mengos-package.json"):
            shutil.copyfile(root / name, REPO / a.pkg / name)
            print(f"已写回 {a.pkg}/{name}")


def _on_signal(signum, _frame):
    raise SystemExit(128 + signum)   # 让 Staged.__exit__ 照常删临时目录


def main():
    signal.signal(signal.SIGTERM, _on_signal)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("verify", cmd_verify), ("test", cmd_test), ("regen", cmd_regen)):
        s = sub.add_parser(name)
        s.add_argument("pkg")
        s.set_defaults(fn=fn)
    s = sub.add_parser("archive")
    s.add_argument("pkg")
    s.add_argument("out_dir")
    s.set_defaults(fn=cmd_archive)
    a = ap.parse_args()
    try:
        a.fn(a)
    except BuildError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
