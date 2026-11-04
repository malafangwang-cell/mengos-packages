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
| M8 | contribution_ref.py：named-lines 同名行追加而不替换 | `test_shared_reference_implementation_matches_record`、引擎夹具 merge-algebra「U3 named-lines 同名替换…」、`test_replacing_a_named_line_keeps_its_position…`（3 红） |
| M9 | contribution_ref.py：by-id 命中时整元素替换 | 共享实现记录、merge-algebra 四条（5 红） |
| M10 | contribution_ref.py：append 去重 | 共享实现记录、merge-algebra「U2 append 不去重…」（2 红） |
| M11 | contribution_ref.py：by-id 触及键把 id 键也算进去 | 共享实现记录、merge-touched-keys 八条、disjoint_pairs 一条（10 红） |
| M12 | contribution_ref.py：append 字段不算整体一个键 | 共享实现记录、merge-touched-keys 两条 append（3 红） |
| M13 | contribution_ref.py：空槽清单不认 fill | 共享实现记录、merge-empty-slots 两条（3 红） |

> 自 2.5.0 之后的变更（tests 内部，不动 lock）：合并金样改为引擎自己的夹具（`merge-algebra.json`、`merge-touched-keys.json`、`merge-empty-slots.json`，逐字节拷贝，来源 commit 与 sha256 见 `fixtures/contribution/SOURCE.json`），原先的 named-lines 子集转写件已删；夹具全量跑，其中 named-lines 相关条目覆盖 cad 的 `plan`。基线 74 项全过。M9–M13 是对 contribution_ref.py 的变异；因 `test_shared_reference_implementation_matches_record` 核该文件 sha256，任何对它的改动都会多红这一项。
