"""测量、网格与导出。所有输出字节确定：同一计划两次运行，文件逐字节相同。"""
from __future__ import annotations

import io
import json
import math
import os
import struct
import tempfile
import zipfile

from build123d import CenterOf, ExportDXF, ExportSVG, Line, LineType, Unit, Vector, export_step

from builder import BuildResult, cylinder_info, face_owner

FIXED_TIME = "2000-01-01T00:00:00"


def r6(x):
    return round(float(x), 6) + 0.0


# ---------------------------------------------------------------- 测量
def _axis_canon(d, p):
    first = next(v for v in d if abs(v) > 1e-9)
    if first < 0:
        d = tuple(-x for x in d)
    t = p[0] * d[0] + p[1] * d[1] + p[2] * d[2]
    return d, (p[0] - t * d[0], p[1] - t * d[1], p[2] - t * d[2])


def _revolved_faces(part):
    """凹的圆柱面与圆锥面：(轴向, 轴点, 半径或口径, 种类, t 区间, u 区间, 半锥角)。"""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools
    out = []
    for f in part.faces():
        gt = str(f.geom_type).split(".")[-1]
        if gt not in ("CYLINDER", "CONE"):
            continue
        s = BRepAdaptor_Surface(f.wrapped)
        surf = s.Cylinder() if gt == "CYLINDER" else s.Cone()
        ax = surf.Axis()
        d, q = _axis_canon((ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()),
                           (ax.Location().X(), ax.Location().Y(), ax.Location().Z()))
        p = f.position_at(0.5, 0.5)
        n = f.normal_at(p)
        t = (p.X - q[0]) * d[0] + (p.Y - q[1]) * d[1] + (p.Z - q[2]) * d[2]
        foot = (q[0] + t * d[0], q[1] + t * d[1], q[2] + t * d[2])
        if n.X * (foot[0] - p.X) + n.Y * (foot[1] - p.Y) + n.Z * (foot[2] - p.Z) <= 0:
            continue                                   # 凸面：外圆、凸台，不是孔
        ts, rs = [], []
        for v in f.vertices():
            tv = (v.X - q[0]) * d[0] + (v.Y - q[1]) * d[1] + (v.Z - q[2]) * d[2]
            fx = (q[0] + tv * d[0], q[1] + tv * d[1], q[2] + tv * d[2])
            ts.append(tv)
            rs.append(math.dist((v.X, v.Y, v.Z), fx))
        if not ts:
            continue
        u1, u2, _, _ = BRepTools.UVBounds_s(f.wrapped)
        r = surf.Radius() if gt == "CYLINDER" else max(rs)
        semi = 0.0 if gt == "CYLINDER" else abs(math.degrees(surf.SemiAngle()))
        out.append({"d": d, "q": q, "r": r, "kind": gt, "t": (min(ts), max(ts)), "u": (u1, u2), "semi": semi})
    return out


def _covers_circle(intervals):
    segs = []
    for a, b in intervals:
        if b - a >= 2 * math.pi - 1e-6:
            return True
        a %= 2 * math.pi
        b = a + (b - a)
        segs.append((a, b))
        if b > 2 * math.pi:
            segs.append((a - 2 * math.pi, b - 2 * math.pi))
    segs.sort()
    reach = 0.0
    for a, b in segs:
        if a > reach + 1e-6:
            if a > 1e-6 or reach > 0:
                return False
        reach = max(reach, b)
    return reach >= 2 * math.pi - 1e-6


def detect_holes(part):
    """孔 = 一整圈的凹圆柱面（可带同轴的沉头、锥口）。圆角、长圆槽端头只有半圈或四分之一圈，不算孔。"""
    faces = _revolved_faces(part)
    # 同一曲面（同轴同径同种类）上的面合并，判断是否满一圈
    surf = {}
    for f in faces:
        k = (tuple(round(x, 5) for x in f["d"]), tuple(round(x, 3) for x in f["q"]), round(f["r"], 4) if f["kind"] == "CYLINDER" else round(f["semi"], 3), f["kind"])
        g = surf.setdefault(k, {"d": f["d"], "q": f["q"], "r": f["r"], "kind": f["kind"], "semi": f["semi"], "t": list(f["t"]), "u": []})
        g["t"][0], g["t"][1] = min(g["t"][0], f["t"][0]), max(g["t"][1], f["t"][1])
        g["r"] = max(g["r"], f["r"])
        g["u"].append(f["u"])
    full = [g for g in surf.values() if _covers_circle(g["u"])]
    # 同轴的整圈面按轴向相接成串，一串就是一个孔
    axes = {}
    for g in full:
        k = (tuple(round(x, 5) for x in g["d"]), tuple(round(x, 3) for x in g["q"]))
        axes.setdefault(k, []).append(g)
    holes = []
    for segs in axes.values():
        segs.sort(key=lambda g: g["t"][0])
        stacks, cur = [], [segs[0]]
        for g in segs[1:]:
            if g["t"][0] <= max(x["t"][1] for x in cur) + 1e-6:
                cur.append(g)
            else:
                stacks.append(cur)
                cur = [g]
        stacks.append(cur)
        for st in stacks:
            d, q = st[0]["d"], st[0]["q"]
            t0, t1 = min(g["t"][0] for g in st), max(g["t"][1] for g in st)
            cyl = [g for g in st if g["kind"] == "CYLINDER"]
            if not cyl:
                continue
            main = min(cyl, key=lambda g: g["r"])
            pt = lambda t: Vector(q[0] + t * d[0], q[1] + t * d[1], q[2] + t * d[2])
            open0 = not part.is_inside(pt(t0 - 0.05))
            open1 = not part.is_inside(pt(t1 + 0.05))
            axis = next((n for n, v in zip("xyz", d) if abs(abs(v) - 1) < 1e-6), None)
            c = pt((t0 + t1) / 2)
            at = {"z": (c.X, c.Y), "y": (c.X, c.Z), "x": (c.Y, c.Z)}.get(axis)
            h = {"d": r6(2 * main["r"]), "axis": axis or [r6(v) for v in d],
                 "at": [r6(v) for v in at] if at else None, "center": [r6(c.X), r6(c.Y), r6(c.Z)],
                 "dir": [r6(v) for v in d],
                 "length": r6(t1 - t0), "through": open0 and open1, "open_ends": int(open0) + int(open1)}
            if not h["through"]:
                h["depth"] = h["length"]
            bigger = [g for g in cyl if g is not main and g["r"] > main["r"] + 1e-6]
            if bigger:
                b = max(bigger, key=lambda g: g["r"])
                h["cbore"] = {"d": r6(2 * b["r"]), "depth": r6(b["t"][1] - b["t"][0])}
            cones = [g for g in st if g["kind"] == "CONE"]
            if cones:
                cn = cones[0]
                h["csk"] = {"d": r6(2 * cn["r"]), "angle": r6(2 * cn["semi"])}
            holes.append(h)
    holes.sort(key=lambda h: (h["d"], str(h["axis"]), h["at"] or []))
    return holes


def measure(res: BuildResult, mesh=None) -> dict:
    part = res.part
    bb = part.bounding_box()
    com = part.center(CenterOf.MASS)
    out = {
        "bbox": {"min": [r6(bb.min.X), r6(bb.min.Y), r6(bb.min.Z)], "max": [r6(bb.max.X), r6(bb.max.Y), r6(bb.max.Z)],
                 "size": [r6(bb.size.X), r6(bb.size.Y), r6(bb.size.Z)]},
        "volume_mm3": r6(part.volume), "area_mm2": r6(part.area),
        "center_of_mass": [r6(com.X), r6(com.Y), r6(com.Z)],
        "solids": len(part.solids()), "faces": len(part.faces()), "edges": len(part.edges()),
        "valid": bool(part.is_valid), "holes": detect_holes(part),
        "material": res.material, "density_g_cm3": res.density,
        "mass_g": r6(part.volume / 1000 * res.density) if res.density else None,
    }
    if mesh is not None:
        out["watertight"] = mesh["watertight"]
        out["triangles"] = mesh["n_tri"]
    return out


# ---------------------------------------------------------------- 网格
def tessellate(res: BuildResult, linear=None, angular=0.1):
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location
    part = res.part
    diag = part.bounding_box().diagonal
    lin = linear if linear else max(0.005, min(0.1, diag * 0.0005))
    BRepMesh_IncrementalMesh(part.wrapped, lin, False, angular, False)
    groups = {}
    weld, wtris = {}, []
    for face in part.faces():
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face.wrapped, loc)
        if tri is None:
            continue
        trsf = loc.Transformation()
        nodes = []
        for i in range(1, tri.NbNodes() + 1):
            p = tri.Node(i).Transformed(trsf)
            nodes.append((p.X(), p.Y(), p.Z()))
        rev = face.wrapped.Orientation() == TopAbs_REVERSED
        tris = []
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            tris.append((a - 1, c - 1, b - 1) if rev else (a - 1, b - 1, c - 1))
        # 面内平滑法向
        normals = [[0.0, 0.0, 0.0] for _ in nodes]
        for a, b, c in tris:
            pa, pb, pc = nodes[a], nodes[b], nodes[c]
            u = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
            v = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
            n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            for k in (a, b, c):
                normals[k][0] += n[0]; normals[k][1] += n[1]; normals[k][2] += n[2]
        for n in normals:
            L = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) or 1.0
            n[0] /= L; n[1] /= L; n[2] /= L
        owner = face_owner(face, res.features) or "body"
        g = groups.setdefault(owner, {"pos": [], "nrm": [], "idx": []})
        base = len(g["pos"])
        g["pos"] += nodes
        g["nrm"] += [tuple(n) for n in normals]
        g["idx"] += [(a + base, b + base, c + base) for a, b, c in tris]
        # 全局焊接，用于水密检查、STL、3MF
        ids = []
        for p in nodes:
            k = (round(p[0], 6), round(p[1], 6), round(p[2], 6))
            if k not in weld:
                weld[k] = len(weld)
            ids.append(weld[k])
        wtris += [(ids[a], ids[b], ids[c]) for a, b, c in tris]
    edge_count = {}
    for a, b, c in wtris:
        for e in ((a, b), (b, c), (c, a)):
            k = (min(e), max(e))
            edge_count[k] = edge_count.get(k, 0) + 1
    watertight = bool(edge_count) and all(v == 2 for v in edge_count.values())
    verts = [None] * len(weld)
    for k, i in weld.items():
        verts[i] = k
    # B-rep 边的折线，供界面描边
    lines = []
    for e in part.edges():
        gt = str(e.geom_type).split(".")[-1]
        n = 1 if gt == "LINE" else 48
        pts = e.positions([i / n for i in range(n + 1)])
        lines.append([(p.X, p.Y, p.Z) for p in pts])
    return {"groups": groups, "verts": verts, "tris": wtris, "watertight": watertight, "n_tri": len(wtris),
            "lines": lines, "linear": lin, "angular": angular}


# ---------------------------------------------------------------- GLB（按特征分组，可拾取）
def to_glb(res: BuildResult, mesh) -> bytes:
    feats = {f.id: f for f in res.features}
    bin_parts, views, accessors, meshes, nodes = [], [], [], [], []
    offset = 0

    def add_view(data: bytes, target):
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

    order = [f.id for f in res.features if f.id in mesh["groups"]] + [k for k in mesh["groups"] if k not in feats]
    for fid in order:
        g = mesh["groups"][fid]
        pos = [c for p in g["pos"] for c in p]
        nrm = [c for n in g["nrm"] for c in n]
        idx = [i for t in g["idx"] for i in t]
        mn = [r6(min(p[i] for p in g["pos"])) for i in range(3)]
        mx = [r6(max(p[i] for p in g["pos"])) for i in range(3)]
        pa = add_acc(add_view(struct.pack(f"<{len(pos)}f", *pos), 34962), 5126, len(g["pos"]), "VEC3", mn, mx)
        na = add_acc(add_view(struct.pack(f"<{len(nrm)}f", *nrm), 34962), 5126, len(g["nrm"]), "VEC3")
        ia = add_acc(add_view(struct.pack(f"<{len(idx)}I", *idx), 34963), 5125, len(idx), "SCALAR")
        meshes.append({"name": fid, "primitives": [{"attributes": {"POSITION": pa, "NORMAL": na}, "indices": ia, "material": 0}]})
        f = feats.get(fid)
        extras = {"feature": fid, "op": f.op if f else "body", "line": f.line if f else 0}
        nodes.append({"name": fid, "mesh": len(meshes) - 1, "extras": extras})
    lp, li = [], []
    for poly in mesh["lines"]:
        base = len(lp)
        lp += poly
        li += [j for i in range(len(poly) - 1) for j in (base + i, base + i + 1)]
    if lp:
        flat = [c for p in lp for c in p]
        mn = [r6(min(p[i] for p in lp)) for i in range(3)]
        mx = [r6(max(p[i] for p in lp)) for i in range(3)]
        pa = add_acc(add_view(struct.pack(f"<{len(flat)}f", *flat), 34962), 5126, len(lp), "VEC3", mn, mx)
        ia = add_acc(add_view(struct.pack(f"<{len(li)}I", *li), 34963), 5125, len(li), "SCALAR")
        meshes.append({"name": "edges", "primitives": [{"attributes": {"POSITION": pa}, "indices": ia, "mode": 1, "material": 1}]})
        nodes.append({"name": "edges", "mesh": len(meshes) - 1, "extras": {"edges": True}})
    s = 0.001   # mm → m，并把 z 向上转成 glTF 的 y 向上
    root = {"name": "part", "matrix": [s, 0, 0, 0, 0, 0, -s, 0, 0, s, 0, 0, 0, 0, 0, 1],
            "children": list(range(1, len(nodes) + 1)), "extras": {"units": "mm", "up": "z"}}
    gltf = {
        "asset": {"version": "2.0", "generator": "mengos cad-v2"},
        "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [root] + nodes, "meshes": meshes, "accessors": accessors, "bufferViews": views,
        "buffers": [{"byteLength": offset}],
        "materials": [
            {"name": "body", "pbrMetallicRoughness": {"baseColorFactor": [0.82, 0.82, 0.8, 1], "metallicFactor": 0.15, "roughnessFactor": 0.55}},
            {"name": "edge", "pbrMetallicRoughness": {"baseColorFactor": [0.08, 0.08, 0.08, 1], "metallicFactor": 0, "roughnessFactor": 1}},
        ],
    }
    js = json.dumps(gltf, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode()
    js += b" " * ((-len(js)) % 4)
    binb = b"".join(bin_parts)
    total = 12 + 8 + len(js) + 8 + len(binb)
    return (struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binb), 0x004E4942) + binb)


# ---------------------------------------------------------------- STL / 3MF
def to_stl(mesh) -> bytes:
    v, t = mesh["verts"], mesh["tris"]
    out = [b"mengos cad-v2 binary STL, units mm".ljust(80, b" "), struct.pack("<I", len(t))]
    for a, b, c in t:
        pa, pb, pc = v[a], v[b], v[c]
        u = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        w = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        L = math.sqrt(sum(x * x for x in n)) or 1.0
        out.append(struct.pack("<12fH", n[0] / L, n[1] / L, n[2] / L, *pa, *pb, *pc, 0))
    return b"".join(out)


def to_3mf(mesh, name="part") -> bytes:
    v, t = mesh["verts"], mesh["tris"]
    vx = "".join(f'<vertex x="{p[0]:.6f}" y="{p[1]:.6f}" z="{p[2]:.6f}"/>' for p in v)
    tx = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in t)
    model = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources><object id="1" type="model" name="{name}"><mesh><vertices>{vx}</vertices><triangles>{tx}</triangles></mesh></object></resources>'
             '<build><item objectid="1"/></build></model>')
    ct = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, data in (("[Content_Types].xml", ct), ("_rels/.rels", rels), ("3D/3dmodel.model", model)):
            zi = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data.encode())
    return buf.getvalue()


# ---------------------------------------------------------------- STEP
def to_step(res: BuildResult) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "part.step")
        export_step(res.part, p, timestamp=FIXED_TIME)
        data = open(p, "rb").read()
    lines = data.split(b"\n")
    lines = [ln for ln in lines if not ln.startswith(b"/*")]
    return b"\n".join(lines)


# ---------------------------------------------------------------- 工程图（第一角画法：主视、俯视、左视）
def _hlr(part, origin, up, look_at):
    """正投影消隐。可见 = 棱边 + 轮廓线；隐藏同理。不画圆角的相切边（按制图习惯省略）。"""
    from OCP.BRepLib import BRepLib
    from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from build123d import Edge
    from build123d.topology.shape_core import downcast
    algo = HLRBRep_Algo()
    algo.Add(part.wrapped)
    o, la = Vector(origin), Vector(look_at)
    dirv = (o - la).normalized()
    ax = gp_Ax2()
    ax.SetAxis(gp_Ax1(gp_Pnt(o.X, o.Y, o.Z), gp_Dir(dirv.X, dirv.Y, dirv.Z)))
    ax.SetYDirection(gp_Dir(*up))
    algo.Projector(HLRAlgo_Projector(ax))
    algo.Update()
    algo.Hide()
    h = HLRBRep_HLRToShape(algo)

    def edges(*comps):
        out = []
        for c in comps:
            if c.IsNull():
                continue
            ex = TopExp_Explorer(c, TopAbs_EDGE)
            while ex.More():
                e = downcast(ex.Current())
                BRepLib.BuildCurves3d_s(e, 1e-6)
                out.append(Edge(e))
                ex.Next()
        return out
    X, Y = ax.XDirection(), ax.YDirection()

    def proj(p):
        d = (p[0] - o.X, p[1] - o.Y, p[2] - o.Z)
        return (d[0] * X.X() + d[1] * X.Y() + d[2] * X.Z(), d[0] * Y.X() + d[1] * Y.Y() + d[2] * Y.Z())
    return edges(h.VCompound(), h.OutLineVCompound()), edges(h.HCompound(), h.OutLineHCompound()), proj, (dirv.X, dirv.Y, dirv.Z)


def _bounds(edges):
    if not edges:
        return (0.0, 0.0, 0.0, 0.0)
    bbs = [e.bounding_box() for e in edges]
    return (min(b.min.X for b in bbs), min(b.min.Y for b in bbs), max(b.max.X for b in bbs), max(b.max.Y for b in bbs))


def _layout(part):
    """主视图（从前往后看）居左上；俯视图在主视图正下方；左视图在主视图正右方（GB/T 14692 第一角画法）。"""
    from build123d import Location
    bb = part.bounding_box()
    c = bb.center()
    D = bb.diagonal * 4
    spec = {
        "front": ((c.X, c.Y - D, c.Z), (0, 0, 1)),
        "top": ((c.X, c.Y, c.Z + D), (0, 1, 0)),
        "left": ((c.X - D, c.Y, c.Z), (0, 0, 1)),
    }
    views = {k: _hlr(part, o, up, (c.X, c.Y, c.Z)) for k, (o, up) in spec.items()}
    gap = max(bb.size.X, bb.size.Y, bb.size.Z) * 0.3 + 12
    b = {k: _bounds(v[0] + v[1]) for k, v in views.items()}
    fb, tb, lb = b["front"], b["top"], b["left"]
    off = {
        "front": (-fb[0], -fb[1]),
        "top": (-fb[0], -gap - tb[3]),                   # 长对正：与主视图同一 x 平移
        "left": ((fb[2] - fb[0]) + gap - lb[0], -fb[1]),  # 高平齐：与主视图同一 y 平移
    }
    holes = detect_holes(part)
    placed, frames = {}, {}
    for k, (vis, hid, proj, vdir) in views.items():
        dx, dy = off[k]
        mv = lambda es: [e.moved(Location((dx, dy, 0))) for e in es]
        cl = []
        for h in holes:
            dvec, ctr = h["dir"], h["center"]
            ext = max([h["d"]] + [h[x]["d"] for x in ("cbore", "csk") if x in h]) / 2 + 3
            par = abs(sum(dvec[i] * vdir[i] for i in range(3)))
            u, v = proj(ctr)
            if par > 0.999:                               # 孔轴朝向视线：画十字中心线
                cl += [Line((u - ext, v + dy * 0), (u + ext, v)), Line((u, v - ext), (u, v + ext))]
            elif par < 1e-3:                              # 孔轴垂直视线：画轴线
                L = h["length"] / 2 + 3
                p0 = proj([ctr[i] - dvec[i] * L for i in range(3)])
                p1 = proj([ctr[i] + dvec[i] * L for i in range(3)])
                cl.append(Line(p0, p1))
        placed[k] = (mv(vis), mv(hid), [e.moved(Location((dx, dy, 0))) for e in cl])
        bx = b[k]
        frames[k] = (bx[0] + dx, bx[1] + dy, bx[2] + dx, bx[3] + dy)
    return placed, frames


_VIEW_NAME = {"front": "主视图", "top": "俯视图", "left": "左视图"}


def _title(res: BuildResult, meta: dict | None):
    meta = meta or {}
    bb = res.part.bounding_box()
    name = meta.get("name") or "part"
    mat = res.material or "未指定材料"
    return [f"{name}    材料 {mat}    比例 1:1    单位 mm    第一角画法",
            f"外形 {bb.size.X:.2f} × {bb.size.Y:.2f} × {bb.size.Z:.2f}    plan sha256 {meta.get('plan_sha', '')[:12]}"]


def to_svg(res: BuildResult, meta=None) -> bytes:
    import re
    placed, frames = _layout(res.part)
    exp = ExportSVG(unit=Unit.MM, margin=8, line_weight=0.25, precision=4)
    exp.add_layer("visible", line_weight=0.35)
    exp.add_layer("hidden", line_weight=0.18, line_type=LineType.ISO_DASH)
    exp.add_layer("center", line_weight=0.18, line_type=LineType.ISO_DASH_DOT)
    for vis, hid, cl in placed.values():
        if vis:
            exp.add_shape(vis, layer="visible")
        if hid:
            exp.add_shape(hid, layer="hidden")
        if cl:
            exp.add_shape(cl, layer="center")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "d.svg")
        exp.write(p)
        svg = open(p, "r", encoding="utf-8").read()
    # 视图名与标题栏：模型坐标里 y 向上，SVG 外层组做了 y 翻转，文字放在翻转组之外
    m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg)
    vx, vy, vw, vh = (float(x) for x in m.groups())
    fs = max(2.5, min(6.0, vw / 60))
    texts = []
    for k, (x0, y0, x1, y1) in frames.items():
        texts.append(f'<text x="{(x0 + x1) / 2:.3f}" y="{-y1 - fs * 0.8:.3f}" font-size="{fs:.3f}" text-anchor="middle">{_VIEW_NAME[k]}</text>')
    lines = _title(res, meta)
    ty = vy + vh + fs * 1.6
    for i, t in enumerate(lines):
        texts.append(f'<text x="{vx + 2:.3f}" y="{ty + i * fs * 1.5:.3f}" font-size="{fs * 0.85:.3f}">{t}</text>')
    nh = vh + fs * 1.6 + len(lines) * fs * 1.5 + 2
    top_extra = fs * 2
    svg = svg.replace(m.group(0), f'viewBox="{vx:.3f} {vy - top_extra:.3f} {vw:.3f} {nh + top_extra:.3f}"')
    svg = re.sub(r'height="[-\d.]+mm"', f'height="{nh + top_extra:.3f}mm"', svg, count=1)
    svg = svg.replace("</svg>", '<g font-family="Noto Sans CJK SC, Source Han Sans SC, PingFang SC, Microsoft YaHei, sans-serif" fill="rgb(0,0,0)">' + "".join(texts) + "</g></svg>")
    return svg.encode("utf-8")


def to_dxf(res: BuildResult, meta=None) -> bytes:
    import ezdxf
    prev = ezdxf.options.write_fixed_meta_data_for_testing
    ezdxf.options.write_fixed_meta_data_for_testing = True     # 固定时间戳、GUID 与 ezdxf 标记，输出逐字节确定
    try:
        return _to_dxf(res, meta)
    finally:
        ezdxf.options.write_fixed_meta_data_for_testing = prev


def _to_dxf(res: BuildResult, meta=None) -> bytes:
    placed, frames = _layout(res.part)
    exp = ExportDXF(unit=Unit.MM)
    exp.add_layer("visible", line_weight=0.35)
    exp.add_layer("hidden", line_weight=0.18, line_type=LineType.ISO_DASH)
    exp.add_layer("center", line_weight=0.18, line_type=LineType.ISO_DASH_DOT)
    for vis, hid, cl in placed.values():
        if vis:
            exp.add_shape(vis, layer="visible")
        if hid:
            exp.add_shape(hid, layer="hidden")
        if cl:
            exp.add_shape(cl, layer="center")
    doc = exp._document
    msp = doc.modelspace()
    xs = [f[0] for f in frames.values()] + [f[2] for f in frames.values()]
    ys = [f[1] for f in frames.values()] + [f[3] for f in frames.values()]
    fs = max(2.5, min(6.0, (max(xs) - min(xs)) / 60))
    doc.layers.add("text")
    for k, (x0, y0, x1, y1) in frames.items():
        msp.add_text(_VIEW_NAME[k], height=fs, dxfattribs={"layer": "text"}).set_placement(((x0 + x1) / 2, y1 + fs * 0.8), align=__import__("ezdxf").enums.TextEntityAlignment.BOTTOM_CENTER)
    for i, t in enumerate(_title(res, meta)):
        msp.add_text(t, height=fs * 0.85, dxfattribs={"layer": "text", "insert": (min(xs), min(ys) - fs * 2 - i * fs * 1.5)})
    from ezdxf import zoom
    zoom.extents(msp)
    doc.header["$TDINDWG"] = 0.0
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


FORMATS = {
    "step": ("model/step", ".step"),
    "glb": ("model/gltf-binary", ".glb"),
    "stl": ("model/stl", ".stl"),
    "3mf": ("model/3mf", ".3mf"),
    "svg": ("image/svg+xml", ".svg"),
    "dxf": ("image/vnd.dxf", ".dxf"),
}


def export(res: BuildResult, fmt: str, mesh=None, meta=None) -> bytes:
    if fmt == "step":
        return to_step(res)
    if fmt == "svg":
        return to_svg(res, meta)
    if fmt == "dxf":
        return to_dxf(res, meta)
    mesh = mesh or tessellate(res)
    if fmt == "glb":
        return to_glb(res, mesh)
    if fmt == "stl":
        return to_stl(mesh)
    if fmt == "3mf":
        return to_3mf(mesh)
    raise ValueError(fmt)
