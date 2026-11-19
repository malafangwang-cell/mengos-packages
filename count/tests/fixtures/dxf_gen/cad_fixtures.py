#!/usr/bin/env python3
"""合成 DXF 样本生成器 (CAD 抽取支 d 的测试夹具; 不入真图)。无随机数; 同一版本 ezdxf 下两次生成逐字节相同。
用法: python3 cad_fixtures.py OUTDIR [NAME ...]
  d1.dxf      D1 类: 6 个图幅 (4 个闭合多段线图框、2 个散线图框)、线画标题栏、1 张带合并格的 ACAD_TABLE、框外说明、尺寸、图块插入
  d2.dxf      D2 类: 无图框, 4 簇内容之间有留白, 一条贯通全图的长线 (桥), 一个块基点远离几何的插入
  d1_big.dxf  D1 类的大图幅: 单图幅文字远超单元上限 B 以验证按行块再切
  d1_huge.dxf D1 类 6 个大图幅: 总字数超过 CAD 整份随附阈值 (30 万字), 多分片 (立法者 2026-11-18 顺序随附用例)
  d1_old.dxf  同 d1 但 $ACADVER 写成 AC1015 (早于 AC1018)
  bomb.dxf    指数嵌套: 展开插入 1,111,111 次 (E=4,000,000), 默认 I_max 下 5 s 内拒收
  selfref.dxf 图块自引用 (CAD_BLOCK_CYCLE)
  deep.dxf    嵌套 13 层 (CAD_NESTING_TOO_DEEP)
  empty.dxf   0 个实体 (CAD_EMPTY)
  med.dxf     中等规模 (展开约 60 万线段), 供 RLIMIT_AS 干净失败用例
  tol.dxf     带 TOLERANCE 实体 (形位公差)
  e5.dxf      E-CAD5: GDT 公差、GDT 字体文字、*U 回溯、代理实体
  utab.dxf    E-CAD8 必修: 表只在未插入图块里
  ublk.dxf    R2000 非 ASCII 块名的未插入块 (\\U+ 转义)
  dwgmagic.dxf 文件头是 DWG 魔数 AC1032 的假 .dxf
  rack.dxf    计数工具夹具 F1 (设计-确定性计数工具-2026-11-18 §八): 33 列 × 10 层 × 前后 2 排, 同名图块等距插入 660 次
              (x 步长 2760, y 向 20 个位置: 每排 10 层步长 1500, 两排之间 900); 尺寸串 33*2760=91080 (测量值 91080);
              12 段、每段 2760 的连续尺寸链; 图层 COL_A、COL_B 各 1100 根同长竖线 (10275、11250)
  rack_gap.dxf   F2: F1 抽掉 3 个插入 (缺位)
  rack_bad.dxf   F3: F1 的尺寸串写成 33*2760=91000 (不自洽)
  rack_long.dxf  F4: F1 加 3000 条填充文字, 单元超长被按行块切成 3 块, 图块插入一节跨块
"""
import os, sys
import ezdxf
from ezdxf.enums import TextEntityAlignment

ezdxf.options.write_fixed_meta_data_for_testing = True
H = 5  # 字高: 全图文字字高中位数


def new_doc(ver="R2010"):
    d = ezdxf.new(ver, setup=True)
    d.header["$INSUNITS"] = 4
    d.header["$TDCREATE"] = 2461000.5
    d.header["$TDUPDATE"] = 2461000.5
    return d


def txt(msp, s, x, y, h=H, layer="TEXT"):
    t = msp.add_text(s, height=h, dxfattribs={"layer": layer})
    t.set_placement((x, y), align=TextEntityAlignment.LEFT)
    return t


def rect_poly(msp, x0, y0, x1, y1, layer="FRAME"):
    return msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer})


def rect_lines(msp, x0, y0, x1, y1, layer="FRAME"):
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        msp.add_line(a, b, dxfattribs={"layer": layer})


def title_block(msp, x1, y0, no, name, scale="1:50", n=6, k=1):
    """右下角 4×4 线画标题栏 (格宽 40, 高 10), 右下角 = (x1, y0)。"""
    cw, ch = 40, 10
    xs = [x1 - 4 * cw + i * cw for i in range(5)]
    ys = [y0 + j * ch for j in range(5)]
    for x in xs:
        msp.add_line((x, ys[0]), (x, ys[-1]), dxfattribs={"layer": "TB"})
    for y in ys:
        msp.add_line((xs[0], y), (xs[-1], y), dxfattribs={"layer": "TB"})
    rows = [  # 自上而下
        ["图号", no, "比例", scale],
        ["图名", name, "设计", "张三"],
        ["校对", "李四", "审核", "王五"],
        ["日期", "2026-11-01", "页", f"共{n}张 第{k}张"],
    ]
    for r, row in enumerate(rows):
        y = ys[3 - r]
        for c, v in enumerate(row):
            txt(msp, v, xs[c] + 2, y + 2)


def sheet_content(doc, msp, ox, oy, i):
    msp.add_blockref("BOLT", (ox + 60, oy + 200), dxfattribs={"layer": "PART"}).add_auto_attribs({"SPEC": f"M{8 + i}"})
    txt(msp, f"技术要求{i + 1}：未注倒角C1", ox + 30, oy + 260)
    txt(msp, f"材料 Q235B 件{i + 1}", ox + 30, oy + 240)
    txt(msp, f"孔径 {10 + i} 通孔", ox + 30, oy + 220)
    rect_poly(msp, ox + 100, oy + 100, ox + 130, oy + 120, layer="OUTLINE")
    msp.add_line((ox + 100, oy + 100), (ox + 200, oy + 60), dxfattribs={"layer": "OUTLINE"})
    d = msp.add_linear_dim(base=(ox + 100, oy + 80), p1=(ox + 100, oy + 100), p2=(ox + 200, oy + 100), dimstyle="EZDXF",
                           override={"dimtxt": H, "dimasz": 2, "dimexe": 1, "dimexo": 1, "dimdec": 0}, dxfattribs={"layer": "DIM"})
    d.render()


def acad_table_tags(x, y):
    """3×3 ACAD_TABLE: 第 0 行首格横向合并 3 列 (175=3), 被覆盖格 173=1 且文字为空。"""
    cells = [  # (合并列跨, 合并行跨, 被覆盖, 文字)
        (3, 1, False, "材料表"), (1, 1, True, ""), (1, 1, True, ""),
        (1, 1, False, "序号"), (1, 1, False, "材质"), (1, 1, False, "重量"),
        (1, 1, False, "1"), (1, 1, False, "Q235B"), (1, 1, False, "12.5"),
    ]
    t = [(0, "ACAD_TABLE"), (5, "ABCDE0"), (100, "AcDbEntity"), (8, "TABLE"), (100, "AcDbBlockReference"), (2, "*T1"),
         (10, x), (20, y), (30, 0.0), (100, "AcDbTable"), (280, 0), (11, 1.0), (21, 0.0), (31, 0.0), (91, 3), (92, 3)]
    for w, h, cov, text in cells:
        t += [(171, 1), (173, 1 if cov else 0), (175, w), (176, h), (1, text)]
    return t


def inject_table(path, x, y):
    raw = open(path, encoding="utf-8").read()
    marker = "  0\nENDSEC\n  0\nSECTION\n  2\nOBJECTS"
    i = raw.index(marker)
    body = "".join(f"{c:3d}\n{v}\n" for c, v in acad_table_tags(x, y))
    open(path, "w", encoding="utf-8", newline="\n").write(raw[:i] + body + raw[i:])


def make_d1(path, ver="R2010", n=6, texts_per=0):
    doc = new_doc(ver)
    b = doc.blocks.new("BOLT")
    b.add_circle((0, 0), 4, dxfattribs={"layer": "PART"})
    b.add_line((-6, 0), (6, 0), dxfattribs={"layer": "PART"})
    b.add_attdef("SPEC", insert=(0, 6), height=H, dxfattribs={"layer": "PART"})
    msp = doc.modelspace()
    for i in range(n):
        ox, oy = (i % 3) * 520, -(i // 3) * 400
        W, Hh = 420, 297
        if i < 4:
            rect_poly(msp, ox, oy, ox + W, oy + Hh)
        else:
            rect_lines(msp, ox, oy, ox + W, oy + Hh)
        title_block(msp, ox + W, oy, f"TX-{i + 1:02d}", f"测试零件{i + 1}", n=n, k=i + 1)
        sheet_content(doc, msp, ox, oy, i)
        for t in range(texts_per):
            txt(msp, f"说明行{t:05d} 本行用于撑大单元并验证按行块再切", ox + 30 + (t % 5) * 70, oy + 160 - (t // 5) % 12 * 6)
    txt(msp, "总说明：本图所有尺寸单位为毫米", 0, -1000)
    txt(msp, "图例：见各图幅", 0, -1100)
    doc.saveas(path)
    if ver not in ("R12", "R2000"):  # AC1015 及更早没有表格对象
        inject_table(path, 150, 150)  # 落在第 1 图幅内


def make_d2(path):
    doc = new_doc()
    for nm, off in (("PIPE", 0), ("VALVE", 0), ("FAR", 5000)):
        b = doc.blocks.new(nm)
        b.add_line((off, 0), (off + 80, 0)); b.add_line((off + 80, 0), (off + 80, 40)); b.add_circle((off + 40, 20), 10)
    msp = doc.modelspace()
    for k in range(4):
        ox = k * 2000
        txt(msp, f"视图{k + 1}", ox, 200)
        for j in range(5):  # 文字行距 8 < g=15: 同簇内部没有宽 ≥ g 的空带
            txt(msp, f"构件{k + 1}-{j + 1} 规格 DN{50 + j}", ox, 190 - j * 8)
        for r in range(3):  # 构件网格: 块宽 80 高 40, 间距 5
            for c in range(10):
                msp.add_blockref("PIPE" if (r + c) % 2 else "VALVE", (ox + 70 + c * 85, 40 + r * 45), dxfattribs={"layer": "PART"})
    msp.add_blockref("FAR", (-80, 40), dxfattribs={"layer": "PART"})  # 基点远离几何 (在原点附近); 几何落在第 3 簇网格右端 (x≈4920..5000, 与网格同高)
    msp.add_line((-100, -30), (7000, -30), dxfattribs={"layer": "AXIS"})  # 贯通全图的长线 (桥)
    doc.saveas(path)


def make_bomb(path):
    d = new_doc("R2007")
    leaf = d.blocks.new("L6")
    for k in range(4):
        leaf.add_line((0, k), (10, k))
    for lv in range(5, -1, -1):
        bb = d.blocks.new(f"L{lv}")
        for k in range(10):
            bb.add_blockref(f"L{lv + 1}", (k * 20 ** (6 - lv), 0))
    d.modelspace().add_blockref("L0", (0, 0))
    d.saveas(path)


def make_selfref(path):
    d = new_doc("R2007"); s = d.blocks.new("SELF")
    s.add_line((0, 0), (100, 0)); s.add_blockref("SELF", (10, 10))
    d.modelspace().add_blockref("SELF", (0, 0))
    d.saveas(path)


def make_deep(path, depth=13):
    d = new_doc("R2007")
    d.blocks.new(f"N{depth}").add_line((0, 0), (1, 1))
    for lv in range(depth - 1, 0, -1):
        d.blocks.new(f"N{lv}").add_blockref(f"N{lv + 1}", (1, 1))
    d.modelspace().add_blockref("N1", (0, 0))
    d.saveas(path)


def make_empty(path):
    new_doc("R2007").saveas(path)


def make_med(path):
    d = new_doc("R2007"); b = d.blocks.new("DECK")
    for k in range(300):
        b.add_line((k * 10, 0), (k * 10, 5000))
    msp = d.modelspace()
    for i in range(40):
        for j in range(50):
            msp.add_blockref("DECK", (i * 4000, j * 6000))
    txt(msp, "med", 0, 0)
    d.saveas(path)


def make_tol(path):
    doc = new_doc()
    msp = doc.modelspace()
    txt(msp, "公差样例", 0, 0)
    msp.add_line((0, -10), (100, -10))
    msp.new_entity("TOLERANCE", {"insert": (10, 20, 0), "layer": "TEXT", "dimstyle": "EZDXF",
                                 "content": "{\\Fgdt;j}%%v{\\Fgdt;n}0.05{\\Fgdt;m}%%vA%%vB^J{\\Fgdt;a}%%v0.02"})
    doc.saveas(path)


def make_e5(path):
    """E-CAD5 夹具: GDT 公差译码 (块内 3 处展开 + 表外码)、GDT 字体文字、*U 的 BTag/RepData 回溯、拆不出图元的代理实体。"""
    from ezdxf.lldxf.types import DXFTag
    from ezdxf.lldxf.tags import Tags
    doc = new_doc()
    msp = doc.modelspace()
    doc.styles.add("AMGDT", font="amgdt.shx")
    txt(msp, "e5", 0, 0)
    msp.add_line((0, -10), (100, -10))
    # 块 TB1 里一条公差, 模型空间插入 3 次 -> 展开 3 处
    tb = doc.blocks.new("TB1")
    tb.add_line((0, 0), (10, 0))
    tb.new_entity("TOLERANCE", {"insert": (1, 2, 0), "layer": "TEXT", "dimstyle": "EZDXF", "content": "{\\Fgdt;i}%%v0.5%%v%%vC%%v%%v"})
    for k in range(3):
        msp.add_blockref("TB1", (100 * k, 50))
    # 根空间: 位置度复合 (两行) 与表外码 z
    msp.new_entity("TOLERANCE", {"insert": (300, 20, 0), "layer": "TEXT", "dimstyle": "EZDXF",
                                 "content": "{\\Fgdt;j}%%v{\\Fgdt;n}0.05{\\Fgdt;m}%%v%%vA%%vB{\\Fgdt;m}%%vC"})
    msp.new_entity("TOLERANCE", {"insert": (300, 40, 0), "layer": "TEXT", "dimstyle": "EZDXF", "content": "{\\Fgdt;z}%%v1"})
    # GDT 字体文字: 根 1 处 + 块 GB 内 1 处 × 插入 2 = 3
    t = msp.add_text("f", height=H, dxfattribs={"layer": "TEXT", "style": "AMGDT"}); t.set_placement((400, 0), align=TextEntityAlignment.LEFT)
    gb = doc.blocks.new("GB")
    gt = gb.add_text("b", height=H, dxfattribs={"layer": "TEXT", "style": "AMGDT"}); gt.set_placement((0, 0), align=TextEntityAlignment.LEFT)
    for k in range(2):
        msp.add_blockref("GB", (400 + 50 * k, 60))
    # *U: DYN 为原动态块; *U1 BTag->DYN; *U2 无信息; *U3 BTag->*U1 (链); *U4 只有 RepData(INSERT 扩展字典)->DYN
    dyn = doc.blocks.new("DYN"); dyn.add_line((0, 0), (5, 5))
    h_dyn = doc.block_records.get("DYN").dxf.handle
    for nm in ("*U1", "*U2", "*U3", "*U4"):
        b = doc.blocks.new(nm); b.add_circle((0, 0), 2)
    doc.block_records.get("*U1").set_xdata("AcDbBlockRepBTag", [(1070, 1), (1005, h_dyn)])
    doc.block_records.get("*U3").set_xdata("AcDbBlockRepBTag", [(1070, 1), (1005, doc.block_records.get("*U1").dxf.handle)])
    for k, nm in enumerate(("*U1", "*U2", "*U3", "*U4")):
        ins = msp.add_blockref(nm, (500 + 30 * k, 100))
        if nm == "*U4":
            xd = ins.new_extension_dict()
            d1 = xd.add_dictionary("AcDbBlockRepresentation")
            rep = doc.objects.add_dxf_object_with_reactor("ACDB_BLOCKREPRESENTATION_DATA", {"owner": d1.dxf.handle})
            rep_h = rep.dxf.handle
            d1.add("AcDbRepData", rep)
    # 代理实体: 块 PX 里 1 个 (无图形, 拆不出), 模型空间插入 2 次; 未插入块 NOUSE 里 1 个
    for nm in ("PX", "NOUSE"):
        b = doc.blocks.new(nm); b.add_line((0, 0), (1, 1))
        e = b.new_entity("ACAD_PROXY_ENTITY", {"layer": "0"})
        e.acdb_proxy_entity = Tags([DXFTag(100, "AcDbProxyEntity"), DXFTag(90, 498), DXFTag(91, 500)])
    from ezdxf.entities.dxfclass import DXFClass
    c = DXFClass.new(); c.dxf.name = "AEC_X"; c.dxf.cpp_class_name = "TH_PARAM_BASE"; c.dxf.app_name = "THCAD"
    doc.classes.register(c)
    for k in range(2):
        msp.add_blockref("PX", (700 + 20 * k, 0))
    doc.saveas(path)
    # ezdxf 把未知对象写成 DXFENTITY; 按真实 DXF 的形态改回 ACDB_BLOCKREPRESENTATION_DATA 并补组码 340 (原动态块块记录句柄)
    import re
    t = open(path, encoding="utf-8").read()
    pat = re.compile(r"  0\nDXFENTITY\n  5\n%s\n((?:102\n\{ACAD_REACTORS\n330\n\w+\n102\n\}\n)?330\n\w+\n)" % rep_h)
    t2, n = pat.subn(lambda m: "  0\nACDB_BLOCKREPRESENTATION_DATA\n  5\n%s\n%s100\nAcDbBlockRepresentationData\n340\n%s\n" % (rep_h, m.group(1), h_dyn), t)
    assert n == 1
    open(path, "w", encoding="utf-8", newline="\n").write(t2)


def make_utab(path):
    """E-CAD8 必修: 表只在未插入的图块 TBLK 里 (块内另有 1 条文字); 模型空间只有一段线与一条文字。L-1 首发不读该块, 但总览须如实声明。"""
    doc = new_doc()
    msp = doc.modelspace()
    txt(msp, "主图", 0, 0)
    msp.add_line((0, -10), (100, -10))
    b = doc.blocks.new("TBLK")
    txt(b, "块内说明", 0, 50)
    doc.saveas(path)
    raw = open(path, encoding="utf-8").read()
    i = raw.index("\n  2\nTBLK\n", raw.index("\n  2\nBLOCKS\n"))  # BLOCKS 段里的块定义 (不是 BLOCK_RECORD 表项)
    j = raw.index("  0\nENDBLK\n", i)
    body = "".join(f"{c:3d}\n{v}\n" for c, v in acad_table_tags(10, 20))
    open(path, "w", encoding="utf-8", newline="\n").write(raw[:j] + body + raw[j:])


def make_ublk(path):
    """验收 11-04 必修 2: R2000 (AC1015) 文件里块名非 ASCII 的未插入块 “图框库” (DXF 里写成 \\U+ 转义), 块内 2 条文字。"""
    doc = new_doc("R2000")
    msp = doc.modelspace()
    txt(msp, "主图", 0, 0)
    msp.add_line((0, -10), (100, -10))
    b = doc.blocks.new("图框库")
    txt(b, "甲", 0, 0)
    txt(b, "乙", 0, 10)
    doc.saveas(path)


RACK_BLOCK = "awegewye4ry4"   # 无意义块名 (真图常见), 工具与测试都不认块名的含义
RACK_GAPS = ((5, 3), (17, 10), (30, 19))   # F2 抽掉的 (列, y 位置序号)


def rack_ys():
    """y 向 20 个位置: 前排 10 层 0..13500 步长 1500, 后排从 14400 起 (两排之间 900)。"""
    return [1500 * k for k in range(10)] + [14400 + 1500 * k for k in range(10)]


def make_rack(path, gaps=(), dim_text="33*2760=91080", filler=0):
    doc = new_doc()
    b = doc.blocks.new(RACK_BLOCK)
    for a, c in (((0, 0), (2700, 0)), ((2700, 0), (2700, 1400)), ((2700, 1400), (0, 1400)), ((0, 1400), (0, 0))):
        b.add_line(a, c)
    msp = doc.modelspace()
    skip = set(gaps)
    for i in range(33):
        for j, y in enumerate(rack_ys()):
            if (i, j) not in skip:
                msp.add_blockref(RACK_BLOCK, (2760 * i, y), dxfattribs={"layer": "RACK"})
    ov = {"dimtxt": 250, "dimasz": 100, "dimexe": 50, "dimexo": 50, "dimdec": 0}
    d = msp.add_linear_dim(base=(0, -1000), p1=(0, -500), p2=(91080, -500), text=dim_text, dimstyle="EZDXF", override=ov, dxfattribs={"layer": "DIM"})
    d.render()
    for k in range(12):
        d = msp.add_linear_dim(base=(0, -2000), p1=(2760 * k, -1500), p2=(2760 * (k + 1), -1500), dimstyle="EZDXF", override=ov, dxfattribs={"layer": "DIM"})
        d.render()
    for k in range(1100):
        msp.add_line((10 + 80 * k, 0), (10 + 80 * k, 10275), dxfattribs={"layer": "COL_A"})
        msp.add_line((50 + 80 * k, 0), (50 + 80 * k, 11250), dxfattribs={"layer": "COL_B"})
    txt(msp, "货架立面 33 列 10 层 前后两排", 0, 30000, h=500)
    for t in range(filler):
        txt(msp, f"填充行{t:05d} 本行用于撑大单元并验证按行块再切", 200 + (t % 30) * 2900, 29000 - (t // 30) * 280, h=250)
    doc.saveas(path)


def make_dwgmagic(path):
    open(path, "wb").write(b"AC1032\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 64)


MAKERS = {
    "d1": lambda p: make_d1(p), "d1_old": lambda p: make_d1(p, ver="R2000"),
    "d1_big": lambda p: make_d1(p, n=2, texts_per=2200),
    "d1_huge": lambda p: make_d1(p, n=6, texts_per=2200), "d2": make_d2, "bomb": make_bomb, "selfref": make_selfref,
    "deep": make_deep, "empty": make_empty, "med": make_med, "tol": make_tol, "e5": make_e5, "utab": make_utab, "ublk": make_ublk, "dwgmagic": make_dwgmagic,
    "rack": lambda p: make_rack(p), "rack_gap": lambda p: make_rack(p, gaps=RACK_GAPS),
    "rack_bad": lambda p: make_rack(p, dim_text="33*2760=91000"), "rack_long": lambda p: make_rack(p, filler=3000),
}

if __name__ == "__main__":
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    names = sys.argv[2:] or list(MAKERS)
    for n in names:
        MAKERS[n](os.path.join(out, n + ".dxf"))
        print(n, os.path.getsize(os.path.join(out, n + ".dxf")))
