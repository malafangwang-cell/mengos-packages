"""0.2.3 逐项一致对照的用例矩阵（tests/test_streaming.py 与生成期望值共用）。

0.2.3 起 count.rows 不建行表、边读边算。这里列出若干合成图纸 × 节 × 查询（条件、分组、合计、分布、分页、解析不了的格）
× 两条取法（读解析结构 / 回原件读）；期望值 tests/fixtures/stream_equiv.json 由 0.2.2（建行表的旧实现）跑出，
记每条回执 output 规范化后的 sha256 与条数。
"""
FIXTURES = ("f_seg_exact", "f_nested_owner", "rack", "d1")
# 节 → (文字列, 数值列, 二维分布的 y 列或 None)
SECTIONS = {
    "线段明细": ("图层", "长度", None),
    "嵌套插入": ("名称", "x", "y"),
    "图块插入": ("名称", "x", "y"),
    "文字": ("图层", "字高", None),
}


def queries(section: str) -> dict:
    t, n, y = SECTIONS[section]
    dist = {"x": n, "tol": 0} if y is None else {"x": n, "y": y, "tol": 1}
    return {
        "plain": {},
        "group": {"group_by": ["单元", t]},
        "agg": {"group_by": ["单元"], "aggregate": [{"col": n, "fn": "sum"}, {"col": n, "fn": "min"}, {"col": n, "fn": "max"}]},
        "where": {"where": [{"col": n, "op": "ge", "value": 1}], "any_of": [[{"col": t, "op": "contains", "value": "A"}], [{"col": t, "op": "ne", "value": "0"}]]},
        "dist": {"distribution": dist},
        "page": {"list": True, "offset": 1, "limit": 3},
        "list": {"list": True},
        "unparsed": {"where": [{"col": t, "op": "lt", "value": 5}], "aggregate": [{"col": t, "fn": "sum"}]},
    }


def cases():
    for fx in FIXTURES:
        for section in SECTIONS:
            for qn, q in queries(section).items():
                for parsed in (True, False):
                    yield f"{fx}/{section}/{qn}/{'parsed' if parsed else 'original'}", fx, section, q, parsed
