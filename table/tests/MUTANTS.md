# 变异读数（table 2.0.0）

补裁三（sheets 去掉 fill）之后全部重跑一遍，读数如下。

每条变异只改一处，在包的临时副本上跑 `pytest -q`，必须变红；跑完丢弃副本，包本身不动。
改 `registration.json` 或执行体源文件的变异，lock 与 content_hash 的两条自检（`test_version_is_current_lock_hash`、`test_content_hash_is_current`）必然一起红，下表不再重复列。

| # | 变异（改的位置） | 红的用例（不含上述两条） |
|---|---|---|
| MTB-1 | registration.json：去掉 table.build 的 `sheets` by-id 标注 | `test_annotation_declarations_on_table_build`、`test_tb10_skeleton_of_table_build…`、`test_incremental_rows_merge…`、TB-5 合并金样 6 例（按 id 加 sheet、改 caption 与 name、sheet 内追加、columns 整替两例、sheet 缺 id）（9 红） |
| MTB-2 | registration.json：table.build 两处 `rows` 去掉 append 标注 | `test_annotation_declarations_on_table_build`、`test_tb10_skeleton_of_table_build…`、`test_incremental_rows_merge…`、TB-5 合并金样 4 例（单表追加、sheet 内追加、按 id 加 sheet、columns 整替配合对象行）（7 红） |
| MTB-3 | model.py `_row`：比列数短的数组行补 null | `test_array_row_length_mismatch_reports…`、`test_short_array_row_is_not_padded_with_null`、TB-5「columns 整替而原有的是数组行」（3 红） |
| MTB-4 | registration.json：table.check 也带贡献词汇（base 槽与 sheets by-id） | `test_check_and_export_input_schemas_have_no_contribution_vocabulary`、`…_equal_1_0_1`、`test_exactly_one_base_slot…`、`test_table_build_is_contribution_tool…`（4 红） |
| MTB-5 | model.py `_sheet`：被引用列不要求 type（去掉 `_declared_types` 调用） | `test_referenced_column_without_type_is_bad_input_naming_it` 4 例、`test_referenced_column_rule_also_in_sheets`（5 红） |
| MTB-6 | registration.json：sheets 标注加回 `fill: "rows"`（补裁三之前的写法） | `test_annotation_declarations_on_table_build`、`test_tb10_skeleton_of_table_build…`（TB-10）、`test_incremental_rows_merge…`（3 红） |
| M6a | 守恒变异（施工纪律第 5 条③）：`no_rows` 警告无条件生效（去掉“没有行”的判断） | TB-6 `test_whole_mode_output_byte_identical_to_1_0_1` 全部 6 例，及 TB-5 4 例、`test_unreferenced_columns_still_inferred`、`test_tables_without_rows…[sheet 无行]`（12 红） |
| M6b | 守恒变异：要求 type 对所有列无条件生效（不论是否被引用） | TB-6 5 例（只有全部列都写了 type 的 `div_zero_and_percent` 不红），及金样运行、样例、格式、确定性等 26 条（31 红） |
| M6c | 守恒变异：2.0.0 的 build 口径对核对、导出也生效 | `test_check_and_export_keep_1_x_typing_rules`（1 红） |

TB-6 的金样（`fixtures/whole-mode-1.0.1.json`）在 table 1.0.1 代码上录（lock 0c8725745e60700f），输入带非规范形：首尾空白、键序打乱、数字写法 `4` / `4.0` / `"1,200"` / `"¥95"`、对象行与只写非公式列的短数组行。
