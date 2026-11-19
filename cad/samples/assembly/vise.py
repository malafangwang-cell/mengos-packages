"""题 A 平口虎钳：钳口宽 100、最大开口 80（人手写的装配计划，第 1 阶段离线验证用）。运行本文件重写 vise.json。"""
import json
from pathlib import Path

parts = {
"固定钳身": """
material Q235
base: box 260 100 25 at=(0,-50,0)
jaw: add box 30 100 50 at=(230,-50,25)
end: add box 15 60 40 at=(0,-30,25)
孔: cut cylinder d=18 h=17 axis=x at=(-1,0,45)
t1: hole d=6 at=(-25,55) from=right depth=30
t2: hole d=6 at=(25,55) from=right depth=30
""",
"钳口板": """
material 45
plate: box 10 100 40 at=(0,-50,0)
m1: hole d=6.6 at=(-25,20) from=left through csk=(13,90)
m2: hole d=6.6 at=(25,20) from=left through csk=(13,90)
""",
"螺钉": """
material 45
shank: cylinder d=6 h=22
head: add cone d1=6 d2=12 h=3 at=(0,0,22)
""",
"活动钳身": """
material Q235
body: box 60 100 50 at=(0,-50,25)
孔: cut cylinder d=30 h=62 axis=x at=(-1,0,45)
t1: hole d=6 at=(-25,55) from=right depth=20
t2: hole d=6 at=(25,55) from=right depth=20
""",
"螺母": """
material H62
body: cylinder d=30 h=60
孔: cut cylinder d=18 h=62 at=(0,0,-1)
""",
"丝杠": """
material 45
杆: cylinder d=18 h=120
肩: add cylinder d=28 h=8 at=(0,0,-8)
头: add cylinder d=18 h=30 at=(0,0,-38)
横孔: cut cylinder d=10 h=20 axis=y at=(0,-10,-23)
""",
"手柄": """
material Q235
杆: cylinder d=10 h=140 axis=y at=(0,-70,0)
球1: add sphere d=16 at=(0,-70,0)
球2: add sphere d=16 at=(0,70,0)
""",
"挡圈": """
material 45
环: cylinder d=28 h=5
孔: cut cylinder d=18 h=7 at=(0,0,-1)
""",
}

layout = """
# 平口虎钳：x 沿丝杠，钳口开到最大 80
b:   fix 固定钳身
p1:  put 钳口板 face=right to=b.jaw.left face2=bottom to2=b.base.top gap2=10 face3=front to3=b.front flush3
sc1: put 螺钉 coaxial=p1.m1 face=top to=p1.left flush gap=-0.5
pattern sc1 linear n=2 dy=50
m:   put 活动钳身 coaxial=b.孔 face=right to=p1.left gap=90 angle=0
p2:  put 钳口板 face=right to=m.right face2=bottom to2=b.base.top gap2=10 face3=back to3=m.front flush3
sc3: put 螺钉 coaxial=p2.m1 face=top to=p2.left flush gap=-0.5
pattern sc3 linear n=2 dy=-50
n:   put 螺母 coaxial=m.孔 face=bottom to=m.left flush
s:   put 丝杠 coaxial=b.孔 face=肩.top to=b.left angle=0
h:   put 手柄 at=(-23,0,45)
r:   put 挡圈 coaxial=s face=bottom to=b.end.right
"""

if __name__ == "__main__":
    doc = {"name": "vise", "parts": [{"id": k, "plan": v.strip() + "\n"} for k, v in parts.items()],
           "layout": layout.strip() + "\n"}
    (Path(__file__).with_suffix(".json")).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
