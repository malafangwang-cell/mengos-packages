#!/usr/bin/env python3
"""（照 mengosv2 vetc/cadlib/golden/features.py 原样复制，只改夹具库的路径；cad_fixtures.py 照 vetc/tests/helpers/cad_fixtures.py 原样复制。）
金样: 每类图纸特性一份只含该特性的合成图纸 (解析规格 ../SPEC.md §9)。全部内容虚构; 无随机数, 同一版本 ezdxf 下逐字节重生成。
新遇到一类解析库没处理过的特性: 先在这里加一个只含它的生成函数 (此时它应出现在未解析清单里), 再决定是否进规格。"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cad_fixtures as cf  # noqa: E402


def make_unparsed(path):
    """规格未覆盖的对象: 根容器里 POINT×3、RAY×1 (左簇)、XLINE×1 (右簇)、SHAPE×1 (左簇, 走“其余类型”分支);
    图块 MARK 里 POINT×1, 左右各插入一次 (按展开处计, 各归所在单元)。期望: 未解析清单按单元给处数, 对象总数守恒。"""
    d = cf.new_doc(); msp = d.modelspace()
    b = d.blocks.new("MARK")
    b.add_point((0, 0)); b.add_line((0, 0), (10, 0))
    cf.txt(msp, "左簇说明", 0, 0); msp.add_line((0, -10), (100, -10))
    for k in range(3):
        msp.add_point((10 + 10 * k, 20))
    msp.add_ray((0, 30), (1, 0))
    msp.add_shape("MARKSHAPE", (20, 50), 2.5)
    msp.add_blockref("MARK", (50, 40))
    cf.txt(msp, "右簇说明", 5000, 0); msp.add_line((5000, -10), (5100, -10))
    msp.add_xline((5050, 30), (0, 1))
    msp.add_blockref("MARK", (5050, 40))
    d.saveas(path)


def make_nested_owner(path):
    """嵌套插入的归属: 外层块 OUTER 里两层嵌套 (MID → LEAF), 在两个相距很远的位置各直接插入一次 (一次带 90° 旋转);
    期望: 嵌套插入按所属直接插入归单元, 坐标与旋转为世界值, 嵌套层 1、2。"""
    d = cf.new_doc(); msp = d.modelspace()
    leaf = d.blocks.new("LEAF"); leaf.add_circle((0, 0), 2)
    mid = d.blocks.new("MID"); mid.add_blockref("LEAF", (5, 0)); mid.add_line((0, 0), (10, 0))
    out = d.blocks.new("OUTER"); out.add_blockref("MID", (0, 20)); out.add_blockref("LEAF", (30, 0)); out.add_line((0, 0), (40, 0))
    cf.txt(msp, "甲处", 0, -20); msp.add_blockref("OUTER", (0, 0))
    cf.txt(msp, "乙处", 6000, -20); msp.add_blockref("OUTER", (6000, 0), dxfattribs={"rotation": 90})
    d.saveas(path)


def make_seg_exact(path):
    """线段明细的数值写法: 长度不取整 (71、74、70.5、0.25), 坐标三位小数 (0.001 级偏移), 斜线与零长线段。"""
    d = cf.new_doc(); msp = d.modelspace()
    cf.txt(msp, "线长样例", 0, 120)
    for k, L in enumerate((71, 74, 70.5, 0.25)):
        msp.add_line((10 * k, 0), (10 * k, L), dxfattribs={"layer": "COL"})
    msp.add_line((100.0004, 5.0006), (130.0004, 45.0006), dxfattribs={"layer": "OBL"})
    msp.add_line((200, 0), (200, 0), dxfattribs={"layer": "ZERO"})
    d.saveas(path)


MAKERS = {"f_unparsed": make_unparsed, "f_nested_owner": make_nested_owner, "f_seg_exact": make_seg_exact}

if __name__ == "__main__":
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    for n in (sys.argv[2:] or list(MAKERS)):
        MAKERS[n](os.path.join(out, n + ".dxf"))
