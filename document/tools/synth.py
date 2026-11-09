"""程序生成测试用 PNG（只用 zlib，不依赖 Pillow）：金样、样例、边界测试共用。"""
import base64
import random
import struct
import zlib


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(w: int, h: int, seed: int = 0, noise: bool = False, rgba: bool = False) -> bytes:
    """w×h 的 8 位 RGB（或 RGBA）PNG。默认是可压缩的渐变图案；noise=True 用确定性伪随机噪声（几乎不可压缩）。"""
    bpp = 4 if rgba else 3
    rows = []
    rng = random.Random(seed)
    for y in range(h):
        if noise:
            row = rng.randbytes(w * bpp)             # 确定性伪随机：几乎不可压缩
            if rgba:
                row = bytes(b if i % 4 != 3 else 255 for i, b in enumerate(row))
        else:
            rt = bytes((x * 255 // max(1, w - 1) + seed * 37) % 256 for x in range(w))     # R：横向渐变
            row = bytearray(w * bpp)
            row[0::bpp] = rt
            row[1::bpp] = bytes([(y * 255 // max(1, h - 1)) % 256]) * w                      # G：纵向渐变
            row[2::bpp] = bytes((seed * 71 + (x // 16 + y // 16) * 40) % 256 for x in range(w))   # B：方格
            if rgba:
                row[3::4] = bytes(0 if (x // 8 + y // 8) % 2 else 255 for x in range(w))     # 棋盘状透明
            row = bytes(row)
        rows.append(b"\x00" + row)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6 if rgba else 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + _chunk(b"IEND", b"")


def b64png(*a, **k) -> str:
    return base64.b64encode(png(*a, **k)).decode("ascii")
