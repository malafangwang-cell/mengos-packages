"""把解析后的计划逐行变成实体。

约定（写在使用说明里，模型照此写计划）：
- 单位 mm；x 向右、y 向后、z 向上。
- box 的 at 是最小角点；cylinder / cone 的 at 是底面圆心；sphere 的 at 是球心；gear 以 at 为中心、从 at 的 z 向上。
- hole / pocket / slot 从 from 指定的外表面（按当前零件的包围盒：top、bottom、front、back、left、right）向里加工；
  at=center 是该面中心，at=(u,v) 是该面上的坐标：top/bottom 用 (x,y)，front/back 用 (x,z)，left/right 用 (y,z)。
- 每一行可以命名（name: op ...）。名字就是特征的句柄：引用它可以倒角、阵列，界面上点中它也能定位到这一行。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from build123d import (Align, Axis, Box, Circle, Cone, Cylinder, FilletPolyline, Helix, Location, Part,
                       Plane, Polygon, Polyline, Solid, Sphere, Spline, Transition, extrude, make_face,
                       mirror, offset, revolve, sweep)

from cad_dsl import DslError, Stmt

EPS = 0.5            # 刀具伸出加工面的余量（mm），避免共面布尔
MAX_SIZE = 10000.0   # 单个尺寸上限（mm）
MIN_SIZE = 0.01
MAX_PATTERN = 200
MAX_FEATURES = 400
DEBUG = False

MATERIALS = {   # 密度 g/cm³（常用工程值）
    "6061-T6": 2.70, "6061": 2.70, "7075-T6": 2.81, "7075": 2.81, "5052": 2.68, "2A12": 2.78,
    "Q235": 7.85, "45": 7.85, "45#": 7.85, "304": 7.93, "316": 7.98, "H62": 8.43, "T2": 8.89,
    "TC4": 4.43, "Ti-6Al-4V": 4.43, "ABS": 1.04, "PLA": 1.24, "PETG": 1.27, "PA6": 1.14, "POM": 1.41, "PC": 1.20,
}

SUPPORTED = ["units", "material", "let", "box", "cylinder", "sphere", "cone", "prism", "gear",
             "revolve", "sweep", "helix",
             "hole", "pocket", "slot", "cut", "add", "fillet", "chamfer", "shell", "pattern", "mirror"]


@dataclass
class Feature:
    id: str
    op: str
    line: int
    src: str
    sign: int                      # +1 加料，-1 去料，0 修饰
    surfaces: set = field(default_factory=set)
    tool: object = None            # 用于阵列的刀具（世界坐标）
    axis: tuple | None = None      # 加工方向（从外向里），阵列与测量用
    face: str | None = None
    params: dict = field(default_factory=dict)
    copies: list = field(default_factory=list)   # pattern / mirror 复制出来的刀具，第 k 个即实例 k（源特征本身是实例 0）


@dataclass
class BuildResult:
    part: Part
    features: list
    material: str | None
    density: float | None
    warnings: list


# ---------------------------------------------------------------- 面的身份
def cylinder_info(face):
    """圆柱面的 (单位轴向, 轴上离原点最近的点, 半径)，轴向取首个非零分量为正。"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    cyl = BRepAdaptor_Surface(face.wrapped).Cylinder()
    ax = cyl.Axis()
    d, p = ax.Direction(), ax.Location()
    dx, dy, dz = d.X(), d.Y(), d.Z()
    first = next(v for v in (dx, dy, dz) if abs(v) > 1e-9)
    if first < 0:
        dx, dy, dz = -dx, -dy, -dz
    px, py, pz = p.X(), p.Y(), p.Z()
    t = px * dx + py * dy + pz * dz
    return (dx, dy, dz), (px - t * dx, py - t * dy, pz - t * dz), cyl.Radius()


def surface_key(face):
    """面所在曲面的身份：后续布尔把面切开，曲面不变，以此把面归到产生它的特征。"""
    gt = str(face.geom_type).split(".")[-1]
    if gt == "PLANE":
        c = face.center()
        n = face.normal_at(c)
        d = n.X * c.X + n.Y * c.Y + n.Z * c.Z
        return ("P", round(n.X, 5) + 0.0, round(n.Y, 5) + 0.0, round(n.Z, 5) + 0.0, round(d, 3) + 0.0)
    if gt == "CYLINDER":
        (dx, dy, dz), (qx, qy, qz), r = cylinder_info(face)
        return ("C", round(dx, 5) + 0.0, round(dy, 5) + 0.0, round(dz, 5) + 0.0,
                round(qx, 3) + 0.0, round(qy, 3) + 0.0, round(qz, 3) + 0.0, round(r, 4) + 0.0)
    c = face.center()
    return ("O", gt, round(c.X, 3), round(c.Y, 3), round(c.Z, 3), round(face.area, 3))


def face_key_text(key) -> str:
    """曲面键的文字形式（2.6.0）：特征表的 face_digest、网格的 face_key 用同一写法，逐字节确定。"""
    return "|".join(k if isinstance(k, str) else repr(float(k) + 0.0) for k in key)


def key_is_uncertain(key) -> bool:
    """键里含面积的面（非平面、非圆柱面）：被后续特征切一下就成了“新曲面”，归属可能跳到切它的那一行。"""
    return key[0] == "O"


def face_instance(face, feat) -> int | None:
    """阵列、镜像行名下的面来自第几个复制体（1 起；源特征本身是实例 0，面归源特征那一行）。
    先按曲面键对刀具的面，对不上（键里含面积的面）再取离面中心最近的复制体。"""
    if not feat.copies:
        return None
    k = surface_key(face)
    hit = [i for i, c in enumerate(feat.copies, 1) if any(surface_key(g) == k for g in c.faces())]
    if len(hit) == 1:
        return hit[0]
    ctr = face.center()
    cand = hit or list(range(1, len(feat.copies) + 1))
    return min(cand, key=lambda i: (feat.copies[i - 1].distance_to(ctr), i))


def _surfaces(part):
    return {surface_key(f) for f in part.faces()} if part is not None else set()


# ---------------------------------------------------------------- 参数读取
class _Args:
    def __init__(self, st: Stmt):
        self.st = st
        self.used = set()

    def err(self, msg, hint=""):
        raise DslError(self.st.line, f"第 {self.st.line} 行（{self.st.op}）：{msg}", hint)

    def num(self, key, default=None, positive=True, required=True):
        self.used.add(key)
        if key not in self.st.kw:
            if default is not None or not required:
                return default
            self.err(f"缺少参数 {key}")
        v = self.st.kw[key]
        if isinstance(v, (int, float)):
            v = float(v)
            if positive and not (MIN_SIZE <= v <= MAX_SIZE):
                self.err(f"{key}={v:g} 不在 {MIN_SIZE}–{MAX_SIZE} mm 之内")
            return v
        self.not_number(v, key)

    def not_number(self, v, key=None):
        what = f"{key} 应当是数，" if key else ""
        if isinstance(v, str):
            self.err(f"{what}“{v}”不是数，也不是已定义的变量", "变量先用 let 定义，例如：let w = 80")
        self.err(f"{what}实际是 {v}")

    def word(self, key, choices, default=None):
        self.used.add(key)
        v = self.st.kw.get(key, default)
        if v is None:
            self.err(f"缺少参数 {key}")
        if v not in choices:
            self.err(f"{key}={v} 不在可选值内：{'、'.join(choices)}")
        return v

    def tup(self, key, n, default=None):
        self.used.add(key)
        v = self.st.kw.get(key, default)
        if v is None:
            return None
        if not isinstance(v, tuple) or len(v) != n:
            self.err(f"{key} 应当是 {n} 个数的括号，例如 ({', '.join(['0'] * n)})")
        return tuple(float(x) for x in v)

    def done(self):
        extra = set(self.st.kw) - self.used
        if extra:
            self.err(f"不认识的参数：{'、'.join(sorted(extra))}")


# ---------------------------------------------------------------- 加工面
_FACE = {
    #       inward 方向           u 轴        v 轴      包围盒上的坐标分量
    "top":    ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
    "bottom": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    "front":  ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "back":   ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    "left":   ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "right":  ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
}


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _ray_hits(part, origin, inward):
    """从 origin 沿 inward 的射线与零件表面的交点参数（升序，≥0）。"""
    from OCP.BRepIntCurveSurface import BRepIntCurveSurface_Inter
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    it = BRepIntCurveSurface_Inter()
    it.Init(part.wrapped, gp_Lin(gp_Pnt(*origin), gp_Dir(*inward)), 1e-7)
    ws = []
    while it.More():
        if it.W() > -1e-7:
            ws.append(max(0.0, it.W()))
        it.Next()
    return sorted(ws)


def _face_frame(part, face, at, a: _Args):
    """加工面坐标系。返回 (入口点, 向里方向, U, V, 入口到对面的距离, 是否找到材料)。

    入口点 = 从包围盒的该面沿向里方向，在 at 处碰到的第一个材料表面；
    这样 L 形件上从 top 打孔，孔口落在真正的上表面，而不是悬在包围盒顶上。"""
    if part is None:
        a.err("还没有零件可以加工；先用 box、cylinder 等建一个基体")
    bb = part.bounding_box()
    mn, mx = (bb.min.X, bb.min.Y, bb.min.Z), (bb.max.X, bb.max.Y, bb.max.Z)
    inward, U, V = _FACE[face]
    k = next(i for i in range(3) if inward[i] != 0)
    plane_c = mx[k] if inward[k] < 0 else mn[k]
    iu = next(i for i in range(3) if U[i] != 0)
    iv = next(i for i in range(3) if V[i] != 0)
    if at == "center" or at is None:
        u, v = (mn[iu] + mx[iu]) / 2, (mn[iv] + mx[iv]) / 2
    elif isinstance(at, tuple) and len(at) == 2:
        u, v = at
    else:
        a.err("at 应当是 center 或 (u, v)；top/bottom 写 (x, y)，front/back 写 (x, z)，left/right 写 (y, z)")
    p = [0.0, 0.0, 0.0]
    p[k], p[iu], p[iv] = plane_c, u, v
    extent = mx[k] - mn[k]
    hits = _ray_hits(part, tuple(p), inward)
    if hits and hits[0] < extent - 1e-9:
        w = hits[0]
        p = [p[i] + w * inward[i] for i in range(3)]
        return tuple(p), inward, U, V, extent - w, True
    return tuple(p), inward, U, V, extent, False


def _place(tool, origin, inward, xdir):
    return tool.moved(Location(Plane(origin=origin, x_dir=xdir, z_dir=inward)))


def _rot_dir(U, V, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return tuple(c * U[i] + s * V[i] for i in range(3))


# ---------------------------------------------------------------- 正向实体
def _at3(a: _Args):
    return a.tup("at", 3, (0.0, 0.0, 0.0))


def _axis_loc(axis, at):
    rot = {"z": (0, 0, 0), "x": (0, 90, 0), "y": (-90, 0, 0)}[axis]
    return Location(at, rot)


def make_box(st, a):
    for x in st.pos:
        if not isinstance(x, float):
            a.not_number(x)
    if len(st.pos) == 3:
        L, W, H = st.pos
    elif st.pos:
        a.err("box 写成 box 长 宽 高，或 box l= w= h=")
    else:
        L, W, H = a.num("l"), a.num("w"), a.num("h")
    for v in (L, W, H):
        if not (MIN_SIZE <= v <= MAX_SIZE):
            a.err(f"尺寸 {v:g} 不在 {MIN_SIZE}–{MAX_SIZE} mm 之内")
    at = _at3(a)
    a.done()
    return Box(L, W, H, align=(Align.MIN,) * 3).moved(Location(at)), {"size": (L, W, H), "at": at}


def make_cylinder(st, a):
    d, h = a.num("d"), a.num("h")
    axis = a.word("axis", ["x", "y", "z"], "z")
    at = _at3(a)
    a.done()
    return Cylinder(d / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(_axis_loc(axis, at)), {"d": d, "h": h, "axis": axis, "at": at}


def make_sphere(st, a):
    d = a.num("d")
    at = _at3(a)
    a.done()
    return Sphere(d / 2).moved(Location(at)), {"d": d, "at": at}


def make_cone(st, a):
    d1, d2, h = a.num("d1"), a.num("d2", positive=False, default=0.0), a.num("h")
    if d2 < 0:
        a.err("d2 不能为负")
    axis = a.word("axis", ["x", "y", "z"], "z")
    at = _at3(a)
    a.done()
    return Cone(d1 / 2, d2 / 2, h, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(_axis_loc(axis, at)), {"d1": d1, "d2": d2, "h": h, "axis": axis, "at": at}


def _profile_pts(st, a, what, n_min=3):
    """轮廓点：(u,v) 或 (u,v,r)。r 为该顶点的圆角半径（0 或缺省为尖角）。"""
    pts = [p for p in st.pos if isinstance(p, tuple)]
    if len(pts) < n_min or len(pts) != len(st.pos) or any(len(p) not in (2, 3) for p in pts):
        a.err(f"{what} 需要至少 {n_min} 个点，写成 (u,v) (u,v) (u,v) …；某个顶点要倒圆时写 (u,v,r)")
    if len(pts) > 200:
        a.err(f"{what} 最多 200 个点")
    for p in pts:
        if len(p) == 3 and p[2] < 0:
            a.err(f"顶点 {p} 的圆角半径不能为负")
    return [(float(p[0]), float(p[1]), float(p[2]) if len(p) == 3 else 0.0) for p in pts]


def _ccw(pts):
    n = len(pts)
    area2 = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    return area2


def _profile_face(pts, smooth, a, plane):
    """闭合轮廓 → 平面上的面。smooth：过各点的闭合样条；否则多边形，(u,v,r) 的顶点倒圆。"""
    area2 = _ccw(pts)
    if abs(area2) < 1e-9:
        a.err("轮廓围成的面积为零")
    if area2 < 0:
        pts = list(reversed(pts))
    uv = [(p[0], p[1]) for p in pts]
    if smooth:
        if any(p[2] > 0 for p in pts):
            a.err("smooth 轮廓不再给顶点圆角：样条本身是光滑的，去掉 (u,v,r) 里的 r")
        try:
            w = Spline(*uv, periodic=True)
            f = make_face(w)
        except Exception:
            a.err("样条轮廓做不出来：点可能重复或自相交", "点按轮廓顺序给出，不要重复首点")
    elif any(p[2] > 0 for p in pts):
        rad = [p[2] if p[2] > 0 else 1e-6 for p in pts]
        try:
            w = FilletPolyline(*uv, radius=rad, close=True)
            f = make_face(w)
        except Exception:
            a.err("轮廓的顶点圆角做不出来：圆角半径大于相邻边能容纳的长度", "减小 r，或加长相邻的边")
    else:
        f = Polygon(*uv, align=None)
    return plane * f, pts


_PLANES = {"xy": ((1, 0, 0), (0, 0, 1)), "xz": ((1, 0, 0), (0, -1, 0)), "yz": ((0, 1, 0), (1, 0, 0))}


def make_prism(st, a):
    """平面轮廓拉伸。plane=xy（默认，点为 (x,y)，沿 +z 拉伸，起点 off=z）、
    xz（点为 (x,z)，沿 +y）、yz（点为 (y,z)，沿 +x）。点可写 (u,v,r) 给顶点倒圆；
    smooth 表示过各点的光滑闭合曲线；twist= 拉伸过程中绕平面原点的法线转过的角度（度）。"""
    smooth = False
    if "smooth" in st.pos:
        st.pos = [p for p in st.pos if p != "smooth"]
        smooth = True
    pts = _profile_pts(st, a, "prism")
    h = a.num("h")
    pl = a.word("plane", ["xy", "xz", "yz"], "xy")
    off = a.num("off", default=0.0, positive=False)
    if "z" in st.kw and pl == "xy":          # 兼容写法 z=
        off = a.num("z", positive=False)
    twist = a.num("twist", default=0.0, positive=False)
    a.done()
    if abs(twist) > 3600:
        a.err("twist 不超过 3600 度")
    xd, zd = _PLANES[pl]
    origin = tuple(off * c for c in {"xy": (0, 0, 1), "xz": (0, 1, 0), "yz": (1, 0, 0)}[pl])
    plane = Plane(origin=origin, x_dir=xd, z_dir=zd)
    face, pts = _profile_face(pts, smooth, a, plane)
    d = {"xy": (0, 0, 1), "xz": (0, 1, 0), "yz": (1, 0, 0)}[pl]
    if twist:
        faces = face.faces()
        if len(faces) != 1:
            a.err("twist 只用于单个闭合轮廓")
        solid = Solid.extrude_linear_with_rotation(faces[0], origin, tuple(h * c for c in d), twist)
    else:
        solid = extrude(face, amount=h, dir=d)
        if solid.volume < 0:
            solid = extrude(face, amount=-h, dir=d)
    return solid, {"points": [p[:2] for p in pts], "h": h, "plane": pl, "off": off, "smooth": smooth, "twist": twist}


def make_revolve(st, a):
    """回转：轮廓点 (r,z) 在过轴的半平面上，r ≥ 0，绕 axis 转 angle 度。at 为轴上 z=0 的点。"""
    pts = _profile_pts(st, a, "revolve")
    if any(p[0] < 0 for p in pts):
        a.err("revolve 的点写成 (r,z)，r 是到轴的距离，不能为负")
    angle = a.num("angle", default=360.0)
    if angle > 360:
        a.err("angle 不超过 360")
    axis = a.word("axis", ["x", "y", "z"], "z")
    at = _at3(a)
    a.done()
    face, pts = _profile_face(pts, False, a, Plane(origin=(0, 0, 0), x_dir=(1, 0, 0), z_dir=(0, -1, 0)))
    solid = revolve(face, Axis.Z, angle)
    return solid.moved(_axis_loc(axis, at)), {"points": [p[:2] for p in pts], "angle": angle, "axis": axis, "at": at}


def make_sweep(st, a):
    """圆截面沿折线路径扫掠。路径点 (x,y,z)；r= 为各拐角的弯曲半径（缺省 0：尖角，按圆接头处理）；
    id= 给出内径时为管。"""
    pts = [p for p in st.pos if isinstance(p, tuple)]
    if len(pts) < 2 or len(pts) != len(st.pos) or any(len(p) != 3 for p in pts):
        a.err("sweep 的路径写成至少 2 个点 (x,y,z) (x,y,z) …")
    if len(pts) > 100:
        a.err("sweep 的路径最多 100 个点")
    d = a.num("d")
    idia = a.num("id", required=False)
    r = a.num("r", default=0.0, positive=False)
    a.done()
    if idia is not None and idia >= d:
        a.err("内径 id 应当小于外径 d")
    if r < 0:
        a.err("弯曲半径 r 不能为负")
    pts = [tuple(float(c) for c in p) for p in pts]
    if r > 0 and len(pts) > 2:
        if r < d / 2:
            a.err(f"弯曲半径 r={r:g} 小于截面半径 {d / 2:g}，管子会自交", f"r 至少取 {d / 2:g}")
        try:
            path = FilletPolyline(*pts, radius=r)
        except Exception:
            a.err(f"弯曲半径 r={r:g} 太大：拐角相邻的路径段装不下", "减小 r，或加长相邻的段")
    else:
        path = Polyline(*pts)
    plane = Plane(origin=path @ 0, z_dir=path % 0)

    def tube(dd):
        return sweep(plane * Circle(dd / 2), path=path, transition=Transition.ROUND)
    solid = tube(d)
    if idia:
        solid = solid - tube(idia)
    return solid, {"path": pts, "d": d, "id": idia, "r": r}


def make_helix(st, a):
    """螺旋（弹簧）：圆截面线径 wire，中径 d，螺距 pitch，高 h。at 为底面中心；axis 为螺旋轴；left 为左旋。"""
    d, pitch, h, wire = a.num("d"), a.num("pitch"), a.num("h"), a.num("wire")
    axis = a.word("axis", ["x", "y", "z"], "z")
    hand = a.word("hand", ["right", "left"], "right")
    at = _at3(a)
    a.done()
    if wire >= pitch:
        a.err(f"线径 wire={wire:g} 不小于螺距 pitch={pitch:g}，相邻圈会相交", "并紧的端圈另用 add 一个圆环表示")
    if wire >= d:
        a.err("线径 wire 应当小于中径 d")
    if h / pitch > 200:
        a.err("圈数超过 200")
    path = Helix(pitch, h, d / 2, lefthand=(hand == "left"))
    plane = Plane(origin=path @ 0, z_dir=path % 0)
    solid = sweep(plane * Circle(wire / 2), path=path, is_frenet=True)
    return solid.moved(_axis_loc(axis, at)), {"d": d, "pitch": pitch, "h": h, "wire": wire, "axis": axis, "hand": hand, "at": at}


def gear_profile(m, z, alpha_deg=20.0, n_inv=12):
    """直齿渐开线齿廓（标准齿：齿顶高 m，齿根高 1.25m；不计根切与齿根圆角）。
    每个齿：齿根径向线 → 渐开线（样条，过 n_inv+1 个精确点）→ 齿顶圆弧 → 渐开线 → 径向线 → 齿根圆弧。"""
    from build123d import Line, Spline, ThreePointArc, Wire
    alpha = math.radians(alpha_deg)
    r = m * z / 2
    rb = r * math.cos(alpha)
    ra = r + m
    rf = r - 1.25 * m
    inv = lambda phi: math.tan(phi) - phi
    beta = math.pi / (2 * z) + inv(alpha)          # 基圆上的半齿角
    r0 = max(rb, rf)
    pitch = 2 * math.pi / z

    def psi(rho):
        return beta if rho <= rb else beta - inv(math.acos(rb / rho))

    P = lambda rho, th: (rho * math.cos(th), rho * math.sin(th))
    if psi(ra) <= 0:
        raise ValueError("齿顶变尖")
    edges = []
    for k in range(z):
        c = k * pitch
        flank = [r0 + (ra - r0) * (i / n_inv) ** 1.5 for i in range(n_inv + 1)]   # 靠近基圆处加密
        lo = [P(rho, c - psi(rho)) for rho in flank]
        up = [P(rho, c + psi(rho)) for rho in reversed(flank)]
        if rf < rb:
            edges.append(Line(P(rf, c - beta), lo[0]))
        edges.append(Spline(*lo))
        edges.append(ThreePointArc(lo[-1], P(ra, c), up[0]))
        edges.append(Spline(*up))
        if rf < rb:
            edges.append(Line(up[-1], P(rf, c + beta)))
        a0, a1 = c + beta, c + pitch - beta
        start = P(rf, a0) if rf < rb else up[-1]
        nxt = c + pitch
        end = P(rf, a1) if rf < rb else P(r0, nxt - psi(r0))
        edges.append(ThreePointArc(start, P(rf if rf < rb else r0, (a0 + a1) / 2), end))
    wire = Wire(edges)
    return wire, {"pitch_d": 2 * r, "tip_d": 2 * ra, "root_d": 2 * rf, "base_d": 2 * rb}


def make_gear(st, a):
    from build123d import Face
    m = a.num("m")
    zf = a.num("z")
    if abs(zf - round(zf)) > 1e-9 or not (6 <= zf <= 300):
        a.err("齿数 z 应当是 6–300 的整数")
    z = int(round(zf))
    b = a.num("width")
    alpha = a.num("alpha", default=20.0)
    if not (14.5 <= alpha <= 30):
        a.err("压力角 alpha 应当在 14.5°–30° 之间")
    bore = a.num("bore", required=False)
    at = _at3(a)
    a.done()
    if z < 17 and abs(alpha - 20) < 1e-9:
        pass   # 标准齿 z<17 会根切；这里不建模根切，说明里写明
    wire, dims = gear_profile(m, z, alpha)
    g = extrude(Face(wire), amount=b, dir=(0, 0, 1))
    if bore:
        if bore >= dims["root_d"]:
            a.err(f"孔径 {bore:g} 不小于齿根圆直径 {dims['root_d']:.3f}")
        g = g - Cylinder(bore / 2, b + 2 * EPS, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -EPS)))
    return g.moved(Location(at)), dict(m=m, z=z, width=b, alpha=alpha, bore=bore, at=at, **dims)


POSITIVE = {"box": make_box, "cylinder": make_cylinder, "sphere": make_sphere, "cone": make_cone, "prism": make_prism, "gear": make_gear,
            "revolve": make_revolve, "sweep": make_sweep, "helix": make_helix}


# ---------------------------------------------------------------- 去料特征
def _depth(a, extent, found):
    """返回 (加工深度, 是否贯穿)。深度从入口表面量起。"""
    if "through" in a.st.pos or a.st.kw.get("depth") == "through":
        a.used.add("depth")
        return extent + 2 * EPS, True
    d = a.num("depth", required=False)
    if d is None:
        a.err("要写 depth=深度，或写 through 表示贯穿")
    if not found:
        a.err("at 处沿加工方向没有材料（可能正对已有的孔或空腔），无法确定深度从哪里量起",
              "换一个 at，或改用 through")
    return d, False


def make_hole(part, st, a):
    d = a.num("d")
    face = a.word("from", list(_FACE), "top")
    a.used.add("at")
    origin, inward, U, V, extent, found = _face_frame(part, face, st.kw.get("at", "center"), a)
    depth, through = _depth(a, extent, found)
    cb = a.tup("cbore", 2)
    cs = a.tup("csk", 2)
    a.done()
    L = depth + EPS
    tool = Cylinder(d / 2, L, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -EPS)))
    if cb:
        D, dd = cb
        if D <= d:
            a.err("沉头直径应当大于孔径")
        tool = tool + Cylinder(D / 2, dd + EPS, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -EPS)))
    if cs:
        D, ang = cs
        if D <= d or not (30 <= ang <= 150):
            a.err("锥孔写成 csk=(口径, 角度)，口径大于孔径，角度 30–150°")
        hcone = (D - d) / 2 / math.tan(math.radians(ang / 2))
        tool = tool + Cone(D / 2 + EPS * math.tan(math.radians(ang / 2)), d / 2, hcone + EPS,
                           align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -EPS)))
    world = _place(tool, origin, inward, U)
    return world, dict(d=d, face=face, at=origin, through=through, depth=None if through else depth, cbore=cb, csk=cs), inward, face


def make_pocket(part, st, a):
    shape = st.pos[0] if st.pos and isinstance(st.pos[0], str) else a.err("pocket 后面写形状：rect 或 circle")
    face = a.word("from", list(_FACE), "top")
    a.used.add("at")
    origin, inward, U, V, extent, found = _face_frame(part, face, st.kw.get("at", "center"), a)
    depth, through = _depth(a, extent, found)
    if shape == "rect":
        w, l = a.num("w"), a.num("l")
        ang = a.num("angle", default=0.0, positive=False)
        r = a.num("r", required=False)
        a.done()
        tool = Box(w, l, depth + EPS, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -EPS)))
        if r:
            if 2 * r >= min(w, l):
                a.err("圆角半径太大")
            tool = tool.fillet(r, tool.edges().filter_by(Axis.Z))
        world = _place(tool, origin, inward, _rot_dir(U, V, ang))
        params = dict(shape="rect", w=w, l=l, r=r, angle=ang)
    elif shape == "circle":
        d = a.num("d")
        a.done()
        tool = Cylinder(d / 2, depth + EPS, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((0, 0, -EPS)))
        world = _place(tool, origin, inward, U)
        params = dict(shape="circle", d=d)
    else:
        a.err(f"pocket 的形状只支持 rect、circle，不支持“{shape}”")
    params.update(face=face, at=origin, through=through, depth=None if through else depth)
    return world, params, inward, face


def make_slot(part, st, a):
    w, l = a.num("w"), a.num("l")
    if l <= w:
        a.err("槽的总长 l 应当大于槽宽 w")
    face = a.word("from", list(_FACE), "top")
    ang = a.num("angle", default=0.0, positive=False)
    a.used.add("at")
    origin, inward, U, V, extent, found = _face_frame(part, face, st.kw.get("at", "center"), a)
    depth, through = _depth(a, extent, found)
    a.done()
    H = depth + EPS
    c = (l - w) / 2
    tool = Box(l - w, w, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for sx in (-c, c):
        tool = tool + Cylinder(w / 2, H, align=(Align.CENTER, Align.CENTER, Align.MIN)).moved(Location((sx, 0, 0)))
    tool = tool.moved(Location((0, 0, -EPS)))
    world = _place(tool, origin, inward, _rot_dir(U, V, ang))
    return world, dict(w=w, l=l, angle=ang, face=face, at=origin, through=through, depth=None if through else depth), inward, face


NEGATIVE = {"hole": make_hole, "pocket": make_pocket, "slot": make_slot}


# ---------------------------------------------------------------- 边的选择
def _edges_of_faces(faces):
    out = []
    for f in faces:
        for e in f.edges():
            if not any(e.is_same(x) for x in out):
                out.append(e)
    return out


def _sharp_edges(part, edges):
    """去掉圆柱、圆锥等曲面自身的接缝边（两侧是同一个面），它们不能倒角。"""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as _Map
    m = _Map()
    TopExp.MapShapesAndAncestors_s(part.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    out = []
    for e in edges:
        faces = list(m.FindFromKey(e.wrapped)) if m.Contains(e.wrapped) else []
        distinct = []
        for f in faces:
            if not any(f.IsSame(g) for g in distinct):
                distinct.append(f)
        if len(distinct) >= 2:
            out.append(e)
    return out


def select_edges(part, sel, features, a):
    if sel == "all":
        return _sharp_edges(part, list(part.edges()))
    if sel == "vertical":
        return _sharp_edges(part, list(part.edges().filter_by(Axis.Z)))
    if sel in _FACE:
        inward = _FACE[sel][0]
        bb = part.bounding_box()
        k = next(i for i in range(3) if inward[i] != 0)
        level = (bb.max.X, bb.max.Y, bb.max.Z)[k] if inward[k] < 0 else (bb.min.X, bb.min.Y, bb.min.Z)[k]
        faces = []
        for f in part.faces():
            if str(f.geom_type).endswith("PLANE"):
                c = f.center()
                n = f.normal_at(c)
                if abs(_dot((n.X, n.Y, n.Z), inward) + 1) < 1e-6 and abs((c.X, c.Y, c.Z)[k] - level) < 1e-6:
                    faces.append(f)
        if not faces:
            a.err(f"零件的 {sel} 面上没有平面可选边")
        return _edges_of_faces(faces)
    feat = next((f for f in features if f.id == sel), None)
    if feat is None:
        a.err(f"edges={sel}：既不是 all、vertical、top/bottom/front/back/left/right，也不是已命名的特征")
    out = [e for e, owner in edge_owners(part, features) if owner == feat.id]
    if not out:
        a.err(f"特征 {sel} 在当前零件上已经没有属于它的边了")
    return out


def edge_owners(part, features):
    """边的归属：两侧面的归属特征里较晚的那个。
    这样凸台的顶边、根部边归凸台；后打的孔口边归那个孔。"""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as _Map
    from build123d import Edge, Face
    order = {f.id: i for i, f in enumerate(features)}
    m = _Map()
    TopExp.MapShapesAndAncestors_s(part.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    out = []
    for e in part.edges():
        if not m.Contains(e.wrapped):
            continue
        faces = []
        for f in m.FindFromKey(e.wrapped):
            if not any(f.IsSame(g) for g in faces):
                faces.append(f)
        if len(faces) < 2:
            continue                                   # 接缝边
        owners = [face_owner(Face(f), features) for f in faces]
        owner = max(owners, key=lambda o: order.get(o, -1))
        out.append((e, owner))
    return out


# ---------------------------------------------------------------- 主流程
def build(stmts: list[Stmt]) -> BuildResult:
    part = None
    features: list[Feature] = []
    material, density, warnings = None, None, []
    auto = {}

    def new_id(st):
        if st.name:
            return st.name
        auto[st.op] = auto.get(st.op, 0) + 1
        return f"{st.op}#{auto[st.op]}"

    def record(st, sign, before, after, **kw):
        if len(features) >= MAX_FEATURES:
            raise DslError(st.line, f"特征超过 {MAX_FEATURES} 个")
        f = Feature(id=new_id(st), op=st.op, line=st.line, src=st.src, sign=sign,
                    surfaces=_surfaces(after) - _surfaces(before), **kw)
        features.append(f)
        return f

    def check_part(st, p):
        if p is None or len(p.solids()) == 0:
            raise DslError(st.line, f"第 {st.line} 行之后零件变空了（去料把实体全部切掉）")
        if not p.is_valid:
            raise DslError(st.line, f"第 {st.line} 行之后几何无效；请检查尺寸与位置是否自相矛盾")
        return p

    for st in stmts:
        a = _Args(st)
        try:
            if st.op == "units":
                if st.pos[0].lower() != "mm":
                    a.err("目前只支持 units mm")
                continue
            if st.op == "material":
                material = st.pos[0]
                density = MATERIALS.get(material)
                if density is None:
                    warnings.append({"line": st.line, "message": f"材料“{material}”不在密度表里，不计算质量"})
                continue
            if st.op in POSITIVE or (st.op in ("add", "cut") and st.pos and st.pos[0] in POSITIVE):
                if st.op in ("add", "cut"):
                    sign = 1 if st.op == "add" else -1
                    kind = st.pos[0]
                    sub = Stmt(line=st.line, op=kind, name=st.name, pos=st.pos[1:], kw=dict(st.kw), src=st.src)
                    solid, params = POSITIVE[kind](sub, _Args(sub))
                else:
                    sign, kind = 1, st.op
                    solid, params = POSITIVE[kind](st, a)
                before = part
                if sign > 0:
                    part = solid if part is None else part + solid
                else:
                    if part is None:
                        a.err("cut 之前要先有零件")
                    part = part - solid
                part = check_part(st, part)
                record(st, sign, before, part, tool=solid, params=dict(params, kind=kind))
                continue
            if st.op in ("add", "cut"):
                a.err(f"{st.op} 后面写一个基本体：{'、'.join(POSITIVE)}")
            if st.op in NEGATIVE:
                tool, params, inward, face = NEGATIVE[st.op](part, st, a)
                before = part
                part = check_part(st, part - tool)
                if abs(part.volume - before.volume) < 1e-9:
                    warnings.append({"line": st.line, "message": "这一行没有切到材料，请检查位置"})
                record(st, -1, before, part, tool=tool, axis=inward, face=face, params=params)
                continue
            if st.op in ("fillet", "chamfer"):
                if part is None:
                    a.err("先建零件再倒角")
                size = a.num("r" if st.op == "fillet" else "c")
                sel = st.kw.get("edges", "all")
                a.used.add("edges")
                a.done()
                edges = select_edges(part, sel, features, a)
                before = part
                try:
                    part = part.fillet(size, edges) if st.op == "fillet" else part.chamfer(size, None, edges)
                except Exception:
                    hint = ""
                    if st.op == "fillet":
                        try:
                            hint = f"这组边能做的最大圆角约 r={part.max_fillet(edges, tolerance=0.05, max_iterations=12):.2f}"
                        except Exception:
                            hint = "可能是相邻两条边相距小于 2r，或边所在的面太窄"
                    a.err(f"{'圆角' if st.op == 'fillet' else '倒角'} {size:g} 做不出来：尺寸大于相邻面能容纳的范围（选中 {len(edges)} 条边）", hint)
                part = check_part(st, part)
                record(st, 0, before, part, params={"size": size, "edges": sel})
                continue
            if st.op == "shell":
                if part is None:
                    a.err("先建零件再抽壳")
                t = a.num("t")
                face = a.word("open", list(_FACE) + ["none"], "top")
                a.done()
                openings = None
                if face != "none":
                    ax = {"top": (Axis.Z, -1), "bottom": (Axis.Z, 0), "back": (Axis.Y, -1), "front": (Axis.Y, 0), "right": (Axis.X, -1), "left": (Axis.X, 0)}[face]
                    openings = part.faces().sort_by(ax[0])[ax[1]]
                bb = part.bounding_box()
                if 2 * t >= min(bb.size.X, bb.size.Y, bb.size.Z):
                    a.err(f"抽壳 t={t:g} 太厚：零件最小外形 {min(bb.size.X, bb.size.Y, bb.size.Z):g} mm，壁厚应当小于它的一半")
                before = part
                try:
                    part = offset(part, amount=-t, openings=openings)
                except Exception:
                    a.err(f"抽壳 t={t:g} 做不出来：壁厚相对零件太大，或者形状不适合抽壳")
                part = check_part(st, part)
                if part.volume >= before.volume - 1e-6:
                    a.err(f"抽壳 t={t:g} 没有生效：几何内核没能向内偏置这个形状", "试试更小的壁厚，或先去掉过小的圆角")
                record(st, -1, before, part, params={"t": t, "open": face})
                continue
            if st.op == "pattern":
                if not st.pos or not isinstance(st.pos[0], str):
                    a.err("pattern 后面写要阵列的特征名，例如：pattern hole1 linear n=3 dx=20")
                src = next((f for f in features if f.id == st.pos[0]), None)
                if src is None or src.tool is None:
                    a.err(f"“{st.pos[0]}”不是可以阵列的特征（要先命名，且是加料或去料特征）")
                mode = st.pos[1] if len(st.pos) > 1 else None
                nf = a.num("n")
                if abs(nf - round(nf)) > 1e-9 or not (2 <= nf <= MAX_PATTERN):
                    a.err(f"n 应当是 2–{MAX_PATTERN} 的整数")
                n = int(round(nf))
                copies = []
                if mode == "linear":
                    dx = a.num("dx", default=0.0, positive=False)
                    dy = a.num("dy", default=0.0, positive=False)
                    dz = a.num("dz", default=0.0, positive=False)
                    if dx == dy == dz == 0:
                        a.err("线性阵列至少要有 dx、dy、dz 之一")
                    a.done()
                    copies = [src.tool.moved(Location((dx * i, dy * i, dz * i))) for i in range(1, n)]
                elif mode == "circular":
                    ctr = a.tup("center", 2)
                    if ctr is None:
                        a.err("环形阵列要写 center=(u, v)，坐标规则与 at 相同")
                    total = a.num("angle", default=360.0)
                    a.done()
                    ax_dir = src.axis or (0, 0, -1)
                    k = next(i for i in range(3) if ax_dir[i] != 0)
                    p = [0.0, 0.0, 0.0]
                    others = [i for i in range(3) if i != k]
                    p[others[0]], p[others[1]] = ctr
                    from build123d import Axis as _Ax
                    axis = _Ax(tuple(p), tuple(abs(x) for x in ax_dir))
                    step = total / n if abs(total - 360) < 1e-9 else total / (n - 1)
                    copies = [src.tool.rotate(axis, step * i) for i in range(1, n)]
                elif mode == "grid":
                    dx = a.num("dx", default=0.0, positive=False)
                    dy = a.num("dy", default=0.0, positive=False)
                    dz = a.num("dz", default=0.0, positive=False)
                    steps = [v for v in ((dx, 0, 0), (0, dy, 0), (0, 0, dz)) if any(v)]
                    if len(steps) != 2:
                        a.err("网格阵列在两个方向上各给一个间距，例如 dx= dy=（nx 个乘 ny 个）")
                    mf = a.num("m")
                    if abs(mf - round(mf)) > 1e-9 or not (1 <= mf <= MAX_PATTERN):
                        a.err(f"m 应当是 1–{MAX_PATTERN} 的整数")
                    m = int(round(mf))
                    if n * m > MAX_PATTERN * 4:
                        a.err(f"网格阵列共 {n * m} 个，超过 {MAX_PATTERN * 4}")
                    a.done()
                    (s1, s2) = steps
                    copies = [src.tool.moved(Location(tuple(s1[k] * i + s2[k] * j for k in range(3))))
                              for i in range(n) for j in range(m) if (i, j) != (0, 0)]
                else:
                    a.err("阵列方式写 linear、circular 或 grid")
                before = part
                for c in copies:
                    part = part + c if src.sign > 0 else part - c
                part = check_part(st, part)
                record(st, src.sign, before, part, params={"of": src.id, "mode": mode, "n": n}, copies=copies)
                continue
            if st.op == "mirror":
                if not st.pos or not isinstance(st.pos[0], str):
                    a.err("mirror 后面写要镜像的特征名，例如：mirror rib1 plane=yz off=60")
                src = next((f for f in features if f.id == st.pos[0]), None)
                if src is None or src.tool is None:
                    a.err(f"“{st.pos[0]}”不是可以镜像的特征（要先命名，且是加料或去料特征）")
                pl = a.word("plane", ["xy", "xz", "yz"])
                off = a.num("off", default=0.0, positive=False)
                a.done()
                normal = {"yz": (1, 0, 0), "xz": (0, 1, 0), "xy": (0, 0, 1)}[pl]
                mp = Plane(origin=tuple(off * c for c in normal), z_dir=normal)
                copy = mirror(src.tool, about=mp)
                before = part
                part = part + copy if src.sign > 0 else part - copy
                part = check_part(st, part)
                record(st, src.sign, before, part, tool=copy, params={"of": src.id, "plane": pl, "off": off}, copies=[copy])
                continue
            a.err(f"不支持的操作“{st.op}”", "支持的操作：" + "、".join(SUPPORTED))
        except DslError:
            raise
        except Exception as e:  # 几何内核的异常，按行报告
            if DEBUG:
                raise
            raise DslError(st.line, f"第 {st.line} 行几何运算失败：{type(e).__name__}")
    if part is None:
        raise DslError(0, "计划没有产生任何实体")
    if len(part.solids()) != 1:
        warnings.append({"line": 0, "message": f"零件由 {len(part.solids())} 个互不相连的实体组成"})
    return BuildResult(part=part, features=features, material=material, density=density, warnings=warnings)


def face_owner(face, features):
    """面归属：最后一个产生了该曲面的特征。"""
    k = surface_key(face)
    for f in reversed(features):
        if k in f.surfaces:
            return f.id
    return features[0].id if features else None
