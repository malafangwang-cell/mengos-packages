# document · 通用长文包 2.2.0

> 2.2.0（立法者 2026-11-09：长文图文能力与 PDF 进首发，合并为一个版本、认证一次；合并原定 2.1.0 的图文能力与 doc.export 的 PDF 格式）。给模型看的文字只改 doc.export 一件（加 PDF、删“不直接交 PDF”）；doc.build、doc.check 的说明与 schema 不动，doc.export 的 `format`/`formats` 词表只放宽（加 `pdf`），其余输入 schema 不变。工具代码、依赖、字体、登记都变，lock 变，须重新认证。
>
> **A. 图文能力**：最多 20 张 2K PNG 也稳定收下，不因体积整篇失败。
> - **嵌入副本**：位图入口校验后确定性生成嵌入副本——长边 >1600 px 等比缩到 1600（否则不变），统一 JPEG q85，只留像素（去 EXIF、ICC），透明 PNG 先合成白底。副本用于 Word（`word/media`）、网页 data URI、产出台 `.view.json` 各节 html、PDF，并内嵌在 `.doc.json` 里。SVG 不变。1600 与 85 是 `model.py` 里的包内常量（`EMBED_MAX_EDGE`、`EMBED_QUALITY`）。同输入同 Pillow 版本逐字节相同。
> - **原图单独成文件**（架构线 2026-11-09 裁决：对象层单次写入上限 50 MiB，`.doc.json` 内嵌 20 张 2K 原图在任何上限下都存不进去）：`doc.build` 只要有位图，不论 `formats` 选了什么，都把每张原图作为独立产出文件输出，路径 `figures/<id>.<ext>`，`role: document.figure_original`，原字节不改。`.doc.json` 里位图项的 `source` 内嵌嵌入副本，并加 `original: {sha256, bytes, media_type, path}` 指向原图文件（哈希由包按原字节计算，与对象层内容哈希一致）；原图仍是真源，只是按哈希引用。Markdown 导出的位图直接引用这些文件（同一字节，不另存一份）；SVG 照旧内嵌，Markdown 仍为 SVG 附一个文件。`doc.export` 只在导出 `md` 或 `json` 时随带原图文件（只导 Word、PDF、网页不带）。**已知限制**：带 `original` 的 `.doc.json` 里的位图再作为 `doc` 输入时，`source` 不认 `original`（输入 schema 不变），不能直接回灌；要回灌请换回原图 base64。
> - **上限**：单张原图 8 MB → 16 MB；嵌入副本合计 `images_total_bytes` 48 MB → 36 MB（按副本计，SVG 按原文），使 base64 后的 `.doc.json` 与网页仍低于单文件 48 MB；原图合计 `originals_total_bytes` 320 MB（防滥用，20 × 16）；单个产出文件 `MAX_FILE_BYTES` 64 MB → 48 MB（低于对象层 50 MiB，登记 `constraints.max_file_mb` 同步为 48）；产出合计 `MAX_TOTAL_BYTES` 160 MB → 512 MB；单张像素上限 `image_pixels` 1 亿（解码内存保护，原先只限单边 30000）。超限一律在输入阶段判为 `BAD_INPUT`，信息写明是哪张图或哪项合计、多大、上限多少；规范模型文件会超过 48 MB 时同样在输入阶段拒收；产出阶段的 `RESOURCE_LIMIT` 只作最后兜底。**无法解码的位图**（块与 CRC 都对、但压缩流损坏）在入口就拒收（`BAD_INPUT`，`where` 指到该图）。
> - **依赖**：新增 Pillow 12.3.0（`pyproject.toml` 钉死，`uv.lock` 锁定）。
> - **读数**（§9 开销表）：20 张 2048² PNG（可压缩图案，原图合计 7.2 MB），`doc.build`（含 Word 与网页）2.6 s，Word 6.3 MB、网页 9.6 MB；`doc.export` 出 PDF 6.6 s、9.1 MB。20 张不可压缩 2048² PNG（每张 12.6 MB，原图合计 252 MB）`doc.build` 7.8 s，`.doc.json` 44.9 MB，产出合计 420 MB，整篇成功。均低于 30 s 的调整门槛，`cost.timeout` 仍为 60 000 ms，不调。
> - **随之改了的测试**：`tests/test_review_regressions.py` 的 `png()` 夹具原先生成的 PNG 像素数据不足（只有结构合法，Pillow 解不出），改为生成完整像素；`test_jpeg_without_jfif_and_png_embed_in_word` 里 Word 媒体名由 `mengos_img2.png` 变为 `mengos_img2.jpeg`——位图一律以 JPEG 嵌入副本入 Word，是本版设计，不是迁就实现；`test_export_object.py` 里“pdf 不支持”的反例改用仍不支持的 `odt`。
>
> **B. PDF 导出**：`doc.export` 新增 `pdf`（`doc.build` 不加）。纯 Python 从已装配的文档模型直接排版（reportlab，invariant 模式），与 Word、网页同源，编号与交叉引用已解析；输出 `role: document.pdf`、`media_type: application/pdf`。
> - **版式**：A4，页边距上下 25 mm、左右 22 mm（同网页打印样式）；正文衬线、标题无衬线，字号行距照 Word 的 zh-CN / en 两套；封面 `meta.cover`、目录 `meta.toc`（带页码与内部链接，两遍排版）、按 numbering 编号的各级标题、Markdown 正文（段落、粗体、行内代码、删除线、有序无序列表、引用、代码块、表格）、图（图题在下）、表（表题在上、表注）、`[[sec:]]`/`[[fig:]]`/`[[tab:]]` 为可点内部链接、要求响应对照表、页脚页码、按标题层级的书签；元数据标题与作者取自 `meta`，不写当前时间；`kind=outline` 照出。斜体没有对应字形，PDF 里与正文同形。
> - **图**：位图用嵌入副本；SVG 转矢量（svglib，纯 Python，不依赖 cairo；SVG 里的字体名一律落到随包字体，不查系统字体）；转不了的 SVG 在原位画占位框，写图题与“此图无法在 PDF 中绘制”，并在 `warnings` 里报 `pdf_figure_unsupported`。随包字体没有的字符（如 emoji）报 `pdf_glyph_missing`，列出前 20 个，PDF 里显示为空框。
> - **字体**（`fonts/`，SIL OFL 1.1，随包带许可全文；静态 TrueType，glyf 轮廓；嵌入 PDF 时再子集化，PDF 里的字体全是嵌入子集）：
>
>   | 文件 | 字体 | 版本 | sha256 |
>   |---|---|---|---|
>   | `NotoSerifSC-Regular.ttf` | Noto Serif SC 常规（正文） | 2.003 | `a2179731f768a8bb2dcf4319209443ed4956063abe2a4b55df62a716a4a43abc` |
>   | `NotoSerifSC-Bold.ttf` | Noto Serif SC 粗体 | 2.003 | `4203ed96c9d6d7091b5a7e21437be496804479e98eabbe75471a2980bca904bc` |
>   | `NotoSansSC-Regular.ttf` | Noto Sans SC 常规（标题、表头、页脚） | 2.004 | `04d7e3052e440741e70f6ffecc59ed71e3d0228bdc38783751ffa83d2118e01e` |
>   | `NotoSansSC-Bold.ttf` | Noto Sans SC 粗体 | 2.004 | `d09a6ba02ec7d38d337e01d84a716f3135319dad96a8a2fdcad631d6b93b2470` |
>
>   来源：Google Fonts 公开仓库 `ofl/notosanssc/NotoSansSC[wght].ttf`（sha256 `a3041811…0af9`）与 `ofl/notoserifsc/NotoSerifSC[wght].ttf`（sha256 `050080d9…66f9`）两个可变字体；`tools/make_fonts.py` 实例化出 wght=400、700 两个静态实例，再裁到 CJK 统一汉字基本区（U+4E00–9FFF）、CJK 兼容符号（U+3300–33FF，含㎡ ㎏）、希腊字母整区（U+0370–03FF）、GB 2312 全部字符、ASCII、Latin-1、常用标点、全角形式、数学符号与带圈数字，去掉提示与排版表，写入固定时间戳（重跑逐字节相同）。许可全文见 `fonts/OFL-NotoSansSC.txt`、`fonts/OFL-NotoSerifSC.txt`；OFL 的保留字体名是“Source”，本包字体仍叫 Noto，不含该名。四个字体与两份许可文本都在 `tools_lock.covers` 内。
> - **依赖**：reportlab 5.1.0、svglib 1.5.1（及其纯 Python 依赖 cssselect2、tinycss2、webencodings、charset-normalizer）钉在 `pyproject.toml`、锁在 `uv.lock`；dev 依赖加 pypdf 6.17.0（只用于测试读回 PDF）与 fonttools 4.68.0（只用于重新生成字体）。不依赖任何系统库。
> - **干净环境验证**：另起目录、全新虚拟环境（Python 3.12.3），只 `uv sync --frozen`，257 项测试全过，`uv.lock` 无改写（未用 python:3.12-slim 容器，开发环境无 docker；依赖全为纯 Python 或带自带 wheel，不依赖系统库）。
> - **为什么不用 LibreOffice**：把 Word 转成 PDF 要带一个很大的外部程序，输出随版本与系统字体回退而变，不能保证逐字节复现（确定性，TL-12 ②），也违背包自足（TL-25）。本包直接排版、字体随包，同一文档任何时候、任何机器导出的 PDF 逐字节相同。
> - **网页版**：不再在页面顶部写“在浏览器里打印另存为 PDF”的说明（PDF 现在直接导出）；打印样式（`@page`、`@media print`）保留。产出台下载菜单里的 PDF 一项由渲染器的格式表提供（`renderer/index.html` 的 `FORMATS`）。渲染器握手的 `format_hints`（契约 0.2，P8 可选）本版未做。

> 2.0.2（立法者 2026-11-08 同意；只改渲染器，依据渲染器契约 v0.1 §4.2，认证继承 TL-25）：宿主发 `chrome:"host"` 时整条顶栏连同“下载 ▾”隐去（2.0.1 只隐了标题）；窄屏只保留目录按钮（目录在抽屉里），与 cad 2.5.1、table 2.0.0 一致。独立打开（不发 chrome:"host"）时顶栏与下载不变。工具代码、registration.json、schema、金样均未改，lock 仍为 `219a4dd622f9cda7`，只有 content_hash 变。

> 2.0.1（mengosv2 执行令-2026-11-05-PLAN声明书与F环清单交互 支 T）：包清单加显示名 `title`「长文档编排」与 `tool_titles`（`doc.build`「编排并交付长文档」、`doc.check`「核对长文档交付要求」、`doc.export`「导出长文档文件」）。两字段只供界面显示（声明书、商店），不进工具选择，也不进给模型看的任何文字；不在 `tools_lock.covers` 内，lock 不变（工具版本与认证继承），只有 content_hash 变。工具代码与 registration.json 未改（其中 `family_version` 仍写 2.0.0）。

> 2.0.0（产出规则 支 B，第一单；17 TL-30a）：doc.build 接入贡献型声明，让长文可以分多次写、由引擎累积，不再要求模型一次输出整份文档。**输入契约收紧，所以升大版本**；工具代码未改，只改登记（input_schema）：
> - **破坏性变更：doc.build 的节 id 由可选改为必填。** 同时 tables、figures、requirements 的元素本来就要 id。四个容器的元素 `required:["id"]` 写在 if/then/else 之外，恒生效。原因：不带 id 的节没法被后续增量定位，增量会静默追加出重复的节。这是契约变更，不是迁就实现：旧契约 `{title, sections:[{heading, body}]}` 在 doc.build 上不再是合法输入（doc.check、doc.export 仍原样接受）；金样、样例里缺 id 的节补上 id（取工具原来会缺省出的 `s<序号>`，输出与期望值不变）。
> - doc.build 顶层加 base 槽（`x-mengos-base`）；`doc.sections`（by-id，label=heading，fill=body）、`doc.tables`（by-id，label=caption；其 `rows` 为 append）、`doc.figures`、`doc.requirements` 标 `x-mengos-merge`。doc.check、doc.export 的 schema 不动。
> - 必填放宽：`if {required:[base]} then {required:[base]} else {…}`。id 以外的原必填（顶层 doc、doc 的 title/sections、各元素的 heading/caption/columns/rows/source/text）搬进 else：不带 base 的整体写法走 else，校验口径与 1.2.5 相比只多了节 id 必填一处（`tests/test_contribution.py` 比对 1.2.5 schema 的 sha256）；带 base 的增量只要求 base 与各元素的 id。
> - 带空槽的中间版本：`body` 缺席、空串、纯空白都接受（本就接受，只出 `empty_section` 提醒），不报 BAD_INPUT。
> - 包内预检加三项：标注合法、base 槽唯一、引擎合并金样（`tests/fixtures/contribution/`，引擎自己的夹具 merge-algebra / merge-touched-keys / merge-empty-slots 逐字节拷贝，来源 commit 与 sha256 见其 `SOURCE.json`）；合并代数的 Python 参照实现在 `tests/contribution_ref.py`，靠金样验证。缺 id 时工具自己的缺省 id 行为另由 `tests/test_legacy_default_ids.py` 守住。
> - 版本：lock `219a4dd622f9cda7`，须重新认证。

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
| PDF | A4 版式固定：封面、带页码的目录、书签、可点的内部链接、嵌入字体；纯 Python 排版，逐字节确定 | 用户下载（`doc.export`） | `document.pdf`（`.pdf`） |
| 网页 | 单个 HTML 文件，可在浏览器里打开、打印 | 用户下载 | `document.web`（`.html`） |

**派生是确定的。**同一文档模型，任何时候导出都逐字节相同，跨进程、跨哈希种子也一样（测试覆盖）。平台因此可以按 ⟨doc_sha256, 格式, 工具版本⟩ 缓存派生文件：服务层 S4 的“派生下载”端点直接用这个键。

## 2 三件工具

| 工具 | 动词 → 类型 | 做什么 | 文件 |
|---|---|---|---|
| `doc.build` | generate → `document` / `outline` | 内容 → 文档：编号、目录、引用、要求追溯、提醒 | 总有模型、产出台数据、Markdown（含图）；`formats` 缺省加 Word，可加网页 |
| `doc.check` | check → `verdict` | 内置结构核对 + 期望清单，每条 pass / fail / unknown，总判定取最差 | 无 |
| `doc.export` | convert → `doc_file` | 文档 → 指定格式：`docx`、`pdf`、`md`、`html`、`json` | 所列格式 |

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

**旧契约的简写**：`{title, sections:[{heading, body}]}` 在 doc.check、doc.export 上仍是合法输入；doc.build 自 2.0.0 起要求每节带 id。缺省值如下：
- id 依次为 `s1`、`s2`…（doc.check、doc.export；doc.build 需显式给出）；
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

- **PDF**（2.2.0 起 `doc.export` 直接出）：不读系统字体，字形集见顶部字体说明（CJK 基本区全收），集外字符（如 emoji、扩展 B 区生僻字）报 `pdf_glyph_missing`；斜体不单独区分；SVG 里 svglib 不支持的写法会落到占位框并报 `pdf_figure_unsupported`；`doc.build` 不出 PDF（只在导出时生成）。
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
uv sync --frozen && .venv/bin/python -m pytest -q -p no:cacheprovider      # 项数以实跑为准
```

不要用不带 `--frozen` 的 `uv sync` / `uv run`：环境变量里配了别的索引（例如国内镜像）时，uv 会重新解析并改写 `uv.lock`，工具版本（lock hash）与 content_hash 随之失配。安装区里只用环境解释器跑，不运行 uv。

| 测试 | 内容 |
|---|---|
| `test_golden.py` | 39 条金样（含 2.1.0 的位图结构金样 `fig_bitmap_structure`：图 1–3、所在节、图题、Word 图形数与图题样式、网页 `<figure>` 数、附图文件数，只比结构），期望值手写，可直接作为认证 ③ 的金样材料：<br>· 四种编号；<br>· 中文数字；<br>· 旧契约兼容；<br>· 引用与放置顺序；<br>· 代码里的记号不解析；<br>· 字数口径；<br>· 结构核对；<br>· 要求追溯；<br>· 期望清单逐条；<br>· 表格对齐；<br>· 英文；<br>· 对照表；<br>· 十种拒收 |
| `test_determinism.py` | 不同进程、不同哈希种子：输出与全部文件逐字节相同。export 与 build 产出一致；规范模型再输入一次，doc_sha256 与文件都不变 |
| `test_formats.py` | Word：<br>· 标题样式与顺序；<br>· 每节、每图表都有书签；<br>· 内部链接都有落点；<br>· 目录域；<br>· 表格；<br>· zip 时间戳固定；<br>· SVG 部件与内容类型。<br>网页：id 唯一、链接有落点、无脚本。<br>Markdown：链接与图片都有落点。<br>产出台数据：字段齐全 |
| `test_registration.py` | 例子合 input_schema。例子与三份样例跑三件工具，输出合 output_schema。schema 与代码对同一批坏输入都拒收。version 等于 lock hash |
| `test_package.py` | 只用 TL-6 字段；类型与渲染器；lock 覆盖范围；content_hash 最新；替换映射；选择金样每件应选与不应选各 3 条；给模型看的文字不含实现用词 |
| `test_review_regressions.py` | 57 项。独立审查（另起的审查代理用对抗性输入找出 22 处缺陷）逐条钉住：<br>· 信封与预算的各种坏值不再让进程无输出退出；<br>· 坏图、非有限尺寸、实体解码出的控制字符、超长文件名不再导致内部错误，出错时不留半截文件；<br>· 两万行表格导出 Word 是线性耗时；<br>· 各种代码块里的记号不处理，跨块的行内代码不吞引用；<br>· Markdown 里的标题、表注不能注入结构，没闭合的代码块不吞后文；<br>· 十五种 SVG 绕过写法被拒；<br>· 核对的引号、参数与同名节 |
| `test_contribution.py` | 60 项（另有 `test_legacy_default_ids.py` 3 项），贡献型接入预检（TL-30a）：标注合法、base 槽唯一、引擎合并金样（合并 / 触及键 / 空槽 / 骨架）；整体写法 schema 与 1.2.5 等价；带 base 的增量被接受；空槽中间版本被接受；分次合并出的文档与一次写成的交出同一份产物（文件逐字节相同）。夹具与参照实现见 `tests/fixtures/contribution/`、`tests/contribution_ref.py`；变异读数见 `tests/MUTANTS.md` |
| `test_figures_embed.py` | 2.1.0 图文能力（图片全由 `tools/synth.py` 程序生成）：嵌入副本（2048²→1600² JPEG、800×600 不变、1600/1601 边界、透明合成白底、去 EXIF 与 ICC、字节确定、坏流拒收）；Word/网页/产出台/PDF/`.doc.json` 内嵌用副本，原图单独成文件、Markdown 引用它；单张 15 MB 收、16 MB 恰收、多 1 字节与 17 MB 拒（含图 id 与字节数）；原图合计与嵌入合计（36 MB）各自的上限与报错；像素上限；规范模型文件将超 48 MB 时输入阶段拒收；20 张 2K（可压缩与不可压缩各一）整篇成功，各产出文件 <48 MB，`.doc.json` 不含原图 base64、原图文件的 sha256 与 `original.sha256` 逐一相等；原图随 `doc.build` 恒出、随 `doc.export` 仅 md 与 json 出；同节多图顺序；孤立图 `figure_orphan` 提醒 |
| `test_pdf.py` | 2.2.0 PDF：每份样例都能出 PDF 且双跑逐字节相同；跨进程、跨哈希种子一致；元数据无当前时间；中英文结构金样（页数区间、书签树与标题一致、目录页码与书签单调一致、页脚页码、图表题文字与位置、内部链接数、字体全是嵌入子集）；位图用嵌入副本；提纲、封面与目录开关；SVG 转不了时的占位框与提醒；缺字提醒；SVG 字体不查系统；超长表、代码、列表分页；单个超大单元格；`object` 入参；`doc.build` 不出 PDF；20 张 2K 图的体积与耗时 |
| `test_safety.py` | 源码不执行代码；十种不合格 SVG 拒收且不写文件；正文里的原始 HTML 被转义、`javascript:` 链接失效；文件名不能越出 workdir；控制字符拒收；超时结构化 |

**开销**：同一台机器，进程冷启动，含 Word。

| 场景 | 耗时 |
|---|---|
| 投标样例 9 节、2 图、2 表 | `doc.build` 约 0.25 s；`doc.check` 约 0.1 s；`doc.export` Word 约 0.28 s |
| 120 节、13 万字 | `doc.build` 约 1.05 s；`doc.check` 约 0.2 s |
| 投标样例 `doc.export` PDF（6 页，2 张 SVG 转矢量） | 约 0.4 s，188 KB |
| 20 张 2048² PNG（不可压缩噪声，每张 12.6 MB，原图合计 252 MB），一节 | `doc.build` 7.8 s：`.doc.json` 44.9 MB（不含原图），原图 20 个文件，产出合计 420 MB |
| 20 张 2048² PNG（可压缩图案，原图合计 7.2 MB），一节 | `doc.build`（Word 与网页）2.6 s：Word 6.3 MB、网页 9.6 MB；`doc.export` PDF 6.6 s、9.1 MB、20 页 |

## 10 文件

| 文件 | 内容 |
|---|---|
| `doc_tool.py` | process 入口：读一行信封，写一行回执 |
| `model.py` | 文档模型：校验、缺省、图片与 SVG 检查、规范化、doc_sha256 |
| `assemble.py` | 组装：编号、放置、引用、字数、结构提醒、要求追溯 |
| `render.py` | Markdown、产出台数据、单文件网页 |
| `pdf_writer.py` | PDF：reportlab 排版、两遍目录页码、书签与内部链接、SVG 转矢量、缺字与降级提醒 |
| `fonts/` | 随包字体（Noto Serif SC、Noto Sans SC 的常规与粗体静态子集）与 OFL 许可全文，见顶部版本记录 |
| `tools/make_fonts.py` | 由可变字体重新生成 `fonts/` 的脚本（固定时间戳，可复现） |
| `tools/synth.py` | 程序生成测试用 PNG（金样、样例、边界测试共用） |
| `docx_writer.py` | Word：版式、样式、目录域、书签与链接、图（含 SVG）、表格、页码、zip 规范化 |
| `checker.py` | 内置核对与期望清单 |
| `registration.json` | 三件工具的登记资产（TL-6 字段），version 等于 lock hash |
| `mengos-package.json` | 安装包清单：类型、渲染器、lock 覆盖范围、运行环境、替换映射 |
| `golden_cases.json` | 39 条金样（认证 ③） |
| `selection_cases.json` | 选择金样（认证 ⑥），每件应选与不应选各 3 条 |
| `renderer/index.html` | 产出台原型 |
| `samples/` | 投标文件技术部分、读书角方案（无 level 的简写，各节带 id）、英文简报 |
| `lock.py`、`tools/` | lock hash、content_hash、登记资产、金样与样例的生成程序 |
| `tests/` | §9 |
