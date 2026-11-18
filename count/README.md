# count 0.1.0 · 确定性计数

行式数据上的确定性计数工具包。四件工具，T1、效应 none、process 执行器、只用 Python 标准库、不出网、不调模型；同一入参两次输出逐字节相同。

依据：mengosv2 `docs/alignment/arch/设计-确定性计数工具-2026-11-18.md`（PR #916）§三、§四、§七、§十一、§十二。本版只做设计里的**第一阶段（零引擎改动）**。

| 工具 | 做什么 | 回执要点 |
|---|---|---|
| `count.rows` | 按条件数行；分组；列合计（G-1）；“或”条件 `any_of`（G-2）；组数 `groups_count`（G-3）；一列或两列数值的分布（不同取值数、步长、等距、网格缺位）；`list` 出逐行清单与稳定序号 | `count`、`groups`、`aggregate`、`distribution`、`items`、`source`、`checks`、`assumptions` |
| `count.series` | 乘积串 `左*右=合计` 的解析与验算（与测量列比对）；首尾相接的区间连成链 | `product.hits[]`（`left/right/stated_total/product_ok/measure_ok`）、`chain.chains[]`（`segments/values/uniform/pitch/total`） |
| `count.coverage` | 数苹果：清单 + 已贴标记 → 未贴清单 | `unmarked_count`、`unmarked`、`unknown_marks`、`duplicate_marks`、`total_ok` |
| `count.agree` | 两种数法互证（G-4）：相等或差一个定数 | `holds`、`diff_actual` |

## 通用性

接口只认“行、条件、清单与标记、数值间隔”。执行体不认任何行业词；“这一列是 x 坐标”“x 向 33 个位置就是 33 列”都是调用方的判断。换行业只换域包，不改工具（设计 §十一、§十二）。

## 来源与读取器

`source` 二选一：

- `{columns, rows, declared?, label?}`：列名与逐行单元格（单元格是字符串、数或 null）。`rows` 声明为数据字段（17 TL-30，`x-mengos-data`），行里的数要有证件（08 PD-1e）。
- `{text: [...], reader, section?}`：原文一段或多段。`reader`：
  - `mengos-cad-v1`：图纸解析单元。节头 `#名称（列|列）共 N 条|组`，按行块再切时 `｜本块第 a–b 条` 与 `#分块 k/n`。读到的行数须等于声明条数、各块行号连续，否则 `BAD_INPUT`，不出数；没有声明条数的节（图块插入汇总）要求分块给全。最后一列吸收多余的 `|`。格式由 mengosv2 `vetc/tests/cad-count-contract.test.ts` 钉住，解析改格式时两边一起动。
  - `gfm`：首行表头、次行分隔的表格；续块重复表头；`\|` 转义；带 `#表 T1｜…｜R×C` 头时按 R−1 核对行数。

第一阶段来源一律由调用方给出（回执 `source.mode = "inline"`），行数上限 **50**（`MAX_INLINE_ROWS`，登记在 `capability.constraints.max_inline_rows`），回执带假设声明“来源行由调用方转录，程序未与原文逐字核对”（17 TL-22a）。引擎按引用取解析单元（设计 E-A）之前没有 `resolved` 模式；几百行的逐条坐标在入口报 `BAD_INPUT`。

## 草案说明（提示词禁触区）

`registration.json` 里进模型上下文的文字——`input_schema` 各层 `description`、`capability.examples`、`input_example`，以及包清单 `title / summary / tool_titles`——是**施工方草案，待立法者定稿**。单一来源是 `tools/make_registration.py`；定稿只改这些字符串，结构不动，改后重算 lock 并重新认证。

## 构建与测试

```
python tools/make_registration.py   # 登记
python lock.py                      # lock hash → registration.json
python tools/make_package.py        # content_hash → mengos-package.json
uv run --frozen --group dev python -m pytest -q tests
uv run --frozen python tools/run_golden.py
```

`tests/fixtures/*.units.json` 是 mengosv2 `vetc/src/cadx.py`（主干 e3023866）对 `vetc/tests/helpers/cad_fixtures.py` 里 `rack`、`rack_gap`、`rack_bad`、`rack_long` 四个合成 DXF 的真实解析输出（只取区块与图块插入汇总单元），供 `tests/test_acceptance.py` 跑设计 §八 的验收用例。

## 版本记录

- 0.1.0（2026-11-18）：首版，四件工具，第一阶段（inline 来源、行数上限 50）。
