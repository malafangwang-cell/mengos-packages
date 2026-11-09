"""由 Google Fonts 的 Noto Sans SC / Noto Serif SC 可变字体生成随包字体（SIL OFL 1.1）。

只在更新字体时运行（需 dev 依赖 fonttools）：
  python tools/make_fonts.py <NotoSansSC[wght].ttf> <NotoSerifSC[wght].ttf>
做三件事，全部确定、可复现：
  1. 实例化 wght=400（常规）与 wght=700（粗体）：得到静态 TrueType（glyf 轮廓）；
  2. 裁成 GB 2312 全部字符 + ASCII/Latin-1 + 常用标点符号（约 7 千字），去掉提示（hinting）与排版表；
  3. 写入 fonts/，并打印 sha256 供 README 登记。
RFN 说明：OFL 的保留字体名是 “Source”；本包字体仍叫 Noto Sans SC / Noto Serif SC，不含该名。
"""
import hashlib
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

OUT = Path(__file__).resolve().parents[1] / "fonts"
JOBS = [("NotoSansSC", 400, "NotoSansSC-Regular.ttf"), ("NotoSansSC", 700, "NotoSansSC-Bold.ttf"),
        ("NotoSerifSC", 400, "NotoSerifSC-Regular.ttf"), ("NotoSerifSC", 700, "NotoSerifSC-Bold.ttf")]


def charset() -> list[int]:
    cps = set(range(0x20, 0x7F)) | set(range(0xA0, 0x100))
    cps |= set(range(0x2010, 0x2028)) | set(range(0x2030, 0x203C)) | {0x20AC, 0x2103, 0x2116, 0x2122}
    cps |= set(range(0x2150, 0x2190)) | set(range(0x2190, 0x21A0)) | set(range(0x2200, 0x2210)) | {0x2248, 0x2260, 0x2264, 0x2265}
    cps |= set(range(0x2460, 0x2474)) | set(range(0x25A0, 0x25B0)) | {0x2605, 0x2606, 0x2713, 0x2714, 0x2717}
    cps |= set(range(0x3000, 0x3040)) | set(range(0xFF01, 0xFF5F)) | {0xFFE0, 0xFFE1, 0xFFE5}
    for hi in range(0xA1, 0xF8):                      # GB 2312 全部双字节字符
        for lo in range(0xA1, 0xFF):
            try:
                cps.add(ord(bytes([hi, lo]).decode("gb2312")))
            except UnicodeDecodeError:
                pass
    return sorted(cps)


def build(src: Path, weight: int, dst: Path):
    font = TTFont(src, recalcTimestamp=False)
    font = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=False)
    opts = subset.Options()
    opts.layout_features = []
    opts.hinting = False
    opts.glyph_names = False
    opts.notdef_outline = True
    opts.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    opts.drop_tables += ["GSUB", "GPOS", "GDEF", "STAT", "MVAR", "HVAR", "avar", "fvar", "gvar", "cvar", "DSIG", "vhea", "vmtx", "VORG", "meta"]
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=charset())
    sub.subset(font)
    assert "glyf" in font and "CFF " not in font
    fam = dst.stem.split("-")[0]                           # NotoSansSC
    family = {"NotoSansSC": "Noto Sans SC", "NotoSerifSC": "Noto Serif SC"}[fam]
    style = "Bold" if weight == 700 else "Regular"
    for rec in list(font["name"].names):                   # 实例化后名称仍是可变字体的默认实例（Thin/ExtraLight），改成实际字重
        if rec.nameID == 1:
            rec.string = family
        elif rec.nameID == 2:
            rec.string = style
        elif rec.nameID == 4:
            rec.string = f"{family} {style}"
        elif rec.nameID == 6:
            rec.string = f"{fam}-{style}"
        elif rec.nameID == 3:
            rec.string = f"{fam}-{style};subset"
    font["OS/2"].usWeightClass = weight
    font["head"].macStyle = 1 if weight == 700 else 0
    font["OS/2"].fsSelection = (font["OS/2"].fsSelection & ~0x61) | (0x20 if weight == 700 else 0x40)
    font["head"].created = font["head"].modified = 3786825600      # 固定时间戳（2020-01-01），保证每次生成逐字节相同
    font.save(dst)


if __name__ == "__main__":
    srcs = {"NotoSansSC": Path(sys.argv[1]), "NotoSerifSC": Path(sys.argv[2])}
    OUT.mkdir(exist_ok=True)
    for fam, w, name in JOBS:
        build(srcs[fam], w, OUT / name)
        b = (OUT / name).read_bytes()
        print(name, len(b), hashlib.sha256(b).hexdigest())
