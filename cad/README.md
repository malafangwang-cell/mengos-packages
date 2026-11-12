# cad v2（W3 的 CAD 工具包）

> 2.6.0（mengosv2《执行令-局部追问-cad包补强-2026-11-12》K1–K14；设计《局部追问 r9.2》§五 C1–C9；终审 M7；交互定稿 #728）：给“只改零件里的一处”补包内的东西。**只放宽**：只加输出字段、告警与一件新工具；2.5.2 已有的输出字段逐字节不变，35 条金样一字未动、全过（`tests/test_local_edit.py` 拿 2.5.2 的实跑输出逐样件比对：STEP、STL、3MF、SVG、DXF 的 sha256 不变，GLB 去掉新加的 `extras.faces` 后逐字节相同）。
> - **K1 行行有名**：cad.build 对无名的特征行（实体、加工、圆角、倒角、抽壳、阵列、镜像）出告警 `{line, code: "unnamed_feature", feature: "chamfer#1", message}`，排在原有告警之后；plan 的说明由“想以后还能改的特征都写上名字”改为要求。只告警，不拒收（拒收留到大版本）。
> - **K2、K11 全行表**：输出加 `lines`，计划里每一行一项 `{line, name?, op?, kind: feature|declaration|modifier|copy|comment, feature_id?, selectable, why_not?, scope?}`；`let`、`material`、`units`（具名也一样）为 declaration、不可选；每个特征行恰好对应一个特征 id。特征表每项加 `selectable` 与 `why_not`（`unnamed`；0 面特征仍可选，`faces = 0`）。另加 `part: {material, density, mass}`。
> - **K3 阵列与镜像分组**：pattern、mirror 行加 `group: {kind, source, instances}`（instances 含源特征）；GLB 里复制出来的面带实例号（源特征本身是实例 0，面归源特征那一行）。
> - **K4 面摘要**：特征表每项加 `face_digest`：名下各面的 `[曲面键, 面积]`，按键排序，面积 3 位小数；曲面键沿用 `builder.surface_key`，文字形式见 `builder.face_key_text`。
> - **K5、K11、K14 新工具 `cad.compare`**：两份特征表（`old`、`new`）→ `{changed, followed, trimmed, added, removed, part_changed, param_diffs}`。计划行（只看代码部分，注释与空白不算）变了算 changed，行没变、曲面键集合变了算 followed，只有面积变了算 trimmed；`part_changed` 报材料、密度，质量只在密度变了或有无质量变了时列出（几何变化带来的质量变化不算）；`param_diffs` 逐个参数给前后值，原样取自计划行（如 `{name: boss, param: d, before: "60", after: "70"}`，位置参数记 arg1、arg2…）。不建模、不读几何；旧表缺 `face_digest` 或 `part` 时回 BAD_INPUT，提示先用当前版本重建一次。登记动词 check、入参类型 `cad_feature_table`、产物类型 `cad_diff`（新声明的两个值类型），不声明 review_coverage；`cad_diff` 没有别的工具产出、普通任务也不要它，所以不进普通 run 的选择管线。
> - **K6、K12 依赖与作用范围**：特征表每项加 `refs`（`edges=名`、`pattern 名`、`mirror 名`）与反向 `referenced_by`，只是下限；加 `scope`：shell 与按 all、vertical、面名选边（含缺省 all）的圆角、倒角为 global，其余 local。
> - **K7、K13 面一级**：特征表每项加 `uncertain_faces`（键里含面积的面，即非平面、非圆柱面）；GLB 每个特征节点的 `extras.faces` 列出名下各面 `{tris: [起, 数], face_key, uncertain?, instance?}`，渲染器据此带出点中的面。
> - **K8 局部补丁形状**：registration.json 顶层加 `local_patch {tool_id: cad.build, field: plan, schema, description}`，schema 为 `{lines: string[]}`，每行必须是“名字: 操作 …”；随登记进 lock，换包版本即换形状。
> - **K9 按行合并的金样**：`tests/fixtures/local/merge_goldens.json`，底稿 + 补丁行经 `contribution_ref.merge` 合并后与手写完整计划逐字节相同，建模输出也逐字节相同；覆盖原位替换、末尾追加、全角冒号、中文名、带点的名字。合并本身未改。
> - **K10 渲染器**（锁外）：两步选中、计划面板 Shift 加选至多 3 行、不可选行灰显与 `mengos.select_denied`、处理中颜色呼吸（`mengos.busy`）、修改记录按步分色（`mengos.marks`）、三维少文字，见 §7。
> - 金样追加 16 条（K1、K2、K3、K6、K7、K12 的建模金样与 cad.compare 的 7 条：调研 §3.1 法兰五例、旧表缺摘要、改材料），共 51 条。cad_dsl.py、checker.py、pyproject.toml、uv.lock 未改；不引新依赖。lock 与 content_hash 见 PR。

> 2.5.2（mengosv2 立法者 2026-11-09 批准；依据 `实验-工具描述规范-2026-11-09` TD-23）：只改 cad.check 的 `expect` 参数说明——原说明只举了 6 类期望的写法，模型会自造 `centroid` 之类执行器不认的写法；现在 12 类（bbox、fits、volume、area、mass、com、solids、valid、watertight、holes、hole、feature）各给一个可照抄的样例，样例逐条用 `checker.run_checks` 离线解析过（见 PR 描述）。执行逻辑与其它工具的说明未改。说明文字在 registration.json（由 `tools/make_registration.py` 生成），registration 在 `tools_lock.covers` 内，所以 lock 从 `2a4efb009363fc73` 变为 `7ac22328b400cf72`（cad.build、cad.check、cad.export 三件同一个值，随族走），须重新认证；content_hash 随之变化。

> 2.5.1（mengosv2 执行令-2026-11-05-PLAN声明书与F环清单交互 支 T）：包清单加显示名 `title`「三维零件建模」与 `tool_titles`（`cad.build`「建三维零件模型」、`cad.check`「核对零件尺寸与特征」、`cad.export`「导出零件加工与图纸文件」）。两字段只供界面显示（声明书、商店），不进工具选择，也不进给模型看的任何文字；不在 `tools_lock.covers` 内，lock 不变（工具版本与认证继承），只有 content_hash 变。工具代码与 registration.json 未改（其中 `family_version` 仍写 2.5.0）。

> 2.5.0（产出规则 支 B，第二单；17 TL-30a v0.2.62，设计 `产出不受模型输出长度限制` r8 §五）：cad.build 接入贡献型声明，让零件计划可以分多次写、由引擎按行合并，不再要求模型一次输出整份计划。**只放宽、不收紧**，所以升小版本；只改登记（input_schema 与说明），**工具代码未改**：
> - cad.build 顶层加 base 槽（`x-mengos-base`）；`plan` 标 `x-mengos-merge`，mode 为 named-lines，行名正则 `^\s*([A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff.]*)\s*[:：]`（恰一个捕获组，与计划解析器认的行名一致，全角冒号也认）。cad.check、cad.export 的 schema 不动。
> - 必填放宽：`if {required:[base]} then {required:[base]} else {required:[plan]}`。不带 base 时与 2.4.4 的校验口径逐键相同（`tests/test_contribution.py` 比对 2.4.4 schema 的 sha256），带 base 时 plan 只写改动的行。
> - **分次写的约定**（写进 plan 的说明，也是引擎合并语义的结果）：带名字的行与上一版同名 ⟹ 整行替换、留在原位；新名字 ⟹ 追加在末尾；不带名字的行（material、units、let、fillet、chamfer、pattern、mirror、shell，以及注释行、空行）一律追加在末尾，不替换已有的行；追加的 let 只对其后的行生效。想以后还能改的特征都写上名字。
> - **空行名与注释的读数**（实跑，`tests/test_contribution.py`）：`# 注释` 行、行尾注释、空行、全角冒号的行名，cad.build 都接受；**只有名字、没有操作的行（如 `h1:`）被拒**（BAD_INPUT「缺少操作名」，报行号）；同名两行被拒（「名字已经用过」，所以合并才按名字替换）；重复的 material、let 无害。因此 cad 的约定是不留空行名：cad 没有"空槽中间版本"，合并与运行不受影响，只是引擎没有空槽可以定向。
> - 包内预检加三项：标注合法（行名正则恰一个捕获组）、base 槽唯一、引擎合并金样（`tests/fixtures/contribution/`，引擎自己的夹具逐字节拷贝，其中含 named-lines 相关条目；来源 commit 与 sha256 见其 `SOURCE.json`）；另核行名正则与计划解析器在全部样例与金样的每一行上读法一致。合并代数的 Python 参照实现 `tests/contribution_ref.py` 与 document 包同名文件逐字节相同。变异读数见 `tests/MUTANTS.md`。
> - 版本：lock `2a4efb009363fc73`，须重新认证。既有 35 条金样与确定性测试逐项照旧通过。

> 2.4.4（W-11，17 TL-16c v0.2.32）：cad.export 的输入类型改为“或”：`in_types: []`、`in_any: [cad_plan, cad_model, cad_part]`——它要的是建模计划或三维模型二选一（input_schema 无 required）。按旧形状这三个类型会被 PLAN 的路径搜索读成“全都要”，导出就走不通。cad.check 的 `[cad_plan, cad_spec]` 两个都必填，不变。工具代码未改；registration 改了，lock 变（d4d06bdf0e22b172），须重新认证。本容器无 cadquery，执行类测试未跑；登记与包自检 12 项过。

> 2.4.0（检查点 P 后）：计划里的工程记号按规范读——数前的直径记号 Φ φ Ø ø ⌀、数后的 ° 与 mm 都去掉再解析（只在代码部分，注释照旧）；无法识别的 ±、Φ、° 等给出提示；给模型看的语法说明加一句“数只写数”。起因是检查点 P 的真模读数：五件里四件卡在 Φ、° 上。解析器改了，工具版本（lock hash）随之变化，须重新认证。金样加两条（35 条）。
>
> 2.3.1（检查点 O 后，只改包、不改工具版本）：① 加金样运行入口 `tools/run_golden.py`（WP-W6 §2；经进程入口与信封调工具，certify 的 ③ 不再 SKIPPED）；② 渲染器按渲染器契约 v0.1 改写为正式渲染器（数据经 postMessage 由宿主传入，不取网络数据；三维库从 CDN 按需加载，失败不影响其他面板）。lock hash 仍为 57b5fde1468f0266，认证按工具版本，不受影响（TL-25）。
>

> 状态：**安装包 2.4.3**。相对 2.4.2：给模型看的文字不再出现工具名（工具开发者指南修订草案：说明里点名别的工具，选择模型会被带去调那件）——cad.export 的 object 说明改为“要导出的三维模型（cad_model）；也可以直接给建模计划 plan，二选一”，导出入参的四条报错同改；plan 的上限句（行数、行长、特征数、尺寸）由 cad.build 扩到 cad.check、cad.export 的 plan 说明（三件读同一种计划）；`tools/make_registration.py` 补齐 2.4.1、2.4.2 的手改，重新生成即得本版登记。registration 与 cad_tool.py 改了，lock 变（f44a8c04988e9da0），须重新认证。本容器连不上 PyPI，全量测试未跑（施工方按测试命令跑）；登记、选择金样、覆盖检查已过。
>
> 2.4.2 相对 2.4.1：cad.export 的输入类型加 cad_model（派生下载按交付类型 cad_model 查导出工具，W-6 T3 读数 404）。registration 改了，lock 变，须重新认证。2.4.1 相对 2.4.0：给模型看的 plan 说明补上行数、行长、特征数与尺寸上限（17 TL-16b 正面约束）；constraints 加 max_line_chars；渲染器认 `chrome:"host"`（渲染器契约 v0.1）。registration 改了，lock 变，须重新认证。2.4.0 的说明：**已自测**（84 项通过）。2.3.0 的说明：相对 2.2.1：① 完整计划语法写进给模型看的登记资产（检查点 L 裁决 §2.2，立法者 2026-10-08 11:46）；② 新增 revolve、sweep、helix 三种实体，prism 支持顶点圆角 (u,v,r)、smooth 光滑轮廓与 twist 扭转，pattern 新增 grid，新增 mirror；③ cad.export 可接 cad.build 的产出记录（object），输入类型加 cad_part；④ 表达式里的 `a-b` 按减法读（名字里不再允许连字符）。工具版本（lock hash）随之变化，须重新人签。覆盖面实测见 `实验/exp-cad-coverage/REPORT.md`。2.2.1 的状态说明：2.2.0 已在检查点 G 前装入；2.2.1 修包侧三处。
> 依据：kernel-spec 17 章（TL-6 登记资产、TL-8 执行器、TL-10 引擎与执行体分工、TL-12 认证自检、TL-16 至 TL-22 能力声明与审核工具）；WP-W0 拟定条款 TL-9a（工具产出文件，见 §6）；WP-W6 拟定条款 TL-25 至 TL-27（安装单位、两级审批、形态与类型的绑定）。
> 产出物渲染原型：claude.ai 上的"CAD 产出物台"页面，数据全部由本包实际生成。

## 1 选型

| 方案 | 结论 | 理由 |
|---|---|---|
| build123d 0.13（OCCT 8.0，pip 安装） | **采用** | 与 FreeCAD 用同一个 OpenCASCADE 内核，B-rep 精确；pip 安装、无界面运行，不需要部署整套 FreeCAD（旧 T4 冒烟就卡在本机没有 FreeCAD）；API 清楚，导出 STEP、SVG、DXF 齐全 |
| FreeCAD（现行） | 替换 | 部署重；无头运行麻烦；导出的确定性难控 |
| CadQuery | 备选 | 能力与 build123d 相当，同一内核；build123d 的拓扑选择与导出接口更顺手 |
| 让模型直接写 build123d / CadQuery 代码 | 否决 | 公开基准上，前沿模型直接写 CAD 代码的成功率仍然很低；而且执行任意代码要沙箱，违背 T1"同输入同输出、无副作用"。与 calc v2 的教训相同：让模型写它写得稳的形式，执行保持确定 |

**做法**：模型写一份行式的**零件计划**（§3）。工具只认白名单语法、不执行代码，按计划逐行建精确实体，再测量、核对、导出。

## 2 四件工具

一个执行体，三件工具。全部申报 T1，effect = none，执行器为 process。信任类由立法者签字决定，申报不生效（TL-13）。

| 工具 | 动词 | 输入 → 产物类型 | 用途 |
|---|---|---|---|
| `cad.build` | generate | cad_plan → cad_part | 计划 → 精确实体。返回测量值、特征表、警告，以及文件（缺省 STEP + GLB + SVG） |
| `cad.check` | check | cad_plan + cad_spec → verdict | 按期望清单逐条判 pass / fail / unknown，给总判定。审核工具，`review_coverage.by_predicate = cad_model_meets_spec` |
| `cad.export` | convert | cad_plan → cad_file | 导出指定格式 |
| `cad.compare` | check | cad_feature_table → cad_diff | 比较改前、改后两份特征表（2.6.0）。不建模；供局部修改的服务端在 run 外调用 |

原先设想的 `cad.measure` 并进了 `cad.build`：build 总是返回测量值；`formats: []` 时就是只测量、不出文件。

**类型**（声明在 `mengos-package.json`，经安装器入册；引擎不含这些名字）：

| 类型 | 上位 | 种类 | 说明 |
|---|---|---|---|
| `cad_model` | — | 交付物 | 三维几何实体模型。`realizes: [assembly_model]`，即实现码本的这个形态（TL-27 拟定）。渲染器：完整视图是产出台，嵌入视图是三视图 SVG |
| `cad_part` | cad_model | 交付物 | 单个零件，继承上位的 realizes 与渲染器。cad.build 只产出它，因为本包不做装配（TL-16：登记在真正支持的类型上） |
| `cad_plan`、`cad_spec`、`cad_file` | — | 值 | 计划、期望清单、导出的文件 |

`verdict` 是平台类型，本包只引用。

**无状态。** 每次调用都从计划重建。建模是确定的，一般零件 0.1–0.5 s，所以不需要在调用之间保存模型。

**描述只写目标，不写实现**（立法者 2026-10-03，检查点 F 裁决 §4）：登记资产里给模型看的文字，即 input_schema 的说明、能力声明的例子与不做的事，只说"能做出什么、解决什么问题"，不写用了哪个几何库、代码怎么组织。
- 2.2.0 把 cad.build 的说明从"建精确实体（OCCT B-rep）"改为"做出可以加工或 3D 打印的三维零件"；
- 去掉了能力声明里的几何内核版本。

实现细节只写在本 README 里。历史上 CAD 工具按"FreeCAD 与代码结构"来描述时，选择和调用都容易失败；改成按"产出 CAD 零件、几何体"来描述后，就容易成功。

## 3 零件计划

一行一个操作。`#` 后是注释。单位 mm，**x 向右、y 向后、z 向上**。

```
# L 形支架
material 6061-T6
let t = 10
base: box 120 60 t
wall: add box 120 t 50 at=(0,50,0)
m1: hole d=8.5 at=(20,25) from=top through cbore=(14,5)
pattern m1 linear n=4 dx=80/3
s1: slot w=8 l=24 at=(60,32) from=back through
rib: add prism (10,10) (50,10) (50,50) h=6 plane=yz off=0
pattern rib linear n=2 dx=114
fillet r=3 edges=vertical
```

**语法。**
- `[名字:] 操作 参数…`。参数可以是位置参数，也可以是 `键=值`。
- 值可以是：
  - 数或表达式：`+ - * / %`、括号、`pi`、`let` 定义的变量；
  - 括号元组，如 `(20,25)`；
  - 单词，如 `top`、`through`。
- 全角括号、逗号、冒号、等号和 `×` 会自动规范化（`×` 按 `*` 读）。
- 数前的直径记号 `Φ φ Ø ø ⌀`、数后的 `°` 与 `mm` 解析前去掉（2.4.0）：`d=Φ25`、`angle=38°`、`h=12mm` 分别等于 `d=25`、`angle=38`、`h=12`。
- 上限：300 行，每行 400 字符，最多 400 个特征，单个尺寸 0.01–10000 mm。

**名字就是特征的句柄。** 倒角、阵列、核对都靠名字引用特征，界面点选也靠它定位到计划行。没有命名的特征自动编号为 `fillet#1` 这样的形式。**特征行都要写名字**（2.6.0）：没有名字的特征行收到 `unnamed_feature` 告警，以后也不能单独改它（`#` 是注释符，`fillet#1` 在计划里不是句柄）。

### 3.1 操作

| 操作 | 写法 | 说明 |
|---|---|---|
| `units` | `units mm` | 目前只支持 mm |
| `material` | `material 6061-T6` | 用于算质量。密度表见 `builder.MATERIALS`（6061、7075、Q235、45、304、316、TC4、ABS、PLA、PETG 等）；不在表里的给警告，不算质量 |
| `let` | `let w = 80` | 定义变量，此后的行都可以用 |
| `box` | `box L W H [at=(x,y,z)]` 或 `box l= w= h=` | `at` 是最小角点 |
| `cylinder` | `cylinder d= h= [axis=z] [at=(x,y,z)]` | `at` 是底面圆心 |
| `cone` | `cone d1= [d2=0] h= [axis=] [at=]` | 圆台或圆锥 |
| `sphere` | `sphere d= [at=]` | `at` 是球心 |
| `prism` | `prism (u,v) (u,v) … h= [plane=xy\|xz\|yz] [off=]` | 多边形拉伸。xy 面上的点是 (x,y)，沿 +z 拉伸；xz 面上的点是 (x,z)，沿 +y 拉伸；yz 面上的点是 (y,z)，沿 +x 拉伸。`off` 是起始平面的坐标。点的绕向不限 |
| `gear` | `gear m= z= width= [alpha=20] [bore=] [at=]` | 标准直齿渐开线齿轮：齿顶高 m，齿根高 1.25m。不建根切与齿根圆角（z < 17 时与实际加工件有差别） |
| `add` / `cut` | `add box …`、`cut cylinder …` | 把一个基本体并上去，或减掉 |
| `hole` | `hole d= [at=center\|(u,v)] [from=top] through\|depth= [cbore=(D,深)] [csk=(D,角度)]` | 从某个外表面向里打孔。`(u,v)` 的取法：top/bottom 是 (x,y)，front/back 是 (x,z)，left/right 是 (y,z) |
| `pocket` | `pocket rect w= l= [r=] [angle=]` 或 `pocket circle d=`，加 `at= from= through\|depth=` | 型腔 |
| `slot` | `slot w= l= [angle=] at= from= through\|depth=` | 长圆槽，l 为总长 |
| `fillet` / `chamfer` | `fillet r= edges=…`、`chamfer c= edges=…` | 选边方式见 3.2 |
| `shell` | `shell t= [open=top\|…\|none]` | 抽壳，向内偏置 |
| `pattern` | `pattern 名字 linear n= dx= [dy=] [dz=]` 或 `pattern 名字 circular n= center=(u,v) [angle=360]` | 阵列一个已命名的加料或去料特征。环形阵列绕过 center 的轴：去料特征为其加工方向，加料特征为 z。`pattern 名字 grid n= m= dx= dy=` 为 n×m 网格（2.3.0） |
| `mirror` | `mirror 名字 plane=yz\|xz\|xy [off=]` | 镜像一个已命名的加料或去料特征（2.3.0） |
| `prism` 扩展 | 点写 `(u,v,r)` 给该顶点倒圆；加 `smooth` 为过各点的光滑闭合曲线；`twist=度` 为拉伸中绕平面原点的扭转 | 2.3.0 |
| `revolve` | `revolve (r,z) (r,z) … [angle=360] [axis=z] [at=]` | r ≥ 0 的轮廓绕轴回转；点可写 (r,z,圆角半径)（2.3.0） |
| `sweep` | `sweep d= (x,y,z) (x,y,z) … [r=] [id=]` | 圆截面沿折线路径扫掠，r 为拐角弯曲半径，给 id 为管（2.3.0） |
| `helix` | `helix d= pitch= h= wire= [axis=] [at=] [hand=right\|left]` | 螺旋弹簧，d 为中径（2.3.0） |

### 3.2 选边与加工入口

**选边** `edges=` 可以是：
- `all`；
- `vertical`：平行于 z 的边；
- `top`、`bottom`、`front`、`back`、`left`、`right`：零件该侧最外平面上的边；
- 特征名：归属该特征的边。一条边归它两侧面中**较晚产生**的那个特征。所以凸台的顶边和根部边归凸台，后来打的孔的孔口边归那个孔。

圆柱等曲面的接缝边不参与倒角。

**加工入口。** `from=top` 等面名先按包围盒确定方向，再沿这个方向在 `at` 处找第一个碰到的材料表面，孔口就落在那里。所以在 L 形件上 `from=top` 打孔，孔口在底板的真实上表面，而不是悬在立板顶的高度。
- `depth=` 从入口量起；
- `through` 一直贯穿到零件另一侧；
- 若 `at` 处沿方向没有材料，`depth=` 报错（例如正对一个已有的孔）。

### 3.3 出错

所有错误都是结构化的 `BAD_INPUT`，带行号，多数带提示：

```json
{"code":"BAD_INPUT","line":1,"message":"第 1 行（box）：“w”不是数，也不是已定义的变量","hint":"变量先用 let 定义，例如：let w = 80"}
{"code":"BAD_INPUT","line":2,"message":"第 2 行（fillet）：圆角 6 做不出来：尺寸大于相邻面能容纳的范围（选中 12 条边）","hint":"这组边能做的最大圆角约 r=4.97"}
```

以下情形同样报错，不会默默产出一个错的零件：
- 去料切空了零件；
- 几何无效；
- 抽壳过厚或没有生效。

去料没切到材料、零件变成多个不相连的实体时，给出警告。

## 4 期望清单（cad.check）

与计划用同一种行语法，一行一条：

```
bbox 120 60 50                       # 外形尺寸 x y z，缺省 tol=0.01
fits 220 220 250                     # 能放进这个包络（允许换方向）
volume 123524 rtol=0.001             # 体积 mm³（缺省 rtol=0.001；也可写 tol= 绝对值）
mass 1.254 kg rtol=0.01              # 质量（g 或 kg）；计划没写材料 ⟹ unknown
mass max=300                         # 上下限：max= / min=
com (60,40.03,15.71) tol=0.1         # 质心
solids 1
valid                                # B-rep 有效
watertight                           # 网格水密
holes 4 d=8.5                        # 直径 8.5 的孔有 4 个
hole d=8.5 cbore=(14,5) at=(20,25) through    # 存在这样一个孔；可写 axis= depth= csk=(D,角) blind
feature boss                         # 这个特征还在零件上
```

**判定规则。**
- 只依据测量值，不依据计划文字。
- 单条结果是 pass、fail 或 unknown。总判定：
  - 有 fail 就是 fail；
  - 否则有 unknown 就是 unknown；
  - 都不是则为 pass。
- `covered = (verdict ≠ unknown)`，对应 TL-22 的"覆盖范围外"。

**孔的识别。**
- 孔指一整圈的凹圆柱面。同轴相接的圆柱面和圆锥面合成一个孔，较大的圆柱记为沉头，圆锥记为锥口。
- 圆角和长圆槽的端头只有四分之一圈或半圈，不算孔。
- 孔的位置 `at` 按孔轴方向投影：z 轴孔为 (x,y)，y 轴孔为 (x,z)，x 轴孔为 (y,z)。
- 孔口倒角在几何上就是 90° 锥口，所以会报为 csk。

## 5 文件与格式

| 格式 | role | 说明 |
|---|---|---|
| STEP | model.exact | AP214，精确 B-rep，交给加工或其他 CAD |
| GLB | model.view | glTF 2.0 二进制，供网页查看，详见下文 |
| STL | mesh.print | 二进制 STL，焊接后的水密网格 |
| 3MF | mesh.print | 打印包，单位 millimeter |
| SVG | drawing | 三视图 |
| DXF | drawing | 三视图，图层分为 visible、hidden、center、text |

**GLB 的结构。**
- 每个特征是一个节点：节点名为特征名，`extras = {feature, op, line, faces}`。界面点中一个面，就能知道它是哪一行产生的。
- `faces`（2.6.0）：名下各面在本节点三角形里的区间与身份，`{tris: [起, 数], face_key, uncertain?, instance?}`。射线命中的三角形序号落在哪个区间，点中的就是哪个面；`uncertain` 标出键里含面积的面（归属不确定），`instance` 是阵列、镜像复制体的序号（1 起）。
- 另有一个 `edges` 节点，是 B-rep 的边线（LINES）。
- 单位为米，y 向上（glTF 约定）。根节点把模型的 z 向上转过去，根节点的 `extras` 记录 `units: mm, up: z`。

**三视图。**
- 第一角画法（GB/T 14692）：主视图在左上，俯视图在主视图正下方（长对正），左视图在主视图正右方（高平齐）。
- 线型：
  - 粗实线为可见轮廓；
  - 细虚线为不可见轮廓；
  - 细点划线为孔的中心线（孔轴朝向视线时画十字，垂直视线时画轴线）。
- 圆角的相切边按制图习惯不画。
- 标题栏写名称、材料、比例 1:1、单位、画法、外形和计划 sha256。
- **暂无尺寸与公差标注。**

**确定性（TL-12 ②）。** 同一计划在不同进程、不同哈希种子下运行，输出 JSON 与六种文件逐字节相同。做法：
- STEP 的时间戳固定，去掉注释行；
- GLB、STL、3MF 由本包自写，3MF 的 zip 时间戳固定；
- DXF 打开 ezdxf 的固定元数据开关；
- 进程入口固定 `PYTHONHASHSEED=0`，用一次自我重启实现。原因是 ezdxf 内部的对象顺序随字符串哈希变化。

## 6 文件产出约定（工具侧）

引擎侧对应 WP-W0 的探针 P14 与拟定条款 TL-9a。

- 信封里多一个字段 `workdir`：引擎为每次调用新建的空目录，绝对路径。
- 执行体只往 `workdir` 里写，不读写别处。
- 输出的 `files` 列出每个文件：
  ```json
  {"path":"bracket.step","format":"step","role":"model.exact","media_type":"model/step","bytes":116104,"sha256":"9cc6…"}
  ```
- 引擎核对以下各项，通过后收进 ObjectStore，回执与节点以对象引用：
  - 路径不越界；
  - 是普通文件，没有未声明的文件；
  - 字节数与 sha256 一致；
  - 大小在预算内。
- 文件名由 `name` 派生，只允许 `[A-Za-z0-9_-]`，所以不可能写出 workdir。
- 请求了文件却没给 workdir：`BAD_INPUT`。
- 输出含 sha256，所以引擎的确定性双跑比较输出，也就比较了文件。

## 7 产出物台的渲染（cad_model）

产出物台按**产物类型**选渲染，不按工具（WP-A1 §5、WP-W6 §6）。`cad_model` 的渲染器原型已发布为"CAD 产出物台"页面，用的是本包真实产出的五个样件。`cad_part` 继承它。

**嵌入视图**用于这个零件出现在别的产出里，比如长文里的插图。嵌入时直接展示 role = drawing 的 SVG 三视图，不需要另写代码。

| 区域 | 内容 | 数据来源 |
|---|---|---|
| 顶栏 | 零件名；核对判定（通过数 / 未通过项） | `cad.check` 的 verdict |
| 视口 | 三维模型。可选等轴测、主视、俯视、左视（视角与三视图一致）；按 X、Y、Z 剖切，剖面显示为实心；可开关边线；点选特征 | role = model.view 的 GLB |
| 计划 | 带行号的计划。产生特征的行可以点选，与视口里的选择双向联动；已被后续操作完全覆盖的特征标为"已被覆盖" | 计划原文 + `features` |
| 测量 | 外形、体积、表面积、质量、质心、拓扑、有效与水密。孔表可以点选，点中后在模型上显示孔轴 | `measure` |
| 核对 | 逐条显示：✓、✕ 或空心点，实测值，失败原因 | `cad.check` 的 checks |
| 三视图 | 图纸 | role = drawing 的 SVG |
| 文件 | 每种格式一行，写明用途、大小、sha256 前缀，可下载，也可全部打包下载；还有出处（工具版本、计划 sha256、内核版本） | `files` |

原型源码在 `renderer/index.html`，样件数据用 `python tools/make_viewer_data.py renderer` 生成，然后起一个静态服务器打开。页面依赖 three.js 0.170 与 JSZip 3.10，从 CDN 加载。

**局部修改（2.6.0，K10；渲染器的私有扩展，r9.2 L11，不进公开的渲染器契约；细节以 #728 定稿为准）：**

| 方向 | 消息 | 内容 |
|---|---|---|
| 渲染器 → 宿主 | `mengos.select` | `handles: [feature:名…]`（三维单选；计划面板 Shift 加选至多 3 行）、`anchor: {x, y}`（点中处的屏幕坐标，宿主在这里画“改这里”按钮与浮层）、`picked?: {feature, face_key}`、`instance?`、`uncertain?: true`；`handle_id` 照旧给第一个句柄。点空白或再点同一个为取消（`handles: []`） |
| 渲染器 → 宿主 | `mengos.select_denied` | `{handle_id, why_not, anchor}`：点了不可选的行（`unnamed`、`declaration`），灰字由宿主出 |
| 宿主 → 渲染器 | `mengos.open` | `{handles?}`：用户点了“改这里”，开始聚光（其余元件淡到 0.16）。没收到之前只标出选中，按钮阶段点别处即换选 |
| 宿主 → 渲染器 | `mengos.close` | 关浮层：退出聚光并清空选中 |
| 宿主 → 渲染器 | `mengos.busy` | `{handles}`：选中元件颜色呼吸（原色与朱之间缓慢往复，周期 1.6 s），计划行同一节拍；减少动效时静止为淡朱；`handles: []` 停 |
| 宿主 → 渲染器 | `mengos.marks` | `{steps: [{step, color?, changed, followed, param_diffs}], upto?}`：每一步一个颜色（不给 color 时用 #728 的六色序列），改过的元件染该步颜色，随动淡染并描同色点线；`upto` 之后的步不着色；比 `upto` 早 6 步及以上的统一变灰；悬停一句如“boss · 第 1 次：boss d 60→70” |

计划面板里不可选的行灰显并标“未命名”或“声明”；三维上不挂“改”“随动”字标，说明只在悬停时出现；宿主接管外框（`chrome: "host"`）时角上的选中说明也不显示，由宿主的浮层回显。

**接入表面层时要做的事：**
1. 下载直接取 ObjectStore 的原文件。原型页受预览环境限制，只能托管网页类文件、只能保存 zip，所以把二进制存成 base64 文本，下载时打成 zip。正式环境没有这些限制。
2. 界面读 `role` 与 `media_type` 决定怎么展示；引擎不解释 role（TL-4）。
3. 定稿按钮、版本号、"你定的"标注沿用表面层 demo 里的交付卡，不属于渲染器。

## 8 测试

```
uv sync --frozen && .venv/bin/python -m pytest -q -p no:cacheprovider   # 224 条，约 150 s
```

不要用不带 `--frozen` 的 `uv sync` / `uv run`：环境变量里配了别的索引（例如国内镜像）时，uv 会重新解析并改写 `uv.lock`，工具版本（lock hash）与 content_hash 随之失配。安装区里只用环境解释器跑，不运行 uv。

| 文件 | 内容 |
|---|---|
| `test_golden.py` | 20 条金样（TL-12 ③）。体积参考值来自手算或独立计算，与工具无关，例如：<br>· 底座：80·50·20 − π·10²·20 − 两个倒角环（Pappus）；<br>· 法兰：凸台根部的凹圆角加、顶边的凸圆角减（Pappus）；<br>· 齿轮：4000 点/段的渐开线多边形面积。<br>多数一致到 1e-7；齿轮在 1e-5 以内（样条拟合）；带圆角的支架只给近似手算，放宽到 5e-5。还包括错误用例的行号与提示 |
| `test_formats.py` | 第三方读回：<br>· trimesh 读 STL、3MF、GLB，体积与 B-rep 相差小于 0.2%（弦高误差）；<br>· STEP 读回体积一致；<br>· GLB 节点就是特征；<br>· DXF 图层齐全 |
| `test_determinism.py` | 五个样件，六种格式，两个进程、不同哈希种子，逐字节相同 |
| `test_safety.py` | · 源码中没有 eval、exec、compile；<br>· 16 种恶意或畸形计划只得到结构化失败；<br>· 150 条随机组合的计划从不出现 INTERNAL；<br>· workdir 与 name 不能越界 |
| `test_registration.py` | · 登记资产的件数与入口一致；<br>· lock hash 是最新的，覆盖执行体、依赖与登记资产；<br>· input_example 与金样的输入、输出都通过 schema；<br>· 动词在受控表内；<br>· 审核工具声明了覆盖范围 |
| `test_contribution.py` | 74 项，贡献型接入预检：标注合法、base 槽唯一、引擎合并金样（引擎自己的夹具逐字节拷贝，全量跑，含 named-lines 条目）；整体写法 schema 与 2.4.4 等价；行名正则与计划解析器逐行一致；合并后的计划与一次写成的交出同一份产物；注释行、空行、空行名的读数。夹具与参照实现见 `tests/fixtures/contribution/`、`tests/contribution_ref.py`；变异读数见 `tests/MUTANTS.md` |
| `test_local_edit.py` | 2.6.0 局部修改用的输出（执行令 K1–K9、K11–K14 的先红测试，在 2.5.2 上 41 红 8 绿，绿的 8 条是只加金样、不改代码的 K9 合并金样与“全具名零告警”）。其中“旧样例除新增字段外逐字节不变”拿 `tests/fixtures/v252/` 里 2.5.2 的实跑输出比对 |
| `test_package.py` | 登记资产严格是 TL-6 的字段，cost 全为数值；选择金样每件应选与不应选各 3 条，且应选的能通过程序过滤。安装包清单：<br>· 交付物类型有 realizes 与渲染器（可继承）；<br>· 工具引用的类型都已声明或是平台类型；<br>· cad.build 只产出 cad_part；<br>· 运行环境不出网；<br>· content_hash 是最新的 |

维护顺序：
1. 改登记内容运行 `tools/make_registration.py`；改金样运行 `tools/make_goldens.py`；
2. 运行 `python lock.py`，重写工具 version；
3. 运行 `python tools/make_package.py`，重写包的 content_hash。

只改渲染器时，第 2 步得到的工具 version 不变，认证不失效（WP-W6 §2）。

## 9 安装（服务层 S1）

前提：
- W0 完成；
- 检查点 E 已裁定 TL-9a（文件产出）与 TL-25 至 TL-27（安装机制）；
- 安装器已实现（WP-W6 §3）。

1. **平台审批**（TL-26 拟定）。审批人核对：
   - 执行器为 process；
   - 不出网；
   - 效应为 none；
   - 没有凭据；
   - 新根类型 `cad_model`、`cad_plan`、`cad_spec`、`cad_file`；
   - `realizes` 用的形态词 `assembly_model` 已在码本里。
2. **安装**。安装器：
   - 校验 content_hash；
   - 按 `uv.lock` 建隔离环境：Python 3.12–3.13，build123d 0.13.0、cadquery-ocp-novtk 8.0.1、ezdxf 1.4.4；
   - 在一个事务里依次入册类型、工具、渲染器；
   - 发 PackageInstalled。
3. **认证**。在引擎侧运行认证程序，取得 schema、双跑、金样、选择金样的结果；签字留给立法者，T1 必须人签。签好的记录放进包的 `certification`，以后升级时只要工具版本没变就继承。
4. **替换旧 CAD 族**（WP-W6 §7）：
   - 旧 FreeCAD 执行体摘册，旧 tool_id 不复用；
   - 引擎删除旧族，作为引擎侧变更单独合并；
   - TL-4 允许清单减一项；
   - 旧的 24 件确定性检查对照本包的核对项与金样，逐条写明覆盖关系。
5. **端到端**（服务层末尾，依赖 PLAN 与表面层）："帮我画一个铝合金底座"：
   - PLAN 投影到 `assembly_model`；
   - 反查得 `cad_model`；
   - 选中 cad.build（产出 cad_part，属于 cad_model 的子类型）；
   - cad.check 核对；
   - 文件进 ObjectStore；
   - 产出台渲染。
6. **模型侧的使用说明**就是登记资产里的 `input_domain` 与 examples（TL-16，描述由结构渲染）。不另写提示词，不在代码里替模型补救。

**关于装配体。** cad.build 登记为只产出 `cad_part`。目前码本形态只有一个 `assembly_model`，PLAN 只能要求到 `cad_model` 这一层，所以用户要装配体时，cad.build 仍会被选中，然后在核对或执行时失败。要让选择这一步就报 ToolSelectionMissed，需要码本把"零件"与"装配体"分开（码本的升维条款），使 PLAN 能要求 `cad_assembly`。等有装配工具时再做。

## 10 已知限制

- **不做：**
  - 装配、运动；
  - 有限元；
  - 自由曲面造型（放样、样条曲面）；扫掠只支持圆截面沿折线（带拐角弯曲半径）；
  - 读入外部模型；
  - 尺寸与公差标注；
  - 壁厚与可加工性检查。
- **相切实体的布尔运算**可能非常慢（例如弹簧端圈与螺旋相切），以超时结束。
- **螺旋与扫掠件的网格化**较慢：弹簧约 20 万个三角形，约 9 秒。
- **超时。** 进程内的超时（SIGALRM）打断不了 OCCT 里正在执行的 C++ 运算，硬超时靠引擎杀进程（TL-10）。
- **水密与三角形数**来自网格，是确定的，但依赖网格参数：弦高取外形对角线的 0.05%，限制在 0.005–0.1 mm 之间。
- **入口探测**沿 `at` 的那一条射线进行。型腔的中心正对已有孔时，`depth=` 会报"没有材料"，要换 `at` 或改用 through。
- **`fillet edges=vertical`** 会选中所有竖直棱。相邻两条棱距离小于 2r 时做不出来，错误提示会给出这组边能做的最大半径。
