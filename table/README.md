# table 2.2.0 — 表格交付物包

> 2.2.0（执行令《首发后-table包2.2.0》，调度 11-12 派单；依据 mengosv2 #710 §5.5–§5.8、§6.3、§6.3a，#711 §2.5–§2.7、§六，返工稿 #717（§六 调度已定：层级按一列文字映射、合并行不算格级覆盖、T9-06 判部分），kernel-spec v0.2.98 08 PD-1e、17 TL-30/TL-30b，引擎 #719 对包的两条要求）：G7–G11 与 G17 的包内一项。**只放宽**：只加可选字段、枚举值、函数、核对项、告警码与输出字段；不带新字段的合规输入，表模型、Markdown、CSV 照旧逐字节相同（`tests/test_contribution.py`；入参 schema 剥掉 2.1.0、2.2.0 的新增项后与 1.0.1 逐键相同）。
> - **G17 格公式**：输入列的格可写 `{"$expr": 式}`（数、函数、本行的列、`@行id.列`、`@表id/行id.列`），行带保留键 `$id`；`rows` 上声明 `"x-mengos-expr": true`（引擎沿 properties/items 可达），格的 schema 收 `{"$expr"}`；公式列、编号列的格写 `$expr` 回 BAD_INPUT（工具把关）。整本表一起算、成环报错；每格在 Excel 里写自己的公式（别表加引号）。取整的步长、位数可省（`ceiling(x)`、`roundup(x)`、`round(x)`），导出时补全为 `CEILING(…,1)` 等。不连续函数照 G4 用双精度再算一遍，不同就告警。
> - **G8 编号**：`numbering: seq | outline`；层级来源 `outline_from {column: 一列文字, levels: {文字: 1–4}}`，不收整数层级列。编号每次重算，存为文字（1.10 不会变成 1.1），层级为空不编。
> - **G7 分组与小计**：`group {by: 列}`（组头由工具生成，同组的行排到一起）或 `{by: "outline", rest_label}`（层级 1 的行自己就是组头，仍是数据行）；`subtotals`；行种类 group、subtotal 可在 `row_styles` 着色。Excel：分级显示，小计与合计写 `SUBTOTAL(…, 看得见的数据行)`。
> - **G9 按键合并**：`merge_rows {by, scope, agg: {列: sum | formula}, join}`；含取整的公式列不写 agg 回 BAD_INPUT；带式的列只能 sum；键按 NFKC 去首尾空白后逐字比，写法相近（大小写、x/X/*/＊ 与 ×）的不合并、告警 `merge_key_near`；各行不同又没写口径的列留空、告警 `merge_blank`。明细保留，视图与 Excel 默认折叠在合并行上方；CSV 只写看得见的行；口径逐列写进说明。
> - **G10 跨表**：`sumif(表id.条件列, 本行的列, 表id.求和列)`、`countif`、`total(表id.列)`，按依赖次序算、成环报错，对不上告警 `ref_no_match`；Excel 写等值匹配的 SUMPRODUCT（不用 SUMIF）。派生表 `derive {from, where, by, agg: sum}`，每格是引用来源格的求和公式。`sheet_order` 定表序。
> - **G11 核对**：unique 报出每组重复的每一行；有整行为空的行时内置提示（pass）；`sheet=*`；跨表 `match`、`sum_equal`；`optional 列…` 标明按规定可以整列为空的列；每条问题带 表、行、格、现值、应值（`problems`），回执加一句 `summary`（“全部通过”或几条不通过）。不在 build 里生成问题表。
> - 顺带修正 2.0.x 起的一处：从表模型（`.table.json`）再导出时，百分比列被再除了一次 100。
> - 不做：G6、G12–G15；G16 随局部追问。上线次序：先引擎（#719 已在 main），后包。

> 2.1.0（执行令《首发后-table包2.1.0》，立法者 11-12 批准开工；依据 mengosv2 #710 §6.2、#711、kernel-spec v0.2.98 #713）：G1–G5 与公共项。**只放宽**：只加可选字段、枚举值、函数、告警码与输出字段；不带新字段的合规输入，表模型、Markdown、CSV 与 1.0.1 逐字节相同，产出台数据只多 `totals_fn` 一个输出字段，xlsx 逐格的值不变（`tests/test_contribution.py`）。
> - **第 0 步四个条件**：C1 样式跟着行走——行里的保留键 `$style`（`"x-mengos-display": true` 声明，17 TL-30 v0.2.98），不设按行号寻址的 `cell_styles`，`row_styles` 只按行种类（2.1.0 只有 total）。C2 恒真条件格式——LibreOffice 24.2.7.2 实测：两条规则同时命中同一格时**不按属性合并**（`readings/table-2.1.0-cf/读数-LibreOffice.md`），照 #711 §2.2 第 3 条退路：叠加口径改为与 Excel 相同（规则 > 格 > 行 > 列默认），**不写恒真规则**；Excel、WPS 的读数单在同目录，交本地施工方填。C3 取整与比较的参数按 15 位有效数字归整，Excel 一侧写 `ROUND(x,14-INT(LOG10(ABS(x)+(x=0))))`；不连续的函数再用双精度算一遍，不同就告警 `excel_float`，点名到格。C4 精度口径 b：公式列照旧逐行舍入，Excel 公式外包 `ROUND(…, 位数)`，合计行的平均值等也外包同样位数的 ROUND。
> - **G1 样式层与条件规则**：样式 `{fill, color, bold, italic}`，颜色取 12 色命名色板（浅色、深色主题与 Excel 各一套色值，也认英文名）。`columns[].style` 列默认、`header_style` 表头、`row_styles [{kind: total}]` 合计行、行里 `$style {row, cells}`。`rules` 有序、先命中先得、逐属性，条件直接写条件式（与公式同一种写法），`apply_to` 缺省给条件里的列、`"row"` 整行或列名数组；色阶 `{scale: {column, from, to}}`。规则只管数据行；不标 by-id，给了就整组替换；每张表最多 50 条。Excel 里写成公式型条件格式（带 COUNT/LEN 防空格当 0）与 2_color_scale，说明表列出规则次序。
> - **G2 函数**：roundup、rounddown、ceiling、floor（照 Excel），比较 `> >= < <= = <>`，and、or、not、if（两支暂不收数字常数；结果是文字时 type 写 text），total(列)、cumsum(列)；数后可带 %，日期写 `"YYYY-MM-DD"`。
> - **G3 合计口径**：fn 加 `formula`（合计行按本列公式重算，Excel 写合计行版本的公式）与 `none`；产出台数据带 `totals_fn`，悬停显示每格的算法；告警 `ratio_total`（比率列配了 sum、avg）与 `rounded_sum`（逐行舍入后相加与先加后舍入不同，T3-09）。
> - **G4**：同 C3、C4；公式引用的格有空时 Excel 写 `IF(COUNT(…)=n, 原式, "")`，与产出台“有空就空”一致。登记与说明照实写“产出台与 Excel 重算一致；个别边界值不一致时会告警”。
> - **G5 显示格式**：日期列 `date_format`（五种），数值列 `thousands`；CSV 仍写 ISO 日期与原值。
> - **公共**：三件工具的描述与 constraints 随改，non_goals 去掉“不做条件格式”；选择金样加 3 条；金样 40 → 76 例（测试集 24 条各一例另加边界与报错）；Excel 往返 `tools/lo_roundtrip.py`（LibreOffice 无头重算读回逐格比，45 例 0 处不一致）。渲染器按视图画样式（浅色、深色两套），说明区列出规则。
> - **补（立法者 11-12：表格数字默认就是数字）**：登记描述加一句“表格里能读成数的值一律存为数字，可以计算；不提供把数字列改成文本。用户要文本，如实说明：下载后在 Excel 里改。”包的行为不改（类型推断本来数字优先，xlsx 照旧写数字型，G5 不加“以文本存数字”的格式）。告警 numeric_as_text 等编号一类标识符的口径确认后再做，2.1.0 不做；编号照旧存文字。
> - 不做：G6；G8 的 seq 随 2.2.0。

> 2.0.1（立法者验收页面稿 表格说明区去重-2026-11-10；只改渲染器，认证继承 TL-25）：上方压成一行（副标题·日期＋搜索＋“N 行 × M 列”，行列数只出现一次；单表只显示副标题一句，没有才用表说明）；表格区撑满剩余高度，行少补空行到底，表头与合计固定；公式·来源·假设收成紧贴合计行的一行、点开在表格区内向上推，条目带 data-kind/data-key 钩子。工具代码、registration.json、schema、金样、导出均未改，lock 不变，只有 content_hash 变。

> 2.0.0（承执行令-2026-11-05-table包2.0.0 K 支；17 TL-30a）：table.build 接入贡献型声明，大表可以分多次写、由引擎累积，不再要求模型一次输出整张表。**输入契约收紧，所以升大版本。**
> - **破坏性变更①：table.build 里 sheets 的每张表 id 必填**（原为可选）。`required:["id"]` 写在 if/then/else 之外，整体写法与增量都生效。不带 id 的表没法被后续增量定位。table.check、table.export 的入参照 1.0.1，id 仍可选，照旧接受 1.x 的表对象。
> - **破坏性变更②：被公式或合计引用的列必须显式写 type**（只做 count 的列也要写，text 即可），缺了回 BAD_INPUT，报错点名是哪一列、被哪个公式或合计引用。不写 type 的列按行内容推断，零行或分批追加时推断结果会随行数变，被引用列于是时而能算、时而报错。不被引用的列仍按内容推断。只对 table.build 生效。
> - 数组行照旧严格：格数等于列数，或（有公式列时）等于非公式列数，其余拒收，不补 null。格数不符时报错带行号、期望与实际格数。分批追加行请用对象行（按列的 key 或标题对上）；改了列要把已有的数组行按新列重写。
> - 没有行的表（零行、rows 缺席）table.build 照常交付表头，另给 `no_rows` 警告。
> - table.build 顶层加 base 槽（`x-mengos-base`）；`table.sheets` 标 `x-mengos-merge {mode: by-id, id: id, label: name}`（不设 fill，与 document 的 `doc.tables` 同形：骨架里每张表是 `{id, label, rows: {$count: n}}`，rows 缺席的表不出 rows 键），`table.sheets[].rows` 与单表写法的 `table.rows` 标 `{mode: append}`；`columns` 不标（新值整体覆盖：行依赖列的顺序，且列的字符串简写没有 id）。必填放宽为 `if {required:[base]} then {required:[base]} else {required:[table]，table.title、sheets[].columns 必填}`。
> - 不带 base 的合规输入，产出与 1.0.1 逐字节相同（`tests/test_contribution.py`，金样在 1.0.1 代码上录，见 `tests/fixtures/whole-mode-1.0.1.json`）。
> - 包内预检三项：标注合法、base 槽唯一、引擎合并金样（`tests/fixtures/contribution/`，引擎夹具逐字节拷贝，来源与 sha256 见 `SOURCE.json`）；另有表专属合并金样 `tests/fixtures/table-merge-cases.json`，每例合并后再走一遍 build。合并代数的 Python 参照实现 `tests/contribution_ref.py` 与 document 包同一份。
> - 清单加别名：`title`「表格」，`tool_titles` 各件「生成表格」「核对表格」「导出表格」（只供显示，不在 lock 内）。

码本形态 `data_table` 的实现：把模型给出的表格计划（列、行、公式列、合计）变成可交付的表格，带 Excel / CSV / Markdown 三种文件与网页渲染器。

## 工具

| 工具 | 做什么 | 入 → 出 |
|---|---|---|
| `table.build` | 规范化表格计划，算公式列与合计，写出 `.table.json`、`.view.json`、`.md`，另按需 `xlsx`（默认）/`csv` | `table_plan` → `table` |
| `table.check` | 按 `expect` 逐行核对（列、行数、唯一、非空、范围、合计、排序），另有内置检查（空列、占位词、除零） | `table` → `verdict` |
| `table.export` | 从表格对象导出 `xlsx` / `csv` / `md` / `json` | `table` → `table_file` |

三件都是 T1、无副作用、无网络，进程执行器（`table_tool.py`，同步）。

## 表格计划写法（摘要）

```json
{"title": "钢材参数", "columns": ["牌号", {"title": "密度", "type": "number", "unit": "g/cm³"},
  {"title": "单价", "type": "money"}, {"title": "数量", "type": "integer"},
  {"title": "金额", "type": "money", "formula": "单价*数量"}],
 "rows": [["Q235", 7.85, 4.2, 100]], "totals": ["金额"]}
```

- 列类型：text / integer / number / money / percent（写百分点：12.5 即 12.5%）/ date / bool；不写就推断。被公式或合计引用的列必须写 type（2.0.0）。
- 公式列只能引用输入列和它左边的公式列；支持 + - * / 括号、round/abs/min/max，2.1.0 起另有 roundup/rounddown/ceiling/floor、比较与 and/or/not/if、total/cumsum；除零留空并给警告。
- 样式与条件规则（2.1.0）：见上方 2.1.0 说明与登记里的描述。
- 多张表用 `{"sheets": [{"id": "s1", …}, …]}`，table.build 里每张表的 id 必填（2.0.0）；`freeze_cols` 冻结左侧列。
- 上限：20 张表、200 列、10 万行、100 万格。
- 1.0.1 起，`table.build` 的 `rows`（单表与各 sheet）声明为数据字段（`"x-mengos-data": true`，17 TL-30）：引擎派单前核对行里每个数的证件（原文数、`{"$calc": 算式}` 或 `{"$ref": 计算器回执}`，08 PD-1e），算式由平台计算器求值后再交给本工具。工具本身行为不变。

## 自检

```
uv sync --frozen
.venv/bin/python -m pytest -q          # 单测
.venv/bin/python tools/run_golden.py   # 金样 112 例
.venv/bin/python tools/lo_roundtrip.py # Excel 往返：LibreOffice 无头重算读回逐格比（要 soffice 与系统 Python 的 uno）
```

改动源码后依次运行 `python tools/make_registration.py`、`python lock.py`、`python tools/make_package.py`。

## 文件

- `mengos-package.json` 清单；`registration.json` 工具登记（TL-6）
- `renderer/index.html` 渲染器（契约 v0.1，full + embed，无网络）
- `golden_cases.json`、`selection_cases.json`、`tools/run_golden.py` 认证材料
- `samples/` 四张样例表
- `readings/table-2.1.0-cf/` C2 恒真条件格式实测：样例工作簿、LibreOffice 读回、Excel 与 WPS 读数单
