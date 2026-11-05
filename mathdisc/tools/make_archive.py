"""确定性归档：把包内文件（与 content_hash 同一口径）打成 zip，文件名为其 sha256。

用法：python tools/make_archive.py <输出目录>
同一份源码得到同一字节：固定时间戳、固定权限、按路径字节序、顶层目录 mathdisc-v1/。
"""
import hashlib
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_package import ROOT, files  # noqa: E402

TOP = "mathdisc-v1"
STAMP = (2026, 11, 5, 0, 0, 0)


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "archive.tmp.zip"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files():
            info = zipfile.ZipInfo(f"{TOP}/{rel.as_posix()}", STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            z.writestr(info, (ROOT / rel).read_bytes())
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    final = out_dir / f"{digest}.zip"
    tmp.replace(final)
    return final


if __name__ == "__main__":
    p = build(Path(sys.argv[1]))
    print(p.name, p.stat().st_size)
