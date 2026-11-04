# test_contribution.py 变异读数（cad 2.5.0）

每条变异只改一处，跑 `pytest tests/test_contribution.py`，必须变红；跑完恢复。基线：49 项全过。

| # | 变异（改的位置） | 红的用例 |
|---|---|---|
| M1 | registration.json：plan 的行名正则改成无捕获组（且不认汉字、点、全角冒号） | 标注合法、恰一个捕获组、正则与解析器一致、五条行名读法、分次合并、替换留位、K 集、骨架（12 红） |
| M2 | `else.required` 置空（整体写法 plan 不再必填） | `test_whole_mode_schema_equals_2_4_4_schema`、`test_whole_mode_still_requires_plan…`（2 红） |
| M3 | 顶层再加一个 `x-mengos-base` 槽 | `test_exactly_one_base_slot…`、`test_cad_build_is_contribution_tool…`、`test_whole_mode_schema_equals…`（3 红） |
| M4 | 行名正则的名字字符类去掉点 | `test_name_regex_reads_names_the_way_the_parser_does[底座.一…]`（1 红） |
| M5 | `plan` 的标注 mode 改成 append | 标注合法、分次合并、替换留位、不替换追加、K 集、骨架（6 红） |
| M6 | 行名正则只认半角冒号 | `test_name_regex_reads_names…[base： …]`（1 红） |
| M7 | `then.required` 改成 `[plan]`（带 base 时仍要整份 plan） | `test_whole_mode_still_requires_plan_and_delta_does_not`（1 红） |
| M8 | contribution_ref.py：named-lines 同名行追加而不替换 | `test_shared_reference_implementation_matches_record`、金样 `U3-named-lines-replace-append`、`test_replacing_a_named_line_keeps_its_position…`（3 红） |
