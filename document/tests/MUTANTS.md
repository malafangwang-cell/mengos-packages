# test_contribution.py 变异读数（document 2.0.0）

每条变异只改一处，跑 `pytest tests/test_contribution.py`，必须变红；跑完恢复。M1–M9 是对 1.3.0 的 schema 做的，2.0.0 把 id 必填改成恒必填后重跑了一遍，读数见下（M5 改写为 M5′，新增 M10、M11）。

| # | 变异（改的位置） | 红的用例 |
|---|---|---|
| M1 | registration.json：删 `else…sections.items.required`（整体写法丢节标题必填） | `test_whole_mode_schema_equals_1_2_5_schema_plus_section_id`、`test_whole_mode_requires_section_id_and_the_original_fields`（2 红） |
| M2 | `else.required` 置空（整体写法 doc 不再必填） | 同上两项（2 红） |
| M3 | 顶层再加一个 `x-mengos-base` 槽 | `test_exactly_one_base_slot…`、`test_doc_build_is_contribution_tool…`、`test_whole_mode_schema_equals…`（3 红） |
| M4 | `name` 属性标 `by-id`（标在字符串上，非法标注） | `test_annotations_legal_in_every_unit[doc.build]`（1 红） |
| M5′ | 删去 `sections.items.required` 里的 `id`（节 id 退回可选） | `test_whole_mode_schema_equals…`、`test_element_id_is_required_always_outside_the_branches`、`test_whole_mode_requires_section_id…`、`test_delta_with_base…`（4 红） |
| M6 | base 槽去掉 `type` | `test_base_slot_text_and_type…`、`test_doc_build_is_contribution_tool…`、`test_delta_with_base…`（3 红） |
| M7 | 把 `sections` 的标注挪进 `then`（引擎不可达） | `test_annotation_declarations_on_doc_build`、`test_annotations_are_only_on_reachable_paths`、`test_element_id_is_required_always…`、`test_incremental_contributions…`、`test_overlapping_deltas…`、`test_skeleton_of_doc_build_first_version…`（6 红） |
| M8 | contribution_ref.py：by-id 命中时整元素替换而非递归合并 | 引擎夹具 merge-algebra 的「U1 命中 id…」「U1 元素内嵌套…」「U2 append 不去重…」「U2 append 的 P 缺席…」四条，及 `test_incremental_contributions…`（5 红） |
| M9 | contribution_ref.py：append 去重 | merge-algebra「U2 append 不去重…」（1 红） |
| M10 | 把节 id 必填从主体挪回 `then` 分支（即 1.3.0 的写法） | `test_whole_mode_schema_equals…`、`test_element_id_is_required_always_outside_the_branches`、`test_whole_mode_requires_section_id…`（3 红） |
| M11 | `figures.items.required` 里删 `id`（四个容器之一退回可选） | `test_whole_mode_schema_equals…`、`test_element_id_is_required_always…`、`test_delta_with_base…`（3 红） |
| M12 | contribution_ref.py：空槽清单不认 fill（`empty_slots` 永不入账） | merge-empty-slots 的「fill=字段名…」「填一减一…」，及 `test_incremental_contributions…`（3 红） |
| M13 | contribution_ref.py：named-lines 同名行追加而不替换 | merge-algebra「U3 named-lines 同名替换…」（1 红） |
| M14 | contribution_ref.py：by-id 触及键把 id 键也算进去 | merge-touched-keys 八条、disjoint_pairs 一条，及 `test_overlapping_deltas…`（10 红） |
| M15 | contribution_ref.py：append 字段不算整体一个键（退回字段路径） | merge-touched-keys 的两条 append，及 `test_overlapping_deltas…`（3 红） |

> 自 2.0.0 之后的变更（tests 内部，不动 lock）：合并金样改为引擎自己的夹具 `merge-algebra.json`、`merge-touched-keys.json`、`merge-empty-slots.json`（逐字节拷贝，来源 commit 与 sha256 见 `fixtures/contribution/SOURCE.json`），原先包侧转写的 `merge_golden.json` 已删。M8–M9 的红读数随之改到引擎夹具的条目；M10、M11 编号被 schema 变异占用，引擎夹具变异记为 M12–M15（M14=触及键含 id，M15=append 不整体）。
