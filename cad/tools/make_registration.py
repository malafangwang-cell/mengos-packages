"""生成 registration.json（只在改登记内容时运行；version 由 lock.py 写入）。"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = "cad_tool.py"   # 相对包目录（TL-25）；命令为 ⟨包环境的 python⟩ ⟨包目录⟩/cad_tool.py
PLAN_DOMAIN = (
    "plan：零件计划，一行一个操作，# 之后不读。单位 mm；x 向右、y 向后、z 向上。至多 300 行，每行至多 400 字符，至多 400 个特征，单个尺寸 0.01–10000 mm。\n"
    "行：[名字:] 操作 参数…。参数为位置参数或 键=值。值为数、表达式（+ - * / %、括号、pi、let 变量）、括号元组 (a,b,…) 或单词。"
    "名字由字母、数字、下划线组成，是特征的句柄，倒角、阵列、镜像、核对都按名字引用。\n"
    "声明：units mm；material 牌号（6061-T6、7075、Q235、45、304、316、TC4、ABS、PLA、PETG 等，用于算质量）；let 变量 = 表达式。\n"
    "实体。单独一行为加料；写在 add 后面为并上，写在 cut 后面为减去：\n"
    "· box L W H [at=(x,y,z)]，at 为最小角点；\n"
    "· cylinder d= h= [axis=x|y|z] [at=(x,y,z)]，at 为底面圆心；cone d1= [d2=0] h= [axis=] [at=]；sphere d= [at=]，at 为球心；\n"
    "· prism (u,v) (u,v) (u,v) … h= [plane=xy|xz|yz] [off=] [twist=度] [smooth]：平面轮廓拉伸。xy 的点为 (x,y)，沿 +z；"
    "xz 的点为 (x,z)，沿 +y；yz 的点为 (y,z)，沿 +x；off 为起始平面的坐标。点写成 (u,v,r) 时该顶点倒圆，半径 r。"
    "smooth 为过各点的光滑闭合曲线。twist 为拉伸过程中绕平面原点转过的角度；\n"
    "· revolve (r,z) (r,z) … [angle=360] [axis=z] [at=]：r ≥ 0 的轮廓绕轴回转，点可写 (r,z,圆角半径)，at 为轴上的原点；\n"
    "· sweep d= (x,y,z) (x,y,z) … [r=] [id=]：圆截面沿折线路径扫掠，r 为各拐角的弯曲半径，给 id（内径）为管；\n"
    "· helix d= pitch= h= wire= [axis=] [at=] [hand=right|left]：螺旋弹簧，d 为中径，wire 为线径，at 为底面中心；\n"
    "· gear m= z= width= [alpha=20] [bore=] [at=]：直齿渐开线齿轮，以 at 为中心、从 at 向 +z。\n"
    "加工，从零件的外表面向里：\n"
    "· hole d= [at=center|(u,v)] [from=top|bottom|front|back|left|right] through|depth= [cbore=(直径,深)] [csk=(直径,角度)]；\n"
    "· pocket rect w= l= [r=] [angle=] 或 pocket circle d=，加 at= from= through|depth=，矩形的 w 沿 u、l 沿 v；\n"
    "· slot w= l= [angle=] at= from= through|depth=：长圆槽，l 为总长，沿 u；\n"
    "· at 为孔、型腔、槽的中心；(u,v) 的取法：top/bottom 为 (x,y)，front/back 为 (x,z)，left/right 为 (y,z)；angle 为从 u 向 v 转的角度；"
    "入口落在沿 from 方向在 at 处碰到的第一个材料表面，depth 从入口量起。\n"
    "修饰：fillet r= [edges=]、chamfer c= [edges=]，edges 取 all、vertical、面名（top 等）或特征名；shell t= [open=top|…|none]，向内抽壳。\n"
    "复制已命名的加料或去料特征：pattern 名字 linear n= dx= [dy=] [dz=]；pattern 名字 circular n= center=(u,v) [angle=360]，绕过 center 的轴转：去料特征的轴为它的加工方向，center 的取法同 at；加料特征的轴为 z，center 为 (x,y)；"
    "pattern 名字 grid n= m= 加两个方向的间距（如 dx= dy=），共 n×m 个；mirror 名字 plane=yz|xz|xy [off=]。\n"
    "数只写数：直径写 d=25（写成 d=Φ25 也认），角度写 angle=38（写成 38° 也认），长度一律毫米（12mm 也认）；乘号 × 按 * 读，所以三个尺寸要用空格分开（box 80 50 20，不写 80×50×20）；公差不写进计划。\n"
    "不执行代码，只认上述语法；出错时按行号报错并给提示。"
)
# ---- cad.build 贡献型声明（2.5.0）----
# 只有 cad.build 声明 x-mengos-base 与 plan 的 x-mengos-merge；cad.check / cad.export 的 schema 不动。
# 行名正则恰一个捕获组、匹配包含冒号：与计划解析器认的行名一致（字母、下划线、汉字开头，后接字母数字下划线汉字与点），
# 全角冒号解析前会转成半角，这里一并认。
LINE_NAME = "^\\s*([A-Za-z_\\u4e00-\\u9fff][A-Za-z0-9_\\u4e00-\\u9fff.]*)\\s*[:：]"
BASE_DESC = ("上一版产物的回执节点 id（取输入材料中标 $best:true 的那条）；"
             "给出时只写改动的部分，引擎按标注合并")
BASE_SLOT = {"type": "string", "x-mengos-base": True, "description": BASE_DESC}
BUILD_CONVENTION = (
    "\n分多次写：给 base 时，plan 只写要新增或要改的行，与上一版的计划按行合并。"
    "带名字的行（名字: 操作 …）与上一版同名时，整行替换并留在原来的位置；名字是新的，追加在末尾。"
    "不带名字的行（material、units、let、fillet、chamfer、pattern、mirror、shell，以及注释行、空行）一律追加在末尾，不会替换已有的行；"
    "追加的 let 只对其后的行生效。"
    "每个特征行（实体、add、cut、hole、pocket、slot、fillet、chamfer、shell、pattern、mirror）都要写名字："
    "没有名字的特征行会收到 unnamed_feature 告警，以后也不能单独改它。"
    "名字后面必须有操作，不要留只有名字的空行。注释行与空行可以写，但每次追加都会留在计划里。"
    "不给 base 时 plan 照常是完整的计划。"
)
FILE_ITEM = {
    "type": "object",
    "required": ["path", "format", "role", "media_type", "bytes", "sha256"],
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string", "pattern": "^[A-Za-z0-9_\\-]+\\.(step|glb|stl|3mf|svg|dxf)$",
                 "description": "相对 workdir 的文件名"},
        "format": {"enum": ["step", "glb", "stl", "3mf", "svg", "dxf"]},
        "role": {"enum": ["model.exact", "model.view", "mesh.print", "drawing"]},
        "media_type": {"type": "string"},
        "bytes": {"type": "integer", "minimum": 1},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}
FORMATS = {"type": "array", "uniqueItems": True, "maxItems": 6,
           "items": {"enum": ["step", "glb", "stl", "3mf", "svg", "dxf"]}}
PLAN = {"type": "string", "minLength": 1, "maxLength": 20000}
NAME = {"type": "string", "pattern": "^[A-Za-z0-9_\\-]{1,64}$"}
VEC3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}
HOLE = {
    "type": "object",
    "required": ["d", "axis", "at", "center", "dir", "length", "through", "open_ends"],
    "properties": {
        "d": {"type": "number"}, "axis": {"type": ["string", "array"]}, "at": {"type": ["array", "null"]},
        "center": VEC3, "dir": VEC3, "length": {"type": "number"}, "through": {"type": "boolean"},
        "open_ends": {"type": "integer"}, "depth": {"type": "number"},
        "cbore": {"type": "object"}, "csk": {"type": "object"},
    },
}
MEASURE = {
    "type": "object",
    "required": ["bbox", "volume_mm3", "area_mm2", "center_of_mass", "solids", "faces", "edges", "valid",
                 "holes", "material", "density_g_cm3", "mass_g"],
    "properties": {
        "bbox": {"type": "object", "required": ["min", "max", "size"],
                 "properties": {"min": VEC3, "max": VEC3, "size": VEC3}},
        "volume_mm3": {"type": "number"}, "area_mm2": {"type": "number"}, "center_of_mass": VEC3,
        "solids": {"type": "integer"}, "faces": {"type": "integer"}, "edges": {"type": "integer"},
        "valid": {"type": "boolean"}, "holes": {"type": "array", "items": HOLE},
        "material": {"type": ["string", "null"]}, "density_g_cm3": {"type": ["number", "null"]},
        "mass_g": {"type": ["number", "null"]}, "watertight": {"type": "boolean"}, "triangles": {"type": "integer"},
    },
}
WARN = {"type": "array", "items": {"type": "object", "required": ["line", "message"],
                                   "properties": {"line": {"type": "integer"}, "message": {"type": "string"},
                                                  "code": {"enum": ["unnamed_feature"]}, "feature": {"type": "string"}}}}
# ---- 2.6.0 局部修改用的输出（只加字段；2.5.2 的五个字段照旧）----
FACE_DIGEST = {"type": "array", "description": "名下各面的 [曲面键, 面积 mm²]，按键排序，面积取 3 位小数",
               "items": {"type": "array", "prefixItems": [{"type": "string"}, {"type": "number"}], "minItems": 2, "maxItems": 2}}
SCOPE = {"enum": ["global", "local"], "description": "global：作用到整件（抽壳；按 all、vertical 或面名选边的圆角、倒角）；local：其余"}
WHY_NOT = {"enum": ["unnamed", "declaration", "no_faces", "comment"]}
FEATURES = {"type": "array", "items": {"type": "object",
            "required": ["id", "op", "line", "src", "faces", "selectable", "face_digest", "uncertain_faces", "refs",
                         "referenced_by", "scope"],
            "properties": {"id": {"type": "string"}, "op": {"type": "string"}, "line": {"type": "integer"},
                           "src": {"type": "string"}, "faces": {"type": "integer"},
                           "selectable": {"type": "boolean"}, "why_not": WHY_NOT, "face_digest": FACE_DIGEST,
                           "uncertain_faces": {"type": "integer", "minimum": 0,
                                               "description": "名下键里含面积的面（非平面、非圆柱面）个数：这些面的归属不确定"},
                           "refs": {"type": "array", "items": {"type": "string"},
                                    "description": "本行显式引用的特征名（edges=名、pattern 名、mirror 名）；不含隐式依赖，只是下限"},
                           "referenced_by": {"type": "array", "items": {"type": "string"},
                                             "description": "显式引用本特征的行（refs 的反向）；只是下限"},
                           "scope": SCOPE,
                           "group": {"type": "object", "required": ["kind", "source", "instances"],
                                     "properties": {"kind": {"enum": ["pattern", "mirror"]}, "source": {"type": "string"},
                                                    "instances": {"type": "integer", "minimum": 2}}}}}}
LINES = {"type": "array", "description": "全行表：计划里每一行一项",
         "items": {"type": "object", "required": ["line", "kind", "selectable"],
                   "properties": {"line": {"type": "integer"}, "name": {"type": "string"}, "op": {"type": "string"},
                                  "kind": {"enum": ["feature", "declaration", "modifier", "copy", "comment"]},
                                  "feature_id": {"type": "string"}, "selectable": {"type": "boolean"},
                                  "why_not": WHY_NOT, "scope": SCOPE}}}
PART = {"type": "object", "required": ["material", "density", "mass"],
        "properties": {"material": {"type": ["string", "null"]}, "density": {"type": ["number", "null"]},
                       "mass": {"type": ["number", "null"]}}}
FEATURE_TABLE = {"type": "object", "required": ["features", "part"],
                 "properties": {"features": {"type": "array", "items": {"type": "object", "required": ["id", "src", "face_digest"]}},
                                "part": PART}}
# ---- 局部补丁的形状（2.6.0，K8）：服务端建“改零件”的 run 时按已装版本取来，填进 GEN 的 schema ----
PATCH_LINE = "^[ \\t]*[A-Za-z_\\u4e00-\\u9fff][A-Za-z0-9_\\u4e00-\\u9fff.]*[ \\t]*[:：][ \\t]*[^\\s#][^\\n\\r]*$"
LOCAL_PATCH = {
    "tool_id": "cad.build",
    "field": "plan",
    "schema": {"type": "object", "required": ["lines"], "additionalProperties": False,
               "properties": {"lines": {"type": "array", "minItems": 1, "maxItems": 300,
                                        "items": {"type": "string", "maxLength": 400, "pattern": PATCH_LINE}}}},
    "description": (
        "只改零件计划里选中的几行。lines 里每一项是一整行计划，写成“名字: 操作 参数…”，名字后面必须有操作。"
        "名字与原计划里某一行相同 ⟹ 整行替换那一行，位置不变；名字是新的 ⟹ 追加在计划末尾。"
        "只写要改或要新增的行，不要抄没改的行，不写注释行与空行；不能删行，也不能把新行插到中间。"
        "整行要写全：替换的行里没写的参数按缺省值算，不沿用原来那一行。"
        "行的写法与零件计划相同：一行一个操作，单位 mm，x 向右、y 向后、z 向上；数只写数（d=25、angle=38）。"
    ),
}
SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
EXECUTOR = {"kind": "process", "entry": ENTRY, "mode": "sync"}
NOT_TYPES = [
    {"ops": ["generate"], "required_type": "document", "expect_selected": False},
    {"ops": ["compute"], "required_type": "number", "expect_selected": False},
    {"ops": ["retrieve"], "required_type": "data_record", "expect_selected": False},
]

units = [
    {
        "tool_id": "cad.build",
        "trust_claim": "T1",
        "effect": "none",
        "executor": EXECUTOR,
        "cost": {"latency": "简单零件约 0.3 s；齿轮、多孔阵列约 1–3 s（含 STEP、GLB、三视图）", "price": 0, "timeout": 60000},
        "description": "做出可以加工或 3D 打印的三维零件：给出外形、体积、质量、孔位等测量值，以及精确模型（STEP）、网页可看的模型（GLB）和三视图（SVG）。",
        "input_domain": PLAN_DOMAIN + " formats 缺省 [step, glb, svg]；文件写入引擎给的 workdir。",
        "input_example": {
            "plan": "material 6061-T6\nbase: box 80 50 20\nh1: hole d=20 at=center from=top through\nc1: chamfer c=0.5 edges=h1",
            "name": "plate", "formats": ["step", "glb"]},
        "signature": {
            "input_schema": {"type": "object", "required": ["plan"], "additionalProperties": False,
                             "properties": {"plan": PLAN, "name": NAME, "formats": FORMATS}},
            "output_schema": {"type": "object", "additionalProperties": False,
                              "required": ["name", "plan_sha256", "measure", "features", "warnings", "files", "lines", "part"],
                              "properties": {"name": NAME, "plan_sha256": SHA, "measure": MEASURE, "features": FEATURES,
                                             "warnings": WARN, "files": {"type": "array", "items": FILE_ITEM},
                                             "lines": LINES, "part": PART}},
        },
        "capability": {
            "ops": ["generate"], "in_types": ["cad_plan"], "out_types": ["cad_part"],
            "constraints": {"units": "mm", "exact_geometry": True, "code_execution": False, "max_plan_lines": 300,
                            "max_features": 400, "max_size_mm": 10000, "deterministic_files": True},
            "examples": [
                {"input": "做一块 80×50×20 的 6061 铝板，中间打 Φ20 通孔，孔口倒角 0.5",
                 "output": "plan 四行 → STEP + GLB；体积 73700.845 mm³，质量 199.0 g，孔 d=20 通"},
                {"input": "法兰：Φ120×12 盘，Φ60×18 凸台，Φ30 中心孔，PCD90 上 6×Φ10 螺栓孔",
                 "output": "cylinder + cylinder + hole + hole + pattern circular n=6 → 7 个孔，质量 1254 g（Q235）"},
                {"input": "外径 120、宽 40 的 V 带轮，Φ25 轴孔",
                 "output": "revolve (12.5,0) (60,0) (60,10) (48,14) (48,16) (60,20) (60,40) (12.5,40) → 回转体"},
                {"input": "Φ12 圆棒弯成的 U 形拉手，腿距 100、高 40、弯曲半径 15",
                 "output": "sweep d=12 (0,0,46) (0,0,6) (100,0,6) (100,0,46) r=15"},
                {"input": "线径 2、中径 20、螺距 6、高 48 的压缩弹簧",
                 "output": "helix d=20 pitch=6 h=48 wire=2"},
            ],
            "non_goals": ["不做装配与运动仿真", "不做有限元与强度校核", "不做自由曲面造型（放样、样条曲面）",
                          "不读入外部模型文件", "不执行代码", "不标注尺寸与公差（三视图只有图线、中心线与标题栏）"],
        },
        "selection_cases": [
            {"ops": ["generate"], "required_type": "cad_model", "expect_selected": True},
            {"ops": ["generate"], "required_type": "cad_part", "expect_selected": True},
        ] + NOT_TYPES,
    },
    {
        "tool_id": "cad.check",
        "trust_claim": "T1",
        "effect": "none",
        "executor": EXECUTOR,
        "cost": {"latency": "约 0.1–1 s（含建模）", "price": 0, "timeout": 60000},
        "description": "按期望清单逐条核对零件（外形、包络、体积、质量、质心、孔、特征、有效性、水密），每条 pass/fail/unknown，给总判定。",
        "input_domain": PLAN_DOMAIN + " expect：期望清单，一行一条，每类的写法："
                        "bbox 80 50 20 tol=0.05（外形尺寸）；fits 130 70 60（能放进这个包络，允许换方向）；"
                        "volume 73700 rtol=0.001（体积，数后可加 mm3 或 cm3）；area 21000 rtol=0.01（表面积，数后可加 mm2 或 cm2）；"
                        "mass 199 g rtol=0.01（质量，单位 g 或 kg；计划没写 material 时判 unknown）；"
                        "mass max=350 g（只给上限或下限，用 max= 或 min=，volume、area 同）；"
                        "com (40,25,10) tol=0.1（质心）；solids 1（实体个数）；valid（模型有效）；watertight（网格水密）；"
                        "holes 7（孔的总数）；holes 6 d=10（直径 10 的孔有 6 个，还可加 axis=z）；"
                        "hole d=10 axis=z at=(45,0) through（有这样一个孔；通孔写 through，盲孔写 blind，还可加 depth= cbore=(直径,深) csk=(直径,角度)）；"
                        "feature boss（计划里有名叫 boss 的特征，且它在零件上还有面）。",
        "input_example": {
            "plan": "material 6061-T6\nbase: box 80 50 20\nh1: hole d=20 at=center from=top through",
            "expect": "bbox 80 50 20\nholes 1 d=20\nhole d=20 axis=z at=(40,25) through\nmass 200 g rtol=0.01\nvalid"},
        "signature": {
            "input_schema": {"type": "object", "required": ["plan", "expect"], "additionalProperties": False,
                             "properties": {"plan": PLAN, "expect": {"type": "string", "minLength": 1, "maxLength": 20000}}},
            "output_schema": {"type": "object", "additionalProperties": False,
                              "required": ["verdict", "covered", "checks", "plan_sha256"],
                              "properties": {
                                  "verdict": {"enum": ["pass", "fail", "unknown"]},
                                  "covered": {"type": "boolean", "description": "verdict 为 unknown 时为 false（TL-22 覆盖范围外）"},
                                  "plan_sha256": SHA,
                                  "checks": {"type": "array", "items": {
                                      "type": "object", "required": ["line", "src", "kind", "verdict"],
                                      "properties": {"line": {"type": "integer"}, "src": {"type": "string"},
                                                     "kind": {"type": "string"},
                                                     "verdict": {"enum": ["pass", "fail", "unknown"]},
                                                     "expected": {}, "actual": {}, "tol": {}, "reason": {"type": "string"},
                                                     "note": {"type": "string"}}}}}},
        },
        "capability": {
            "ops": ["check"], "in_types": ["cad_plan", "cad_spec"], "out_types": ["verdict"],
            "constraints": {"three_valued": True, "max_checks": 200, "default_tol_mm": 0.01, "default_rtol": 0.001,
                            "kinds": ["bbox", "fits", "volume", "area", "mass", "com", "solids", "valid", "watertight",
                                      "holes", "hole", "feature"]},
            "examples": [
                {"input": "核对这块板是不是 80×50×20、中间有一个 Φ20 通孔",
                 "output": "expect: bbox 80 50 20 / hole d=20 through → pass"},
                {"input": "法兰的螺栓孔应当是 8 个",
                 "output": "expect: holes 8 d=10 → fail（实际 6）"},
                {"input": "这个零件能不能放进 220×220×250 的打印机",
                 "output": "expect: fits 220 220 250 → pass"},
                {"input": "支架质量不超过 0.35 kg（计划没写材料）",
                 "output": "expect: mass 350 g → unknown（缺材料，covered=false）"},
            ],
            "non_goals": ["不核对壁厚、拔模角、可加工性", "不核对公差配合", "不改计划，只报告"],
        },
        "review_coverage": {"by_predicate": ["cad_model_meets_spec"]},
        "selection_cases": [
            {"ops": ["check"], "required_type": "verdict", "expect_selected": True},
        ] + NOT_TYPES,
    },
    {
        "tool_id": "cad.export",
        "trust_claim": "T1",
        "effect": "none",
        "executor": EXECUTOR,
        "cost": {"latency": "约 0.1–2 s，视格式与零件复杂度", "price": 0, "timeout": 60000},
        "description": "把零件交成需要的文件：给加工厂的精确模型（STEP）、3D 打印用的网格（STL、3MF）、网页查看用的模型（GLB）、三视图图纸（SVG、DXF，第一角画法）。",
        "input_domain": PLAN_DOMAIN + " object：要导出的三维模型（cad_model）；也可以直接给建模计划 plan，二选一。"
                        " formats：step、glb、stl、3mf、svg、dxf 中的一个或多个；也可写单个 format。文件写入引擎给的 workdir。",
        "input_example": {"plan": "base: box 80 50 20\nh1: hole d=20 at=center from=top through",
                          "name": "plate", "formats": ["stl", "dxf"]},
        "signature": {
            "input_schema": {"type": "object", "additionalProperties": False,
                             "oneOf": [{"required": ["plan"]}, {"required": ["object"]}],
                             "properties": {"plan": PLAN, "object": {"type": "object"}, "name": NAME,
                                            "formats": dict(FORMATS, minItems=1),
                                            "format": {"enum": ["step", "glb", "stl", "3mf", "svg", "dxf"]}}},
            "output_schema": {"type": "object", "additionalProperties": False,
                              "required": ["name", "plan_sha256", "files"],
                              "properties": {"name": NAME, "plan_sha256": SHA,
                                             "files": {"type": "array", "items": FILE_ITEM}}},
        },
        "capability": {
            "ops": ["convert"], "in_types": [], "in_any": ["cad_plan", "cad_model", "cad_part"], "out_types": ["cad_file"],
            "constraints": {"formats": ["step", "glb", "stl", "3mf", "svg", "dxf"], "deterministic_files": True,
                            "drawing_projection": "first_angle", "max_file_mb": 64},
            "examples": [
                {"input": "把支架导出成 STL 给 3D 打印", "output": "formats [stl] → bracket.stl"},
                {"input": "给加工厂发 STEP 和 DXF 三视图", "output": "formats [step, dxf]"},
                {"input": "要一个能在网页里转着看的模型", "output": "formats [glb]"},
            ],
            "non_goals": ["不导出 DWG、IGES、Parasolid", "不做格式间的反向转换（不读入文件）"],
        },
        "selection_cases": [
            {"ops": ["convert"], "required_type": "cad_file", "expect_selected": True},
        ] + NOT_TYPES,
    },
    {
        "tool_id": "cad.compare",
        "trust_claim": "T1",
        "effect": "none",
        "executor": EXECUTOR,
        "cost": {"latency": "约 0.05 s，不建模", "price": 0, "timeout": 60000},
        "description": "比较同一零件改前、改后的两份特征表，说出哪些特征的计划行改了、哪些跟着变了、哪些只是被邻居切大切小，"
                       "零件的材料、密度、质量有没有变，以及改了的行逐个参数的前后值。不建模，只读特征表。",
        "input_domain": "old、new：改前、改后的特征表，即两次建模各自的产出（含 features 与 part），特征按名字对应。",
        "input_example": {
            "old": {"features": [{"id": "boss", "src": "boss: cylinder d=60 h=18 at=(0,0,12)",
                                  "face_digest": [["C|0.0|0.0|1.0|0.0|0.0|0.0|30.0", 3392.92]]}],
                    "part": {"material": "Q235", "density": 7.85, "mass": 1254.0}},
            "new": {"features": [{"id": "boss", "src": "boss: cylinder d=70 h=18 at=(0,0,12)",
                                  "face_digest": [["C|0.0|0.0|1.0|0.0|0.0|0.0|35.0", 3958.41]]}],
                    "part": {"material": "Q235", "density": 7.85, "mass": 1395.0}}},
        "signature": {
            "input_schema": {"type": "object", "required": ["old", "new"], "additionalProperties": False,
                             "properties": {"old": FEATURE_TABLE, "new": FEATURE_TABLE}},
            "output_schema": {"type": "object", "additionalProperties": False,
                              "required": ["changed", "followed", "trimmed", "added", "removed", "part_changed", "param_diffs"],
                              "properties": {
                                  "changed": {"type": "array", "items": {"type": "string"},
                                              "description": "计划行变了的特征（只看代码部分，注释与空白不算）"},
                                  "followed": {"type": "array", "items": {"type": "string"},
                                               "description": "计划行没变、名下曲面变了的特征（跟着变）"},
                                  "trimmed": {"type": "array", "items": {"type": "string"},
                                              "description": "计划行没变、曲面没变、只有面积变了的特征（被邻居切大切小）"},
                                  "added": {"type": "array", "items": {"type": "string"}},
                                  "removed": {"type": "array", "items": {"type": "string"}},
                                  "part_changed": {"type": "array", "items": {"enum": ["material", "density", "mass"]},
                                                   "description": "变了的零件级属性。质量随几何变化是常事，只在密度变了或有无质量变了时列出"},
                                  "param_diffs": {"type": "array", "items": {
                                      "type": "object", "required": ["name", "param", "before", "after"],
                                      "properties": {"name": {"type": "string"}, "param": {"type": "string"},
                                                     "before": {"type": ["string", "null"]}, "after": {"type": ["string", "null"]}}},
                                      "description": "改了的行逐个参数的前后值，原样取自计划行（如 d 60→70）；位置参数记为 arg1、arg2…"}}},
        },
        "capability": {
            "ops": ["check"], "in_types": ["cad_feature_table"], "out_types": ["cad_diff"],
            "constraints": {"geometry": False, "rebuild": False, "match_by": "feature_name"},
            "examples": [
                {"input": "法兰凸台直径 60 改 70 前后的两份特征表",
                 "output": "changed [boss]，followed [fl]，trimmed [plate]，param_diffs boss d 60→70"},
                {"input": "螺栓孔 b1 直径 10 改 12 前后的两份特征表",
                 "output": "changed [b1]，followed [ring]（阵列跟着源孔走），trimmed [plate]"},
                {"input": "材料 Q235 改 7075 前后的两份特征表",
                 "output": "changed []，part_changed [material, density, mass]"},
            ],
            "non_goals": ["不建模、不读几何文件", "不判断改动是否越出选区，只报事实", "不比较两个不同零件"],
        },
        "selection_cases": [
            {"ops": ["check"], "required_type": "cad_diff", "expect_selected": True},
        ] + NOT_TYPES,
    },
]

# ---- 收成严格的 TL-6 形状（检查点 E 之后，2026-10-02 晚）----
# · 一句话用途写进 input_schema.description；入参写法写进各属性的 description；
# · cost 全为数值：latency、timeout 单位毫秒，price 为每次调用的平台计价单位；人读的说明进 constraints.latency_note；
# · 选择金样是认证材料（TL-12 ⑥），单独写 selection_cases.json，每件应选与不应选各 3 条。
LATENCY = {"cad.build": (1500, "简单零件约 0.3 s；齿轮、多孔阵列约 1–3 s；扫掠、螺旋约 3–15 s（含 STEP、GLB、三视图）"),
           "cad.check": (800, "约 0.1–1 s（含建模）"),
           "cad.export": (2000, "约 0.1–2 s，视格式与零件复杂度"),
           "cad.compare": (50, "约 0.05 s，不建模")}
SELECTION = {
    "cad.build": [("画一个 80×50×20 的铝底座，中间打 Φ20 通孔", ["generate"], "cad_model", True),
                  ("做一个 m=2、z=30 的直齿轮模型", ["generate"], "cad_part", True),
                  ("设计一个能 3D 打印的 L 形支架", ["generate"], "cad_model", True),
                  ("写一份项目周报", ["generate"], "document", False),
                  ("求 2^10 + 3^5 的精确值", ["compute"], "number", False),
                  ("核对这个零件外形是不是 80×50×20", ["check"], "verdict", False)],
    "cad.check": [("核对这个零件外形是不是 80×50×20", ["check"], "verdict", True),
                  ("检查法兰的螺栓孔是不是 6 个 Φ10", ["check"], "verdict", True),
                  ("这个零件能不能放进 220×220×250 的打印机", ["check"], "verdict", True),
                  ("画一个带孔的铝底座", ["generate"], "cad_model", False),
                  ("把支架导出成 STL", ["convert"], "cad_file", False),
                  ("写一份项目周报", ["generate"], "document", False)],
    "cad.export": [("把支架导出成 STL 给 3D 打印", ["convert"], "cad_file", True),
                   ("给加工厂发 STEP 和 DXF 三视图", ["convert"], "cad_file", True),
                   ("要一个能在网页里转着看的 GLB", ["convert"], "cad_file", True),
                   ("画一个带孔的铝底座", ["generate"], "cad_model", False),
                   ("核对零件外形", ["check"], "verdict", False),
                   ("求 2^10 的值", ["compute"], "number", False)],
    "cad.compare": [("比较零件改前改后的两份特征表，哪些特征跟着变了", ["check"], "cad_diff", True),
                    ("凸台直径改了以后，列出被牵连的特征", ["check"], "cad_diff", True),
                    ("改了材料以后，零件的材料、密度、质量哪些变了", ["check"], "cad_diff", True),
                    ("核对这个零件外形是不是 80×50×20", ["check"], "verdict", False),
                    ("画一个带孔的铝底座", ["generate"], "cad_model", False),
                    ("把支架导出成 STL", ["convert"], "cad_file", False)],
}
selection_out = []
for u in units:
    tid = u["tool_id"]
    lat, note = LATENCY[tid]
    u["cost"] = {"latency": lat, "price": 0, "timeout": u["cost"]["timeout"]}
    u["capability"]["constraints"]["latency_note"] = note
    if tid == "cad.build":
        u["capability"]["constraints"]["max_line_chars"] = 400   # 2.4.1（17 TL-16b 正面约束）
    sch = u["signature"]["input_schema"]
    sch["description"] = u.pop("description")
    dom = u.pop("input_domain")
    if "plan" not in sch["properties"]:          # cad.compare（2.6.0）：不读计划，入参说明写在 old、new 上
        for k in ("old", "new"):
            sch["properties"][k] = dict(sch["properties"][k], description=dom)
        u.pop("selection_cases", None)
        for task, ops, typ, exp in SELECTION[tid]:
            selection_out.append({"tool_id": tid, "task": task, "ops": ops, "required_type": typ, "expect_selected": exp})
        continue
    sch["properties"]["plan"] = dict(sch["properties"]["plan"], description=PLAN_DOMAIN)
    if tid == "cad.build":
        sch["properties"]["plan"]["description"] = PLAN_DOMAIN + BUILD_CONVENTION
        sch["properties"]["plan"]["x-mengos-merge"] = {"mode": "named-lines", "name": LINE_NAME}
        sch["properties"] = {"base": BASE_SLOT, **sch["properties"]}
        sch.pop("required")
        sch["if"] = {"required": ["base"]}
        sch["then"] = {"required": ["base"]}
        sch["else"] = {"required": ["plan"]}
    rest = dom[len(PLAN_DOMAIN):].strip()
    if "expect" in sch["properties"]:
        sch["properties"]["expect"] = dict(sch["properties"]["expect"], description=rest)
    if "object" in sch["properties"]:
        obj_desc, rest = rest.split(" formats：", 1)
        rest = "formats：" + rest
        sch["properties"]["object"] = dict(sch["properties"]["object"], description=obj_desc)
    if "formats" in sch["properties"]:
        sch["properties"]["formats"] = dict(sch["properties"]["formats"], description=rest)
    u.pop("selection_cases", None)
    for task, ops, typ, exp in SELECTION[tid]:
        selection_out.append({"tool_id": tid, "task": task, "ops": ops, "required_type": typ, "expect_selected": exp})
(ROOT / "selection_cases.json").write_text(json.dumps(selection_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

reg = {
    "family": "cad",
    "family_version": "2.6.0",
    "lock_hash": "",
    "note": "字段严格按 kernel-spec 17 章 TL-6；族名在顶层 family，由引擎下发到各件。cost 的 latency 与 timeout 单位为毫秒，price 为每次调用的平台计价单位。"
            "入参写法写在 signature.input_schema 的 description 里；选择金样（TL-12 ⑥）是认证材料，在 selection_cases.json。"
            "类型由本包的 mengos-package.json 声明、经安装器入册（TL-25），引擎不含这些名字；verdict 为平台类型。文件产出按 TL-9a。"
            "本包按安装包交付，仓库现行结构如需额外字段，报工具侧补入，施工方不改包内文件。",
    "units": units,
    "local_patch": LOCAL_PATCH,
}
(ROOT / "registration.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("ok")
