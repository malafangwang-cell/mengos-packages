# table 2.0.0 — 表格交付物包

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
- 公式列只能引用数值列和它左边的公式列；支持 + - * / 括号、round/abs/min/max；除零留空并给警告。
- 多张表用 `{"sheets": [{"id": "s1", …}, …]}`，table.build 里每张表的 id 必填（2.0.0）；`freeze_cols` 冻结左侧列。
- 上限：20 张表、200 列、10 万行、100 万格。
- 1.0.1 起，`table.build` 的 `rows`（单表与各 sheet）声明为数据字段（`"x-mengos-data": true`，17 TL-30）：引擎派单前核对行里每个数的证件（原文数、`{"$calc": 算式}` 或 `{"$ref": 计算器回执}`，08 PD-1e），算式由平台计算器求值后再交给本工具。工具本身行为不变。

## 自检

```
uv sync --frozen
.venv/bin/python -m pytest -q          # 单测
.venv/bin/python tools/run_golden.py   # 金样 40 例
```

改动源码后依次运行 `python tools/make_registration.py`、`python lock.py`、`python tools/make_package.py`。

## 文件

- `mengos-package.json` 清单；`registration.json` 工具登记（TL-6）
- `renderer/index.html` 渲染器（契约 v0.1，full + embed，无网络）
- `golden_cases.json`、`selection_cases.json`、`tools/run_golden.py` 认证材料
- `samples/` 四张样例表
