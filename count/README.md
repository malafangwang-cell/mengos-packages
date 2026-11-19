# count 0.2.2 · 工程文件读取器

行式数据与结构化附件文件上的确定性计数工具包。四件工具，T1、效应 none、process 执行器、不出网、不调模型；同一入参两次输出逐字节相同。包标识 `count`、工具标识与类型名不变，中文名 0.2.0 起为“工程文件读取器”（立法者 2026-11-19 定）。

依据：mengosv2 `docs/alignment/arch/设计-确定性计数工具-2026-11-18.md`（PR #916）第一阶段；`docs/alignment/arch/设计-附件按引用由工具读取-2026-11-19.md` §六、§十一 T-1、§十六、§十七、§二十一；kernel-spec 17 TL-9d。

| 工具 | 做什么 | 回执要点 |
|---|---|---|
| `count.rows` | 按条件数行；分组；列合计（G-1）；“或”条件 `any_of`（G-2）；组数 `groups_count`（G-3）；一列或两列数值的分布（不同取值数、步长、等距、网格缺位）；`list` 出逐行清单与稳定序号 | `count`、`groups`、`aggregate`、`distribution`、`items`、`source`、`checks`、`assumptions` |
| `count.series` | 乘积串 `左*右=合计` 的解析与验算（与测量列比对）；首尾相接的区间连成链 | `product.hits[]`（`left/right/stated_total/product_ok/measure_ok`）、`chain.chains[]`（`segments/values/uniform/pitch/total`） |
| `count.coverage` | 数苹果：清单 + 已贴标记 → 未贴清单 | `unmarked_count`、`unmarked`、`unknown_marks`、`duplicate_marks`、`total_ok` |
| `count.agree` | 两种数法互证（G-4）：相等或差一个定数 | `holds`、`diff_actual` |

## 产物类型

四件工具的产物类型是包自带的 `count_receipt`、`count_check`（新根类型，不挂在平台 number、verdict 之下）。PLAN 按类型匹配资源，所以要求通用数值或判定的任务不会选中计数工具；要用计数工具，由域包在工具表里显式列出。

## 通用性

接口只认“行、条件、清单与标记、数值间隔”。执行体不认任何行业词；“这一列是 x 坐标”“x 向 33 个位置就是 33 列”都是调用方的判断。换行业只换域包，不改工具（设计 §十一、§十二）。

## 来源与读取器

`source` 三选一：

- `{file, section, unit?}`（0.2.0，按文件读）：`file` 声明 `x-mengos-attachment-file`（17 TL-9d）。模型只写附件引用；引擎派单时把原件与存储服务入库时存下的完整解析结构放进工作目录下的只读输入子目录，把 `file` 换成 `{path, sha256, bytes, media_type, parsed?: {path, sha256, parser}}`，信封带 `workdir`。执行体（`file_source.py`）：
  - 核原件与解析结构的 sha256 与字节数；`parsed.parser`（存储服务记在文件上的解析核串，引擎原样转交）与结构里记的 `library` 须与本包带的解析库同一版。任一不过 ⟹ `BAD_INPUT`，不出数。
  - 默认读解析结构，不重新解析；结构里标 `stored: false` 的明细节、或没有解析结构时，用包里带的同一份解析库（`cadlib/`）回原件读，以 `run(..., detail_cap={节名: None})` 取消明细上限、全部留存；回原件读时只在工作目录里临时写解析输出，读完即删。
  - `section` 写节名：单元文本里的各节（文字、尺寸标注、图块插入、闭合轮廓、线段统计、丢失声明、图块）与三类明细（线段明细、嵌套插入、未插入图块文字）；行前加一列“单元”，行序号写成 `单元/节/第几条`。`unit` 只读一个单元（`图幅k` 与 `Sk` 同指、空白不计）。表单元（GFM）不分节，按节读时列在 `units_without_section`。
  - 逐节核读到条数 = 声明条数；回执 `source` 回显 `read_from`、`file`（哈希与字节数）、`parser`、`scope`、`unparsed`（这份图里标为未解析的类型与处数）、`units_read`、`rows_declared`、`rows_read`、`sections_available`（各节与列名）、`units_without_section`。写错节名 ⟹ 失败消息列出有哪些节；节名正落在未解析的类型上 ⟹ 答“拿不到”并给处数，不出数。
  - 不设行数上限，不挂转录假设。文件内容不进回执。

- `{columns, rows, declared?, label?}`：列名与逐行单元格（单元格是字符串、数或 null）。`rows` 声明为数据字段（17 TL-30，`x-mengos-data`），行里的数要有证件（08 PD-1e）。
- `{text: [...], reader, section?}`：原文一段或多段。`reader`：
  - `mengos-cad-v1`：图纸解析单元。节头 `#名称（列|列）共 N 条|组`，按行块再切时 `｜本块第 a–b 条` 与 `#分块 k/n`。读到的行数须等于声明条数、各块行号连续，否则 `BAD_INPUT`，不出数；没有声明条数的节（图块插入汇总）要求分块给全。最后一列吸收多余的 `|`。格式由 mengosv2 `vetc/tests/cad-count-contract.test.ts` 钉住，解析改格式时两边一起动。
  - `gfm`：首行表头、次行分隔的表格；续块重复表头；`\|` 转义；带 `#表 T1｜…｜R×C` 头时按 R−1 核对行数。

调用方给出的两种来源（回执 `source.mode = "inline"`）行数上限 **50**（`MAX_INLINE_ROWS`，登记在 `capability.constraints.max_inline_rows`），回执带假设声明“来源行由调用方转录，程序未与原文逐字核对”（17 TL-22a）。

## 清单分页与 coverage 的新取法（0.2.0）

- `count.rows` 的 `list` 一次最多 2000 条；超过时用 `offset`、`limit` 分批取，回执 `total_matched` 始终是命中的总条数。
- `count.coverage` 的清单可取自按文件读的行（`inventory.source.file`）；标记可写成 `{content, field}`：`content` 多由判据核验入参的 `$best` 换成当前产出，程序在其中按键名 `field` 逐层收集处理记录（数组逐条、对象一条）。清单与标记都由程序取得时回执不挂假设。

## 解析库（按版本带入）

`cadlib/`（`VERSION`、`cadx.py`、`mengos_cad/`）与 `requirements-cad.txt` 逐字节拷自 mengosv2 `vetc/cadlib/` 与 `vetc/requirements-cad.txt`，由 `tools/vendor_cadlib.py <vetc/cadlib> --version V --sha256 H` 带入（现为 mengos-cad 1.0.1）：带入后重算解析库版本，与给定的不同即不写。`cadlib.lock.json` 记名字、规格版本、库版本、内容哈希与逐文件 sha256。读文件的三件在登记里声明 `parsers`（安装与认证时由引擎与存储服务登记的现行版本核对，对不上判不过）与 `attachment_file`（接受的媒体类型闭集、个数与大小上限）。依赖按 `requirements-cad.txt` 的钉版写进 `pyproject.toml` 与 `uv.lock`，测试钉住两边一致。

## 进模型上下文的文字（提示词禁触区）

`registration.json` 里进模型上下文的文字——`input_schema` 各层 `description`、`capability.examples`、`input_example`，以及包清单 `title / summary / tool_titles`——单一来源是 `tools/make_registration.py`。0.2.0 新增与改写的只有包中文名、包摘要，与 `source.file`、`source.section`、`source.unit`、`offset`、`limit` 五处说明，原文照立法者 2026-11-19 批准的文字；其余沿用 0.1.1。改任何一句须经立法者定稿，改后重算 lock 并重新认证。

## 构建与测试

```
python tools/make_registration.py   # 登记
python lock.py                      # lock hash → registration.json
python tools/make_package.py        # content_hash → mengos-package.json
uv run --frozen --group dev python -m pytest -q tests
uv run --frozen python tools/run_golden.py
```

按文件读的测试与金样（`tests/test_file_source.py`、`golden_cases.json` 里带 `fixture` 的条目）现场生成合成图纸：生成器 `tests/fixtures/dxf_gen/` 是 mengosv2 `vetc/tests/helpers/cad_fixtures.py` 与 `vetc/cadlib/golden/features.py` 的副本，用包里带的解析库出解析结构，摆成引擎交文件后的样子（`tools/fixture_files.py`）。不入真图。

`tests/fixtures/*.units.json` 是 mengosv2 `vetc/src/cadx.py`（主干 e3023866）对 `vetc/tests/helpers/cad_fixtures.py` 里 `rack`、`rack_gap`、`rack_bad`、`rack_long` 四个合成 DXF 的真实解析输出（只取区块与图块插入汇总单元），供 `tests/test_acceptance.py` 跑设计 §八 的验收用例。

## 版本记录

- 0.1.0（2026-11-18）：首版，四件工具，第一阶段（inline 来源、行数上限 50）。未入册。
- 0.1.1（2026-11-18）：产物类型改用包自带的两个新根类型 `count_receipt`（count.rows、count.series）与 `count_check`（count.coverage、count.agree），不再登记在平台的 number、verdict 上，PLAN 不把它们匹配到通用目标，只在域包显式列出时使用（立法者 11-18 裁定，经调度转）。工具逻辑不变。
- 0.2.0（2026-11-19）：中文名改为“工程文件读取器”，摘要随改；按文件读的来源（`source.file`，17 TL-9d；默认读解析结构，结构里没有的用带入的解析库回原件读）；按版本带入解析库 mengos-cad 1.0.0；`count.rows` 清单分页（`offset`、`limit`、`total_matched`）；回执回显节与列、未解析清单；`count.coverage` 清单取自文件、标记取自产出内容加字段名；登记 `parsers`、`attachment_file`；`runtime.process.workdir` 为 true，Python ≥ 3.11；`cost.timeout` 120 秒。
- 0.2.1（2026-11-19）：带入解析库 mengos-cad 1.0.1（`run()` 新增可选参数 `detail_cap`；立法者 2026-11-19 批乙方案）；回原件读改用这个参数，去掉 0.2.0 运行时临时调整解析库全局上限的做法。行为与 0.2.0 相同。
- 0.2.2（2026-11-19）：读文件三件 `attachment_file.max_bytes` 由 50 MiB 改为 256 MiB（并到上传上限；立法者 2026-11-19 裁，目标图纸 115 MB、162 MB 曾被挡住）；`max_total_bytes` 400 MiB 不变（不小于单件上限）。其余一字不改，进模型的文字零改动。
