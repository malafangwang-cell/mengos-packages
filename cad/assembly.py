#!/usr/bin/env python3
"""cad.assemble（第 1 阶段原型：包内离线验证，不接引擎、不进登记、不在 lock 覆盖范围内）

依据：mengosv2 docs/alignment/arch/立项-CAD装配工具-2026-11-16.md §四、§九 第 1 阶段（立法者 2026-11-19 裁）。

入参（装配计划）：
  {"name": "装配体名（文件名口径，同 cad.build）",
   "parts":  [{"id": "零件名", "plan": "零件计划（与 cad.build 同一种文字、同一个解析器与建模程序）"}, …],
   "layout": "摆位表，一行摆一个零件或一组阵列",
   "formats": ["step", "glb", "csv", "svg", "dxf"] 的子集，缺省 step、glb、csv、svg}

摆位表（按顺序摆放，不做联立求解；行名不含点）：
  b:  fix 零件 [at=(x,y,z)] [rot=(rx,ry,rz)]
  r:  put 零件 at=(x,y,z) [rot=(rx,ry,rz)]                               给定位姿
  r:  put 零件 coaxial=轴 [axis=本件轴] [face=本件面 to=面 [gap=]|[flush]] [angle=|mesh=行名[.齿轮] [gear=本件齿轮]]
  r:  put 零件 face=本件面 to=面 [gap=] [flush] [face2= to2= gap2= flush2] [face3= to3= gap3= flush3]
  [r:] pattern 行名 linear n= [dx=] [dy=] [dz=]
  [r:] pattern 行名 circular n= axis=轴 [angle=360]

  轴：行名 | 行名.特征名（已摆好的零件）；本件轴：特征名（缺省为零件的主轴，即第一个带轴的特征）。
  面：[行名.][特征名.]方位词 | [行名.]特征名；方位词 top bottom front back left right 指（该特征的）该侧最外平面。
  在 to= / coaxial= 里，开头的名字先按行名找，找不到再按零件名找（该零件只摆了一处时）。
  本件的面与轴可以带本件零件名前缀，也可以不带。

确定性：同一装配计划，产出记录与全部文件逐字节相同（STEP 时间戳固定、去注释行；GLB、CSV 自写；
DXF 用 ezdxf 的固定元数据开关；进程入口固定 PYTHONHASHSEED=0）。
耗时分项写在模块变量 LAST_TIMINGS 里，不进产出记录（否则破坏确定性）。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import struct
import sys
import tempfile
import time

DEFAULT_TIMEOUT_MS = 60_000
MAX_PARTS = 40
MAX_INSTANCES = 200
MAX_PLAN_CHARS = 20_000
MAX_LAYOUT_CHARS = 20_000
MAX_TOTAL_CHARS = 200_000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TRIANGLES = 2_000_000
FORMATS = {"step": ("model/step", ".step", "model.exact"),
           "glb": ("model/gltf-binary", ".glb", "model.view"),
           "csv": ("text/csv", ".bom.csv", "table.bom"),
           "svg": ("image/svg+xml", ".svg", "drawing"),
           "dxf": ("image/vnd.dxf", ".dxf", "drawing")}
DEFAULT_FORMATS = ["step", "glb", "csv", "svg"]
ID_RE = re.compile(r"[A-Za-z_一-鿿][A-Za-z0-9_一-鿿]{0,63}")
DIRS = {"top": (0.0, 0.0, 1.0), "bottom": (0.0, 0.0, -1.0), "front": (0.0, -1.0, 0.0),
        "back": (0.0, 1.0, 0.0), "right": (1.0, 0.0, 0.0), "left": (-1.0, 0.0, 0.0)}
POS_TOL = 0.01         # mm：位置自洽、中心距
ANG_TOL = 1e-4         # 弧度：平行、垂直判定（约 0.006°）
# 干涉阈值（第 1 阶段读数定，见 PR）：公共体积小于此值视为接触而非干涉
INTERFERE_MIN_MM3 = 1e-3
INTERFERE_REL = 1e-7   # 相对较小零件体积
MESH_MIN_MM3 = 1.0     # 声明了啮合的齿轮对：齿面贴合处样条拟合误差带来的微小公共体积
MESH_REL = 1e-4
AXIS_KINDS = ("cylinder", "cone", "revolve", "gear", "helix")

LAST_TIMINGS: dict = {}


class BadInput(Exception):
    def __init__(self, message, line=None, hint=None, problems=None):
        super().__init__(message)
        self.line, self.hint, self.problems = line, hint, problems


class ResourceLimit(Exception):
    pass


class _Timeout(Exception):
    pass


def r6(x):
    return round(float(x), 6) + 0.0


def r3(x):
    return round(float(x), 3) + 0.0


# ---------------------------------------------------------------- 位姿（纯 Python 浮点，确定）
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a):
    L = math.sqrt(_dot(a, a))
    return (a[0] / L, a[1] / L, a[2] / L)


def _snap(x):
    for v in (0.0, 1.0, -1.0, 0.5, -0.5):
        if abs(x - v) < 1e-12:
            return v
    return x + 0.0


class Pose:
    """x_world = R · x_local + t。R 为 3×3 行主序元组。"""
    __slots__ = ("R", "t")

    def __init__(self, R=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), t=(0.0, 0.0, 0.0)):
        self.R = tuple(tuple(_snap(v) for v in row) for row in R)
        self.t = tuple(_snap(v) for v in t)

    def dir(self, v):
        R = self.R
        return (_dot(R[0], v), _dot(R[1], v), _dot(R[2], v))

    def pt(self, p):
        return _add(self.dir(p), self.t)

    def then(self, other):
        """先 self 再 other：other ∘ self。"""
        Ro = other.R
        cols = [self.dir(e) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
        R = tuple(tuple(_dot(Ro[i], cols[j]) for j in range(3)) for i in range(3))
        return Pose(R, other.pt(self.t))

    def matrix12(self):
        R, t = self.R, self.t
        return [R[0][0], R[0][1], R[0][2], t[0], R[1][0], R[1][1], R[1][2], t[1], R[2][0], R[2][1], R[2][2], t[2]]


def _rot_axis(axis, ang, about=(0.0, 0.0, 0.0)):
    """绕过点 about、方向 axis 的直线转 ang 弧度。"""
    k = _norm(axis)
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    x, y, z = k
    R = ((c + x * x * C, x * y * C - z * s, x * z * C + y * s),
         (y * x * C + z * s, c + y * y * C, y * z * C - x * s),
         (z * x * C - y * s, z * y * C + x * s, c + z * z * C))
    p = Pose(R)
    return Pose(p.R, _sub(about, p.dir(about)))


def _perp(d):
    """与 d 垂直的一个确定方向。"""
    ref = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    return _norm(_cross(d, ref))


def _rot_between(a, b):
    """把单位向量 a 转到 b 的最短转动（反向时绕确定的垂直轴转 180°）。"""
    c = _dot(a, b)
    if c > 1 - 1e-12:
        return Pose()
    if c < -1 + 1e-12:
        return _rot_axis(_perp(a), math.pi)
    return _rot_axis(_cross(a, b), math.acos(max(-1.0, min(1.0, c))))


def _euler(rot):
    """rot=(rx,ry,rz) 度：先绕 x、再绕 y、再绕 z（固定轴）。"""
    p = Pose()
    for axis, deg in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rot):
        if deg:
            p = p.then(_rot_axis(axis, math.radians(deg)))
    return p


def _occ_loc(pose):
    from OCP.gp import gp_Trsf
    from OCP.TopLoc import TopLoc_Location
    tr = gp_Trsf()
    m = pose.matrix12()
    tr.SetValues(*m)
    return TopLoc_Location(tr)


# ---------------------------------------------------------------- 零件
class Part:
    def __init__(self, pid, plan, res, order):
        self.id, self.plan, self.res, self.order = pid, plan, res, order
        self.feats = {f.id: f for f in res.features}
        self._axis_cache = {}
        self._planes = None
        self.instances = 0

    # 平面：[(normal, d, feature_id)]，按曲面键去重
    def planes(self):
        if self._planes is None:
            from builder import face_owner, surface_key
            seen, out = set(), []
            for f in self.res.part.faces():
                if str(f.geom_type).split(".")[-1] != "PLANE":
                    continue
                k = surface_key(f)
                own = face_owner(f, self.res.features)
                if (k, own) in seen:
                    continue
                seen.add((k, own))
                c = f.center()
                n = f.normal_at(c)
                n = (n.X, n.Y, n.Z)
                out.append((n, _dot(n, (c.X, c.Y, c.Z)), own, (c.X, c.Y, c.Z)))
            self._planes = out
        return self._planes

    def axis_of(self, fid):
        """特征的轴：(点, 单位方向) 或 None；不唯一时抛 ValueError。"""
        if fid in self._axis_cache:
            v = self._axis_cache[fid]
            if isinstance(v, str):
                raise ValueError(v)
            return v
        f = self.feats[fid]
        kind = f.params.get("kind")
        res = None
        if kind in AXIS_KINDS:
            at = f.params.get("at", (0.0, 0.0, 0.0))
            ax = "z" if kind == "gear" else f.params.get("axis", "z")
            d = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}[ax]
            res = (tuple(float(v) for v in at), d)
        else:
            from builder import cylinder_info, face_owner
            axes = []
            for face in self.res.part.faces():
                if str(face.geom_type).split(".")[-1] != "CYLINDER" or face_owner(face, self.res.features) != fid:
                    continue
                d, p, _ = cylinder_info(face)
                key = (round(d[0], 5), round(d[1], 5), round(d[2], 5), round(p[0], 3), round(p[1], 3), round(p[2], 3))
                if key not in [a[0] for a in axes]:
                    axes.append((key, (p, d)))
            if len(axes) > 1:
                msg = f"特征 {fid} 上有 {len(axes)} 根不同的轴（阵列或多个孔），指不出是哪一根"
                self._axis_cache[fid] = msg
                raise ValueError(msg)
            if axes:
                res = axes[0][1]
        self._axis_cache[fid] = res
        return res

    def main_axis(self):
        for f in self.res.features:
            try:
                a = self.axis_of(f.id)
            except ValueError:
                continue
            if a is not None:
                return f.id, a
        return None, None

    def gear_feats(self):
        return [f for f in self.res.features if f.params.get("kind") == "gear"]

    def is_axisymmetric(self, p, d):
        """零件的每个面都是绕这根轴的回转面（垂直于轴的平面、同轴的圆柱、圆锥、圆环、球）。"""
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus

        def on_axis(ax):
            q = ax.Location()
            dd = ax.Direction()
            dv = (dd.X(), dd.Y(), dd.Z())
            if abs(abs(_dot(dv, d)) - 1) > 1e-6:
                return False
            w = _sub((q.X(), q.Y(), q.Z()), p)
            off = _sub(w, _mul(d, _dot(w, d)))
            return _dot(off, off) < 1e-6
        for f in self.res.part.faces():
            s = BRepAdaptor_Surface(f.wrapped)
            t = s.GetType()
            if t == GeomAbs_Plane:
                n = s.Plane().Axis().Direction()
                if abs(abs(n.X() * d[0] + n.Y() * d[1] + n.Z() * d[2]) - 1) > 1e-6:
                    return False
            elif t == GeomAbs_Cylinder:
                if not on_axis(s.Cylinder().Axis()):
                    return False
            elif t == GeomAbs_Cone:
                if not on_axis(s.Cone().Axis()):
                    return False
            elif t == GeomAbs_Torus:
                if not on_axis(s.Torus().Axis()):
                    return False
            elif t == GeomAbs_Sphere:
                c = s.Sphere().Location()
                w = _sub((c.X(), c.Y(), c.Z()), p)
                off = _sub(w, _mul(d, _dot(w, d)))
                if _dot(off, off) > 1e-6:
                    return False
            else:
                return False
        return True


class Inst:
    def __init__(self, row, part, pose, line, index=0, source=None):
        self.row, self.part, self.pose, self.line = row, part, pose, line
        self.index, self.source = index, source
        self.item = None
        self._shape = None

    @property
    def shape(self):
        if self._shape is None:
            from build123d import Compound
            self._shape = Compound(self.part.res.part.wrapped.Moved(_occ_loc(self.pose)))
        return self._shape


# ---------------------------------------------------------------- 入参
def _payload(payload):
    allowed = {"name", "parts", "layout", "formats"}
    extra = set(payload) - allowed
    if extra:
        raise BadInput(f"不认识的字段：{', '.join(sorted(extra))}")
    name = payload.get("name", "assembly")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", name):
        raise BadInput("name 只能由字母、数字、下划线、连字符组成，1–64 个字符")
    parts = payload.get("parts")
    if not isinstance(parts, list) or not parts:
        raise BadInput("parts 必须是非空数组：每项 {id: 零件名, plan: 零件计划}")
    if len(parts) > MAX_PARTS:
        raise BadInput(f"零件种数超过 {MAX_PARTS}")
    seen, total = set(), 0
    for i, p in enumerate(parts):
        if not isinstance(p, dict) or set(p) != {"id", "plan"}:
            raise BadInput(f"parts[{i}] 应当是 {{id, plan}} 两个字段")
        if not isinstance(p["id"], str) or not ID_RE.fullmatch(p["id"]):
            raise BadInput(f"parts[{i}].id 只能用字母、数字、下划线、汉字，不以数字开头，不含点")
        if p["id"] in seen:
            raise BadInput(f"零件名“{p['id']}”重复")
        seen.add(p["id"])
        if not isinstance(p["plan"], str) or not p["plan"].strip():
            raise BadInput(f"零件“{p['id']}”的 plan 必须是非空字符串")
        if len(p["plan"]) > MAX_PLAN_CHARS:
            raise BadInput(f"零件“{p['id']}”的 plan 超过 {MAX_PLAN_CHARS} 个字符")
        total += len(p["plan"])
    layout = payload.get("layout")
    if not isinstance(layout, str) or not layout.strip():
        raise BadInput("layout 必须是非空字符串（摆位表，一行摆一个零件）")
    if len(layout) > MAX_LAYOUT_CHARS:
        raise BadInput(f"layout 超过 {MAX_LAYOUT_CHARS} 个字符")
    if total + len(layout) > MAX_TOTAL_CHARS:
        raise BadInput(f"装配计划总长超过 {MAX_TOTAL_CHARS} 个字符")
    fs = payload.get("formats", DEFAULT_FORMATS)
    if not isinstance(fs, list) or any(not isinstance(f, str) for f in fs):
        raise BadInput("formats 必须是字符串数组")
    bad = [f for f in fs if f not in FORMATS]
    if bad:
        raise BadInput(f"不支持的格式 {bad[0]}（可用：{', '.join(FORMATS)}）")
    formats = []
    for f in fs:
        if f not in formats:
            formats.append(f)
    return name, parts, layout, formats


def _canonical_sha(parts, layout):
    blob = json.dumps({"parts": [[p["id"], p["plan"]] for p in parts], "layout": layout},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _build_parts(parts):
    import builder
    from cad_dsl import DslError, parse
    out, errors = {}, []
    for i, p in enumerate(parts):
        try:
            res = builder.build(parse(p["plan"]))
        except DslError as e:
            item = {"part": p["id"], "line": e.line, "message": f"零件“{p['id']}”：{e.message}"}
            if e.hint:
                item["hint"] = e.hint
            errors.append(item)
            continue
        out[p["id"]] = Part(p["id"], p["plan"], res, i)
    if errors:
        first = errors[0]
        raise BadInput(f"{len(errors)} 个零件的计划有错：" + "；".join(e["message"] for e in errors),
                       line=None, hint=first.get("hint"), problems=errors)
    return out


# ---------------------------------------------------------------- 摆位表
class _Problem(Exception):
    def __init__(self, status, message, free=None):
        super().__init__(message)
        self.status, self.message, self.free = status, message, free


class Layout:
    def __init__(self, parts):
        self.parts = parts
        self.rows = {}          # 行名 → Inst（阵列的源）
        self.insts = []         # 全部实例，按摆放顺序
        self.table = []         # 约束表
        self.warnings = []
        self.mesh_pairs = []    # (inst_a, inst_b, info)
        self.problems = []
        self.failed = set()     # 出错的行：后面引用它时只说“先改那一行”，不连锁报一串

    # ---- 引用解析
    def _target_inst(self, head, ln):
        if head in self.failed:
            raise _Problem("引用错误", f"引用的行 {head} 本身有错，先改那一行")
        if head in self.rows:
            return self.rows[head]
        if head in self.parts:
            placed = [r for r in self.rows.values() if r.part.id == head]
            if len(placed) == 1:
                return placed[0]
            if not placed:
                raise _Problem("引用错误", f"零件“{head}”还没有摆放（只能引用前面已经摆好的行）")
            raise _Problem("引用错误", f"零件“{head}”摆了 {len(placed)} 处，请写行名："
                           + "、".join(r.row for r in placed))
        raise _Problem("引用错误", f"“{head}”既不是前面已经摆好的行名，也不是零件名")

    def _split_ref(self, ref, own_part=None):
        """→ (inst 或 None 表示本件, 余下部分)。"""
        if not isinstance(ref, str):
            raise _Problem("引用错误", f"引用应当是名字，实际是 {ref!r}")
        head, _, rest = ref.partition(".")
        if own_part is not None:
            if head == own_part.id and rest:
                return None, rest
            return None, ref
        return head, rest

    def _feature_names(self, part):
        names = [f.id for f in part.res.features if "#" not in f.id]
        return "、".join(names) if names else "（没有命名的特征）"

    def _plane_local(self, part, spec):
        """本件局部坐标里的平面 (n, d, 点)；spec 为 [特征名.]方位词 或 特征名。"""
        feat, dirw = None, None
        if spec in DIRS:
            dirw = spec
        elif spec in part.feats:
            feat = spec
        else:
            base, _, last = spec.rpartition(".")
            if last in DIRS and base in part.feats:
                feat, dirw = base, last
            else:
                raise _Problem("引用错误", f"零件“{part.id}”里没有“{spec}”这个特征或方位",
                               free=None) from None
        cands = [pl for pl in part.planes() if feat is None or pl[2] == feat]
        if dirw is not None:
            want = DIRS[dirw]
            cands = [pl for pl in cands if _dot(pl[0], want) > 1 - 1e-6]
            if not cands:
                if feat:
                    have = sorted({w for w, v in DIRS.items() for pl in part.planes() if pl[2] == feat and _dot(pl[0], v) > 1 - 1e-6})
                    raise _Problem("引用错误", f"特征 {feat} 名下没有朝 {dirw} 的平面（与先建的面共面时，面归先建的特征；"
                                   f"可改写 {dirw}，指零件该侧最外平面）" + (f"；{feat} 名下有：{'、'.join(have)}" if have else ""))
                raise _Problem("引用错误", f"零件“{part.id}”没有朝 {dirw} 的平面")
            best = max(cands, key=lambda pl: (pl[1], pl[3]))
            return best[0], best[1], best[3]
        keys = {(round(pl[0][0], 5), round(pl[0][1], 5), round(pl[0][2], 5), round(pl[1], 3)) for pl in cands}
        if len(keys) != 1:
            raise _Problem("引用错误", f"特征 {feat} 有 {len(keys)} 个平面，请加方位词，例如 {feat}.top"
                           if keys else f"特征 {feat} 没有平面")
        pl = min(cands, key=lambda pl: pl[3])
        return pl[0], pl[1], pl[3]

    def _axis_local(self, part, spec):
        if spec is None:
            fid, ax = part.main_axis()
            if ax is None:
                raise _Problem("引用错误", f"零件“{part.id}”没有可用的轴（圆柱、孔、回转体、齿轮）")
            return fid, ax
        if spec not in part.feats:
            raise _Problem("引用错误", f"零件“{part.id}”里没有特征“{spec}”；可用的名字：{self._feature_names(part)}")
        try:
            ax = part.axis_of(spec)
        except ValueError as e:
            raise _Problem("引用错误", str(e)) from None
        if ax is None:
            raise _Problem("引用错误", f"特征 {spec} 没有轴（不是圆柱、孔、回转体或齿轮）")
        return spec, ax

    def world_axis(self, ref, ln):
        head, rest = self._split_ref(ref)
        inst = self._target_inst(head, ln)
        _, (p, d) = self._axis_local(inst.part, rest or None)
        return inst, inst.pose.pt(p), _norm(inst.pose.dir(d))

    def world_plane(self, ref, ln):
        head, rest = self._split_ref(ref)
        if not rest:
            raise _Problem("引用错误", f"“{ref}”要写成 行名.面，例如 {head}.top")
        inst = self._target_inst(head, ln)
        n, d, c = self._plane_local(inst.part, rest)
        nw = _norm(inst.pose.dir(n))
        cw = inst.pose.pt(c)
        return nw, cw

    def own_plane(self, part, ref):
        _, rest = self._split_ref(ref, own_part=part)
        n, d, c = self._plane_local(part, rest)
        return n, c

    # ---- 一行
    def add(self, st):
        ln = st.line
        try:
            if st.name is not None and "." in st.name:
                raise _Problem("写法错误", f"行名“{st.name}”不能带点")
            if st.op == "pattern":
                self._pattern(st)
                return
            if st.op not in ("fix", "put"):
                raise _Problem("写法错误", f"不认识的操作“{st.op}”，摆位表只认 fix、put、pattern")
            if st.name is None:
                raise _Problem("写法错误", "fix、put 行要有名字，例如 b: fix 箱座")
            if st.name in self.rows:
                raise _Problem("写法错误", f"行名“{st.name}”已经用过")
            if not st.pos or st.pos[0] not in self.parts:
                what = st.pos[0] if st.pos else "（空）"
                raise _Problem("引用错误", f"“{what}”不是零件清单里的零件名；零件有：" + "、".join(self.parts))
            part = self.parts[st.pos[0]]
            okflags = {"flush", "flush2", "flush3"} if st.op == "put" else set()
            extra = [w for w in st.pos[1:] if w not in okflags]
            if extra:
                raise _Problem("写法错误", f"多余的参数：{'、'.join(str(w) for w in extra)}")
            self._mesh_rot = None
            pose, notes = (self._fix if st.op == "fix" else self._put)(st, part)
            inst = Inst(st.name, part, pose, ln)
            self.rows[st.name] = inst
            self.insts.append(inst)
            row = {"line": ln, "row": st.name, "part": part.id, "op": st.op, "status": "满足", "dof": 0}
            if notes:
                row["notes"] = notes
            if self._mesh_rot is not None:
                row["mesh_rotation_deg"] = r6(self._mesh_rot)
            self.table.append(row)
        except _Problem as p:
            if st.name is not None:
                self.failed.add(st.name)
            self.problems.append({"line": ln, "row": st.name, "status": p.status, "message": f"第 {ln} 行：{p.message}",
                                  **({"free": p.free} if p.free else {})})
            self.table.append({"line": ln, "row": st.name, "part": (st.pos[0] if st.pos else None), "op": st.op,
                               "status": p.status, **({"free": p.free} if p.free else {})})

    def _keys(self, st, allowed):
        extra = sorted(set(st.kw) - set(allowed))
        if extra:
            raise _Problem("写法错误", f"{st.op} 不认识的参数：{'、'.join(extra)}")

    def _fix(self, st, part):
        self._keys(st, ["at", "rot"])
        return self._given(st), []

    def _given(self, st):
        at = st.kw.get("at", (0.0, 0.0, 0.0))
        rot = st.kw.get("rot", (0.0, 0.0, 0.0))
        for k, v in (("at", at), ("rot", rot)):
            if not (isinstance(v, tuple) and len(v) == 3):
                raise _Problem("写法错误", f"{k}= 应当是三个数，例如 {k}=(0,0,0)")
        return _euler(rot).then(Pose(t=at))

    def _num(self, st, key, default=0.0):
        v = st.kw.get(key, default)
        if not isinstance(v, float):
            raise _Problem("写法错误", f"{key}= 应当是数")
        return v

    def _put(self, st, part):
        allowed = ["at", "rot", "coaxial", "axis", "angle", "mesh", "gear"]
        for i in ("", "2", "3"):
            allowed += [f"face{i}", f"to{i}", f"gap{i}"]
        self._keys(st, allowed)
        flags = {w for w in st.pos[1:] if isinstance(w, str)}
        mates = []
        for i in ("", "2", "3"):
            f, t = st.kw.get(f"face{i}"), st.kw.get(f"to{i}")
            fl = f"flush{i}" in flags or (i == "" and "flush" in flags)
            if (f is None) != (t is None):
                raise _Problem("写法错误", f"face{i}= 与 to{i}= 要成对写")
            if f is not None:
                mates.append((f, t, self._num(st, f"gap{i}"), fl, i))
            elif f"gap{i}" in st.kw:
                raise _Problem("写法错误", f"gap{i}= 要和 face{i}= to{i}= 一起写")
        if "at" in st.kw or "rot" in st.kw:
            others = [k for k in st.kw if k not in ("at", "rot")]
            if others:
                raise _Problem("冲突", f"给了位姿 at=/rot=，又给了 {'、'.join(sorted(others))}：位姿已经定死，其余约束是多余的")
            if "at" not in st.kw:
                raise _Problem("欠约束", "只给了 rot=，没有给位置 at=", free=["沿 x、y、z 移动"])
            return self._given(st), []
        if "coaxial" in st.kw:
            return self._coaxial(st, part, mates)
        if not mates:
            raise _Problem("欠约束", "没有给任何约束", free=["沿 x、y、z 移动", "绕 x、y、z 转动"])
        if any(k in st.kw for k in ("angle", "mesh", "axis", "gear")):
            bad = [k for k in ("angle", "mesh", "axis", "gear") if k in st.kw]
            raise _Problem("写法错误", f"{'、'.join(bad)} 要和 coaxial= 一起用")
        return self._planar(st, part, mates)

    # ---- 同轴 + 贴合 + 转角/啮合
    def _coaxial(self, st, part, mates):
        ln = st.line
        own_fid, (p0, d0) = self._axis_local(part, st.kw.get("axis"))
        tinst, P, D = self.world_axis(st.kw["coaxial"], ln)
        R = _rot_between(_norm(d0), D)
        notes = []
        if len(mates) > 1:
            raise _Problem("冲突", "同轴之后只剩沿轴移动与绕轴转动，只能再贴一对面；多给的面贴合与同轴重复或矛盾")
        if not mates:
            raise _Problem("欠约束", "同轴之后还能沿轴移动，要再给一对贴合面 face= to=", free=["沿轴移动"])
        f, t, gap, flush, _ = mates[0]
        n_own, q_own = self.own_plane(part, f)
        N, Q = self.world_plane(t, ln)
        if abs(abs(_dot(N, D)) - 1) > ANG_TOL:
            deg = math.degrees(math.acos(min(1.0, abs(_dot(N, D)))))
            raise _Problem("冲突", f"贴合面 {t} 的法向与同轴的轴不平行（差 {deg:.3f}°），沿轴的位置定不下来")
        nw = R.dir(n_own)
        if abs(abs(_dot(nw, D)) - 1) > ANG_TOL:
            deg = math.degrees(math.acos(min(1.0, abs(_dot(nw, D)))))
            raise _Problem("冲突", f"本件的面 {f} 与本件的轴不垂直（差 {deg:.3f}°），不能同时同轴又贴合")
        want = N if flush else _mul(N, -1)
        if _dot(nw, want) < 0:
            R = R.then(_rot_axis(_perp(D), math.pi))
        # 绕轴转角
        spin = 0.0
        if "angle" in st.kw and "mesh" in st.kw:
            raise _Problem("冲突", "angle= 与 mesh= 只能给一个：啮合会自己算转角")
        if "angle" in st.kw:
            spin = math.radians(self._num(st, "angle"))
        R = R.then(_rot_axis(D, spin))
        # 平移：轴上过 P，面距 gap
        base = _sub(P, R.dir(p0))
        q = _add(R.dir(q_own), base)
        s = (gap - _dot(_sub(q, Q), N)) / _dot(D, N)
        pose = Pose(R.R, _add(base, _mul(D, s)))
        if "mesh" in st.kw:
            pose, info = self._mesh(st, part, pose, P, D)
            notes.append(f"啮合：转 {info['rotated_deg']:.4f}° 对齿")
        elif "angle" not in st.kw and not part.is_axisymmetric(p0, _norm(d0)):
            notes.append("绕轴转角没有给，取 0°")
            self.warnings.append({"line": ln, "code": "spin_default", "row": st.name,
                                  "message": f"第 {ln} 行：{st.name} 的绕轴转角没有给，按 0° 摆放"})
        return pose, notes

    def _gear_of(self, part, name, side):
        gears = part.gear_feats()
        if name is not None:
            g = part.feats.get(name)
            if g is None or g.params.get("kind") != "gear":
                raise _Problem("引用错误", f"零件“{part.id}”里没有叫“{name}”的齿轮特征")
            return g
        if len(gears) == 1:
            return gears[0]
        if not gears:
            raise _Problem("引用错误", f"{side}零件“{part.id}”里没有齿轮")
        raise _Problem("引用错误", f"{side}零件“{part.id}”里有 {len(gears)} 个齿轮，请指明："
                       + "、".join(g.id for g in gears))

    def _mesh(self, st, part, pose, P, D):
        ln = st.line
        ref = st.kw["mesh"]
        head, rest = self._split_ref(ref)
        other = self._target_inst(head, ln)
        ga = self._gear_of(other.part, rest or None, "啮合对象")
        gb = self._gear_of(part, st.kw.get("gear"), "本件")
        pa, pb = ga.params, gb.params
        if abs(pa["m"] - pb["m"]) > 1e-9 or abs(pa["alpha"] - pb["alpha"]) > 1e-9:
            raise _Problem("冲突", f"模数或压力角不同（{other.row}：m={pa['m']:g} α={pa['alpha']:g}；本件：m={pb['m']:g} α={pb['alpha']:g}），不能啮合")
        ca = other.pose.pt(pa["at"])
        na = _norm(other.pose.dir((0.0, 0.0, 1.0)))
        ua = _norm(other.pose.dir((1.0, 0.0, 0.0)))
        cb = pose.pt(pb["at"])
        nb = _norm(pose.dir((0.0, 0.0, 1.0)))
        if abs(abs(_dot(na, nb)) - 1) > ANG_TOL:
            raise _Problem("冲突", f"两齿轮的轴不平行，不能按直齿轮啮合")
        if abs(abs(_dot(nb, D)) - 1) > ANG_TOL:
            raise _Problem("冲突", "本件齿轮的轴与同轴的轴不平行")
        w = _sub(cb, P)
        off = _sub(w, _mul(D, _dot(w, D)))
        if _dot(off, off) > POS_TOL ** 2:
            raise _Problem("冲突", "本件齿轮的轴不在同轴的那根轴上，转动对齿会让它离开同轴")
        v = _sub(cb, ca)
        vp = _sub(v, _mul(na, _dot(v, na)))
        dist = math.sqrt(_dot(vp, vp))
        want = pa["m"] * (pa["z"] + pb["z"]) / 2
        if abs(dist - want) > POS_TOL:
            raise _Problem("冲突", f"中心距 {dist:.3f}，按 m×(z1+z2)/2 应为 {want:.3f}，差 {dist - want:+.3f}")
        e1 = ua
        e2 = _cross(na, e1)
        ang = lambda vec: math.atan2(_dot(vec, e2), _dot(vec, e1))
        phi = ang(vp)
        za, zb = pa["z"], pb["z"]
        pitch_b = 2 * math.pi / zb
        theta_b = ang(_norm(pose.dir((1.0, 0.0, 0.0))))
        target = phi + math.pi - math.pi / zb + (za / zb) * phi
        delta = (target - theta_b) % pitch_b
        if delta >= pitch_b / 2:
            delta -= pitch_b
        rot = _rot_axis(na, delta, about=cb)
        pose = pose.then(rot)
        self.mesh_pairs.append((other.row, st.name, {"m": pa["m"], "z": [za, zb], "center_distance": r6(dist)}))
        self._mesh_rot = math.degrees(delta)
        return pose, {"rotated_deg": math.degrees(delta)}

    # ---- 只有面贴合（至多三对）
    def _planar(self, st, part, mates):
        ln = st.line
        R = Pose()
        t = (0.0, 0.0, 0.0)
        fixed_n = []           # 已定的平移方向（世界）
        rot_free = 3           # 剩余转动自由度
        spin_axis = None
        for f, tref, gap, flush, idx in mates:
            n_own, q_own = self.own_plane(part, f)
            N, Q = self.world_plane(tref, ln)
            want = N if flush else _mul(N, -1)
            if rot_free == 3:
                R = _rot_between(_norm(n_own), want)
                rot_free, spin_axis = 1, want
            else:
                nw = R.dir(n_own)
                if rot_free == 1:
                    if abs(_dot(want, spin_axis)) > ANG_TOL or abs(_dot(nw, spin_axis)) > ANG_TOL:
                        if abs(_dot(nw, want) - 1) > ANG_TOL:
                            raise _Problem("冲突", f"第 {idx or 1} 对面贴合与前面的面贴合方向矛盾（面 face{idx}= 转不到要求的朝向）")
                    else:
                        a1 = math.atan2(_dot(_cross(nw, want), spin_axis), _dot(nw, want))
                        R = R.then(_rot_axis(spin_axis, a1))
                        rot_free = 0
                else:
                    if abs(_dot(R.dir(n_own), want) - 1) > ANG_TOL:
                        raise _Problem("冲突", f"face{idx}= 的朝向与前面已定死的转动矛盾")
            # 平移：沿 N 的分量
            nw = R.dir(n_own)
            q = _add(R.dir(q_own), t)
            s = gap - _dot(_sub(q, Q), N)
            comp = [x for x in fixed_n if abs(_dot(x, N)) > ANG_TOL]
            if comp:
                # 与已定方向不独立：检查是否自洽
                if any(abs(abs(_dot(x, N)) - 1) > ANG_TOL for x in comp):
                    raise _Problem("冲突", f"face{idx}= 的法向与前面贴合面的法向既不平行也不垂直，第一版不支持")
                if abs(s) > POS_TOL:
                    raise _Problem("冲突", f"face{idx}= 要求的位置与前面的贴合差 {s:+.3f} mm")
                continue
            t = _add(t, _mul(N, s))
            fixed_n.append(N)
        free = []
        if rot_free:
            free.append("绕贴合面法向转动")
        if len(fixed_n) < 3:
            left = 3 - len(fixed_n)
            free.append(f"在贴合面内移动（还差 {left} 个方向）")
        if free:
            raise _Problem("欠约束", "面贴合不够定死这个零件：" + "；".join(free), free=free)
        return Pose(R.R, t), []

    # ---- 阵列
    def _pattern(self, st):
        ln = st.line
        if st.pos and isinstance(st.pos[0], str) and st.pos[0] in self.failed:
            raise _Problem("引用错误", f"引用的行 {st.pos[0]} 本身有错，先改那一行")
        if not st.pos or not isinstance(st.pos[0], str) or st.pos[0] not in self.rows:
            raise _Problem("引用错误", "pattern 后面写前面已经摆好的行名，例如 pattern c1 linear n=4 dx=30")
        src = self.rows[st.pos[0]]
        mode = st.pos[1] if len(st.pos) > 1 else None
        n = st.kw.get("n")
        if not isinstance(n, float) or abs(n - round(n)) > 1e-9 or not (2 <= n <= 100):
            raise _Problem("写法错误", "n 应当是 2–100 的整数（含源件）")
        n = int(round(n))
        poses = []
        if mode == "linear":
            self._keys(st, ["n", "dx", "dy", "dz"])
            dv = (self._num(st, "dx"), self._num(st, "dy"), self._num(st, "dz"))
            if dv == (0.0, 0.0, 0.0):
                raise _Problem("写法错误", "线性阵列至少要有 dx、dy、dz 之一")
            poses = [src.pose.then(Pose(t=_mul(dv, i))) for i in range(1, n)]
        elif mode == "circular":
            self._keys(st, ["n", "axis", "angle"])
            if "axis" not in st.kw:
                raise _Problem("写法错误", "环形阵列要写 axis=行名[.特征名]")
            _, P, D = self.world_axis(st.kw["axis"], ln)
            total = self._num(st, "angle", 360.0)
            step = total / n if abs(total - 360) < 1e-9 else total / (n - 1)
            poses = [src.pose.then(_rot_axis(D, math.radians(step * i), about=P)) for i in range(1, n)]
        else:
            raise _Problem("写法错误", "阵列方式写 linear 或 circular")
        row = st.name or f"pattern@{ln}"
        if st.name is not None:
            if st.name in self.rows:
                raise _Problem("写法错误", f"行名“{st.name}”已经用过")
        for i, p in enumerate(poses, 1):
            inst = Inst(f"{src.row}#{i + 1}", src.part, p, ln, index=i, source=src.row)
            self.insts.append(inst)
        self.table.append({"line": ln, "row": row, "part": src.part.id, "op": "pattern", "status": "满足", "dof": 0,
                           "copies": len(poses)})


def _layout(parts, text):
    from cad_dsl import DslError, parse
    try:
        stmts = parse(text)
    except DslError as e:
        raise BadInput("摆位表：" + e.message, e.line, e.hint) from None
    L = Layout(parts)
    for st in stmts:
        L.add(st)
        if len(L.insts) > MAX_INSTANCES:
            raise ResourceLimit(f"实例数超过 {MAX_INSTANCES}")
    if not L.problems and not any(t["op"] == "fix" for t in L.table):
        L.problems.append({"line": 0, "row": None, "status": "欠约束",
                           "message": "摆位表里没有 fix 行：至少要有一个基准件（第一行写 fix 零件名）"})
    if L.problems:
        first = L.problems[0]
        kinds = sorted({p["status"] for p in L.problems})
        raise BadInput(f"摆位表有 {len(L.problems)} 处问题（{'、'.join(kinds)}）：" + "；".join(p["message"] for p in L.problems),
                       line=first["line"], problems=L.problems)
    unused = [pid for pid, p in parts.items() if not any(i.part is p for i in L.insts)]
    for pid in unused:
        L.warnings.append({"line": 0, "code": "unused_part", "message": f"零件“{pid}”在零件清单里，但摆位表没有摆它"})
    return L


# ---------------------------------------------------------------- 干涉
def _bbox(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, b, False, False)
    lo, hi = b.CornerMin(), b.CornerMax()
    return (lo.X(), lo.Y(), lo.Z()), (hi.X(), hi.Y(), hi.Z())


def _overlap(a, b, tol=1e-6):
    return all(a[0][i] < b[1][i] - tol and b[0][i] < a[1][i] - tol for i in range(3))


def _common(sa, sb):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    op = BRepAlgoAPI_Common(sa.wrapped, sb.wrapped)
    op.Build()
    if not op.IsDone():
        return None, None, None
    sh = op.Shape()
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(sh, g)
    c = g.CentreOfMass()
    return abs(g.Mass()), (c.X(), c.Y(), c.Z()), sh


PAIR_TIMES: list = []   # 每对零件求公共体积的耗时（读数用，不进产出记录）


def _interference(L):
    PAIR_TIMES.clear()
    insts = L.insts
    boxes = [_bbox(i.shape) for i in insts]
    mesh_rows = {}
    for a, b, info in L.mesh_pairs:
        mesh_rows[frozenset((a, b))] = info
    hits, meshes, checked, shapes = [], [], 0, []
    n = len(insts)
    for i in range(n):
        for j in range(i + 1, n):
            if not _overlap(boxes[i], boxes[j]):
                continue
            checked += 1
            A, B = insts[i], insts[j]
            tp = time.perf_counter()
            vol, ctr, sh = _common(A.shape, B.shape)
            PAIR_TIMES.append((time.perf_counter() - tp, A.row, B.row))
            key = frozenset((A.row, B.row))
            vmin = min(A.part.res.part.volume, B.part.res.part.volume)
            if vol is None:
                hits.append({"a": A.row, "b": B.row, "status": "未能判定", "reason": "求公共体积失败"})
                continue
            if key in mesh_rows:
                info = mesh_rows[key]
                lim = max(MESH_MIN_MM3, MESH_REL * vmin)
                ok = vol <= lim
                meshes.append({"a": A.row, "b": B.row, **info, "common_mm3": r6(vol), "limit_mm3": r6(lim), "ok": ok})
                if not ok:
                    hits.append({"a": A.row, "b": B.row, "volume_mm3": r6(vol), "at": [r3(v) for v in ctr], "mesh": True})
                    shapes.append(sh)
                continue
            lim = max(INTERFERE_MIN_MM3, INTERFERE_REL * vmin)
            if vol > lim:
                hits.append({"a": A.row, "b": B.row, "volume_mm3": r6(vol), "at": [r3(v) for v in ctr]})
                shapes.append(sh)
    for a, b, info in L.mesh_pairs:
        if not any({m["a"], m["b"]} == {a, b} for m in meshes):
            meshes.append({"a": a, "b": b, **info, "common_mm3": 0.0, "limit_mm3": 0.0, "ok": True})
    return {"pairs_total": n * (n - 1) // 2, "pairs_checked": checked, "count": len(hits), "hits": hits}, meshes, shapes


# ---------------------------------------------------------------- 测量、明细表
def _bom(L):
    order = []
    for inst in L.insts:
        if inst.part.id not in order:
            order.append(inst.part.id)
    items = {pid: k + 1 for k, pid in enumerate(order)}
    rows = []
    for pid in order:
        part = L.parts[pid]
        qty = sum(1 for i in L.insts if i.part is part)
        res = part.res
        unit = r6(res.part.volume / 1000 * res.density) if res.density else None
        rows.append({"item": items[pid], "part": pid, "qty": qty, "material": res.material,
                     "unit_mass_g": unit, "total_mass_g": r6(unit * qty) if unit is not None else None})
    for inst in L.insts:
        inst.item = items[inst.part.id]
    return rows


def _measure(L, compound):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    lo, hi = _bbox(compound)
    vol = 0.0
    mass, mass_known = 0.0, True
    wsum, cx, cy, cz = 0.0, 0.0, 0.0, 0.0
    cache = {}
    for inst in L.insts:
        part = inst.part
        if part.id not in cache:
            g = GProp_GProps()
            BRepGProp.VolumeProperties_s(part.res.part.wrapped, g)
            c = g.CentreOfMass()
            cache[part.id] = (abs(g.Mass()), (c.X(), c.Y(), c.Z()))
        v, c = cache[part.id]
        cw = inst.pose.pt(c)
        vol += v
        if part.res.density:
            m = v / 1000 * part.res.density
            mass += m
        else:
            mass_known = False
    basis = "mass" if mass_known else "volume"
    for inst in L.insts:
        v, c = cache[inst.part.id]
        w = v * (inst.part.res.density if basis == "mass" else 1.0)
        cw = inst.pose.pt(c)
        wsum += w
        cx += w * cw[0]; cy += w * cw[1]; cz += w * cw[2]
    return {"bbox": {"min": [r6(v) for v in lo], "max": [r6(v) for v in hi],
                     "size": [r6(hi[i] - lo[i]) for i in range(3)]},
            "volume_mm3": r6(vol), "mass_g": r6(mass) if mass_known else None,
            "center_of_mass": [r6(cx / wsum), r6(cy / wsum), r6(cz / wsum)], "com_basis": basis,
            "parts": len({i.part.id for i in L.insts}), "instances": len(L.insts)}


def _part_summary(part):
    res = part.res
    bb = res.part.bounding_box()
    return {"id": part.id, "plan_sha256": hashlib.sha256(part.plan.encode("utf-8")).hexdigest(),
            "material": res.material,
            "mass_g": r6(res.part.volume / 1000 * res.density) if res.density else None,
            "volume_mm3": r6(res.part.volume),
            "size": [r3(bb.size.X), r3(bb.size.Y), r3(bb.size.Z)],
            "features": [f.id for f in res.features if "#" not in f.id],
            **({"warnings": res.warnings} if res.warnings else {})}


# ---------------------------------------------------------------- 文件
def _write(workdir, rel, data, fmt):
    if len(data) > MAX_FILE_BYTES:
        raise ResourceLimit(f"{fmt} 文件超过 {MAX_FILE_BYTES // 1024 // 1024} MB")
    with open(os.path.join(workdir, rel), "wb") as fh:
        fh.write(data)
    media, _, role = FORMATS[fmt]
    return {"path": rel, "format": fmt, "role": role, "media_type": media,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def to_csv(bom, total_mass):
    def cell(v):
        if v is None:
            return ""
        s = f"{v:.3f}" if isinstance(v, float) else str(v)
        return '"' + s.replace('"', '""') + '"' if any(c in s for c in ',"\n') else s
    lines = ["序号,名称,数量,材料,单件质量(g),合计质量(g)"]
    for r in bom:
        lines.append(",".join(cell(v) for v in (r["item"], r["part"], r["qty"], r["material"], r["unit_mass_g"], r["total_mass_g"])))
    lines.append(",".join(cell(v) for v in ("", "合计", sum(r["qty"] for r in bom), "", None, total_mass)))
    return ("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8")


def to_step(L, name):
    """带装配结构的 STEP：每种零件一份几何（原型），每处摆放一个带名字的实例（引用 + 位置）。"""
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Controller, STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_StepModelType
    from OCP.APIHeaderSection import APIHeaderSection_MakeHeader
    from OCP.TCollection import TCollection_ExtendedString, TCollection_HAsciiString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.XSControl import XSControl_WorkSession
    from OCP.Message import Message, Message_Gravity
    from geometry import FIXED_TIME
    doc = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    app = XCAFApp_Application.GetApplication_s()
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)
    app.InitDocument(doc)
    XCAFDoc_DocumentTool.SetLengthUnit_s(doc, 0.001)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    st.SetAutoNaming_s(False)
    # 写出器把非 ASCII 名字按字节截断成乱码：先写 ASCII 占位名，写完再换成 ISO 10303-21 的 \X2\…\X0\ 编码
    names = {}

    def ph(text):
        key = f"MGNAME{len(names):04d}Z"
        names[key] = text
        return TCollection_ExtendedString(key)
    root = st.NewShape()
    TDataStd_Name.Set_s(root, ph(name))
    from OCP.TopLoc import TopLoc_Location
    protos = {}
    for inst in L.insts:
        pid = inst.part.id
        if pid not in protos:
            # 原型几何不带自身位置（带位置的形状会被当成引用，原型名字就丢了）；自身位置并进实例位置
            solids = inst.part.res.part.solids()
            shape = solids[0].wrapped if len(solids) == 1 else inst.part.res.part.wrapped
            own = shape.Location()
            lab = st.AddShape(shape.Located(TopLoc_Location()), False, False)
            TDataStd_Name.Set_s(lab, ph(pid))
            protos[pid] = (lab, own)
        lab, own = protos[pid]
        comp = st.AddComponent(root, lab, _occ_loc(inst.pose).Multiplied(own))
        TDataStd_Name.Set_s(comp, ph(inst.row))
    st.UpdateAssemblies()
    for printer in Message.DefaultMessenger_s().Printers():
        printer.SetTraceLevel(Message_Gravity.Message_Fail)
    ws = XSControl_WorkSession()
    w = STEPCAFControl_Writer(ws, False)
    w.SetNameMode(True)
    w.SetColorMode(False)
    w.SetLayerMode(False)
    STEPCAFControl_Controller.Init_s()
    Interface_Static.SetIVal_s("write.surfacecurve.mode", 1)
    hdr = APIHeaderSection_MakeHeader(w.Writer().Model())
    if not hdr.IsDone():
        hdr = APIHeaderSection_MakeHeader(0)
        hdr.Apply(w.Writer().Model())
    hdr.SetName(TCollection_HAsciiString(name))
    hdr.SetTimeStamp(TCollection_HAsciiString(FIXED_TIME))
    hdr.SetOriginatingSystem(TCollection_HAsciiString("mengos cad"))
    w.Transfer(doc, STEPControl_StepModelType.STEPControl_AsIs)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.step")
        if w.Write(p) != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise RuntimeError("STEP 写出失败")
        data = open(p, "rb").read()
    text = b"\n".join(ln for ln in data.split(b"\n") if not ln.startswith(b"/*")).decode("ascii")
    text = re.sub(r"MGNAME\d{4}Z", lambda m: step_string(names[m.group(0)]), text)
    return text.encode("ascii")


def step_string(s):
    """ISO 10303-21 字符串内容：可打印 ASCII 原样（' 与 \\ 双写），其余按 UTF-16 写成 \\X2\\HHHH…\\X0\\。"""
    out, wide = [], []

    def flush():
        if wide:
            out.append("\\X2\\" + "".join(f"{c:04X}" for c in wide) + "\\X0\\")
            wide.clear()
    for ch in s:
        if 0x20 <= ord(ch) < 0x7F:
            flush()
            out.append({"'": "''", "\\": "\\\\"}.get(ch, ch))
        else:
            b = ch.encode("utf-16-be")
            wide.extend(int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2))
    flush()
    return "".join(out)


def to_glb(L, meshes, inter_shapes):
    """两层节点：零件实例（矩阵、零件名、明细表序号、实例号）→ 特征（同零件 GLB 的结构）。同一零件的多个实例共用网格。"""
    from geometry import r6 as g6
    bin_parts, views, accessors, gmeshes, nodes = [], [], [], [], []
    offset = 0

    def add_view(data, target):
        nonlocal offset
        pad = (-len(data)) % 4
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        bin_parts.append(data + b"\x00" * pad)
        offset += len(data) + pad
        return len(views) - 1

    def add_acc(view, ctype, count, typ, mn=None, mx=None):
        a = {"bufferView": view, "componentType": ctype, "count": count, "type": typ}
        if mn is not None:
            a["min"], a["max"] = mn, mx
        accessors.append(a)
        return len(accessors) - 1

    def tri_mesh(name, pos, nrm, idx, material):
        flat = [c for p in pos for c in p]
        mn = [g6(min(p[i] for p in pos)) for i in range(3)]
        mx = [g6(max(p[i] for p in pos)) for i in range(3)]
        pa = add_acc(add_view(struct.pack(f"<{len(flat)}f", *flat), 34962), 5126, len(pos), "VEC3", mn, mx)
        attrs = {"POSITION": pa}
        if nrm is not None:
            fn = [c for n in nrm for c in n]
            attrs["NORMAL"] = add_acc(add_view(struct.pack(f"<{len(fn)}f", *fn), 34962), 5126, len(nrm), "VEC3")
        fi = [i for t in idx for i in t]
        ia = add_acc(add_view(struct.pack(f"<{len(fi)}I", *fi), 34963), 5125, len(fi), "SCALAR")
        gmeshes.append({"name": name, "primitives": [{"attributes": attrs, "indices": ia, "material": material}]})
        return len(gmeshes) - 1

    part_nodes = {}     # 零件 → [(特征节点模板)]
    order = []
    for inst in L.insts:
        if inst.part.id not in order:
            order.append(inst.part.id)
    for k, pid in enumerate(order):
        part = L.parts[pid]
        mesh = meshes[pid]
        feats = {f.id: f for f in part.res.features}
        tmpl = []
        names = [f.id for f in part.res.features if f.id in mesh["groups"]] + [g for g in mesh["groups"] if g not in feats]
        for fid in names:
            g = mesh["groups"][fid]
            mi = tri_mesh(f"{pid}/{fid}", g["pos"], g["nrm"], g["idx"], 2 + (k % 8))
            f = feats.get(fid)
            tmpl.append({"name": fid, "mesh": mi,
                         "extras": {"feature": fid, "op": f.op if f else "body", "line": f.line if f else 0, "faces": g["faces"]}})
        lp, li = [], []
        for poly in mesh["lines"]:
            base = len(lp)
            lp += poly
            li += [j for i in range(len(poly) - 1) for j in (base + i, base + i + 1)]
        if lp:
            flat = [c for p in lp for c in p]
            mn = [g6(min(p[i] for p in lp)) for i in range(3)]
            mx = [g6(max(p[i] for p in lp)) for i in range(3)]
            pa = add_acc(add_view(struct.pack(f"<{len(flat)}f", *flat), 34962), 5126, len(lp), "VEC3", mn, mx)
            ia = add_acc(add_view(struct.pack(f"<{len(li)}I", *li), 34963), 5125, len(li), "SCALAR")
            gmeshes.append({"name": f"{pid}/edges", "primitives": [{"attributes": {"POSITION": pa}, "indices": ia, "mode": 1, "material": 1}]})
            tmpl.append({"name": "edges", "mesh": len(gmeshes) - 1, "extras": {"edges": True}})
        part_nodes[pid] = tmpl
    children = []
    for inst in L.insts:
        kids = []
        for t in part_nodes[inst.part.id]:
            nodes.append(json.loads(json.dumps(t)))
            kids.append(len(nodes))       # 节点 0 是根，下标整体 +1
        m = inst.pose.matrix12()
        mat = [m[0], m[4], m[8], 0.0, m[1], m[5], m[9], 0.0, m[2], m[6], m[10], 0.0, m[3], m[7], m[11], 1.0]
        nodes.append({"name": inst.row, "matrix": [_snap(r6(v)) for v in mat], "children": kids,
                      "extras": {"part": inst.part.id, "item": inst.item, "instance": inst.index, "row": inst.row,
                                 "line": inst.line}})
        children.append(len(nodes))
    if inter_shapes:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.BRep import BRep_Tool
        from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopLoc import TopLoc_Location
        from build123d.topology.shape_core import downcast
        pos, idx = [], []
        for sh in inter_shapes:
            BRepMesh_IncrementalMesh(sh, 0.05, False, 0.2, False)
            ex = TopExp_Explorer(sh, TopAbs_FACE)
            while ex.More():
                face = downcast(ex.Current())
                loc = TopLoc_Location()
                tri = BRep_Tool.Triangulation_s(face, loc)
                if tri is not None:
                    tr = loc.Transformation()
                    base = len(pos)
                    for i in range(1, tri.NbNodes() + 1):
                        p = tri.Node(i).Transformed(tr)
                        pos.append((p.X(), p.Y(), p.Z()))
                    rev = face.Orientation() == TopAbs_REVERSED
                    for i in range(1, tri.NbTriangles() + 1):
                        a, b, c = tri.Triangle(i).Get()
                        idx.append((base + a - 1, base + c - 1, base + b - 1) if rev else (base + a - 1, base + b - 1, base + c - 1))
                ex.Next()
        if pos:
            mi = tri_mesh("interference", pos, None, idx, 10)
            nodes.append({"name": "interference", "mesh": mi, "extras": {"interference": True}})
            children.append(len(nodes))
    s = 0.001
    root = {"name": "assembly", "matrix": [s, 0, 0, 0, 0, 0, -s, 0, 0, s, 0, 0, 0, 0, 0, 1],
            "children": children, "extras": {"units": "mm", "up": "z", "assembly": True}}
    palette = [[0.82, 0.82, 0.8], [0.62, 0.72, 0.85], [0.85, 0.72, 0.55], [0.6, 0.8, 0.65],
               [0.85, 0.62, 0.62], [0.72, 0.65, 0.85], [0.85, 0.82, 0.55], [0.55, 0.78, 0.8]]
    mats = [{"name": "body", "pbrMetallicRoughness": {"baseColorFactor": [0.82, 0.82, 0.8, 1], "metallicFactor": 0.15, "roughnessFactor": 0.55}},
            {"name": "edge", "pbrMetallicRoughness": {"baseColorFactor": [0.08, 0.08, 0.08, 1], "metallicFactor": 0, "roughnessFactor": 1}}]
    mats += [{"name": f"part{i}", "pbrMetallicRoughness": {"baseColorFactor": c + [1], "metallicFactor": 0.15, "roughnessFactor": 0.55}}
             for i, c in enumerate(palette)]
    mats.append({"name": "interference", "pbrMetallicRoughness": {"baseColorFactor": [0.9, 0.1, 0.1, 1], "metallicFactor": 0, "roughnessFactor": 0.6}})
    gltf = {"asset": {"version": "2.0", "generator": "mengos cad-v2 assemble"},
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [root] + nodes, "meshes": gmeshes,
            "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": offset}], "materials": mats}
    js = json.dumps(gltf, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode()
    js += b" " * ((-len(js)) % 4)
    binb = b"".join(bin_parts)
    total = 12 + 8 + len(js) + 8 + len(binb)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binb), 0x004E4942) + binb)


def _files(L, name, formats, workdir, pmesh, inter_shapes, bom, meas, compound, meta, T):
    import geometry
    files = []
    for fmt in formats:
        t = time.perf_counter()
        rel = name + FORMATS[fmt][1]
        if fmt == "step":
            data = to_step(L, name)
        elif fmt == "glb":
            data = to_glb(L, pmesh, inter_shapes)
        elif fmt == "csv":
            data = to_csv(bom, meas["mass_g"])
        elif fmt == "svg":
            data = geometry.to_svg(_DrawRes(compound), meta)
        else:
            data = geometry.to_dxf(_DrawRes(compound), meta)
        files.append(_write(workdir, rel, data, fmt))
        T["files"][fmt] = time.perf_counter() - t
    return files


class _DrawRes:
    """借用零件三视图程序：只用到 part 与 material（标题栏）。"""
    def __init__(self, part):
        self.part, self.material = part, "见明细表"


# ---------------------------------------------------------------- 主流程
def cad_assemble(payload, workdir=None):
    import geometry
    T = {}
    t0 = time.perf_counter()
    name, parts_in, layout_text, formats = _payload(payload)
    if formats:
        if not workdir:
            raise BadInput("要产出文件时必须提供 workdir（引擎为每次调用新建的空目录）")
        if not os.path.isabs(workdir) or not os.path.isdir(workdir):
            raise BadInput("workdir 必须是已存在目录的绝对路径")
    parts = _build_parts(parts_in)
    T["build_parts"] = time.perf_counter() - t0
    t = time.perf_counter()
    L = _layout(parts, layout_text)
    T["layout"] = time.perf_counter() - t
    t = time.perf_counter()
    inter, meshes, inter_shapes = _interference(L)
    T["interference"] = time.perf_counter() - t
    t = time.perf_counter()
    bom = _bom(L)
    from build123d import Compound
    compound = Compound([i.shape for i in L.insts])
    meas = _measure(L, compound)
    T["measure"] = time.perf_counter() - t
    sha = _canonical_sha(parts_in, layout_text)
    tri_unique, tri_shown = 0, 0
    T["files"] = {}
    used = []
    for i in L.insts:
        if i.part.id not in used:
            used.append(i.part.id)
    pmesh = {}
    if "glb" in formats:
        t = time.perf_counter()
        for pid in used:
            pmesh[pid] = geometry.tessellate(parts[pid].res)
            tri_unique += pmesh[pid]["n_tri"]
        tri_shown = sum(pmesh[i.part.id]["n_tri"] for i in L.insts)
        if tri_shown > MAX_TRIANGLES:
            raise ResourceLimit(f"网格超过 {MAX_TRIANGLES} 个三角形")
        T["files"]["tessellate"] = time.perf_counter() - t
    meta = {"name": name, "plan_sha": sha}
    # 三视图：SVG 与 DXF 用同一份消隐投影，本次调用内只算一次（不改 geometry.py，调用结束即还原）
    orig_layout, memo = geometry._layout, {}

    def _layout_once(part):
        if id(part) not in memo:
            memo[id(part)] = orig_layout(part)
        return memo[id(part)]
    geometry._layout = _layout_once
    try:
        files = _files(L, name, formats, workdir, pmesh, inter_shapes, bom, meas, compound, meta, T)
    finally:
        geometry._layout = orig_layout
    T["total"] = time.perf_counter() - t0
    LAST_TIMINGS.clear()
    LAST_TIMINGS.update(T)
    out = {
        "name": name, "plan_sha256": sha, "measure": meas, "bom": bom,
        "interference": inter, "mesh": meshes,
        "constraints": L.table,
        "parts": [_part_summary(parts[pid]) for pid in used],
        "instances": [{"row": i.row, "part": i.part.id, "item": i.item, "line": i.line,
                       "bbox": [[r3(v) for v in b] for b in _bbox(i.shape)]} for i in L.insts],
        "warnings": L.warnings, "files": files,
    }
    if "glb" in formats:
        out["triangles"] = {"unique": tri_unique, "shown": tri_shown}
    return out


TOOLS = {"cad.assemble": cad_assemble}


def _fail(code, message, line=None, hint=None, problems=None):
    e = {"code": code, "message": message}
    if line is not None:
        e["line"] = line
    if hint:
        e["hint"] = hint
    if problems:
        e["problems"] = problems
    return {"ok": False, "error": e}


def _on_alarm(signum, frame):
    raise _Timeout


def run(envelope, tool_from_argv=None, workdir_from_argv=None) -> dict:
    if not isinstance(envelope, dict):
        return _fail("BAD_INPUT", "输入必须是 JSON 对象")
    if "tool" in envelope and "payload" in envelope:
        tool, payload = envelope["tool"], envelope["payload"]
        budget, workdir = envelope.get("budget") or {}, envelope.get("workdir")
    else:
        tool, payload, budget, workdir = tool_from_argv, envelope, {}, workdir_from_argv
    fn = TOOLS.get(tool)
    if fn is None:
        return _fail("BAD_INPUT", f"未知工具 {tool!r}（可用：{', '.join(sorted(TOOLS))}）")
    if not isinstance(payload, dict):
        return _fail("BAD_INPUT", "payload 必须是 JSON 对象")
    timeout_ms = budget.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    try:
        timeout_s = max(0.05, float(timeout_ms) / 1000 * 0.9)
    except (TypeError, ValueError):
        timeout_s = DEFAULT_TIMEOUT_MS / 1000
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, timeout_s)
    try:
        return {"ok": True, "output": fn(payload, workdir)}
    except _Timeout:
        return _fail("TIMEOUT", f"超过 {timeout_ms} ms")
    except BadInput as e:
        return _fail("BAD_INPUT", str(e), e.line, e.hint, e.problems)
    except ResourceLimit as e:
        return _fail("RESOURCE_LIMIT", str(e))
    except RecursionError:
        return _fail("RESOURCE_LIMIT", "嵌套过深")
    except Exception as exc:  # noqa: BLE001
        return _fail("INTERNAL", f"{type(exc).__name__}: {exc}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main() -> int:
    if os.environ.get("PYTHONHASHSEED") != "0":
        env = dict(os.environ, PYTHONHASHSEED="0")
        os.execve(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:], env)
    args = sys.argv[1:]
    workdir = None
    if "--workdir" in args:
        i = args.index("--workdir")
        workdir = os.path.abspath(args[i + 1]) if i + 1 < len(args) else None
        args = args[:i] + args[i + 2:]
    line = sys.stdin.readline()
    try:
        envelope = json.loads(line)
    except json.JSONDecodeError as exc:
        sys.stdout.write(json.dumps(_fail("BAD_INPUT", f"输入不是合法 JSON：{exc.msg}"), ensure_ascii=False) + "\n")
        return 0
    out = run(envelope, args[0] if args else None, workdir)
    sys.stdout.write(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
