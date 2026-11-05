# table 1.0.1 — 表格交付物包

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

- 列类型：text / integer / number / money / percent（写百分点：12.5 即 12.5%）/ date / bool；不写就推断。
- 公式列只能引用数值列和它左边的公式列；支持 + - * / 括号、round/abs/min/max；除零留空并给警告。
- 多张表用 `{"sheets": [...]}`；`freeze_cols` 冻结左侧列。
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
