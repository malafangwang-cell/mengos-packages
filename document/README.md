# document · 通用长文包 1.2.5

> 1.2.5（W-11，17 TL-16c v0.2.32）：doc.check 的输入类型改为 `in_types: [document]`——input_schema 只 required doc，expect（doc_spec）可有可无，按 TL-16c 不列（规格里就以 doc.check 为例）。旧形状 `[document, doc_spec]` 在 TL-16c 下会被读成两个都要。工具代码未改；registration 改了，lock 变（a0ddb53fe8b9a549），须重新认证。登记与包自检 13 项过。

> 1.2.4（W-9b，派生下载）：doc.export 按 17 TL-9b 接 `{object, format|formats}`。object 是要导出的文档的规范对象（排版那一步的产出记录），文档内容取自其 args.doc，名字缺省沿用排版时的 name；doc 与 object 二选一；单个 format 与 formats 二选一。起因：W-9 H2 读数，派生下载调 doc.export 得 502“不认识的字段：format, object”——1.1.2 起 doc.export 只认 doc，从未合派生下载的契约。给模型看的 object 说明不点名工具。新增 tests/test_export_object.py（5 项，含引擎实际发的 `{object, format}` 形）。registration 与 doc_tool.py 改了，lock 变（11460b6953276596），须重新认证。148 项测试通过。
>
> 1.2.3（W-9 合并令，工具描述按使用者的观察点改写）：doc.build 的说明原先站在工具这一侧写（“把写好的各节内容组装成…”，例子是“把九节内容组装成投标文件”“把这份季度报告整理成…”），关键的一句“正文、标题、图表都由调用方给出”放在 non_goals 里，按 TL-16b 不渲染给模型。PLAN 与出生门审核因此读成“要外部提供现成内容”，只有题目的写作任务被判工具不匹配。改为站在调用方一侧写：说明首句“要交付一份长文档时用。你把文档写进 doc……任务只给了题目时，内容由你按题目写”；场景例前三条（工具卡只渲染前三条）依次为只有题目的写作、按招标要求写、先列提纲，输出写明“你写……填进 doc”。工具代码未改；登记改了，lock 变为 `9373fd01b7d26131`，须重新认证。读者测试（只看工具卡答观察点问题，Haiku 4.5、Sonnet 4.5 各两遍，关思考）：改前 8/12，“只有题目时适不适合”一题 0/4；改后 12/12。

> 1.2.2（W-8 认证 ⑥ 停报后修正，只改包、不改工具版本）：选择金样里 doc.check 的语义负例（“核对这个零件外形是不是 80×50×20”，动词与类型过滤会放行）重新标上 `"stage": "model"`。1.1.2 补过这个标注，1.2.0 由 `tools/make_registration.py` 重新生成选择金样时丢了：生成脚本里没有这一项。现在生成脚本带标注；新增测试 `test_semantic_negatives_marked_stage_model`：按认证 ⑥ 的程序过滤逐条复核，期望不选中而程序放行的必须标 `stage:"model"`，其余不得标。工具版本（lock `3690aa2751cbde32`）不变。

> 1.2.1（W-8 安装被拒后修正）：登记资产里 `width.maximum` 由 `1.0` 改为 `1`。安装器用 JS 规范化 JSON 重算 lock，整数值的浮点数写成 `1`，包侧 Python 写成 `1.0`，两边算出的 lock 不同（`c404efd5…` 对 `4ef60759…`），安装器按 TL-25a 拒装。改后两边一致；新增测试 `tests/test_lock_parity.py`：登记资产里不得出现整数值的浮点数或指数写法的浮点数。
>
> 1.2.0（W-8）：① 产出台按渲染器契约 v0.1 重写：数据由宿主经 mengos.render 送来，完整视图为目录导航加正文，嵌入视图为标题、统计与前几节标题的卡片；下载经 mengos.download 交宿主派生，本页不再取网络数据、不再引第三方脚本；认 chrome:"host"。② 给模型看的节标题说明改为正面写法（17 TL-16b）。registration 改了，lock 变，须重新认证。

> 1.1.2（检查点 O 后，只改包、不改工具版本）：① 加金样运行入口 `tools/run_golden.py`（WP-W6 §2）；② 选择金样里 doc.check 的语义负例（“核对这个零件外形”，动词与类型过滤会放行）补标 `"stage": "model"`（WP-W6 §2，原先漏标）。工具版本不变。
>

> 1.1.1（检查点 G 后）：content_hash 的文件口径与安装器对齐，不计 `.DS_Store` 等系统杂项（WP-W6 §2），去掉多余的 `build` 排除项；工具版本（lock hash）不变。

> 1.1.0（2026-10-03，立法者意见）取代未安装的 1.0.0：
> - 文档只含文字、图片、表格，图随内容一起给出，去掉对象库图片引用；
> - 产出台改为目录导航加正文、右上角一个下载菜单；
> - 网页版加“打印为 PDF”的说明。

报告、方案、标书、手册、论文，都用这一个包。内容由模型写，工具只做确定性的部分：

- 章节、图、表统一编号；
- 生成目录；
- 把交叉引用换成可跳转的编号；
- 列出每条要求由哪些章节响应；
- 核对结构是否达标；
- 交出 Word、网页和 Markdown。

不同领域（投标、科研报告、施工方案）不另做工具。领域的差别由 PLAN 的域扩展提供：
- 章节骨架；
- 从附件（如招标文件）里提取的要求清单；
- 期望清单。

三样都是本包的普通输入（§8）。

> 依据：kernel-spec v0.2.23 17 章（TL-6、TL-9a、TL-12、TL-16、TL-22a、TL-25 至 TL-27）；WP-W6；检查点 F 裁决 §4（描述只写目标）；立法者 2026-10-03“长文一个通用工具即可，给域一个拓展”“默认一种，渲染几种”。

---

## 1 一种规范形态，几种派生视图

| 层 | 是什么 | 给谁 | 文件 role |
|---|---|---|---|
| **文档模型** | 规范形态：标题、各节（Markdown 正文）、图、表、要求、元数据 | 引擎存档；proj 追问时按节 id 改其中一节 | `document.model`（`.doc.json`） |
| Markdown | 模型读的视图，每个标题前带 `<a id="sec-…">` | 模型 | `document.text`（`.md`，图另附） |
| 产出台数据 | 人看的组装视图：目录、按节的正文 HTML、要求追溯、提醒、统计 | 表面层的产出台 | `document.view`（`.view.json`） |
| Word | 缺省交付格式：A4、目录、页码、书签与内部链接 | 用户下载 | `document.word`（`.docx`） |
| 网页 | 单个 HTML 文件。需要 PDF 时在浏览器里打印、另存为 PDF；页面顶部有一行说明，打印时不出现 | 用户下载 | `document.web`（`.html`） |

**派生是确定的。**同一文档模型，任何时候导出都逐字节相同，跨进程、跨哈希种子也一样（测试覆盖）。平台因此可以按 ⟨doc_sha256, 格式, 工具版本⟩ 缓存派生文件：服务层 S4 的“派生下载”端点直接用这个键。

## 2 三件工具

| 工具 | 动词 → 类型 | 做什么 | 文件 |
|---|---|---|---|
| `doc.build` | generate → `document` / `outline` | 内容 → 文档：编号、目录、引用、要求追溯、提醒 | 总有模型、产出台数据、Markdown（含图）；`formats` 缺省加 Word，可加网页 |
| `doc.check` | check → `verdict` | 内置结构核对 + 期望清单，每条 pass / fail / unknown，总判定取最差 | 无 |
| `doc.export` | convert → `doc_file` | 文档 → 指定格式：`docx`、`md`、`html`、`json` | 所列格式 |

三件都是：
- `effect = none`（只写引擎给的 workdir，经 TL-9a 入 ObjectStore）；
- `trust_claim = T1`（确定性双跑、金样、选择金样）；
- process 执行器，不出网。

协议与 cad、calc 相同：

```
stdin  {"tool": "doc.build", "payload": {...}, "budget": {"timeout_ms": 60000}, "workdir": "/abs/dir"}
stdout {"ok": true, "output": {..., "files": [{path, format, role, media_type, bytes, sha256}]}}
       {"ok": false, "error": {"code": "BAD_INPUT|RESOURCE_LIMIT|TIMEOUT|INTERNAL", "message", "where"?, "line"?, "hint"?}}
```

`where` 是出错的位置，例如 `doc.sections[3].level`。期望清单出错时，`line` 给出行号。

## 3 文档内容（`doc`）

```jsonc
{
  "title": "城东街道智慧社区安防改造项目",          // 必填
  "subtitle": "投标文件 · 技术部分",
  "kind": "document",                               // document | outline（提纲，允许空节）
  "meta": {
    "lang": "zh-CN",                                // zh-CN | en：决定“图 / Figure”“第 2.1 节 / Section 2.1”、字体与版式
    "org": "…", "author": "…", "date": "2026-10-03", "version": "V1.0",
    "numbering": "chapter",                         // decimal 1 / 1.1 · chapter 第一章 / 1.1 · zh 一、/（一）/ 1．/（1） · none
    "figure_numbering": "chapter",                  // global 图 1 · chapter 图 2-1
    "toc": true, "cover": true, "trace_table": true // 目录 · 封面页 · 文末附要求响应对照表
  },
  "requirements": [                                 // 任务书或招标文件提出的要求
    { "id": "r1", "text": "★ 录像保存不少于 90 天", "source": "招标文件 第三章 3.2.1",
      "priority": "must", "anchor": { "page": 18 } } // anchor 可带 object(附件 sha256)、page、bbox，只作出处记录
  ],
  "sections": [                                     // 按顺序；level 1–4，每节最多比上一节深一级
    { "id": "video", "level": 2, "heading": "视频监控子系统",
      "body": "共布设摄像机 186 台，见[[tab:devices]]。\n\n[[tab:devices]]",
      "responds_to": ["r1"] }
  ],
  "figures": [ { "id": "arch", "caption": "系统总体架构", "width": 0.9, "source": { "svg": "<svg …>" } } ],
  "tables":  [ { "id": "devices", "caption": "主要设备清单", "columns": ["设备", "数量"], "rows": [["枪机", 132]], "note": "…" } ]
}
```

**旧契约原样可用**：`{title, sections:[{heading, body}]}` 是合法输入。缺省值如下：
- id 依次为 `s1`、`s2`…；
- level 为 1；
- 编号为 decimal。

**正文里的三种记号**（代码块与行内代码里的不处理）：
- 单独一行 `[[fig:id]]` 或 `[[tab:id]]`：把图、表放在这里；
- 行内 `[[sec:id]]`、`[[fig:id]]`、`[[tab:id]]`：引用，换成“第 2.1 节”“图 2-1”“表 1”并链接过去；
- 其余是普通 Markdown：段落、加粗、斜体、删除线、列表、表格、引用、代码块、链接。

**规则（确定、可预期）：**

1. **编号**
   - 图、表按放置顺序编号，不按声明顺序。
   - 只被引用、没有放置的图表，放在第一次引用它的那一节末尾，并给出提醒。
   - 既没放置也没被引用的，不出现，并给出提醒。
   - 同一张图放两次，只采用第一次。
2. **正文里的小标题**（`###` 之类，包括列表和引用块里的）挂在本节之下，不编号，也不进目录；最浅的一级紧接本节的下一级，其余按相对层级顺延，最深到 6 级。
   - 哪些行是代码、哪些行是段落，以解析器的结果为准：缩进代码、列表与引用块里的代码都不处理记号。
   - 链接文字里的引用只换成文字，不再套一层链接。
   - 链接引用定义（`[spec]: https://…`）对整节有效，不受放置行切段影响。
3. **字数**口径接近 Word：每个汉字或全角标点算 1，每个西文词或数字串算 1。
   - `words_total` 含子节。
   - 统计范围是这一节可见的全部文字，包括图题、表格。
4. **拒收**（`BAD_INPUT`，带位置和提示），只用于输出无法确定的情况：
   - 层级跳级；
   - id 重复；
   - 表格格数不符；
   - 不合格的 SVG；
   - 控制字符；
   - 配置冲突。
5. **提醒**：其余问题都输出，但出现在 `warnings` 里，由 `doc.check` 判为 fail。包括：
   - 空节；
   - “待补”“TODO”之类占位；
   - 标题手写编号；
   - 无效引用（正文里显示为“〔节 x 不存在〕”）。
6. **SVG 只收静态图形**。它会作为独立文件交付，可能被浏览器直接打开，所以按白名单检查，不合格就拒收并说明原因，不静默删改：
   - 根元素必须是 SVG 命名空间里的 `<svg>`；
   - 元素只许静态图形元素（路径、形状、文字、渐变、图案、裁剪、蒙版、滤镜；不含 `feImage`）；脚本、动画（`animate`、`set`）、`foreignObject`、XHTML 元素一律拒收；
   - 不许事件属性、处理指令（如 `xml-stylesheet`）、DOCTYPE 与实体声明；
   - 链接只能指向图内（`#id`）或内嵌位图；任何属性与样式里的 `url(…)` 只能指向图内；样式里不许转义写法、`@import`、`image-set` 等；
   - XML 声明里的 encoding 只能是 UTF-8。

   其他命名空间的编辑器元数据（如 Inkscape 的）照收。
7. **位图**要完整：PNG 逐块核对（含校验和，须有 IDAT 与 IEND），JPEG 须有帧头与结束标记，尺寸在 1–30000 像素之间。不带 JFIF/Exif 头的合法 JPEG 也能嵌进 Word。
8. **标题手写编号**的判定：
   - 不会与正文数字混淆的写法一律算：第一章、一、、（一）、1、、1.背景；
   - 纯数字开头的（“3 背景”“2.1 范围”）只有与本节自己的编号对得上才算。所以“24 小时运维保障”“1.5 倍冗余设计”“5 Steps to Success”不会误报。
9. **文档只含文字、图片、表格。**图随内容一起给出：矢量图写 `svg`，位图写 PNG 或 JPEG 的 `base64`。
   - 别的工具的产出（例如 CAD 的三视图）要进长文时，由调用方把图片随内容交进来。
   - 本包不去别处取图，也不渲染别的类型。

## 4 期望清单（`doc.check` 的 `expect`）

一行一条，`#` 开头为注释。标题含空格时加引号，也可写 `id:节id`。匹配标题时忽略自动编号。

| 条目 | 例 | 判定 |
|---|---|---|
| `has 标题 [level=N]` | `has 项目团队` | 有这一节 |
| `order A B …` | `order 投标函 报价 技术方案` | 按此顺序出现 |
| `length 标题\|total [min=] [max=] [unit=words\|chars]` | `length 技术方案 min=3000` | 篇幅，含子节 |
| `contains 标题\|total 短语` | `contains 售后服务 7×24` | 出现这个短语（忽略空白与全半角差异） |
| `figures` / `tables [min=] [max=]` | `figures min=2` | 数量 |
| `pages [min=] [max=]` | `pages max=60` | **恒为 unknown**：页数要排版后才知道，`covered=false` |
| `covered [要求id …]` | `covered` | 必须项（或所列要求）都有非空章节响应。要求都是建议项时为 pass；文档没列要求时为 unknown |

参数写错一律按行号拒收，不静默忽略：
- 不认识的参数；
- 参数写了两次；
- level 不在 1–4；
- pages 带了多余的字；
- contains 的短语为空。

加了引号的永远当标题或短语，不当参数。同名的节不止一个时，`has … level=N` 看任意一节；其余条目按第一节核对，并在 note 里注明。

内置核对总会进行：
- 引用都能解析；
- 图表都已放置且只放一次；
- 没有空节；
- 没有待补占位；
- 标题没有手写编号；
- 图片都能显示；
- 必须项都有章节响应。

提纲不做空节与占位两项。

结论依据的前提如实写进 `assumptions`（TL-22a），例如：
- 要求与章节的对应是作者声明的，本工具不判断内容是否满足要求；
- 字数口径与 Word 可能有小的出入。

## 5 产出台（渲染器原型）

`renderer/index.html` 是 `document` 类型的完整视图，`outline` 继承它。只做一件事：让人读组装好的成品。

- **顶栏**：标题；右上角一个“下载”菜单，内含 Word、Markdown（有图时连图打包成 .zip）、网页三项。
  - 三种格式内容相同，都有目录和全部正文。
  - 网页一项注明“下载后用浏览器打开，需要 PDF 时打印、另存为 PDF”。
- **左侧**：目录导航。点击跳到该节，滚动时高亮当前节；窄屏收进抽屉。
- **正文**：标题、副标题、单位与日期，然后按节排版。

要求追溯如需给人看，写进文档：`meta.trace_table` 会在文末附“要求响应对照表”。核对结论由引擎在交付标注里给出，不放在产出台。

原型的数据契约（B3 定稿前）：

```
data/index.json = { "view": "<document.view 文件>",
                    "files": [{path, format, role, media_type, bytes, sha256, src, encoding?}] }
```

嵌入视图 `{file_role: document.view, view: card}`：标题与目录卡片。

已发布的样张：“长文产出台”，载入投标文件技术部分样例。

## 6 安装与替换（服务层 S1c）

1. **平台审批**（TL-26），逐项：
   - 执行器 process；不出网；
   - 效应 none；没有凭据；
   - 新类型五个：`document`、`outline` 两个交付物类型，`doc_plan`、`doc_spec`、`doc_file` 三个值类型；
   - 码本形态 `long_doc`、`toc_outline` 由 realizes 声明（TL-27）；
   - 给模型看的文字只写目标（`test_package.py` 有禁词自检）。
2. **安装**：安装器校验 content_hash，按 `uv.lock` 建隔离环境（python-docx 1.2.0、markdown-it-py 4.0.0），在一个事务里入册类型、三件工具与渲染器。命令为 ⟨包环境的 python⟩ ⟨包目录⟩/doc_tool.py。
3. **替换**（TL-24）：旧 `doc.assemble.write`（族 t-doc，T4，effect=write）→ `doc.build`（清单 `replaces`）。

   旧件写到 out_dir；新件写到引擎给的 workdir，经 TL-9a 入 ObjectStore，所以效应从 write 变为 none。旧 tool_id 摘册，不复用。
4. **过渡路由**（S3 接通 TL-19 与 TL-27 之前）：引擎现有的 `kind=doc` 产出链改为调用 `doc.build`。

   ```
   GEN 产出 {title, sections:[{heading, body}]}（不变）
     → doc.build { doc: <该计划>, name: docSlug(target) }
     → files 经 TL-9a 入 ObjectStore；交付引用 role=document.word（缺省交付），附 document.model 与 document.text
   ```

   - 这条路由数据不是从包里来的，按检查点 F 裁决 §2 第 3 条标为“过渡”，列入过渡路由台账，S3 后删除。
   - 旧链路交付的是 `.md`；新链路缺省交付 Word，Markdown 仍在文件里。
   - 标题前多了自动编号：`## 1 背景`，旧的是 `## 背景`。
5. **冒烟**：长文任务走 produce 链，交付 Word。用旧链路的三条用例对照：读书角方案、缺 title 拒收、空标题拒收（金样 `compat_old`、`err_old_*`）。

   有一处不同：旧链路拒收空正文，新链路接受，但给出提醒，核对判为 fail。
6. **摘旧族**：引擎内 t-doc 的执行体、`composeDocFactory` 绑定与 `doc:exec:node` 适配器位，作为引擎侧变更单独合并；TL-4 允许清单减去文档产出一项。
7. **签字**：替换完成后，立法者对三件工具的版本逐件人签（TL-13），建议 T1。

改了源码之后依次运行：

```
python tools/make_registration.py   # 只在改登记内容时
python lock.py                      # 重写工具 version
python tools/make_package.py        # 重写包的 content_hash
```

## 7 已知边界

- **不直接出 PDF**（立法者 2026-10-03）：网页版在浏览器里打印、另存为 PDF；网页顶部有说明，打印时不出现。也可以在 Word 里另存为 PDF。
- **Word 里的 SVG**：Word 2019、365 与 LibreOffice 显示矢量图本身；更旧的版本显示浅灰后备框。
- **Word 目录**：打开时 Word 会提示更新域，更新后带页码。不更新也能用：条目已预先填好，没有页码。
- **列表编号**写成文字（“1.”“•”），不用 Word 的自动编号，保证与其他视图一致、可复现。
- **不做**：
  - 脚注与尾注；
  - 参考文献格式；
  - 公式排版；
  - 修订痕迹；
  - 读入已有 Word 文件；
  - 按节局部修改（局部调整怎样走见二期计划，不在本包）。

## 8 领域怎样扩展（不另做工具）

以投标为例，PLAN 的投标域提供三样东西，全部是本包的普通输入：

1. **章节骨架**：招标文件要求的组成与顺序 → `sections` 的标题与层级（`kind=outline` 先给用户确认）。
2. **要求清单**：从招标文件附件里提取实质性条款（★）与评分项 → `requirements`，`anchor` 指向附件页码。
3. **期望清单**：顺序、篇幅、必含内容 → `doc.check` 的 `expect`。`pages max=…` 如实为 unknown，交人工确认。

科研报告、施工方案、运维手册同理。工具不认识任何领域，领域也不需要改工具。

## 9 验证

```
uv sync --frozen && .venv/bin/python -m pytest -q -p no:cacheprovider      # 141 项
```

不要用不带 `--frozen` 的 `uv sync` / `uv run`：环境变量里配了别的索引（例如国内镜像）时，uv 会重新解析并改写 `uv.lock`，工具版本（lock hash）与 content_hash 随之失配。安装区里只用环境解释器跑，不运行 uv。

| 测试 | 内容 |
|---|---|
| `test_golden.py` | 38 条金样，期望值手写，可直接作为认证 ③ 的金样材料：<br>· 四种编号；<br>· 中文数字；<br>· 旧契约兼容；<br>· 引用与放置顺序；<br>· 代码里的记号不解析；<br>· 字数口径；<br>· 结构核对；<br>· 要求追溯；<br>· 期望清单逐条；<br>· 表格对齐；<br>· 英文；<br>· 对照表；<br>· 十种拒收 |
| `test_determinism.py` | 不同进程、不同哈希种子：输出与全部文件逐字节相同。export 与 build 产出一致；规范模型再输入一次，doc_sha256 与文件都不变 |
| `test_formats.py` | Word：<br>· 标题样式与顺序；<br>· 每节、每图表都有书签；<br>· 内部链接都有落点；<br>· 目录域；<br>· 表格；<br>· zip 时间戳固定；<br>· SVG 部件与内容类型。<br>网页：id 唯一、链接有落点、无脚本。<br>Markdown：链接与图片都有落点。<br>产出台数据：字段齐全 |
| `test_registration.py` | 例子合 input_schema。例子与三份样例跑三件工具，输出合 output_schema。schema 与代码对同一批坏输入都拒收。version 等于 lock hash |
| `test_package.py` | 只用 TL-6 字段；类型与渲染器；lock 覆盖范围；content_hash 最新；替换映射；选择金样每件应选与不应选各 3 条；给模型看的文字不含实现用词 |
| `test_review_regressions.py` | 57 项。独立审查（另起的审查代理用对抗性输入找出 22 处缺陷）逐条钉住：<br>· 信封与预算的各种坏值不再让进程无输出退出；<br>· 坏图、非有限尺寸、实体解码出的控制字符、超长文件名不再导致内部错误，出错时不留半截文件；<br>· 两万行表格导出 Word 是线性耗时；<br>· 各种代码块里的记号不处理，跨块的行内代码不吞引用；<br>· Markdown 里的标题、表注不能注入结构，没闭合的代码块不吞后文；<br>· 十五种 SVG 绕过写法被拒；<br>· 核对的引号、参数与同名节 |
| `test_safety.py` | 源码不执行代码；十种不合格 SVG 拒收且不写文件；正文里的原始 HTML 被转义、`javascript:` 链接失效；文件名不能越出 workdir；控制字符拒收；超时结构化 |

**开销**：同一台机器，进程冷启动，含 Word。

| 场景 | 耗时 |
|---|---|
| 投标样例 9 节、2 图、2 表 | `doc.build` 约 0.25 s；`doc.check` 约 0.1 s；`doc.export` Word 约 0.28 s |
| 120 节、13 万字 | `doc.build` 约 1.05 s；`doc.check` 约 0.2 s |

## 10 文件

| 文件 | 内容 |
|---|---|
| `doc_tool.py` | process 入口：读一行信封，写一行回执 |
| `model.py` | 文档模型：校验、缺省、图片与 SVG 检查、规范化、doc_sha256 |
| `assemble.py` | 组装：编号、放置、引用、字数、结构提醒、要求追溯 |
| `render.py` | Markdown、产出台数据、单文件网页 |
| `docx_writer.py` | Word：版式、样式、目录域、书签与链接、图（含 SVG）、表格、页码、zip 规范化 |
| `checker.py` | 内置核对与期望清单 |
| `registration.json` | 三件工具的登记资产（TL-6 字段），version 等于 lock hash |
| `mengos-package.json` | 安装包清单：类型、渲染器、lock 覆盖范围、运行环境、替换映射 |
| `golden_cases.json` | 38 条金样（认证 ③） |
| `selection_cases.json` | 选择金样（认证 ⑥），每件应选与不应选各 3 条 |
| `renderer/index.html` | 产出台原型 |
| `samples/` | 投标文件技术部分、读书角方案（旧契约形状）、英文简报 |
| `lock.py`、`tools/` | lock hash、content_hash、登记资产、金样与样例的生成程序 |
| `tests/` | §9 |
