"""从 LibreOffice 导出的 PDF 读回每个格的底色与字色（C2 读数用）。

做法：pdftoppm 转 PNG（200 dpi），pdftotext -bbox 找到格里那个数的位置；
底色取数字左侧 4 个点处的像素，字色取数字框里离底色最远的像素。
用法：python3 sample_pdf.py <pdf> <B列要读的值，逗号分隔的 行号=值 …>
输出：一行一个格：格  底色  字色  字重（框内深色像素占比，粗体明显偏高）
"""
import subprocess
import sys
import tempfile
from pathlib import Path
import re

from PIL import Image

DPI = 200
WORD = re.compile(r'<word xMin="([\d.-]+)" yMin="([\d.-]+)" xMax="([\d.-]+)" yMax="([\d.-]+)">([^<]*)</word>')


def words(pdf):
    xml = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, check=True).stdout.decode()
    for m in WORD.finditer(xml):
        yield m.group(5), *(float(m.group(i)) for i in range(1, 5))


def hexc(p):
    return "#%02X%02X%02X" % p[:3]


def main(pdf, cells):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-f", "1", "-l", "1", pdf, f"{d}/p"], check=True)
        im = Image.open(next(Path(d).glob("p*.png"))).convert("RGB")
    k = DPI / 72
    ws = list(words(pdf))
    for label, xr, value in cells:
        hits = [w for w in ws if w[0] == value and xr[0] <= w[1] <= xr[1]]
        t, x0, y0, x1, y1 = hits[label[1]]
        bg = im.getpixel((int((x0 - 4) * k), int((y0 + y1) / 2 * k)))
        box = [im.getpixel((x, y)) for x in range(int(x0 * k), int(x1 * k)) for y in range(int(y0 * k), int(y1 * k))]
        far = max(box, key=lambda p: sum(abs(a - b) for a, b in zip(p, bg)))
        ink = sum(1 for p in box if sum(abs(a - b) for a, b in zip(p, bg)) > 200) / len(box)
        print(f"{label[0]}\t底色 {hexc(bg)}\t字色 {hexc(far)}\t深色占比 {ink:.3f}")


if __name__ == "__main__":
    pdf = sys.argv[1]
    spec = []
    for item in sys.argv[2:]:      # 名称:x起-x止:值:第几个
        name, xs, value, nth = item.split(":")
        a, b = xs.split("-")
        spec.append(((name, int(nth)), (float(a), float(b)), value))
    main(pdf, spec)
