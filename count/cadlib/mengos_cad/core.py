"""mengos-cad 解析核 (DXF → 按单元写的 CAD 结构化文本, #mengos-cad v1)。
承 设计-VETC二期缺口-CAD图纸输入-2026-11-03 §四 至 §十、A 类实验报告 (readings/cad-a/报告.md) 的定稿口径;
设计-附件按引用由工具读取-2026-11-19 §21.3: 由 vetc/src/cadx.py 原样迁入, 整理成“可导入的核 + 命令行外壳 (../cadx.py)”, 行为不变。
流程: 读入 → 先估后展 (环/深度/E/I) → 块缓存 → 记录遍 → 轴线遍 → 定单元 (图框法/留白切分) → 流式几何遍 → 写出 (整体原子落盘)。
入口: run(dxf, outdir, fid, emax, imax, max_out_bytes, parsed) → 成功写 OUTDIR/units.json (parsed=True 时另写 OUTDIR/parsed.json,
  即完整解析结构, 写法见 ../SPEC.md), 返回摘要; 失败抛 CadFail(code, message, rc), 不留产物。
  rc 3 = 422 类 (CAD_*), 4 = 内存 (CAD_RESOURCE_EXCEEDED)。地址空间上限 (RLIMIT_AS) 须在导入本模块之前由调用方设 (命令行外壳照做)。
  切分与写出的算法常量写在本文件, 随版本哈希。
"""
import gc, json, math, os, re, sys, time
from collections import Counter, defaultdict

class _Args:  # 定稿口径常量 (A 类实验报告 §六); 限额与输入输出由 run() 填
    pass
args = _Args()
args.max_depth = 12          # 嵌套深度上限 (D2 最深 6 层)
args.g_mult = 3.0            # 留白阈值 g = 3 × 字高中位数
args.bridge_frac = 0.25      # 去桥: 长于区域跨度 25% 的直线/多段线
args.bridge_rect = 2         # 去桥: 外接框包住 ≥2 个其他原子的矩形/插入/多段线/表
args.stop_texts = 0          # 不按条数停, 只在找不到空带时停
args.stop_chars = 0
args.merge_tiny = 3          # 原子 ≤3 且文字 ≤3 的小叶并入最近的叶
args.c_ext = 1               # c 步触发: 不在任何恰含一个标题栏的框内
args.tb_anchor = "tuhao"     # 每个“图号”格一个标题栏
args.mode = "auto"
args.B = 60000               # 单元字数上限: 超过即按行块再切 (只切不截)
args.parsed = False          # 是否另写完整解析结构 parsed.json (由 run() 填)

SPEC_VERSION = "1"           # 解析规格版本 (../SPEC.md); 对象种类、字段、数值写法变时才升
# 完整解析结构里三类明细的节头 (设计-附件按引用由工具读取 附二 M-6, 立法者 2026-11-19 定稿) 与体量上限 (超过不存, 标“未存”与条数)
DETAIL_HEAD = {"线段明细": "#线段明细（图层|方向|长度|起点|终点）共 {n} 条",
               "嵌套插入": "#嵌套插入（名称|x|y|旋转|嵌套层|所属直接插入）共 {n} 条",
               "未插入图块文字": "#未插入图块文字（块名|内容）共 {n} 条"}
DETAIL_CAP = {"线段明细": 500_000, "嵌套插入": 200_000, "未插入图块文字": 200_000}
PX_EMPTY_KIND = "代理实体（专业软件自定义对象，代理图形里没有可读的线和字）"
PX_ERR_KIND = "代理实体：解析出错"
PX_ERR_NOTE = "代理图形解析失败，按拆不出处理，内容未读"


class _AtomCounter(Counter):
    """计数器: 每次增量另记到 log[(键, where())] (根容器里按顶层原子记, 供未解析清单按单元给处数)。不改计数本身。"""
    def __init__(self, log, where):
        super().__init__()
        self.log = log; self.where = where

    def __setitem__(self, k, v):
        d = v - self.get(k, 0)
        if d:
            self.log[(k, self.where())] += d
        super().__setitem__(k, v)


def _n3(v):
    """明细里的数: 四舍五入到 3 位小数 (Python round), 整数不带小数点, 去掉末尾的 0, 负零写 0。"""
    r = round(float(v), 3)
    if r == 0:
        return "0"
    if r == int(r):
        return str(int(r))
    return f"{r:.3f}".rstrip("0").rstrip(".")


class CadFail(Exception):
    """解析失败: code 为 CAD_* 码, message 给人看, rc 为命令行退出码 (3 = 422 类, 4 = 内存)。"""
    def __init__(self, code, message, rc=3):
        super().__init__(code, message, rc)
        self.code = code; self.message = message; self.rc = rc


def fail(code, msg, rc=3):
    import shutil
    shutil.rmtree(args.outdir + ".partial", ignore_errors=True)
    raise CadFail(code, msg, rc)

import numpy as np
import ezdxf
from ezdxf import path as ezpath
from ezdxf.entities.acad_table import read_acad_table_content
from ezdxf.tools.text import plain_mtext
from ezdxf.lldxf.encoding import has_dxf_unicode, decode_dxf_unicode

ARC_SEG_DEG = 15
SKIP_TYPES = {"POINT", "ATTDEF", "VIEWPORT", "XLINE", "RAY", "IMAGE", "WIPEOUT", "OLE2FRAME", "3DSOLID", "BODY",
              "SURFACE", "MESH", "LIGHT", "SECTION", "HELIX", "UNDERLAY", "PDFUNDERLAY", "DWFUNDERLAY", "DGNUNDERLAY"}
EXPLODE_TYPES = {"MULTILEADER", "MLEADER", "MLINE", "ARC_DIMENSION", "LEADER"}
def fx(s):
    """文字规整: 旧版 DXF 的 \\U+XXXX 转义还原成字符; 非法字节经 surrogateescape 读入的孤立代理项换成 U+FFFD。"""
    if not isinstance(s, str):
        return str(s)
    if has_dxf_unicode(s):
        s = decode_dxf_unicode(s)
    return s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
R = lambda v: str(int(round(v)))

LAYERS = {}
def lid_of(name):
    i = LAYERS.get(name)
    if i is None:
        i = LAYERS[name] = len(LAYERS)
    return i
LAYER0 = lid_of("0")


def main():
    t0 = time.time()
    try:
        doc = ezdxf.readfile(args.dxf)
    except ezdxf.DXFStructureError as ex:
        fail("CAD_PARSE_FAILED", "无法读取该 DXF（文件结构有误）：" + " ".join(str(ex).split())[:160])
    except (IOError, UnicodeDecodeError) as ex:
        fail("CAD_PARSE_FAILED", "无法读取该 DXF：" + type(ex).__name__)
    msp = doc.modelspace()
    if len(msp) == 0:
        fail("CAD_EMPTY", "该 DXF 的模型空间里没有任何图形或文字，没有可读取的内容")
    acadver = str(getattr(doc, "dxfversion", "") or "")

    # ───────── P1 先估后展 (只数不展开) ─────────
    t1 = time.time()
    blocks = {}
    def blk(name):
        if name not in blocks:
            blocks[name] = doc.blocks.get(name)
        return blocks[name]

    def refs_formula(container):
        """返回 (本地段数公式估计, 本地文字数, [(子块名, 倍数)])"""
        segs = 0; texts = 0; kids = []
        for e in container:
            t = e.dxftype()
            try:
                if t == "LINE":
                    segs += 1
                elif t == "LWPOLYLINE":
                    pts = e.get_points("xyb"); n = len(pts)
                    closed = e.closed
                    for k in range(n if closed else n - 1):
                        b = pts[k][2]
                        if b:
                            p, q = pts[k], pts[(k + 1) % n]
                            ch = math.hypot(q[0] - p[0], q[1] - p[1]); ang = 4 * math.atan(abs(b))
                            r = ch / (2 * math.sin(ang / 2)) if ang > 1e-9 else 0
                            segs += _arc_n_flat(r, ang)
                        else:
                            segs += 1
                elif t == "POLYLINE":
                    n = len(e.vertices); segs += max(0, n - 1 + (1 if e.is_closed else 0))
                elif t == "CIRCLE":
                    segs += 24
                elif t == "ARC":
                    a0, a1 = e.dxf.start_angle, e.dxf.end_angle
                    if a1 <= a0: a1 += 360
                    segs += max(2, int(math.ceil((a1 - a0) / ARC_SEG_DEG)))
                elif t == "ELLIPSE":
                    a = e.dxf.major_axis; r = math.hypot(a[0], a[1])
                    sp = (e.dxf.end_param - e.dxf.start_param) % (2 * math.pi) or 2 * math.pi
                    segs += _arc_n_flat(r, sp)
                elif t == "SPLINE":
                    segs += max(1, 4 * (max(len(e.control_points), len(e.fit_points)) - 1))
                elif t == "HATCH":
                    for bp in e.paths:
                        if hasattr(bp, "vertices"):
                            segs += len(bp.vertices)
                elif t in ("SOLID", "TRACE", "3DFACE"):
                    segs += 4
                elif t in ("TEXT", "MTEXT"):
                    texts += 1
                elif t == "INSERT":
                    texts += len(e.attribs)
                    kids.append((e.dxf.name, max(1, e.mcount)))
                elif t == "DIMENSION":
                    g = e.dxf.get("geometry")
                    if g: kids.append((g, 1))
                elif t in EXPLODE_TYPES:
                    segs += 6  # 粗估: 引线/公差等按 6 段计
            except Exception:
                pass
        return segs, texts, kids

    form = {}
    def scan(name):
        if name not in form:
            b = blk(name)
            form[name] = refs_formula(b) if b is not None else (0, 0, [])
        return form[name]
    # 环检测 + 深度 (迭代 DFS)
    root = "*MODEL"
    form[root] = refs_formula(msp)
    color = {}; depth_of = {}
    est = {}  # name -> (E, I, Texts)
    stack = [(root, 0)]
    while stack:
        name, st = stack.pop()
        if st == 0:
            if color.get(name) == 2:
                continue
            color[name] = 1
            stack.append((name, 1))
            for (k, mult) in scan(name)[2]:
                if blk(k) is None:
                    continue
                c = color.get(k)
                if c == 1:
                    fail("CAD_BLOCK_CYCLE", f"图块“{fx(k)[:40]}”直接或间接引用了自己（环引用），无法展开")
                if c is None:
                    stack.append((k, 0))
        else:
            color[name] = 2
            s, tx, kids = scan(name)
            E, I, TX, D = s, 0, tx, 0
            for (k, mult) in kids:
                if k not in est:
                    continue
                ke, ki, kt, kd = est[k]
                E += mult * ke; I += mult * (1 + ki); TX += mult * kt; D = max(D, kd + 1)
            est[name] = (E, I, TX, D)
    E_formula, I_est, TX_est, depth = est[root]
    budget = {"E_formula": E_formula, "I_expanded_inserts": I_est, "texts_est": TX_est, "max_nesting": depth}
    if depth > args.max_depth:
        fail("CAD_NESTING_TOO_DEEP", f"图块嵌套 {depth} 层，超过上限 {args.max_depth} 层")
    if E_formula > args.emax:
        fail("CAD_EXPANSION_BUDGET_EXCEEDED", f"图纸展开后规模过大：估计 {E_formula} 条线段（上限 {args.emax}）。请拆分图纸或清理冗余图块后再上传")
    if I_est > args.imax:
        fail("CAD_EXPANSION_BUDGET_EXCEEDED", f"图块展开后插入 {I_est} 次（上限 {args.imax}），规模过大。请拆分图纸或清理冗余图块后再上传")

    # ───────── P2 块缓存 (本地几何只折线化一次) ─────────
    t2 = time.time()
    cache = {}
    urep = {}   # *U 块名 -> INSERT 扩展字典 AcDbRepData 的组码 340 (句柄); 块记录扩展数据读不到时回溯用
    visits = Counter()   # 块名 -> 展开处数 (根=1)
    # 完整解析结构 (args.parsed) 用: 根容器里未解析的增量按顶层原子记, 及该原子的位置 (取实体自身的插入点等, 供归单元)
    SK_ATOM = Counter(); PXE_ATOM = Counter(); PXR_ATOM = Counter(); POS_ATOM = {}
    _gs = {}

    def gdt_style(name):
        """文字样式的字体是 gdt / amgdt (GDT 字体) 时为真; 这类样式下的字母是符号码, 不译 (码位未核实), 只在丢失声明里计数。"""
        if name not in _gs:
            try:
                font = str(doc.styles.get(name).dxf.get("font", "")).lower()
            except Exception:
                font = ""
            _gs[name] = font.rsplit(".", 1)[0].endswith("gdt")
        return _gs[name]

    def proxy_class(e):
        """代理实体的类名: 组码 91 为 CLASSES 的序号 (从 500 起)。取不到写“未知类”。"""
        try:
            cid = next(int(v) for c, v in e.acdb_proxy_entity if c == 91)
            names = [c.dxf.cpp_class_name for c in doc.classes.classes.values()]
            return fx(names[cid - 500])
        except Exception:
            return "未知类"

    def to_wcs_pts(e, pts):
        ex = e.dxf.get("extrusion", (0, 0, 1))
        if abs(ex[0]) < 1e-12 and abs(ex[1]) < 1e-12 and ex[2] > 0:
            return pts
        ocs = e.ocs()
        return [(v.x, v.y) for v in ocs.points_to_wcs([(x, y, 0) for x, y in pts])]

    class BC:
        __slots__ = ("segs", "slid", "texts", "dims", "kids", "ins", "rects", "closed", "tables", "atom_seg", "atom_txt", "atom_kid",
                     "atom_dim", "atom_kind", "atom_len", "atom_rect", "bbox", "n_atoms", "atom_ins", "sk", "px", "gf", "oc", "et")

    def build(name, container, is_model=False):
        S = []; SL = []; TX = []; DM = []; KD = []; INS = []; RC = []; CL = []; TB = []
        a_seg = []; a_txt = []; a_kid = []; a_dim = []; a_kind = []; a_len = []; a_rect = []; a_ins = []
        cur_atom = [0]; cur_ent = [None]
        def where():   # 根容器: 当前顶层原子号; 首次记下该实体的位置
            a = cur_atom[0]
            if a not in POS_ATOM:
                POS_ATOM[a] = _ent_pos(cur_ent[0])
            return a
        if is_model:
            sk = _AtomCounter(SK_ATOM, where); PX = {"ok": [0, 0, 0], "empty": _AtomCounter(PXE_ATOM, where), "err": 0}
        else:
            sk = Counter(); PX = {"ok": [0, 0, 0], "empty": Counter(), "err": 0}
        GF = [0]
        OC = Counter(); ET = Counter()   # 每个实体的去处 (解析/部分/未解析/空) 与空实体的类型: 对象总数守恒用 (只在 args.parsed 时记)

        def add_poly(pts, lay, closed=False):
            for a, b in zip(pts, pts[1:]):
                S.append((a[0], a[1], b[0], b[1])); SL.append(lay); a_seg.append(cur_atom[0])
            if closed and len(pts) > 2 and pts[0] != pts[-1]:
                S.append((pts[-1][0], pts[-1][1], pts[0][0], pts[0][1])); SL.append(lay); a_seg.append(cur_atom[0])

        def text_rec(e, src):
            t = e.dxftype()
            if t == "MTEXT":
                s = e.plain_text(split=False).replace("\n", " ").strip()
                ins = e.dxf.insert; h = e.dxf.char_height; rot = e.get_rotation()
            else:
                s = e.plain_text() if hasattr(e, "plain_text") else e.dxf.text
                h = e.dxf.height; rot = e.dxf.get("rotation", 0)
                hal = e.dxf.get("halign", 0); val = e.dxf.get("valign", 0)
                ins = e.dxf.get("align_point", e.dxf.insert) if (hal or val) else e.dxf.insert
            s = fx(s).strip()
            if not s:
                return
            if gdt_style(e.dxf.get("style", "Standard")):
                GF[0] += 1
            lay = e.dxf.get("layer", "0")
            TX.append((ins[0], ins[1], h, rot, s, lid_of(lay), src)); a_txt.append(cur_atom[0])

        def walk(e, lay_override=None):
            t = e.dxftype()
            lay = lid_of(e.dxf.get("layer", "0"))
            if t == "LINE":
                s, q = e.dxf.start, e.dxf.end
                add_poly([(s[0], s[1]), (q[0], q[1])], lay)
                if is_model: a_len[-1] = max(a_len[-1], math.hypot(q[0] - s[0], q[1] - s[1])); a_kind[-1] = "line"
            elif t == "LWPOLYLINE":
                pts_b = e.get_points("xyb")
                closed = bool(e.closed)
                ex = e.dxf.get("extrusion", (0, 0, 1))
                plain = all(abs(p[2]) < 1e-12 for p in pts_b) and abs(ex[0]) < 1e-12 and abs(ex[1]) < 1e-12 and ex[2] > 0
                if plain:
                    pts = [(p[0], p[1]) for p in pts_b]
                    add_poly(pts, lay, closed)
                else:
                    pts = [(v.x, v.y) for v in ezpath.make_path(e).flattening(distance=1.0)]
                    add_poly(pts, lay, False)
                if closed:
                    pr = pts[:-1] if len(pts) == 5 and pts[0] == pts[-1] else pts
                    if len(pr) == 4 and plain and _axis_rect(pr):
                        RC.append(pr); a_rect.append(cur_atom[0])
                        if is_model: a_kind[-1] = "rect"
                    CL.append((lay, [(round(x), round(y)) for x, y in pts]));
                if is_model and a_kind[-1] != "rect":
                    a_kind[-1] = "poly"; L = 0.0
                    for a, b in zip(pts, pts[1:]): L += math.hypot(b[0] - a[0], b[1] - a[1])
                    a_len[-1] = L if not closed else 0.0
            elif t == "POLYLINE":
                if e.is_poly_face_mesh or e.is_polygon_mesh:
                    for ve in e.virtual_entities():
                        safe(ve)
                    return
                pts = [(v.x, v.y) for v in ezpath.make_path(e).flattening(distance=1.0)]
                add_poly(pts, lay, False)
                if e.is_closed:
                    CL.append((lay, [(round(x), round(y)) for x, y in pts]))
            elif t in ("CIRCLE", "ARC"):
                c = e.dxf.center; r = e.dxf.radius
                a0, a1 = (0, 360) if t == "CIRCLE" else (e.dxf.start_angle, e.dxf.end_angle)
                if a1 <= a0: a1 += 360
                n = max(2, int(math.ceil((a1 - a0) / ARC_SEG_DEG)))
                pts = [(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * k / n)), c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]
                add_poly(to_wcs_pts(e, pts), lay)
            elif t in ("ELLIPSE", "SPLINE"):
                try:
                    add_poly([(v.x, v.y) for v in ezpath.make_path(e).flattening(distance=1.0)], lay)
                except Exception:
                    sk[f"{t}:折线化出错"] += 1
            elif t in ("TEXT", "MTEXT"):
                text_rec(e, "text")
            elif t == "TOLERANCE":
                s_, unk = gdt_text(fx(e.dxf.get("content", "")))
                if unk:
                    sk["形位公差:表外GDT码"] += unk
                s_ = fx(s_).strip()
                if s_:
                    s_ = "〔形位公差〕" + s_
                    ins = e.dxf.get("insert", (0, 0, 0))
                    TX.append((ins[0], ins[1], _tol_height(e), 0.0, s_, lid_of(e.dxf.get("layer", "0")), "tolerance")); a_txt.append(cur_atom[0])
            elif t in ("SOLID", "TRACE", "3DFACE"):
                vs = [e.dxf.get(f"vtx{k}") for k in range(4)]
                add_poly([(v[0], v[1]) for v in vs if v is not None], lay, True)
            elif t == "HATCH":
                for bp in e.paths:
                    if hasattr(bp, "vertices"):
                        add_poly([(v[0], v[1]) for v in bp.vertices], lay, True)
                    else:
                        sk["HATCH:曲线边界未展开"] += 1
            elif t == "DIMENSION":
                try:
                    meas = e.get_measurement()
                    meas = float(meas) if not hasattr(meas, "x") else float(meas.magnitude)
                except Exception:
                    meas = None
                # 两端点: 线性/对齐取 defpoint2/3; 半径/直径取 defpoint 与 defpoint4; 其余取 defpoint 与文字中点
                if e.dxf.hasattr("defpoint2") and e.dxf.hasattr("defpoint3"):
                    p1 = e.dxf.defpoint2; p2 = e.dxf.defpoint3
                elif e.dxf.hasattr("defpoint4"):
                    p1 = e.dxf.get("defpoint", (0, 0)); p2 = e.dxf.defpoint4
                else:
                    p1 = e.dxf.get("defpoint", (0, 0)); p2 = e.dxf.get("text_midpoint", p1)
                    sk["DIMENSION:端点取 defpoint/文字中点"] += 0
                kind = {0: "线性", 1: "对齐", 2: "角度", 3: "直径", 4: "半径", 5: "三点角度", 6: "坐标"}.get(e.dimtype, str(e.dimtype))
                DM.append((kind, meas, fx(e.dxf.get("text", "")), p1[0], p1[1], p2[0], p2[1], lay)); a_dim.append(cur_atom[0])
                g = e.dxf.get("geometry")
                if g and blk(g) is not None:
                    KD.append((g, np.eye(3), lay, "dim")); a_kid.append(cur_atom[0])
            elif t == "INSERT":
                if blk(e.dxf.name) is None:
                    sk["INSERT:块不存在"] += 1; return
                at = {}
                if e.dxf.name.startswith("*U") and e.dxf.name not in urep:
                    urep[e.dxf.name] = _rep_handle(e)
                for a in e.attribs:
                    text_rec(a, "attrib"); at[fx(a.dxf.tag)] = fx(a.dxf.text)
                vis = list(e.multi_insert()) if e.mcount > 1 else [e]
                for vi in vis:
                    m = vi.matrix44()
                    M = np.array([list(r) for r in m.rows()], dtype=float)
                    M3 = np.array([[M[0, 0], M[0, 1], 0], [M[1, 0], M[1, 1], 0], [M[3, 0], M[3, 1], 1]])
                    KD.append((e.dxf.name, M3, lay, "insert")); a_kid.append(cur_atom[0])
                    ip = vi.dxf.insert
                    INS.append((fx(e.dxf.name), ip[0], ip[1], vi.dxf.get("rotation", 0), lay, tuple(sorted(at.items())))); a_ins.append(cur_atom[0])
                if is_model: a_kind[-1] = "insert"
            elif t == "ACAD_TABLE":
                TB.append(e)
                if is_model: a_kind[-1] = "table"
            elif t in EXPLODE_TYPES:
                for ve in e.virtual_entities():
                    safe(ve)
            elif t == "ACAD_PROXY_ENTITY":
                n_l = 0; t0 = len(TX); failed = False
                try:
                    ves = list(e.virtual_entities())
                except Exception:
                    ves = []; failed = True
                for ve in ves:
                    if ve.dxftype() not in ("TEXT", "MTEXT"):
                        n_l += 1
                    safe(ve)
                n_t = len(TX) - t0
                for k in range(t0, len(TX)):
                    x_ = TX[k]; TX[k] = (x_[0], x_[1], x_[2], x_[3], "〔代理图形〕" + x_[4], x_[5], x_[6])
                if failed:
                    PX["err"] += 1
                if n_l + n_t:
                    PX["ok"][0] += 1; PX["ok"][1] += n_l; PX["ok"][2] += n_t
                else:
                    PX["empty"][proxy_class(e)] += 1
            elif t in SKIP_TYPES:
                sk[t] += 1
            else:
                sk[t] += 1

        def safe(e):
            try:
                walk(e)
            except Exception as ex:
                sk[f"{e.dxftype()}:{type(ex).__name__}"] += 1

        for i, e in enumerate(container):
            if is_model:
                cur_atom[0] = i; a_kind.append(e.dxftype().lower()); a_len.append(0.0); cur_ent[0] = e
            if not args.parsed:
                safe(e)
                continue
            o0 = (len(S), len(TX), len(DM), len(KD), len(INS), len(TB), len(CL), len(RC), PX["ok"][0])
            l0 = sum(sk.values()) + sum(PX["empty"].values()) + PX["err"]; r0 = PX["err"]
            safe(e)
            got = o0 != (len(S), len(TX), len(DM), len(KD), len(INS), len(TB), len(CL), len(RC), PX["ok"][0])
            lost_ = (sum(sk.values()) + sum(PX["empty"].values()) + PX["err"]) != l0
            OC[("parsed" if not lost_ else "partial") if got else ("unparsed" if lost_ else "empty")] += 1
            if not got and not lost_:
                ET[e.dxftype()] += 1
            if is_model and PX["err"] != r0:
                PXR_ATOM[where()] += PX["err"] - r0
        bc = BC()
        bc.segs = np.array(S, dtype=float).reshape(-1, 4)
        bc.slid = np.array(SL, dtype=np.int32)
        bc.texts = TX; bc.dims = DM; bc.kids = KD; bc.ins = INS; bc.rects = RC; bc.closed = CL; bc.tables = TB
        bc.atom_seg = np.array(a_seg, dtype=np.int64) if is_model else None
        bc.atom_txt = a_txt if is_model else None; bc.atom_kid = a_kid if is_model else None; bc.atom_dim = a_dim if is_model else None
        bc.atom_kind = a_kind if is_model else None; bc.atom_len = a_len if is_model else None; bc.atom_rect = a_rect if is_model else None
        bc.n_atoms = len(container) if is_model else 0
        bc.atom_ins = a_ins if is_model else None
        bc.bbox = None
        bc.sk = sk; bc.px = PX; bc.gf = GF[0]; bc.oc = OC; bc.et = ET
        return bc

    def get(name):
        if name not in cache:
            cache[name] = build(name, blk(name))
        return cache[name]

    model = build(root, msp, True)
    cache[root] = model
    # 只建可达块
    todo = [k[0] for k in model.kids]
    while todo:
        n = todo.pop()
        if n in cache:
            continue
        b = get(n)
        todo.extend(k[0] for k in b.kids if k[0] not in cache)
    # E_local (记忆化乘倍数)
    el = {}
    def elocal(name):
        if name in el:
            return el[name]
        b = cache[name]; v = len(b.segs)
        for (k, M, lay, kind) in b.kids:
            v += elocal(k)
        el[name] = v
        return v
    sys.setrecursionlimit(10000)
    E_local = elocal(root)
    budget["E_local"] = E_local
    budget["blocks_cached"] = len(cache) - 1
    budget["block_local_segs"] = int(sum(len(b.segs) for k, b in cache.items() if k != root))

    # 块本地外接框 (记忆化, 含子块)
    def lbbox(name):
        b = cache[name]
        if b.bbox is not None:
            return b.bbox
        xs0, ys0, xs1, ys1 = [], [], [], []
        if len(b.segs):
            xs0.append(min(b.segs[:, 0].min(), b.segs[:, 2].min())); xs1.append(max(b.segs[:, 0].max(), b.segs[:, 2].max()))
            ys0.append(min(b.segs[:, 1].min(), b.segs[:, 3].min())); ys1.append(max(b.segs[:, 1].max(), b.segs[:, 3].max()))
        for (x, y, h, rot, s, l, src) in b.texts:
            w = 0.9 * h * len(s)
            xs0.append(x); xs1.append(x + w); ys0.append(y); ys1.append(y + h)
        for (k, M, lay, kind) in b.kids:
            kb = lbbox(k)
            if kb is None:
                continue
            c = _tbox(kb, M)
            xs0.append(c[0]); ys0.append(c[1]); xs1.append(c[2]); ys1.append(c[3])
        b.bbox = (min(xs0), min(ys0), max(xs1), max(ys1)) if xs0 else None
        return b.bbox

    # ───────── 通用遍历 (迭代) ─────────
    def traverse(on_block, with_attrs=True):
        """on_block(bc, M, parent_lid, depth, atom_of_kid_or_None, kid_atom_index) ; 根用单位阵。"""
        st = [(root, np.eye(3), LAYER0, 0, -1)]
        while st:
            name, M, plid, depth, atom = st.pop()
            bc = cache[name]
            on_block(name, bc, M, plid, depth, atom)
            for j, (k, Mk, lay, kind) in enumerate(bc.kids):
                a = bc.atom_kid[j] if name == root else atom
                eff = plid if (lay == LAYER0 and depth > 0) else lay
                st.append((k, Mk @ M, eff, depth + 1, a))

    # ───────── P3 记录遍 ─────────
    t3 = time.time()
    TXT = []   # (x,y,h,rot,s,lid,src,atom,depth)
    INSR = []  # (name,x,y,rot,lid,attribs,depth,atom)
    DIMS = []  # (kind,meas,text,mx,my,p1x,p1y,p2x,p2y,lid,atom)
    RECTS = []  # (x0,y0,x1,y1,depth)
    TABLES = []  # (entity, x, y, M)
    n_dim_text = [0]

    def on_rec(name, bc, M, plid, depth, atom):
        visits[name] += 1
        A = M[:2, :2]; tr = M[2, :2]
        sc = math.sqrt(abs(np.linalg.det(A))) or 1.0
        ra = math.degrees(math.atan2(A[0, 1], A[0, 0]))
        is_dimblk = name.upper().startswith("*D")
        for i, (x, y, h, rot, s, l, src) in enumerate(bc.texts):
            p = np.array([x, y]) @ A + tr
            a = bc.atom_txt[i] if name == root else atom
            ll = plid if (l == LAYER0 and depth > 0) else l
            if is_dimblk:
                n_dim_text[0] += 1; continue  # 尺寸块里的字 = 尺寸显示文字, 尺寸单列
            TXT.append((float(p[0]), float(p[1]), h * sc, (rot + ra) % 360, s, ll, src, a, depth))
        for i, (n, x, y, rot, l, att) in enumerate(bc.ins):
            p = np.array([x, y]) @ A + tr
            a = bc.atom_ins[i] if name == root else atom
            ll = plid if (l == LAYER0 and depth > 0) else l
            INSR.append((n, float(p[0]), float(p[1]), (rot + ra) % 360, ll, att, depth, a))
        for i, (kind, meas, text, x1, y1, x2, y2, l) in enumerate(bc.dims):
            p1 = np.array([x1, y1]) @ A + tr; p2 = np.array([x2, y2]) @ A + tr
            a = bc.atom_dim[i] if name == root else atom
            ll = plid if (l == LAYER0 and depth > 0) else l
            meas2 = meas * sc if (meas is not None and kind not in ("角度", "三点角度")) else meas
            DIMS.append((kind, meas2, text, float((p1[0] + p2[0]) / 2), float((p1[1] + p2[1]) / 2), float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1]), ll, a))
        for pr in bc.rects:
            q = np.array(pr) @ A + tr
            if _axis_rect([tuple(v) for v in q]):
                RECTS.append((float(q[:, 0].min()), float(q[:, 1].min()), float(q[:, 0].max()), float(q[:, 1].max()), depth))
        for e in bc.tables:
            ip = e.dxf.get("insert", (0, 0, 0))
            p = np.array([ip[0], ip[1]]) @ A + tr
            TABLES.append((e, float(p[0]), float(p[1]), M.copy(), name))
    traverse(on_rec)

    # 顶层原子外接框
    atoms = []
    nA = model.n_atoms
    ab = np.full((nA, 4), np.nan)
    def upd(i, x0, y0, x1, y1):
        if np.isnan(ab[i, 0]):
            ab[i] = (x0, y0, x1, y1)
        else:
            ab[i] = (min(ab[i, 0], x0), min(ab[i, 1], y0), max(ab[i, 2], x1), max(ab[i, 3], y1))
    if len(model.segs):
        sg = model.segs
        for k in range(len(sg)):
            a = model.atom_seg[k]; s = sg[k]
            upd(a, min(s[0], s[2]), min(s[1], s[3]), max(s[0], s[2]), max(s[1], s[3]))
    for j, (k, M, lay, kind) in enumerate(model.kids):
        kb = lbbox(k)
        if kb is not None:
            c = _tbox(kb, M); upd(model.atom_kid[j], *c)
    atom_texts = Counter()
    for t in TXT:
        x, y, h, rot = t[0], t[1], t[2], t[3]; w = 0.9 * h * len(t[4])
        if t[7] >= 0:
            atom_texts[t[7]] += 1
            if t[8] == 0:
                upd(t[7], x, y, x + w, y + h)
    for d in DIMS:
        if d[10] >= 0:
            upd(d[10], min(d[5], d[7]), min(d[6], d[8]), max(d[5], d[7]), max(d[6], d[8]))
    for (e, x, y, M, owner) in TABLES:
        pass

    # ───────── P4 轴线遍 (+实际展开计数, 可选全量留存) ─────────
    t4 = time.time()
    HL = []; VL = []; cnt = [0]
    def on_axis(name, bc, M, plid, depth, atom):
        if not len(bc.segs):
            return
        A = M[:2, :2]; tr = M[2, :2]
        p = bc.segs[:, 0:2] @ A + tr; q = bc.segs[:, 2:4] @ A + tr
        cnt[0] += len(p)
        dx = np.abs(q[:, 0] - p[:, 0]); dy = np.abs(q[:, 1] - p[:, 1])
        h = (dy <= 0.01 * dx) & (dy < 1.0) & (dx > 0)
        v = (dx <= 0.01 * dy) & (dx < 1.0) & (dy > 0)
        if h.any():
            HL.append(np.stack([np.minimum(p[h, 0], q[h, 0]), np.maximum(p[h, 0], q[h, 0]), (p[h, 1] + q[h, 1]) / 2], 1))
        if v.any():
            VL.append(np.stack([np.minimum(p[v, 1], q[v, 1]), np.maximum(p[v, 1], q[v, 1]), (p[v, 0] + q[v, 0]) / 2], 1))
    traverse(on_axis)
    H = np.vstack(HL) if HL else np.zeros((0, 3)); V = np.vstack(VL) if VL else np.zeros((0, 3))
    del HL, VL
    E_actual = cnt[0]
    budget["E_actual"] = E_actual
    budget["axis_lines"] = [len(H), len(V)]

    # ───────── P5 定单元 ─────────
    t5 = time.time()
    hs = [t[2] for t in TXT if t[2] > 0]
    hmed = float(np.median(hs)) if hs else 1.0
    U = Units(TXT, INSR, DIMS, RECTS, TABLES, H, V, hmed, model, ab, atom_texts, doc)
    U.decide()
    # ───────── P6 几何遍 ─────────
    t6 = time.time()
    seg_stats = defaultdict(lambda: [0, 0.0]); ASSIGNED = [0]  # (unit, lid, orient, lenbucket) -> [n, total]
    buf = []; bufn = [0]
    SEGD = {"keep": [], "n": 0, "cnt": Counter(), "over": False}   # 线段明细 (args.parsed): 逐根留存, 超过上限只记条数
    def flush():
        if not buf:
            return
        P = np.vstack([b[0] for b in buf]); L = np.concatenate([b[1] for b in buf]); buf.clear(); bufn[0] = 0
        mx = (P[:, 0] + P[:, 2]) / 2; my = (P[:, 1] + P[:, 3]) / 2
        u = U.assign_points(mx, my)
        ASSIGNED[0] += int(((u >= 0) & (u < U.n_units())).sum())
        dx = P[:, 2] - P[:, 0]; dy = P[:, 3] - P[:, 1]
        ln = np.hypot(dx, dy)
        ok = ln >= 1
        ang = np.degrees(np.arctan2(dy, dx)) % 180
        o = np.where((ang < 1) | (ang > 179), 0, np.where(np.abs(ang - 90) < 1, 1, 2))
        if args.parsed:
            for a_, c_ in zip(*np.unique(u, return_counts=True)):
                SEGD["cnt"][int(a_)] += int(c_)
            SEGD["n"] += len(u)
            if not SEGD["over"]:
                if SEGD["n"] > DETAIL_CAP["线段明细"]:
                    SEGD["over"] = True; SEGD["keep"].clear()
                else:
                    SEGD["keep"].append((P, L, u, ln, o))
        lb = (np.round(ln / 10) * 10).astype(np.int64)
        key = np.stack([u[ok], L[ok], o[ok], lb[ok]], 1)
        if not len(key):
            return
        uk, inv, cn = np.unique(key, axis=0, return_inverse=True, return_counts=True)
        tot = np.bincount(inv.ravel(), weights=ln[ok], minlength=len(uk))
        for k, c, s in zip(map(tuple, uk.tolist()), cn.tolist(), tot.tolist()):
            r = seg_stats[k]; r[0] += c; r[1] += s
    def on_geo(name, bc, M, plid, depth, atom):
        if not len(bc.segs):
            return
        A = M[:2, :2]; tr = M[2, :2]
        p = bc.segs[:, 0:2] @ A + tr; q = bc.segs[:, 2:4] @ A + tr
        lid = np.where((bc.slid == LAYER0) & (depth > 0), plid, bc.slid).astype(np.int64)
        buf.append((np.hstack([p, q]), lid)); bufn[0] += len(p)
        if bufn[0] >= 1_000_000:
            flush()
    traverse(on_geo); flush()
    budget["segments_assigned_to_units"] = ASSIGNED[0]
    if args.parsed:
        NEST = _nested_inserts(model, cache)
        UNP, ENT = _unparsed_by_unit(U, root, cache, visits, traverse, ab, SK_ATOM, PXE_ATOM, PXR_ATOM, POS_ATOM)

    # ───────── P7 写出 ─────────
    tab_content = U.read_tables()
    # 丢失声明一律按展开处数计 (块定义内的计数 × 该块被展开的次数, 根 = 1) —— E-CAD5
    skipped = Counter(); gdt_font = 0
    px_ok = [0, 0, 0]; px_empty = Counter(); px_err = 0
    for bn, bc in cache.items():
        v = visits[bn]
        for k, c in bc.sk.items():
            skipped[k] += c * v
        gdt_font += bc.gf * v
        for i in range(3):
            px_ok[i] += bc.px["ok"][i] * v
        for k, c in bc.px["empty"].items():
            px_empty[k] += c * v
        px_err += bc.px["err"] * v
    uninserted = sorted(fx(b.name) for b in doc.blocks if not b.name.startswith("*") and b.name not in cache)
    px_uninserted = 0
    for b in doc.blocks:
        if b.name not in cache and not b.name.lower().startswith(("*model_space", "*paper_space")):
            px_uninserted += sum(1 for e in b if e.dxftype() == "ACAD_PROXY_ENTITY")
    u_names = {}
    for bn in cache:
        if bn.startswith("*U"):
            u_names[fx(bn)] = _u_orig(doc, bn, urep)
    lost = {"skipped": dict(sorted((k, v) for k, v in skipped.items() if v)), "dim_block_texts_excluded": n_dim_text[0], "acadver": acadver,
            "gdt_font_texts": gdt_font, "proxy_ok": px_ok, "proxy_empty": dict(sorted(px_empty.items())), "proxy_err": px_err,
            "proxy_uninserted": px_uninserted, "u_names": u_names}
    # 未插入图块 (不在图面上; 总览列块名与文字条数, 文字内容进完整解析结构的“未插入图块文字”): 文字条数含块内表格 (ACAD_TABLE) 的非空单元格, 表张数另记 —— E-CAD8 必修
    uninserted_texts = {}; uninserted_tables = {}
    UTX = []; sk_before = Counter(skipped)   # 未插入图块文字 (args.parsed): 与条数同一遍取
    for b in doc.blocks:   # 按块对象遍历 (查块用原名; fx() 只用于输出键, 块名带 \U+ 转义时也能对上)
        if b.name.startswith("*") or b.name in cache:
            continue
        bn = fx(b.name)
        n_txt = 0; n_tab = 0
        try:
            for e in b:
                t = e.dxftype()
                if t in ("TEXT", "MTEXT", "ATTRIB"):
                    n_txt += 1
                    if args.parsed:
                        UTX.append((bn, _txt_content(e)))
                elif t == "ACAD_TABLE":
                    n_tab += 1
                    try:
                        cs_ = [_pm(c) for r in read_acad_table_content(e) for c in r if _pm(c).strip()]
                        n_txt += len(cs_)
                        if args.parsed:
                            UTX.extend((bn, c) for c in cs_)
                    except Exception:
                        skipped["ACAD_TABLE:未插入块内表格读取出错"] += 1
        except Exception as ex:
            skipped[f"未插入图块:{type(ex).__name__}"] += 1   # 读块出错: 如实计入丢失声明, 不悄悄记 0 (该块的计数只含出错前读到的)
        uninserted_texts[bn] = n_txt; uninserted_tables[bn] = n_tab
    lost["uninserted_tables"] = uninserted_tables
    lost["skipped"] = dict(sorted((k, v) for k, v in skipped.items() if v))
    if args.parsed:   # 读未插入图块时出错的处数: 不在图面上, 不归单元
        for k, v in skipped.items():
            if v - sk_before.get(k, 0):
                UNP[(k, None, _lost_hint(k))] += v - sk_before.get(k, 0)
    U.doc = None
    TABLES.clear()
    cache.clear(); blocks.clear(); form.clear()
    del doc, msp
    units = U.render(seg_stats, tab_content, lost, uninserted, uninserted_texts, budget, args.fid)
    total_bytes = sum(len(u["text"].encode("utf-8")) for u in units)
    if total_bytes > args.max_out_bytes:
        fail("CAD_RESOURCE_EXCEEDED", f"抽取结果 {total_bytes} 字节，超过上限 {args.max_out_bytes} 字节")
    # 原子写出: 先写临时目录, 再改名; 任何一步失败不留产物
    import shutil
    tmp = args.outdir + ".partial"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    try:
        with open(os.path.join(tmp, "units.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"format": "mengos-cad v1", "ezdxf": ezdxf.__version__, "fid": args.fid, "units": units, "checks": U.checks},
                      f, ensure_ascii=False, indent=0, sort_keys=True, default=_jd)
        if args.parsed:
            pd = _parsed_doc(U, units, SEGD, NEST, UTX, UNP, ENT, lost, uninserted_texts, budget, args.fid)
            with open(os.path.join(tmp, "parsed.json"), "w", encoding="utf-8", newline="\n") as f:
                json.dump(pd, f, ensure_ascii=False, indent=0, sort_keys=True, default=_jd)
        if os.path.exists(args.outdir):
            shutil.rmtree(args.outdir)
        os.rename(tmp, args.outdir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"ok": True, "units": len(units), "budget": budget}


# ───────── 工具 ─────────
GDT_TABLE = {   # gdt.shx 字体码 → (符号, 名称); AutoCAD 公差对话框能产出的 19 个码 (E-CAD5 §1.2; 实证 b、i, 其余照通行码表)
    "a": ("∠", "倾斜度"), "b": ("⊥", "垂直度"), "c": ("⏥", "平面度"), "d": ("⌓", "面轮廓度"), "e": ("○", "圆度"),
    "f": ("∥", "平行度"), "g": ("⌭", "圆柱度"), "h": ("↗", "圆跳动"), "i": ("⌯", "对称度"), "j": ("⌖", "位置度"),
    "k": ("⌒", "线轮廓度"), "l": ("Ⓛ", "最小实体要求"), "m": ("Ⓜ", "最大实体要求"), "n": ("⌀", "直径"), "p": ("Ⓟ", "延伸公差带"),
    "r": ("◎", "同轴度"), "s": ("Ⓢ", "不考虑实际尺寸"), "t": ("⌰", "全跳动"), "u": ("⏤", "直线度"),
}
_GDT_RE = re.compile(r"\{\\F[^;{}]*[gG][dD][tT][^;{}]*;([^}]*)\}")
_CTRL = (("%%c", "⌀"), ("%%C", "⌀"), ("%%d", "°"), ("%%D", "°"), ("%%p", "±"), ("%%P", "±"))


def gdt_text(raw):
    """TOLERANCE 的 content → (可读文本, 表外码数)。只在 \\F 字体名含 gdt 的段内查表; 表外码写 〔GDT码x〕 并计数。
    版式: 框间“ | ”, 空框略去; 第 1 框 符号+中文名; 第 4–6 框(基准)加“基准”前缀; 多行(^J)用“ / ”连接。"""
    unk = [0]
    def tr(frame, named):
        def rep(m):
            out = []
            for i, ch in enumerate(m.group(1)):
                if ch in GDT_TABLE:
                    sym, nm = GDT_TABLE[ch]
                    out.append(sym + (nm if named and i == 0 else ""))
                else:
                    unk[0] += 1; out.append(f"〔GDT码{ch}〕")
            return "".join(out)
        t = _GDT_RE.sub(rep, frame)
        for a, b in _CTRL:
            t = t.replace(a, b)
        return t.strip()
    lines = []
    for ln in re.split(r"\^J|\n", raw or ""):
        frames = []
        for i, fr in enumerate(ln.split("%%v")):
            t = tr(fr, i == 0)
            if t:
                frames.append(("基准" + t) if i >= 3 else t)
        if frames:
            lines.append(" | ".join(frames))
    return " / ".join(lines), unk[0]


def _rep_handle(e):
    """INSERT 扩展字典 AcDbBlockRepresentation → AcDbRepData 的组码 340 (原动态块块记录句柄); 读不到返回 None。"""
    try:
        if not e.has_extension_dict:
            return None
        rd = e.get_extension_dict()["AcDbBlockRepresentation"]["AcDbRepData"]
        for sub in rd.xtags.subclasses:
            for tag in sub:
                if tag.code == 340:
                    return str(tag.value)
    except Exception:
        return None
    return None


def _u_orig(doc, name, urep):
    """匿名块 *U 的原名: 先读块记录扩展数据 AcDbBlockRepBTag 的组码 1005, 读不到再用 INSERT 的 RepData 340;
    目标仍是 *U 时沿链回溯, 深度不超过 8。解不出返回 None。"""
    cur = name
    for _ in range(8):
        h = None
        try:
            xd = doc.block_records.get(cur).get_xdata("AcDbBlockRepBTag")
            h = next((str(v) for c, v in xd if c == 1005), None)
        except Exception:
            h = None
        if h is None:
            h = urep.get(cur)
        if h is None:
            return None
        try:
            nm = str(doc.entitydb.get(h).dxf.name)
        except Exception:
            return None
        if not nm.startswith("*U"):
            return fx(nm)
        cur = nm
    return None


def _tol_height(e):
    try:
        st = e.doc.dimstyles.get(e.dxf.get("dimstyle", "Standard"))
        h = float(st.dxf.get("dimtxt", 0))
        return h if h > 0 else 2.5
    except Exception:
        return 2.5


def _ent_pos(e):
    """实体自身的位置 (插入点、点位、圆心、起点、定义点, 取第一个有的); 取不到 ⟹ None。只用于未解析对象归单元。"""
    try:
        for k in ("insert", "location", "center", "start", "defpoint"):
            if e.dxf.hasattr(k):
                v = e.dxf.get(k)
                return (float(v[0]), float(v[1]))
    except Exception:
        pass
    return None


def _jd(o):
    return o.item() if hasattr(o, "item") else str(o)


def _arc_n_flat(r, ang):
    """distance=1.0 折线化的段数估计 (弦高 ≤ 1)。"""
    if r <= 1:
        return 1
    step = 2 * math.acos(max(-1.0, 1 - 1.0 / r))
    return max(1, int(math.ceil(ang / step))) if step > 0 else 1


def _axis_rect(pts, tol_deg=0.5):
    if len(pts) != 4:
        return False
    for k in range(4):
        a, b = pts[k], pts[(k + 1) % 4]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-9:
            return False
        ang = math.degrees(math.atan2(abs(dy), abs(dx)))
        if not (ang <= tol_deg or abs(ang - 90) <= tol_deg):
            return False
    xs = sorted(p[0] for p in pts); ys = sorted(p[1] for p in pts)
    return (xs[3] - xs[0]) > 0 and (ys[3] - ys[0]) > 0


def _tbox(b, M):
    c = np.array([[b[0], b[1]], [b[2], b[1]], [b[0], b[3]], [b[2], b[3]]]) @ M[:2, :2] + M[2, :2]
    return (float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max()))


def _norm(s):
    return re.sub(r"[\s:：]", "", s)


KW = ["图号", "图名", "比例", "设计", "校对", "审核", "日期", "张"]
KW_ALIAS = {"图名": ["图名", "零件名称", "名称"], "图号": ["图号"]}
CS_KW = ["专业", "签名", "签字", "会签"]


def kw_hits(cells):
    """cells: 归一化后的格文本列表 → 命中的标题栏关键词集合"""
    hit = set()
    for c in cells:
        for k in KW:
            if k == "张":
                if re.search(r"[共第].*张", c): hit.add(k)
            elif c.startswith(k) or c == k:
                hit.add(k)
        if c in ("零件名称",):
            hit.add("图名")
    return hit


def natkey(s):
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", s)]


# ───────── 线画表检测 (移植自 dwg-exp/scripts/tables.py, 索引改为 numpy) ─────────
CELL_H_MAX, CELL_W_MAX, STRIP = 6.0, 80.0, 40.0

class LIdx:
    def __init__(self, L, B):
        self.L = L; self.B = B; self.arr = {}
        self.long = np.zeros(0, dtype=np.int64)
        if len(L) == 0:
            return
        k0 = np.floor(L[:, 0] / B).astype(np.int64); k1 = np.floor(L[:, 1] / B).astype(np.int64)
        span = k1 - k0
        big = span > 400
        self.long = np.nonzero(big)[0]
        idx = np.nonzero(~big)[0]
        rep = (span[idx] + 1)
        ii = np.repeat(idx, rep)
        off = np.arange(rep.sum()) - np.repeat(np.cumsum(rep) - rep, rep)
        kk = np.repeat(k0[idx], rep) + off
        o = np.lexsort((ii, kk)); kk = kk[o]; ii = ii[o]
        if len(kk):
            cut = np.nonzero(np.diff(kk))[0] + 1
            for k, grp in zip(kk[np.r_[0, cut]].tolist(), np.split(ii, cut)):
                self.arr[k] = grp

    def cand(self, p):
        a = self.arr.get(int(math.floor(p / self.B)))
        if a is None:
            return self.long
        return np.concatenate([a, self.long]) if len(self.long) else a


def _anchor(t):
    x, y, h, rot = t[0], t[1], max(t[2], 1e-6), t[3]
    if abs(rot % 360) > 1 and abs(rot % 360 - 360) > 1:
        return None
    return x + 0.4 * h, y + 0.4 * h  # 左下对齐近似 (插入点已按对齐点取)


def line_tables(texts, H, V, hmed):
    if len(H) == 0 or len(V) == 0 or not texts:
        return []
    B = max(hmed * 40, 1.0)
    iH = LIdx(H, B); iV = LIdx(V, B)
    cells = defaultdict(list); eps = 0.3
    for ti, t in enumerate(texts):
        a = _anchor(t); h = t[2]
        if a is None or h <= 0:
            continue
        px, py = a
        L = H[iH.cand(px)]
        m = (L[:, 0] - eps <= px) & (px <= L[:, 1] + eps)
        if not m.any(): continue
        ys = L[m, 2]; Lm = L[m]
        up = ys > py; dn = ys < py
        if not up.any() or not dn.any(): continue
        iu = np.argmin(np.where(up, ys, np.inf)); idn = np.argmax(np.where(dn, ys, -np.inf))
        y1, y0 = ys[iu], ys[idn]
        if y1 - y0 > CELL_H_MAX * h: continue
        lu, ld = Lm[iu, 1] - Lm[iu, 0], Lm[idn, 1] - Lm[idn, 0]
        L = V[iV.cand(py)]
        m = (L[:, 0] - eps <= py) & (py <= L[:, 1] + eps)
        if not m.any(): continue
        xs = L[m, 2]; Lm = L[m]
        rt = xs > px; lf = xs < px
        if not rt.any() or not lf.any(): continue
        ir = np.argmin(np.where(rt, xs, np.inf)); il = np.argmax(np.where(lf, xs, -np.inf))
        x1, x0 = xs[ir], xs[il]
        if x1 - x0 > CELL_W_MAX * h: continue
        lr, ll = Lm[ir, 1] - Lm[ir, 0], Lm[il, 1] - Lm[il, 0]
        if (min(lu, ld) > STRIP * (x1 - x0)) or (min(lr, ll) > STRIP * (y1 - y0)): continue
        cells[(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))].append(ti)
    boxes = sorted(cells.keys())
    if not boxes:
        return []
    arr = np.array(boxes, dtype=float); n = len(boxes)
    w = arr[:, 2] - arr[:, 0]; h = arr[:, 3] - arr[:, 1]
    par = list(range(n))
    def f(i):
        while par[i] != i:
            par[i] = par[par[i]]; i = par[i]
        return i
    S = max(float(np.percentile(np.maximum(w, h), 90)) * 3, 1e-3)
    bk = defaultdict(list)
    for i in range(n):
        kx0, kx1 = int(math.floor((arr[i, 0] - w[i]) / S)), int(math.floor((arr[i, 2] + w[i]) / S))
        ky0, ky1 = int(math.floor((arr[i, 1] - h[i]) / S)), int(math.floor((arr[i, 3] + h[i]) / S))
        if (kx1 - kx0 + 1) * (ky1 - ky0 + 1) > 400: kx1 = kx0 + 19; ky1 = ky0 + 19
        for kx in range(kx0, kx1 + 1):
            for ky in range(ky0, ky1 + 1):
                bk[(kx, ky)].append(i)
    seen = set()
    for key in sorted(bk):
        lst = bk[key]
        for ai in range(len(lst)):
            i = lst[ai]
            for j in lst[ai + 1:]:
                if (i, j) in seen: continue
                seen.add((i, j))
                a = arr[j]; x0, y0, x1, y1 = arr[i]
                gx = max(a[0], x0) - min(a[2], x1); gy = max(a[1], y0) - min(a[3], y1)
                if (-gy >= 0.5 * min(h[i], h[j]) and gx <= max(w[i], w[j]) + 1e-6) or (-gx >= 0.5 * min(w[i], w[j]) and gy <= max(h[i], h[j]) + 1e-6):
                    ri, rj = f(i), f(j)
                    if ri != rj: par[ri] = rj
    g = defaultdict(list)
    for i in range(n):
        g[f(i)].append(i)
    out = []
    for mem in g.values():
        if len(mem) < 4:
            continue
        bx = arr[mem]
        tis = sorted(ti for i in mem for ti in cells[boxes[i]])
        out.append({"bbox": (float(bx[:, 0].min()), float(bx[:, 1].min()), float(bx[:, 2].max()), float(bx[:, 3].max())),
                    "cells": [(boxes[i], cells[boxes[i]]) for i in sorted(mem, key=lambda i: (-arr[i, 3], arr[i, 0]))], "texts": tis})
    out.sort(key=lambda t: (-round(t["bbox"][3]), round(t["bbox"][0])))
    return out


# ───────── 单元 ─────────
class Units:
    def __init__(self, TXT, INSR, DIMS, RECTS, TABLES, H, V, hmed, model, ab, atom_texts, doc):
        self.TXT, self.INSR, self.DIMS, self.RECTS, self.TABLES = TXT, INSR, DIMS, RECTS, TABLES
        self.H, self.V, self.hmed, self.model, self.ab, self.atom_texts, self.doc = H, V, hmed, model, ab, atom_texts, doc
        self.checks = {}; self.index = []

    # —— 视口 (第 0 步)
    def viewports(self):
        res = []
        for lay in self.doc.layouts:
            if lay.name == "Model":
                continue
            for v in lay.query("VIEWPORT"):
                if v.dxf.get("id", 0) == 1:
                    continue
                w, h = v.dxf.get("width", 0), v.dxf.get("height", 0)
                vc = v.dxf.get("view_center_point", (0, 0)); vh = v.dxf.get("view_height", 0)
                tg = v.dxf.get("view_target_point", (0, 0, 0))
                vw = vh * (w / h) if h else 0
                cx, cy = tg[0] + vc[0], tg[1] + vc[1]
                res.append((cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2, v.dxf.get("id", 0)))
        X = np.array([[t[0], t[1]] for t in self.TXT]) if self.TXT else np.zeros((0, 2))
        cov = np.zeros(len(X), bool)
        for (x0, y0, x1, y1, _) in res:
            cov |= (X[:, 0] >= x0) & (X[:, 0] <= x1) & (X[:, 1] >= y0) & (X[:, 1] <= y1)
        uniq = sorted(set((round(a), round(b), round(c), round(d)) for a, b, c, d, _ in res))
        return {"viewports_excl_overall": len(res), "distinct_windows": len(uniq), "texts": len(X), "texts_in_windows": int(cov.sum()),
                "coverage": round(float(cov.mean()), 4) if len(X) else None, "windows": [list(u) for u in uniq],
                "step0_applies": len(uniq) >= 2 and len(X) > 0 and cov.mean() >= 0.8}

    # —— 标题栏
    def title_blocks(self):
        TB = []; CS = []
        lt = line_tables(self.TXT, self.H, self.V, self.hmed)
        self.n_line_tables = len(lt); self.all_line_tables = lt
        self.checks["countersign_keyword_texts"] = {k: sum(1 for t in self.TXT if k in _norm(t[4])) for k in CS_KW}
        for t in lt:
            cells = [_norm(" ".join(self.TXT[i][4] for i in sorted(tis, key=lambda i: (-self.TXT[i][1], self.TXT[i][0])))) for (_, tis) in t["cells"]]
            hit = kw_hits(cells)
            cs = sum(1 for k in CS_KW if any(k in c for c in cells))
            t["kw"] = sorted(hit); t["cells_norm"] = cells
            kb = [t["cells"][j][0] for j, c in enumerate(cells) if kw_hits([c])]
            t["kwbox"] = (min(b[0] for b in kb), min(b[1] for b in kb), max(b[2] for b in kb), max(b[3] for b in kb)) if kb else t["bbox"]
            if cs >= 2 and "日期" in hit and not ({"图号", "比例"} & hit):
                CS.append(t)
            elif len(hit) >= 3:
                if args.tb_anchor == "table":
                    t["kwbox"] = t["bbox"]; TB.append(t)
                elif args.tb_anchor == "kw":
                    TB.append(t)
                else:
                    th = [t["cells"][j][0] for j, c in enumerate(cells) if c.startswith("图号")]
                    if len(th) <= 1:
                        TB.append(t)
                    else:
                        for b in sorted(th, key=lambda b: (-b[3], b[0])):
                            t2 = dict(t); t2["kwbox"] = b; t2["split_from_merged_table"] = len(th); TB.append(t2)
        # ACAD_TABLE 作标题栏
        self.acad_tb = set()
        for k, (e, x, y, M, owner) in enumerate(self.TABLES):
            try:
                rows = read_acad_table_content(e)
            except Exception:
                continue
            cells = [_norm(_pm(c)) for r in rows for c in r]
            hit = kw_hits(cells)
            if len(hit) >= 3:
                self.acad_tb.add(k)
        return TB, CS

    # —— 图框候选
    def frames(self, TB):
        hmed = self.hmed
        Lmin0 = 20 * hmed  # 图框候选的最小边长 (与 b 的长线门槛同)
        A = [(r[0], r[1], r[2], r[3], "a") for r in self.RECTS if (r[2] - r[0]) >= Lmin0 and (r[3] - r[1]) >= Lmin0]
        self.checks.setdefault("frame_prefilter", {})["closed_rects_all"] = len(self.RECTS)
        # b: 散线矩形
        Lmin = 20 * hmed
        H = self.H[(self.H[:, 1] - self.H[:, 0]) >= Lmin] if len(self.H) else self.H
        V = self.V[(self.V[:, 1] - self.V[:, 0]) >= Lmin] if len(self.V) else self.V
        Bf = []
        if len(H) and len(V):
            H = np.unique(np.round(H, 3), axis=0); V = np.unique(np.round(V, 3), axis=0)
            ordV = np.argsort(V[:, 2]); Vs = V[ordV]
            for hb in H:  # 作下边
                x0, x1, y = hb
                tol = 0.005 * (x1 - x0)
                lo, hi = np.searchsorted(Vs[:, 2], [x0 - tol, x0 + tol])
                lefts = Vs[lo:hi]
                lefts = lefts[np.abs(lefts[:, 0] - y) <= tol] if len(lefts) else lefts
                if not len(lefts): continue
                lo2, hi2 = np.searchsorted(Vs[:, 2], [x1 - tol, x1 + tol])
                rights = Vs[lo2:hi2]
                rights = rights[np.abs(rights[:, 0] - y) <= tol] if len(rights) else rights
                if not len(rights): continue
                for lv in lefts:
                    for rv in rights:
                        top = lv[1]
                        t2 = 0.005 * min(x1 - x0, top - y)
                        if abs(rv[1] - top) > t2 or abs(lv[0] - y) > t2 or abs(rv[0] - y) > t2: continue
                        m = (np.abs(H[:, 2] - top) <= t2) & (np.abs(H[:, 0] - x0) <= t2) & (np.abs(H[:, 1] - x1) <= t2)
                        if m.any():
                            Bf.append((float(x0), float(y), float(x1), float(top), "b"))
        F = sorted(set((round(f[0], 1), round(f[1], 1), round(f[2], 1), round(f[3], 1), f[4]) for f in A + Bf))
        # 同一矩形既是 a 又是 b → 记 a
        seen = {}
        for f in F:
            k = f[:4]
            if k not in seen or f[4] == "a": seen[k] = f[4]
        F = [(k[0], k[1], k[2], k[3], v) for k, v in sorted(seen.items())]
        self.checks["frame_candidates"] = {"a_closed_rect": sum(1 for f in F if f[4] == "a"), "b_line_rect": sum(1 for f in F if f[4] == "b"),
                                           "long_lines_HV": [int(len(H)), int(len(V))], "Lmin": round(Lmin, 2)}
        return F

    def frame_c(self, tb):
        """标题栏反推: 过标题栏下边的横线向左延伸、过右边的竖线向上延伸 (共线相接), 得右下角与标题栏相合的线框。"""
        x0, y0, x1, y1 = tb
        H, V = self.H, self.V
        def chain(lo, hi, start, toward_low):
            end = start
            while True:
                if toward_low:
                    m = (hi >= end - 1) & (lo < end - 1)
                    if not m.any(): return end
                    end = lo[m].min()
                else:
                    m = (lo <= end + 1) & (hi > end + 1)
                    if not m.any(): return end
                    end = hi[m].max()
        mh = np.abs(H[:, 2] - y0) < 1; mv = np.abs(V[:, 2] - x1) < 1
        if not mh.any() or not mv.any():
            return None
        xl = chain(H[mh, 0], H[mh, 1], x0, True); yt = chain(V[mv, 0], V[mv, 1], y1, False)
        if (x1 - xl) < 1.2 * (x1 - x0) or (yt - y0) < 1.5 * (y1 - y0):
            return None
        # 要求左边、上边也有线 (最小线框的另两边)
        ok_top = ((np.abs(H[:, 2] - yt) < 1) & (H[:, 0] <= xl + 1) & (H[:, 1] >= x1 - 1)).any() or \
                 ((np.abs(H[:, 2] - yt) < 1) & (H[:, 1] - H[:, 0] >= 0.9 * (x1 - xl))).any()
        ok_left = ((np.abs(V[:, 2] - xl) < 1) & (V[:, 1] - V[:, 0] >= 0.9 * (yt - y0))).any()
        if not (ok_top or ok_left):
            return None
        return (float(xl), float(y0), float(x1), float(yt))

    def decide(self):
        self.vp = self.viewports(); self.checks["viewports"] = self.vp
        TB, CS = self.title_blocks()
        self.TB, self.CS = TB, CS
        tbb = [t["kwbox"] for t in TB]  # 标题栏锚框 = 命中关键词的格的外接框 (整表可能跨图框线与邻格拼接)
        tbfull = [t["bbox"] for t in TB]
        F = self.frames(TB)
        X = np.array([[t[0], t[1]] for t in self.TXT]) if self.TXT else np.zeros((0, 2))
        def inside(b, f, tol=1.0):
            return b[0] >= f[0] - tol and b[1] >= f[1] - tol and b[2] <= f[2] + tol and b[3] <= f[3] + tol
        # 嵌套去重: 内框面积 ≥ 外框 80% 且被包含 → 同一图幅的内外框线, 取外框
        F = sorted(F, key=lambda f: (-(f[2] - f[0]) * (f[3] - f[1]), f[:4]))
        keep = []; KA = np.zeros((0, 4))
        for f in F:
            a = (f[2] - f[0]) * (f[3] - f[1])
            if len(KA):
                ins_ = (f[0] >= KA[:, 0] - 1) & (f[1] >= KA[:, 1] - 1) & (f[2] <= KA[:, 2] + 1) & (f[3] <= KA[:, 3] + 1)
                ag = (KA[:, 2] - KA[:, 0]) * (KA[:, 3] - KA[:, 1])
                if (ins_ & (a >= 0.8 * ag)).any():
                    continue
            keep.append(f); KA = np.vstack([KA, np.array(f[:4], dtype=float)[None]])
        self.checks["frame_candidates"]["after_dedup_80pct"] = len(keep)
        F = keep
        tbc = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in tbb]
        TBA = np.array(tbb, dtype=float).reshape(-1, 4)
        def tbs_in(f):
            if not len(TBA): return []
            m = (TBA[:, 0] >= f[0] - 1) & (TBA[:, 1] >= f[1] - 1) & (TBA[:, 2] <= f[2] + 1) & (TBA[:, 3] <= f[3] + 1)
            return np.nonzero(m)[0].tolist()
        Ftb = [tbs_in(f) for f in F]
        # c: 不在任何 a/b 图框内的标题栏反推
        in_any = set(i for l in Ftb for i in l) if not args.c_ext else set(i for l in Ftb if len(l) == 1 for i in l)
        cF = []
        orphan = []
        for i, b in enumerate(tbb):
            if i in in_any:
                continue
            fc = self.frame_c(tbfull[i])
            if fc:
                cF.append((round(fc[0], 1), round(fc[1], 1), round(fc[2], 1), round(fc[3], 1), "c"))
            else:
                orphan.append(i)
        cF = sorted(set(cF))
        F = F + cF; Ftb = Ftb + [tbs_in(f) for f in cF]
        self.checks["frame_candidates"]["c_from_title"] = len(cF)
        # 图幅: 恰含 1 个标题栏, 且不被另一个恰含同一标题栏的框包含 (那是视图框)
        one = [k for k, l in enumerate(Ftb) if len(l) == 1]
        by1 = defaultdict(list)
        for k in one: by1[Ftb[k][0]].append(k)
        sheets = []
        for k in one:
            f = F[k]
            outer = [j for j in by1[Ftb[k][0]] if j != k and inside(f, F[j]) and F[j][:4] != f[:4]]
            if outer:
                continue
            sheets.append((f, Ftb[k][0], f[4]))
        # 同一标题栏可能落在多个互不包含的框 (交叠) → 取面积最小的
        by_tb = defaultdict(list)
        for s in sheets: by_tb[s[1]].append(s)
        sheets = [min(v, key=lambda s: ((s[0][2] - s[0][0]) * (s[0][3] - s[0][1]), s[0][:4])) for k, v in sorted(by_tb.items())]
        containers = sum(1 for l in Ftb if len(l) >= 2)
        # 无标题栏图幅: 0 个标题栏、≥5 条文字、不与已定图幅互相包含、取最大的
        zero = [k for k, l in enumerate(Ftb) if len(l) == 0]
        S0 = []
        sfr = [s[0] for s in sheets]
        for k in sorted(zero, key=lambda k: (-(F[k][2] - F[k][0]) * (F[k][3] - F[k][1]), F[k][:4])):
            f = F[k]
            G = np.array([g[:4] for g in sfr + S0], dtype=float).reshape(-1, 4)
            if len(G):
                a1 = (f[0] >= G[:, 0] - 1) & (f[1] >= G[:, 1] - 1) & (f[2] <= G[:, 2] + 1) & (f[3] <= G[:, 3] + 1)
                a2 = (G[:, 0] >= f[0] - 1) & (G[:, 1] >= f[1] - 1) & (G[:, 2] <= f[2] + 1) & (G[:, 3] <= f[3] + 1)
                if (a1 | a2).any():
                    continue
            n = int(((X[:, 0] >= f[0]) & (X[:, 0] <= f[2]) & (X[:, 1] >= f[1]) & (X[:, 1] <= f[3])).sum()) if len(X) else 0
            if n >= 5:
                S0.append(f)
        self.sheets = [dict(frame=s[0][:4], how=s[2], tb=s[1]) for s in sheets] + [dict(frame=f[:4], how=f[4], tb=None) for f in S0]
        # 标题栏覆盖: 每个标题栏落在几张图幅里
        tb_in = Counter()
        SF = np.array([s["frame"] for s in self.sheets], dtype=float).reshape(-1, 4)
        for i, b in enumerate(tbb):
            tb_in[int(((b[0] >= SF[:, 0] - 1) & (b[1] >= SF[:, 1] - 1) & (b[2] <= SF[:, 2] + 1) & (b[3] <= SF[:, 3] + 1)).sum())] += 1
        self.checks["title_blocks"] = {"line_tables": self.n_line_tables, "title_blocks": len(TB), "countersign_blocks": len(CS),
                                       "acad_table_title_blocks": len(self.acad_tb),
                                       "tb_in_n_sheets": {str(k): v for k, v in sorted(tb_in.items())},
                                       "tb_in_exactly_one_sheet_ratio": round(tb_in.get(1, 0) / len(TB), 4) if TB else None,
                                       "orphan_title_blocks": len(orphan), "container_frames(>=2 TB)": containers,
                                       "sheets_with_tb": len(sheets), "sheets_without_tb": len(S0),
                                       "sheet_frame_how": dict(Counter(s["how"] for s in self.sheets)),
                                       "countersign_in_sheet": sum(1 for t in CS if any(inside(t["bbox"], s["frame"]) for s in self.sheets))}
        self.tb_list = TB; self.orphan = orphan; self.F = F; self.Ftb = Ftb
        # 用不用图框法
        sh = self.sheet_index()
        tin = (sh >= 0).sum() / len(X) if len(X) else 0
        self.checks["frame_method"] = {"sheets": len(self.sheets), "texts_in_sheets_ratio": round(float(tin), 4)}
        use_frames = (args.mode == "frames") or (args.mode == "auto" and len(self.sheets) >= 1 and tin >= 0.5)
        self.use_frames = use_frames
        if not use_frames:
            self.sheets = []; self._sg = None
        self.order_sheets()
        # 框外池 (或全图) 留白切分
        self.cut_pool()

    def n_units(self):
        return len(self.sheets) + len(self.leaf_box)

    def sheet_index(self, X=None):
        if X is None:
            X = np.array([[t[0], t[1]] for t in self.TXT]) if self.TXT else np.zeros((0, 2))
        return self._assign_sheets(X[:, 0], X[:, 1]) if len(X) else np.zeros(0, int)

    def _sheet_grid(self):
        SF = np.array([s["frame"] for s in self.sheets], dtype=float)
        ext = (SF[:, 0].min(), SF[:, 1].min(), SF[:, 2].max(), SF[:, 3].max())
        cs = max(float(np.median(np.maximum(SF[:, 2] - SF[:, 0], SF[:, 3] - SF[:, 1]))), 1e-6)
        nx = int((ext[2] - ext[0]) / cs) + 1; ny = int((ext[3] - ext[1]) / cs) + 1
        cells = defaultdict(list)
        order = sorted(range(len(SF)), key=lambda k: ((SF[k, 2] - SF[k, 0]) * (SF[k, 3] - SF[k, 1]), k))
        for k in order:
            f = SF[k]
            for i in range(int((f[0] - 1 - ext[0]) // cs), int((f[2] + 1 - ext[0]) // cs) + 1):
                for j in range(int((f[1] - 1 - ext[1]) // cs), int((f[3] + 1 - ext[1]) // cs) + 1):
                    cells[(i, j)].append(k)
        K = max(len(v) for v in cells.values())
        C = np.full((nx + 2) * (ny + 2), -1, dtype=np.int64).reshape(nx + 2, ny + 2)
        CC = np.full((nx + 2, ny + 2, K), -1, dtype=np.int64)
        for (i, j), v in cells.items():
            if 0 <= i + 1 < nx + 2 and 0 <= j + 1 < ny + 2:
                CC[i + 1, j + 1, :len(v)] = v
        self._sg = (SF, ext, cs, CC)

    def _assign_sheets(self, x, y):
        out = np.full(len(x), -1, dtype=np.int64)
        if not getattr(self, "sheets", None):
            return out
        if getattr(self, "_sg", None) is None or len(self._sg[0]) != len(self.sheets):
            self._sheet_grid()
        SF, ext, cs, CC = self._sg
        i = np.floor((x - ext[0]) / cs).astype(np.int64) + 1; j = np.floor((y - ext[1]) / cs).astype(np.int64) + 1
        ok = (i >= 0) & (i < CC.shape[0]) & (j >= 0) & (j < CC.shape[1])
        ii = np.nonzero(ok)[0]
        cand = CC[i[ii], j[ii]]
        for kk in range(CC.shape[2]):
            c = cand[:, kk]; m = (c >= 0) & (out[ii] < 0)
            if not m.any(): continue
            f = SF[c[m]]; px = x[ii[m]]; py = y[ii[m]]
            hit = (px >= f[:, 0] - 1) & (px <= f[:, 2] + 1) & (py >= f[:, 1] - 1) & (py <= f[:, 3] + 1)
            out[ii[m][hit]] = c[m][hit]
        return out

    def _assign_sheets_bruteforce(self, x, y):
        out = np.full(len(x), -1, dtype=np.int64)
        best = np.full(len(x), np.inf)
        for k, s in enumerate(self.sheets):
            f = s["frame"]
            m = (x >= f[0] - 1) & (x <= f[2] + 1) & (y >= f[1] - 1) & (y <= f[3] + 1)
            a = (f[2] - f[0]) * (f[3] - f[1])
            upd = m & (a < best)
            out[upd] = k; best[upd] = a
        return out

    def order_sheets(self):
        self._sg = None
        # 标签: 图号 + 图名 (标题栏格: 关键词格右邻格的文本)
        for s in self.sheets:
            s["no"] = None; s["name"] = None; s["fields"] = []
            if s["tb"] is not None:
                t = self.tb_list[s["tb"]]
                cells = t["cells"]
                for ci, ((x0, y0, x1, y1), tis) in enumerate(cells):
                    k = _norm(" ".join(self.TXT[i][4] for i in tis))
                    for key, al in (("no", ["图号"]), ("name", ["图名", "零件名称"])):
                        if any(k == a for a in al) and s[key] is None:
                            # 右邻格: 同一行 (y 重叠) x0 ≈ 本格 x1
                            nb = [c for c in cells if abs(c[0][0] - x1) < 1 and min(c[0][3], y1) - max(c[0][1], y0) > 0.5 * (y1 - y0)]
                            if nb:
                                s[key] = " ".join(self.TXT[i][4] for i in sorted(nb[0][1], key=lambda i: (-self.TXT[i][1], self.TXT[i][0])))
        has_no = [s for s in self.sheets if s["no"]]
        self.checks["sheet_label"] = {"with_no": len(has_no), "with_name": sum(1 for s in self.sheets if s["name"]), "sheets": len(self.sheets)}
        if self.sheets and len(has_no) >= 0.9 * len(self.sheets):
            self.sheets.sort(key=lambda s: (natkey(s["no"] or "~"), s["frame"]))
            self.checks["sheet_order"] = "图号自然序"
        elif self.sheets:
            hm = float(np.median([s["frame"][3] - s["frame"][1] for s in self.sheets])) / 2
            self.sheets.sort(key=lambda s: (-round(s["frame"][3] / hm) if hm else 0, s["frame"][0], s["frame"][1]))
            self.checks["sheet_order"] = "位置"

    # —— 留白切分
    def atoms_for_cut(self):
        ab = self.ab; m = self.model
        ok = ~np.isnan(ab[:, 0])
        idx = np.nonzero(ok)[0]
        if self.sheets:
            cx = (ab[idx, 0] + ab[idx, 2]) / 2; cy = (ab[idx, 1] + ab[idx, 3]) / 2
            sidx = self._assign_sheets(cx, cy)
            idx = idx[sidx < 0]
        kinds = [m.atom_kind[i] for i in idx]
        lens = np.array([m.atom_len[i] for i in idx]) if len(idx) else np.zeros(0)
        nt = np.array([self.atom_texts.get(int(i), 0) for i in idx]) if len(idx) else np.zeros(0, int)
        return idx, ab[idx], kinds, lens, nt

    def xycut(self, idx, B, kinds, lens, nt, g, bridge_frac, bridge_rect, stop_texts, stop_chars, est_chars):
        leaves = []; stats = Counter()
        def rec(sel, depth):
            bb = B[sel]
            ntx = int(nt[sel].sum())
            ch = int(est_chars[sel].sum())
            stop = len(sel) <= 1 or (stop_chars > 0 and ch <= stop_chars) or (stop_chars <= 0 and stop_texts > 0 and ntx <= stop_texts)
            if stop or depth >= MAXD:
                leaves.append((sel, "stop" if stop else "max_depth")); stats["stop_rule" if stop else "max_depth"] += 1; return ("L", len(leaves) - 1)
            ext = (bb[:, 0].min(), bb[:, 1].min(), bb[:, 2].max(), bb[:, 3].max())
            span = max(ext[2] - ext[0], ext[3] - ext[1])
            br = np.zeros(len(sel), bool)
            if bridge_frac > 0:
                ks = [kinds[i] for i in sel]
                br |= np.array([k in ("line", "poly") for k in ks]) & (lens[sel] > bridge_frac * span)
            if bridge_rect:
                rect = np.array([(kinds[i] in ("rect",)) or (bridge_rect >= 2 and kinds[i] in ("insert", "poly", "lwpolyline", "polyline", "table")) for i in sel])
                if rect.any():
                    cxy = np.stack([(bb[:, 0] + bb[:, 2]) / 2, (bb[:, 1] + bb[:, 3]) / 2], 1)
                    for j in np.nonzero(rect)[0]:
                        f = bb[j]
                        inn = (cxy[:, 0] >= f[0]) & (cxy[:, 0] <= f[2]) & (cxy[:, 1] >= f[1]) & (cxy[:, 1] <= f[3]); inn[j] = False
                        if inn.sum() >= 2:
                            br[j] = True
            BRG[sel[br]] = True
            core = ~br
            if core.sum() <= 1:
                leaves.append((sel, "no_core")); stats["no_core"] += 1; return ("L", len(leaves) - 1)
            cb = bb[core]
            best = None
            for ax in (0, 1):
                lo = cb[:, ax]; hi = cb[:, ax + 2]
                o = np.argsort(lo, kind="stable"); lo = lo[o]; hi = hi[o]
                run = np.maximum.accumulate(hi)
                gaps = lo[1:] - run[:-1]
                if len(gaps):
                    j = int(np.argmax(gaps))
                    if gaps[j] >= g and (best is None or gaps[j] > best[0]):
                        best = (float(gaps[j]), ax, float((run[j] + lo[j + 1]) / 2))
            if best is None:
                leaves.append((sel, "no_gap")); stats["no_gap"] += 1; return ("L", len(leaves) - 1)
            _, ax, c = best
            ctr = (bb[:, ax] + bb[:, ax + 2]) / 2
            a = sel[ctr < c]; b = sel[ctr >= c]
            self.cuts.append((ax, c, best[0]))
            # 递归 (上/左 先)
            if ax == 1:
                nb_ = rec(b, depth + 1); na_ = rec(a, depth + 1)
            else:
                na_ = rec(a, depth + 1); nb_ = rec(b, depth + 1)
            return ("S", ax, c, na_, nb_)
        self.cuts = []
        BRG = np.zeros(len(idx), bool); self.BRG = BRG
        MAXD = 64
        self.tree = None
        if len(idx) and g > 0:
            self.tree = rec(np.arange(len(idx)), 0)
        elif len(idx):
            leaves.append((np.arange(len(idx)), "no_cut")); stats["no_cut(无文字或 g=0)"] += 1; self.tree = ("L", 0)
        return leaves, stats

    def merge_tiny(self, leaves, B, nt, N):
        self.leaf_map = list(range(len(leaves)))
        if N <= 0 or len(leaves) <= 1:
            return leaves, 0
        def box(sel):
            nb = sel[~self.BRG[sel]]; b = B[nb] if len(nb) else B[sel]
            return np.array([b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()])
        tiny = [len(sel) <= N and int(nt[sel].sum()) <= N for sel, why in leaves]
        if all(tiny):
            return leaves, 0
        big = [k for k, t in enumerate(tiny) if not t]
        bb = np.array([box(leaves[k][0]) for k in big])
        add = defaultdict(list)
        for k, t in enumerate(tiny):
            if not t:
                continue
            b = box(leaves[k][0])
            dx = np.maximum(0, np.maximum(bb[:, 0] - b[2], b[0] - bb[:, 2])); dy = np.maximum(0, np.maximum(bb[:, 1] - b[3], b[1] - bb[:, 3]))
            j = int(np.argmin(np.hypot(dx, dy)))
            add[big[j]].append(leaves[k][0]); self.leaf_map[k] = ("big", big[j])
        out = []
        newidx = {k: n for n, k in enumerate(big)}
        self.leaf_map = [newidx[m[1]] if isinstance(m, tuple) else newidx[m] for m in self.leaf_map]
        for k in big:
            sel, why = leaves[k]
            if add[k]:
                sel = np.sort(np.concatenate([sel] + add[k])); why = why + "+tiny"
            out.append((sel, why))
        return out, sum(tiny)

    def est_chars(self, idx, nt):
        # 粗估: 每条文字 ~ 30 字 + 内容; 尺寸 ~ 45; 插入 ~ 30
        m = self.model
        return nt * 40 + 30

    def cut_pool(self):
        idx, B, kinds, lens, nt = self.atoms_for_cut()
        g = args.g_mult * self.hmed if self.TXT else 0.0
        ec = self.est_chars(idx, nt)
        leaves, st = self.xycut(idx, B, kinds, lens, nt, g, args.bridge_frac, args.bridge_rect, args.stop_texts, args.stop_chars, ec)
        leaves, nm = self.merge_tiny(leaves, B, nt, args.merge_tiny); st["tiny_merged"] = nm
        self.leaves = leaves; self.leaf_atoms = [idx[sel] for sel, why in leaves]
        self.leaf_box = []
        for sel, why in leaves:
            nb = sel[~self.BRG[sel]]
            b = B[nb] if len(nb) else B[sel]
            self.leaf_box.append((float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())))
        self.checks["cut"] = {"atoms": int(len(idx)), "g": round(g, 3), "hmed": round(self.hmed, 3), "leaves": len(leaves), "why": dict(st),
                              "params": {"g_mult": args.g_mult, "bridge_frac": args.bridge_frac, "bridge_rect": args.bridge_rect,
                                         "stop_texts": args.stop_texts, "stop_chars": args.stop_chars}}
        self.atom_leaf = {}
        for k, a in enumerate(self.leaf_atoms):
            for i in a.tolist():
                self.atom_leaf[i] = k
        # 叶的点归属: 用切线树 (保证覆盖平面)
        self._tree = self._build_tree(idx, B)

    def _build_tree(self, idx, B):
        """重放切分为点查询: 叶号按 leaves 的次序; 用 leaf 外接框中心最近 + 切线顺序近似 → 改为直接按 cuts 重放。"""
        return None

    def assign_points(self, x, y):
        """单元号: 图幅 k → k; 否则 → 区块 (len(sheets) + leaf)。区块用叶外接框: 含点的最小叶框, 否则最近的叶框 (按到框的距离)。"""
        s = self._assign_sheets(x, y)
        rest = s < 0
        if rest.any():
            s[rest] = len(self.sheets) + self._leaf_of(x[rest], y[rest])
        return s

    def _leaf_of(self, x, y):
        if not self.leaf_box:
            return np.zeros(len(x), dtype=np.int64)
        if getattr(self, "tree", None) is not None:
            out = np.zeros(len(x), dtype=np.int64)
            st = [(self.tree, np.arange(len(x)))]
            while st:
                node, ii = st.pop()
                if not len(ii):
                    continue
                if node[0] == "L":
                    out[ii] = self.leaf_map[node[1]]; continue
                _, ax, c, na, nb = node
                v = (x if ax == 0 else y)[ii]
                st.append((na, ii[v < c])); st.append((nb, ii[v >= c]))
            return out
        LB = np.array(self.leaf_box)
        best = np.full(len(x), np.inf); out = np.zeros(len(x), dtype=np.int64)
        for k, f in enumerate(LB):
            dx = np.maximum(np.maximum(f[0] - x, 0), x - f[2]); dy = np.maximum(np.maximum(f[1] - y, 0), y - f[3])
            d = np.hypot(dx, dy)
            # 含点时用面积作次序 (小者优先), 用负数区分
            a = (f[2] - f[0]) * (f[3] - f[1])
            key = np.where(d == 0, -1.0 / (1.0 + a), d)
            upd = key < best
            out[upd] = k; best[upd] = key[upd]
        return out

    def assign_atoms_or_points(self, atom, x, y, kind):
        """插入 (直接插入) 在切分模式下按原子 (外接框中心) 归; 其余按点。"""
        pass

    # —— 表
    def read_tables(self):
        out = []
        for k, (e, x, y, M, owner) in enumerate(self.TABLES):
            st = e.xtags.get_subclass("AcDbTable")
            nr, nc = st.get_first_value(91, 0), st.get_first_value(92, 0)
            rows = read_acad_table_content(e)
            spans = {}; covered = set()
            cells = []; cur = None
            for tag in st:
                if tag.code == 171:
                    cur = {}; cells.append(cur)
                if cur is not None and tag.code in (173, 175, 176) and str(tag.code) not in cur:
                    cur[str(tag.code)] = tag.value
            for i, c in enumerate(cells):
                if nc == 0: break
                r, cc = divmod(i, nc)
                w, h = c.get("175", 1) or 1, c.get("176", 1) or 1
                if w > 1 or h > 1:
                    spans[(r, cc)] = (h, w)
                    for dr in range(h):
                        for dc in range(w):
                            if dr or dc: covered.add((r + dr, cc + dc))
            out.append(dict(k=k, x=x, y=y, nr=nr, nc=nc, rows=[[_pm(c) for c in r] for r in rows], spans=spans, covered=covered,
                            title=(k in self.acad_tb), owner=owner))
        return out

    # —— 写出
    def render(self, seg_stats, tabs, lost, uninserted, uninserted_texts, budget, fid):
        TXT, INSR, DIMS = self.TXT, self.INSR, self.DIMS
        nS = len(self.sheets); nL = len(self.leaf_box)
        nU = nS + nL
        X = np.array([[t[0], t[1]] for t in TXT]) if TXT else np.zeros((0, 2))
        tu = self.assign_points(X[:, 0], X[:, 1]) if len(X) else np.zeros(0, int)
        # 直接插入: 图框法按插入点; 切分 (区块) 按原子外接框中心
        ins0 = [i for i, r in enumerate(INSR) if r[6] == 0]
        IX = np.array([[INSR[i][1], INSR[i][2]] for i in ins0]) if ins0 else np.zeros((0, 2))
        iu = self.assign_points(IX[:, 0], IX[:, 1]) if len(IX) else np.zeros(0, int)
        moved = 0
        for j, i in enumerate(ins0):
            if iu[j] >= nS:  # 不在图幅里 → 按原子
                a = INSR[i][7]
                if a in self.atom_leaf:
                    nu = nS + self.atom_leaf[a]
                    if nu != iu[j]: moved += 1
                    iu[j] = nu
        self._iu = iu   # 直接插入所在单元 (按 INSR 中直接插入的次序), 嵌套插入的归属沿用
        DX = np.array([[d[3], d[4]] for d in DIMS]) if DIMS else np.zeros((0, 2))
        du = self.assign_points(DX[:, 0], DX[:, 1]) if len(DX) else np.zeros(0, int)
        TBX = np.array([[t["x"], t["y"]] for t in tabs]) if tabs else np.zeros((0, 2))
        tbu = self.assign_points(TBX[:, 0], TBX[:, 1]) if len(TBX) else np.zeros(0, int)
        # 顶层闭合轮廓
        CL = self.model.closed
        CX = np.array([[np.mean([p[0] for p in c[1]]), np.mean([p[1] for p in c[1]])] for c in CL]) if CL else np.zeros((0, 2))
        cu = self.assign_points(CX[:, 0], CX[:, 1]) if len(CX) else np.zeros(0, int)
        # 标题栏文字 (进图幅头部, 不进文字列表)
        tb_text = {}; tb_cells = {}
        for si, s in enumerate(self.sheets):
            if s["tb"] is not None:
                f = s["frame"]; keepc = []
                for (b, tis) in self.tb_list[s["tb"]]["cells"]:
                    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                    if f[0] <= cx <= f[2] and f[1] <= cy <= f[3] and all(tu[ti] == si for ti in tis):
                        keepc.append((b, tis))
                        for ti in tis: tb_text[ti] = si
                tb_cells[si] = keepc
        LN = {v: k for k, v in LAYERS.items()}
        per_t = defaultdict(list); per_i = defaultdict(list); per_d = defaultdict(list); per_c = defaultdict(list); per_tb = defaultdict(list)
        for i, u in enumerate(tu.tolist()): per_t[u].append(i)
        for j, u in enumerate(iu.tolist()): per_i[u].append(ins0[j])
        for i, u in enumerate(du.tolist()): per_d[u].append(i)
        for i, u in enumerate(cu.tolist()): per_c[u].append(i)
        for i, u in enumerate(tbu.tolist()): per_tb[u].append(i)
        per_s = defaultdict(list)
        for (u, l, o, lb), (n, tot) in seg_stats.items():
            per_s[u].append((LN[l], ("水平", "竖直", "斜")[o], lb, n, tot))
        # 表号: 按 (所在单元, -y, x)
        tab_order = sorted(range(len(tabs)), key=lambda i: (int(tbu[i]), -round(tabs[i]["y"]), round(tabs[i]["x"])))
        tab_no = {i: k + 1 for k, i in enumerate(tab_order)}
        cons = Counter()
        def label(u):
            if u < nS:
                s = self.sheets[u]
                if s["no"] or s["name"]:
                    return " ".join(x for x in (s["no"], s["name"]) if x)
            ts = per_t.get(u, [])
            ts = [i for i in ts if i not in tb_text]
            if ts:
                i = min(ts, key=lambda i: (-TXT[i][2], -TXT[i][1], TXT[i][0]))
                return TXT[i][4][:40]
            b = self.sheets[u]["frame"] if u < nS else self.leaf_box[u - nS]
            return f"({R(b[0])},{R(b[1])})"
        def sections_of(u):
            ts = sorted([i for i in per_t.get(u, []) if i not in tb_text], key=lambda i: (-round(TXT[i][1]), round(TXT[i][0]), TXT[i][4]))
            ins = sorted(per_i.get(u, []), key=lambda i: (INSR[i][0], round(INSR[i][2]), round(INSR[i][1])))
            ds = sorted(per_d.get(u, []), key=lambda i: (DIMS[i][0], round(DIMS[i][6]), round(DIMS[i][5]), round(DIMS[i][7])))
            cs = sorted(per_c.get(u, []), key=lambda i: (LN[CL[i][0]], -CL[i][1][0][1], CL[i][1][0][0]))
            sec = []
            tl = sorted(per_tb.get(u, []), key=lambda i: tab_no[i])
            if tl:
                sec.append(("#表（见表单元）" + "、".join(f"T{tab_no[i]}" for i in tl), []))
            sec.append((f"#文字（x|y|图层|字高|内容）共 {len(ts)} 条",
                        [f"{R(TXT[i][0])}|{R(TXT[i][1])}|{LN[TXT[i][5]]}|{R(TXT[i][2])}|{TXT[i][4]}" for i in ts]))
            dl = []
            for i in ds:
                d = DIMS[i]
                mv = "" if d[1] is None else (R(d[1]) if d[0] not in ("角度", "三点角度") else f"{d[1]:.2f}")
                dl.append(f"{d[0]}|{mv}|{d[2] if d[2] not in ('', '<>') else ''}|{R(d[5])},{R(d[6])}|{R(d[7])},{R(d[8])}|{LN[d[9]]}")
            sec.append((f"#尺寸标注（类型|测量值|显示文字|端点1|端点2|图层）共 {len(ds)} 条", dl))
            il = []
            for i in ins:
                r = INSR[i]
                il.append(f"{r[0]}|{R(r[1])}|{R(r[2])}|{R(r[3])}|" + ";".join(f"{k}={v}" for k, v in r[5]))
            sec.append((f"#图块插入（名称|x|y|旋转|属性）共 {len(ins)} 条", il))
            cl = []
            for i in cs:
                lay, pts = CL[i]
                xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                cl.append(f"{LN[lay]}|{max(xs)-min(xs)}|{max(ys)-min(ys)}|{len(pts)}|{R((max(xs)+min(xs))/2)}|{R((max(ys)+min(ys))/2)}|" + " ".join(f"{x},{y}" for x, y in pts))
            sec.append((f"#闭合轮廓（图层|外接宽|外接高|顶点数|中心x|中心y|顶点）共 {len(cs)} 条", cl))
            ss = sorted(per_s.get(u, []))
            sec.append((f"#线段统计（图层|方向|长度≈|根数|总长）共 {len(ss)} 组", [f"{a}|{b}|{c}|{n}|{R(t)}" for a, b, c, n, t in ss]))
            cons["texts"] += len(ts); cons["inserts"] += len(ins); cons["dims"] += len(ds); cons["closed"] += len(cs)
            cons["seg"] += sum(x[3] for x in ss)
            return sec
        units = []      # 最终单元 (已按 B 再切)
        catalog_rows = []   # (kind, no, label, bbox, chars)
        def push(kind, label_, bbox, no, texts, extra=None):
            n = len(texts)
            for k, t in enumerate(texts):
                d = {"kind": kind, "label": _clean(label_), "bbox": bbox, "no": _clean(no) if no else no, "text": _clean(t), "part": [k + 1, n] if n > 1 else None}
                if extra: d.update(extra)
                units.append(d)
            return sum(len(t) for t in texts)
        # 图幅单元
        sheet_units = []
        for u in range(nS):
            s = self.sheets[u]; f = s["frame"]
            hdr = ["#mengos-cad v1", f"#单元 图幅 S{u + 1}｜{label(u)}｜外接框 {R(f[0])},{R(f[1])},{R(f[2])},{R(f[3])}｜图框 {s['how']}" + ("" if s["tb"] is not None else "｜无标题栏")]
            if s["tb"] is not None:
                hdr.append("#标题栏（格：x0,y0|内容）")
                for (b, tis) in tb_cells[u]:
                    hdr.append(f"{R(b[0])},{R(b[1])}|" + " ".join(TXT[i][4] for i in sorted(tis, key=lambda i: (-TXT[i][1], TXT[i][0]))))
                    cons["texts"] += len(tis)
            sheet_units.append((u, hdr, sections_of(u)))
        for (u, hdr, sec) in sheet_units:
            s = self.sheets[u]; f = s["frame"]
            ch = push("图幅", label(u), [R(v) for v in f], s["no"], _chunk_texts(hdr, sec, args.B), {"has_tb": s["tb"] is not None, "how": s["how"]})
            catalog_rows.append(("图幅", u + 1, label(u), [R(v) for v in f], ch))
        # 区块单元 (框外池 / 全图)
        for k in range(nL):
            u = nS + k; f = self.leaf_box[k]
            pre = "图框外·区块" if nS else "区块"
            hdr = ["#mengos-cad v1", f"#单元 {pre} {k + 1}｜{label(u)}｜外接框 {R(f[0])},{R(f[1])},{R(f[2])},{R(f[3])}"]
            ch = push("区块", label(u), [R(v) for v in f], None, _chunk_texts(hdr, sections_of(u), args.B))
            catalog_rows.append(("区块", k + 1, label(u), [R(v) for v in f], ch))
        # 无归属检查 (单元号越界)
        stray = sum(1 for d in (per_t, per_i, per_d, per_c, per_s) for u in d if u >= nU or u < 0)
        # 表单元
        for i in tab_order:
            t = tabs[i]
            hdr = f"#mengos-cad v1\n#表 T{tab_no[i]}｜所在单元 {_unit_name(int(tbu[i]), nS)}｜位置 {R(t['x'])},{R(t['y'])}｜{t['nr']}×{t['nc']}" + ("｜标题栏类" if t["title"] else "")
            push("表", f"T{tab_no[i]}", None, None, _table_texts(hdr, t, args.B), {"table_no": tab_no[i], "rows": t["nr"], "cols": t["nc"], "unit": int(tbu[i])})
        # 插入汇总
        tot = Counter(r[0] for r in INSR); direct = Counter(r[0] for r in INSR if r[6] == 0)
        att = defaultdict(Counter)
        for r in INSR:
            for kk, vv in r[5]:
                att[r[0]][f"{kk}={vv}"] += 1
        dist = defaultdict(Counter)
        for j, i in enumerate(ins0):
            dist[INSR[i][0]][int(iu[j])] += 1
        sl = []
        for n in sorted(tot):
            if n.startswith("*U"):
                o = lost["u_names"].get(n)
                nm = f"{o}（动态块实例 {n}）" if o else f"{n}（原名未解出）"
            else:
                nm = n
            sl.append(f"{nm}|{direct.get(n, 0)}|{tot[n]}|" + ";".join(f"{_unit_name(u, nS)}×{c}" for u, c in sorted(dist[n].items())) + "|" +
                      ";".join(f"{a}×{c}" for a, c in sorted(att[n].items())))
        summ_texts = _chunk_texts(["#mengos-cad v1", "#单元 图块插入汇总", "#图块（名称|直接插入|含嵌套总数|直接插入所在单元分布|属性取值）"], [(None, sl)], args.B)
        # 总览
        ov_head = ["#mengos-cad v1", "#单元 总览", f"#文件 {fid}", f"#DXF版本 {lost['acadver'] or '未知'}",
                   f"#单元数 图幅 {nS}｜区块 {nL}｜表 {len(tabs)}",
                   f"#展开 线段 {budget.get('E_actual')}｜插入 {len(INSR)}｜文字 {len(TXT)}｜尺寸 {len(DIMS)}",
                   "#切法 " + ("图框法" if self.use_frames else "留白切分") + f"｜g={self.checks['cut']['g']}"]
        ls_lines = []
        if lost["acadver"] and lost["acadver"] < "AC1018":
            ls_lines.append(f"DXF版本 {lost['acadver']} 早于 AC1018|1|此版本 DXF 不含表格对象，图中的表以线条与文字呈现，未识别为表")
        for k, v in sorted(lost["skipped"].items()):
            if v:
                ls_lines.append(f"{k}|{v}|{_lost_hint(k)}")
        po, pe = lost["proxy_ok"], lost["proxy_empty"]
        if po[0]:
            ls_lines.append(f"代理实体（专业软件自定义对象）|{po[0]}|按代理图形读出线 {po[1]} 条、文字 {po[2]} 条；对象自身数据未读")
        if pe:
            ls_lines.append(f"{PX_EMPTY_KIND}|{sum(pe.values())}|类名 " + "、".join(f"{k}×{v}" for k, v in pe.items()) +
                            "：内容未读。需要读全的，请在原专业软件里先分解（EXPLODE）再另存 DXF")
        if lost["proxy_err"]:
            ls_lines.append(f"{PX_ERR_KIND}|{lost['proxy_err']}|{PX_ERR_NOTE}")
        if lost["proxy_uninserted"] and not uninserted:
            ls_lines.append(f"代理实体（只在未插入的图块里）|{lost['proxy_uninserted']}|不在图面上，未读")
        if lost["gdt_font_texts"]:
            ls_lines.append(f"GDT 字体文字|{lost['gdt_font_texts']}|GDT 字体文字 {lost['gdt_font_texts']} 处，按原字母输出")
        if lost["dim_block_texts_excluded"]:
            ls_lines.append(f"尺寸块内文字（已由尺寸标注项承载，不重复列出）|{lost['dim_block_texts_excluded']}|无需处理")
        ov_sec = [("#丢失声明（类型|处数|说明）", ls_lines)]
        if uninserted:
            ut = lost["uninserted_tables"]; n_ut = sum(ut.values())
            ov_sec.append((f"#未插入图块（不在图面上；块名|其中文字条数" + ("，含表格非空单元格|含表张数" if n_ut else "") + f"）共 {len(uninserted)} 个，文字合计 {sum(uninserted_texts.values())} 条" +
                           (f"，其中含表 {n_ut} 张" if n_ut else "") +
                           (f"，其中含代理实体 {lost['proxy_uninserted']} 个" if lost["proxy_uninserted"] else ""),
                           [f"{nm}|{uninserted_texts.get(nm, 0)}" + (f"|含表 {ut[nm]} 张" if ut.get(nm) else "") for nm in uninserted]))
        ovt = _chunk_texts(ov_head, ov_sec, args.B)
        # 目录
        cat = [f"{kind}{no}|{lb}|{','.join(bb)}|{ch}" for (kind, no, lb, bb, ch) in catalog_rows]
        catt = _chunk_texts(["#mengos-cad v1", "#单元 图幅目录（序号|标签|外接框|字数）"], [(None, cat)], args.B)
        out = []
        def put(kind, label_, texts):
            n = len(texts)
            for k, t in enumerate(texts):
                out.append({"kind": kind, "label": label_, "bbox": None, "no": None, "text": _clean(t), "part": [k + 1, n] if n > 1 else None})
        put("总览", "总览", ovt)
        put("图幅目录", "图幅目录", catt)
        out += units
        put("图块插入汇总", "图块插入汇总", summ_texts)
        # 守恒
        self.checks["conservation"] = {
            "texts_total": len(TXT), "texts_in_units(incl.title-block)": cons["texts"],
            "inserts_direct_total": len(ins0), "inserts_in_units": cons["inserts"],
            "dims_total": len(DIMS), "dims_in_units": cons["dims"],
            "tables_total": len(tabs), "table_units": len(tab_order),
            "closed_top_total": len(CL), "closed_in_units": cons["closed"],
            "segments_total": int(budget.get("E_actual", 0)), "segments_in_stats(len>=1)": cons["seg"],
            "stray": stray, "direct_inserts_moved_by_atom": moved,
            "ok": cons["texts"] == len(TXT) and cons["inserts"] == len(ins0) and cons["dims"] == len(DIMS) and len(tab_order) == len(tabs) and stray == 0}
        tc = Counter(tu.tolist())
        self.checks["text_share"] = {"texts_in_sheets": int(sum(v for u, v in tc.items() if u < nS)), "texts_total": len(TXT),
                                     "max_unit_share": round(max(tc.values()) / len(TXT), 4) if TXT else None, "units_with_text": len(tc)}
        self.checks["unit_count"] = len(out)
        return out


def _clean(s):
    """输出前的最后一道: 孤立代理项 (非法字节经 surrogateescape 读入所致) 一律换成 U+FFFD, 保证 units.json 是合法 UTF-8。"""
    return s.encode("utf-8", "surrogatepass").decode("utf-8", "replace") if isinstance(s, str) else s


def _unit_name(u, nS):
    return f"图幅 S{u + 1}" if u < nS else f"区块 {u - nS + 1}"


LOST_HINTS = {
    "3DSOLID": "三维实体不读几何（本身不带文字）",
    "BODY": "三维实体不读几何（本身不带文字）",
    "REGION": "面域不读几何（本身不带文字）",
    "SURFACE": "曲面不读几何（本身不带文字）",
    "MESH": "网格不读几何（本身不带文字）",
    "WIPEOUT": "遮罩只影响渲染，未处理",
    "IMAGE": "光栅图像未读",
    "OLE2FRAME": "嵌入对象未读",
    "VIEWPORT": "布局视口不读",
}


def _lost_hint(k):
    t = k.split(":")[0]
    if t in LOST_HINTS:
        return LOST_HINTS[t]
    if t.startswith("形位公差") or t.startswith("TOLERANCE"):
        return "表外码按 〔GDT码x〕 保留原码，未译"
    if k.startswith("未插入图块:"):
        return "统计未插入图块时读取出错，该块的计数可能偏少"
    if ":块不存在" in k:
        return "引用了不存在的图块，该插入未展开"
    return "此类对象未读或读取出错，已计数"


def _chunk_texts(head, sections, B):
    """把 head (每块重复的头部行) 加若干段 (hdr, lines) 写成文本; 总长 ≤ B 则一块, 否则按行块再切 (只切不截,
    单行超过 B 也整行保留)。每块重复头部与所在段的段头 (段头加“本块第 a–b 条”); 多块时头部后加“#分块 k/n”。hdr 为 None 的段不写段头。"""
    def seg_header(hdr, a, m, total):
        if hdr is None:
            return None
        return hdr if (a == 0 and m == total) else f"{hdr}｜本块第 {a + 1}–{a + m} 条"
    full_len = sum(len(x) + 1 for x in head) + sum((len(h) + 1 if h is not None else 0) + sum(len(l) + 1 for l in ls) for h, ls in sections)
    if full_len <= B:
        out = list(head)
        for h, ls in sections:
            if h is not None:
                out.append(h)
            out += ls
        return ["\n".join(out) + "\n"]
    base = sum(len(x) + 1 for x in head) + 20
    chunks = []; segs = []; used = base; content = 0
    for hdr, ls in sections:
        seg = None
        if not ls:
            hl = (len(hdr) + 1) if hdr is not None else 0
            if content and used + hl > B:
                chunks.append(segs); segs = []; used = base; content = 0
            segs.append([hdr, 0, [], 0]); used += hl
            continue
        for j, line in enumerate(ls):
            hcost = 0 if seg is not None else ((len(hdr) + 40) if hdr is not None else 0)
            if content and used + hcost + len(line) + 1 > B:
                chunks.append(segs); segs = []; used = base; content = 0; seg = None
                hcost = (len(hdr) + 40) if hdr is not None else 0
            if seg is None:
                seg = [hdr, j, [], len(ls)]; segs.append(seg); used += hcost
            seg[2].append(line); used += len(line) + 1; content += 1
    if segs:
        chunks.append(segs)
    n = len(chunks)
    texts = []
    for ci, sg in enumerate(chunks):
        out = list(head)
        if n > 1:
            out.append(f"#分块 {ci + 1}/{n}")
        for hdr, a, ls, total in sg:
            sh = seg_header(hdr, a, len(ls), total) if ls else hdr
            if sh is not None:
                out.append(sh)
            out += ls
        texts.append("\n".join(out) + "\n")
    return texts


def _table_texts(hdr, t, B):
    """表单元文本: 头 + GFM 表; 超过 B 按行块切, 每块重复头与首行 (表头)。竖向合并跨块界时, 下一块在该列首行重复左上格文本并加〔续〕。"""
    rows = _gfm_rows(t)
    head_lines = hdr.split("\n") + rows[:2]
    body = rows[2:]
    full = "\n".join(head_lines + body) + "\n"
    if len(full) <= B:
        return [full]
    nr = t["nr"]
    base = sum(len(x) + 1 for x in head_lines) + 20
    chunks = []; cur = []; used = base; first_row = 1
    for k, line in enumerate(body):
        r = k + 1
        if cur and used + len(line) + 1 > B:
            chunks.append((first_row, cur)); cur = []; used = base; first_row = r
        cur.append(line); used += len(line) + 1
    if cur:
        chunks.append((first_row, cur))
    n = len(chunks); texts = []
    for ci, (fr, ls) in enumerate(chunks):
        lines = list(head_lines)
        if n > 1:
            lines.append(f"#分块 {ci + 1}/{n}｜表行 {fr + 1}–{fr + len(ls)}")
        lines += _continue_marks(t, fr, ls)
        texts.append("\n".join(lines) + "\n")
    return texts


def _continue_marks(t, first_row, lines):
    """块首行若有竖向合并区从上一块延续进来, 在该列写“左上格文本〔续〕”。"""
    if first_row <= 0 or not lines:
        return lines
    nc = t["nc"]; rows = t["rows"]
    cells = _split_gfm(lines[0], nc)
    for (r0, c0), (h, w) in t["spans"].items():
        if r0 < first_row <= r0 + h - 1 and h > 1:
            v = rows[r0][c0] if r0 < len(rows) and c0 < len(rows[r0]) else ""
            if c0 < nc and not cells[c0].strip():
                cells[c0] = (v.replace("|", "\\|") + " " if v else "") + "〔续〕"
    return ["| " + " | ".join(cells) + " |"] + lines[1:]


def _split_gfm(line, nc):
    body = line[2:-2] if line.startswith("| ") and line.endswith(" |") else line
    parts = re.split(r"(?<!\\) \| ", body)
    return (parts + [""] * nc)[:nc]


def _h8(s):
    import hashlib
    return hashlib.sha256((s or "").encode("utf-8", "surrogateescape")).hexdigest()[:8]


def _pm(c):
    try:
        return fx(plain_mtext(c)).replace("\n", " ").strip()
    except Exception:
        return fx(c).strip()


def _gfm_rows(t):
    """合并格写法: 合并区左上格写文本并加跨度记号〔合并 行×列〕; 被覆盖格留空; 竖线转义; 第 0 行为表头, 其后一行分隔线。"""
    nr, nc = t["nr"], t["nc"]
    rows = t["rows"]
    esc = lambda s: s.replace("|", "\\|")
    out = []
    for r in range(nr):
        cells = []
        for c in range(nc):
            v = rows[r][c] if r < len(rows) and c < len(rows[r]) else ""
            v = esc(v)
            if (r, c) in t["spans"]:
                h, w = t["spans"][(r, c)]
                v = (v + " " if v else "") + f"〔合并 {h}×{w}〕"
            cells.append(v)
        out.append("| " + " | ".join(cells) + " |")
        if r == 0:
            out.append("|" + "---|" * nc)
    return out


# ───────── 完整解析结构 (解析规格 ../SPEC.md §6、§7) ─────────
def _txt_content(e):
    """未插入图块里一条文字的内容: 规整同图面文字 (MTEXT 去格式、换行换空格; 转义还原); 读不出 ⟹ 退回原始串, 不抛。"""
    try:
        if e.dxftype() == "MTEXT":
            s = e.plain_text(split=False).replace("\n", " ").strip()
        else:
            s = e.plain_text() if hasattr(e, "plain_text") else e.dxf.text
        return _clean(fx(s).strip())
    except Exception:
        try:
            return _clean(fx(e.dxf.get("text", "")).strip())
        except Exception:
            return ""


def _nested_inserts(model, cache):
    """嵌套插入: 直接插入 (根容器的 INSERT) 之下各层图块里的 INSERT, 世界坐标与旋转同记录遍的算法。
    返回 [(名称, x, y, 旋转, 嵌套层, 所属直接插入的序号 或 -1)]; 序号 = 根容器 INSERT 展开后的次序 (= INSR 里直接插入的次序);
    由尺寸标注图块带出的 (不在任何直接插入之下) 记 -1。"""
    out = []; st = []; k_ins = 0
    for (k, Mk, lay, kind) in model.kids:
        own = -1
        if kind == "insert":
            own = k_ins; k_ins += 1
        st.append((k, Mk, 1, own))
    while st:
        name, M, depth, own = st.pop()
        bc = cache[name]
        A = M[:2, :2]; tr = M[2, :2]
        ra = math.degrees(math.atan2(A[0, 1], A[0, 0]))
        for (n, x, y, rot, l, att) in bc.ins:
            p = np.array([x, y]) @ A + tr
            out.append((n, float(p[0]), float(p[1]), (rot + ra) % 360, depth, own))
        for (k2, Mk2, lay2, kind2) in bc.kids:
            st.append((k2, Mk2 @ M, depth + 1, own))
    return out


def _unparsed_by_unit(U, root, cache, visits, traverse, ab, SK_ATOM, PXE_ATOM, PXR_ATOM, POS_ATOM):
    """未解析清单按单元: 根容器里的按记下的顶层原子归单元; 图块里的按每一处展开所在的顶层原子归单元。
    原子位置取实体自身位置, 否则取原子外接框中心; 都没有或不落在任何单元 ⟹ 单元为 None。
    同时按展开处数汇总每个实体的去处 (对象总数守恒)。"""
    nS = len(U.sheets); nU = U.n_units()
    memo = {}
    def uoa(a):
        if a in memo:
            return memo[a]
        pt = POS_ATOM.get(a) if a >= 0 else None
        if pt is None and 0 <= a < len(ab) and not np.isnan(ab[a, 0]):
            pt = ((ab[a, 0] + ab[a, 2]) / 2, (ab[a, 1] + ab[a, 3]) / 2)
        r = None
        if pt is not None:
            u = int(U.assign_points(np.array([pt[0]], dtype=float), np.array([pt[1]], dtype=float))[0])
            if 0 <= u < nU:
                r = _unit_name(u, nS)
        memo[a] = r
        return r
    UNP = Counter()
    for (k, a), c in SK_ATOM.items():
        UNP[(k, uoa(a), _lost_hint(k))] += c
    for (cls, a), c in PXE_ATOM.items():
        UNP[(PX_EMPTY_KIND, uoa(a), "类名 " + cls)] += c
    for a, c in PXR_ATOM.items():
        UNP[(PX_ERR_KIND, uoa(a), PX_ERR_NOTE)] += c
    OUT = Counter(); ET = Counter()
    def on(name, bc, M, plid, depth, atom):
        OUT.update(bc.oc); ET.update(bc.et)
        if name == root:
            return
        u = None
        for k, c in bc.sk.items():
            if c:
                u = uoa(atom); UNP[(k, u, _lost_hint(k))] += c
        for cls, c in bc.px["empty"].items():
            if c:
                UNP[(PX_EMPTY_KIND, uoa(atom), "类名 " + cls)] += c
        if bc.px["err"]:
            UNP[(PX_ERR_KIND, uoa(atom), PX_ERR_NOTE)] += bc.px["err"]
    traverse(on)
    return UNP, {"outcomes": OUT, "empty_types": ET}


_DIR = ("水平", "竖直", "斜")


def _detail(unit, section, rows_or_count, stored):
    n = rows_or_count if isinstance(rows_or_count, int) else len(rows_or_count)
    return {"unit": unit, "section": section, "header": DETAIL_HEAD[section].format(n=n), "count": n, "stored": stored,
            "lines": [] if (not stored or isinstance(rows_or_count, int)) else rows_or_count}


def _parsed_doc(U, units, SEGD, NEST, UTX, UNP, ENT, lost, uninserted_texts, budget, fid):
    from . import library
    nS = len(U.sheets); nU = U.n_units()
    INSR = U.INSR
    LN = {v: k for k, v in LAYERS.items()}
    uname = lambda u: _unit_name(u, nS) if 0 <= u < nU else None
    # 线段明细: 每单元一节; 行序 = (图层, 方向, 长度, 起点x, 起点y, 终点x, 终点y)
    seg_rows = defaultdict(list)
    seg_cnt = Counter()
    for u, c in SEGD["cnt"].items():
        seg_cnt[u if 0 <= u < nU else -1] += c
    seg_stored = not SEGD["over"]
    if seg_stored and SEGD["keep"]:
        P = np.vstack([k[0] for k in SEGD["keep"]]); L = np.concatenate([k[1] for k in SEGD["keep"]])
        uu = np.concatenate([k[2] for k in SEGD["keep"]]); ln = np.concatenate([k[3] for k in SEGD["keep"]])
        oo = np.concatenate([k[4] for k in SEGD["keep"]])
        uu = np.where((uu >= 0) & (uu < nU), uu, -1)
        names = sorted(set(LN[int(l)] for l in np.unique(L).tolist()))
        rank = {n: i for i, n in enumerate(names)}
        lr = np.array([rank[LN[int(l)]] for l in L.tolist()], dtype=np.int64)
        order = np.lexsort((P[:, 3], P[:, 2], P[:, 1], P[:, 0], ln, oo, lr, uu))
        for i in order.tolist():
            seg_rows[int(uu[i])].append(f"{LN[int(L[i])]}|{_DIR[int(oo[i])]}|{_n3(ln[i])}|{_n3(P[i, 0])},{_n3(P[i, 1])}|{_n3(P[i, 2])},{_n3(P[i, 3])}")
    # 嵌套插入: 归所属直接插入的单元; 尺寸标注带出的按自身位置
    iu = getattr(U, "_iu", np.zeros(0, int))
    nest_items = defaultdict(list)
    loose = [i for i, r in enumerate(NEST) if r[5] < 0]
    lu = U.assign_points(np.array([NEST[i][1] for i in loose], dtype=float), np.array([NEST[i][2] for i in loose], dtype=float)).tolist() if loose else []
    lmap = dict(zip(loose, lu))
    for i, (n, x, y, rot, depth, own) in enumerate(NEST):
        if own >= 0:
            u = int(iu[own]); d = INSR[own]; ow = f"{d[0]}@{R(d[1])},{R(d[2])}"
        else:
            u = int(lmap[i]); ow = ""
        u = u if 0 <= u < nU else -1
        r3 = round(rot, 3) % 360
        nest_items[u].append(((n, round(x, 3), round(y, 3), r3, depth, ow), f"{n}|{_n3(x)}|{_n3(y)}|{_n3(r3)}|{depth}|{ow}"))
    nest_stored = len(NEST) <= DETAIL_CAP["嵌套插入"]
    nest_rows = {u: [t for _, t in sorted(v, key=lambda kv: kv[0])] for u, v in nest_items.items()}
    details = []
    for u in list(range(nU)) + [-1]:
        sr = seg_rows.get(u, []); nr = nest_rows.get(u, [])
        if u == -1 and not seg_cnt.get(-1) and not nr:
            continue
        details.append(_detail(uname(u), "线段明细", sr if seg_stored else seg_cnt.get(u, 0), seg_stored))
        details.append(_detail(uname(u), "嵌套插入", nr if nest_stored else len(nr), nest_stored))
    ut_rows = [f"{bn}|{c}" for bn, c in sorted(UTX, key=lambda t: t[0])]
    ut_stored = len(ut_rows) <= DETAIL_CAP["未插入图块文字"]
    details.append(_detail(None, "未插入图块文字", ut_rows if ut_stored else len(ut_rows), ut_stored))
    unparsed = [{"kind": k, "unit": u, "count": c, "note": note} for (k, u, note), c in
                sorted(UNP.items(), key=lambda kv: (kv[0][0], kv[0][1] or "", kv[0][2]))]
    declared = sum(lost["skipped"].values()) + sum(lost["proxy_empty"].values()) + lost["proxy_err"]
    oc = ENT["outcomes"]
    n_direct = sum(1 for r in INSR if r[6] == 0)
    cons = {
        "entities": {"expanded": sum(oc.values()), "parsed": oc.get("parsed", 0), "partial": oc.get("partial", 0),
                     "unparsed": oc.get("unparsed", 0), "empty": oc.get("empty", 0), "empty_types": dict(sorted(ENT["empty_types"].items()))},
        "segments": {"total": int(budget.get("E_actual", 0)), "detail": SEGD["n"]},
        "inserts": {"total": len(INSR), "direct": n_direct, "nested": len(NEST)},
        "uninserted_texts": {"total": sum(uninserted_texts.values()), "detail": len(UTX)},
        "unparsed": {"declared": declared, "listed": sum(UNP.values())},
    }
    cons["ok"] = (cons["segments"]["total"] == cons["segments"]["detail"] and n_direct + len(NEST) == len(INSR)
                  and cons["uninserted_texts"]["total"] == cons["uninserted_texts"]["detail"] and declared == cons["unparsed"]["listed"])
    return {"format": "mengos-cad-parsed", "spec": SPEC_VERSION, "library": library(), "ezdxf": ezdxf.__version__, "fid": fid,
            "units": units, "details": details, "unparsed": unparsed, "conservation": cons}


def run(dxf, outdir, fid="X", emax=25_000_000, imax=500_000, max_out_bytes=64 * 1024 * 1024, parsed=False):
    """解析一份 DXF, 写 outdir/units.json (parsed=True 另写 outdir/parsed.json); 返回摘要 {"ok", "units", "budget"}。失败抛 CadFail。"""
    args.dxf = dxf; args.outdir = outdir; args.fid = fid
    args.emax = emax; args.imax = imax; args.max_out_bytes = max_out_bytes; args.parsed = bool(parsed)
    LAYERS.clear(); lid_of("0")   # 图层编号表每次从 "0" 起 (LAYER0 恒为 0)
    try:
        return main()
    except MemoryError:
        fail("CAD_RESOURCE_EXCEEDED", "处理该图纸所需内存超过上限", 4)
