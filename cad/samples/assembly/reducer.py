"""题 B 两级展开式直齿圆柱齿轮减速器（人手写的装配计划，第 1 阶段离线验证用）。运行本文件重写 reducer.json。

一级 m=2，z1=20、z2=70（中心距 90）；二级 m=3，z3=20、z4=72（中心距 138）；总传动比 3.5×3.6=12.6（与 12.5 差 0.8%）。
三根轴沿 y，轴线在剖分面 z=0 上，x=0、90、228。
"""
import json
from pathlib import Path


def housing(top):
    """箱座（z≤0）或箱盖（z≥0）：外形 424×174×140，壁厚 12，两端凸缘各 2 个螺栓孔，三处轴承孔为半孔。"""
    z0 = 0 if top else -140
    fz = 0 if top else -12
    cz = -1 if top else -125
    return f"""
material Q235
box: box 424 174 140 at=(-57,-12,{z0})
flange: add box 484 174 12 at=(-87,-12,{fz})
cavity: cut box 400 150 126 at=(-45,0,{cz})
孔1: cut cylinder d=62 h=176 axis=y at=(0,-13,0)
孔2: cut cylinder d=72 h=176 axis=y at=(90,-13,0)
孔3: cut cylinder d=90 h=176 axis=y at=(228,-13,0)
孔b: hole d=11 at=(-72,25) from=top through
pattern 孔b linear n=2 dy=100
孔c: hole d=11 at=(382,25) from=top through
pattern 孔c linear n=2 dy=100
"""


def bearing(d, D, B):
    """简化轴承：内圈、外圈，中间一圈滚动体带（一个实体）。"""
    return f"""
material 45
let ri = {d}/2
let ro = {D}/2
let t = (ro-ri)/4
let b = {B}
ring: revolve (ri,0) (ri+t,0) (ri+t,b/4) (ro-t,b/4) (ro-t,0) (ro,0) (ro,b) (ro-t,b) (ro-t,b*3/4) (ri+t,b*3/4) (ri+t,b) (ri,b)
"""


def cap(D, hole=None):
    s = f"""
material Q235
disc: cylinder d={D + 20} h=10
"""
    if hole:
        s += f"孔: cut cylinder d={hole} h=12 at=(0,0,-1)\n"
    return s


def gear(m, z, width, bore):
    return f"""
material 45
齿: gear m={m} z={z} width={width} bore={bore}
"""


parts = {
    "箱座": housing(False),
    "箱盖": housing(True),
    "高速轴": """
material 45
杆: cylinder d=30 h=212
肩: add cylinder d=36 h=8 at=(0,0,62)
""",
    "中间轴": """
material 45
杆: cylinder d=35 h=174
肩: add cylinder d=42 h=30 at=(0,0,62)
""",
    "低速轴": """
material 45
杆: cylinder d=50 h=224
肩: add cylinder d=58 h=20 at=(0,0,72)
""",
    "齿轮1": gear(2, 20, 30, 30),
    "齿轮2": gear(2, 70, 30, 35),
    "齿轮3": gear(3, 20, 45, 35),
    "齿轮4": gear(3, 72, 45, 50),
    "轴承6206": bearing(30, 62, 16),
    "轴承6207": bearing(35, 72, 17),
    "轴承6210": bearing(50, 90, 20),
    "透盖62": cap(62, hole=32),
    "闭盖62": cap(62),
    "闭盖72": cap(72),
    "闭盖90": cap(90),
    "透盖90": cap(90, hole=52),
    "螺栓": """
material 45
杆: cylinder d=10 h=40
头: add prism (8,0) (4,6.928) (-4,6.928) (-8,0) (-4,-6.928) (4,-6.928) h=7 off=40
""",
    "螺母M10": """
material 45
体: prism (8,0) (4,6.928) (-4,6.928) (-8,0) (-4,-6.928) (4,-6.928) h=8
孔: cut cylinder d=10 h=10 at=(0,0,-1)
""",
}

layout = """
# 两级展开式直齿圆柱齿轮减速器：轴沿 y，剖分面 z=0
b:   fix 箱座
c:   put 箱盖 face=bottom to=b.top face2=left to2=b.left flush2 face3=front to3=b.front flush3
# 轴承：前后各一，外侧与壁外面齐平
k1:  put 轴承6206 coaxial=b.孔1 face=bottom to=b.box.front flush
k2:  put 轴承6206 coaxial=b.孔1 face=top to=b.box.back flush
k3:  put 轴承6207 coaxial=b.孔2 face=bottom to=b.box.front flush
k4:  put 轴承6207 coaxial=b.孔2 face=top to=b.box.back flush
k5:  put 轴承6210 coaxial=b.孔3 face=bottom to=b.box.front flush
k6:  put 轴承6210 coaxial=b.孔3 face=top to=b.box.back flush
# 轴
s1:  put 高速轴 coaxial=b.孔1 face=bottom to=b.box.front flush gap=38
s2:  put 中间轴 coaxial=b.孔2 face=bottom to=b.box.front flush
s3:  put 低速轴 coaxial=b.孔3 face=bottom to=b.box.front flush
# 齿轮：靠轴肩定位，从动轮按齿数自动对齿
g1:  put 齿轮1 coaxial=s1 face=bottom to=s1.肩.top angle=0
g2:  put 齿轮2 coaxial=s2 face=top to=s2.肩.bottom mesh=g1
g3:  put 齿轮3 coaxial=s2 face=bottom to=s2.肩.top angle=0
g4:  put 齿轮4 coaxial=s3 face=bottom to=s3.肩.top mesh=g3
# 端盖
e1:  put 透盖62 coaxial=b.孔1 face=bottom to=b.box.front
e2:  put 闭盖62 coaxial=b.孔1 face=bottom to=b.box.back
e3:  put 闭盖72 coaxial=b.孔2 face=bottom to=b.box.front
e4:  put 闭盖72 coaxial=b.孔2 face=bottom to=b.box.back
e5:  put 闭盖90 coaxial=b.孔3 face=bottom to=b.box.front
e6:  put 透盖90 coaxial=b.孔3 face=bottom to=b.box.back
# 凸缘螺栓：两端各 2 个
bt1: put 螺栓 coaxial=c.孔b face=头.bottom to=c.flange.top angle=0
pattern bt1 linear n=2 dy=100
bt3: put 螺栓 coaxial=c.孔c face=头.bottom to=c.flange.top angle=0
pattern bt3 linear n=2 dy=100
n1:  put 螺母M10 coaxial=bt1 face=top to=b.flange.bottom angle=0
pattern n1 linear n=2 dy=100
n3:  put 螺母M10 coaxial=bt3 face=top to=b.flange.bottom angle=0
pattern n3 linear n=2 dy=100
"""

if __name__ == "__main__":
    doc = {"name": "reducer", "parts": [{"id": k, "plan": v.strip() + "\n"} for k, v in parts.items()],
           "layout": layout.strip() + "\n"}
    Path(__file__).with_suffix(".json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
