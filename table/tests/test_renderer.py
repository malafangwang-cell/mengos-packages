"""表格渲染器页面自检（2.3.1：选区）。只读页面文本，不起浏览器；浏览器走查见 tools/check_renderer_select.cjs。"""
import re
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "renderer" / "index.html").read_text(encoding="utf-8")


def test_selection_messages_and_handles():
    assert 'type: "mengos.select", handle_id' in PAGE and 'type: "mengos.select_denied", why_not' in PAGE
    for h in ("cell:${sid}/", "row:${sid}/", "col:${sid}/", "fx:${sid}/"):
        assert h in PAGE, h
    for k in ('"cells"', '"rows"', '"column_def"', '"formula"'):
        assert k in PAGE, k
    assert "totals_def" not in PAGE and "totals:${sid}" not in PAGE                  # 2.3.1 r10 改：合计不可选


def test_row_and_sheet_keys_fall_back_to_input_ordinals():
    # 包不补 id（2.3.0 r10）：没写 id 的表按 sheets 里的 #序号；没写 id 的行按入参 rows 里的 #序号（分组时取 src 对回）
    assert 'const sheetId = (s, si) => s.id || "#" + si;' in PAGE
    assert 'const rowId = (s, r) => (s.ids && s.ids[r]) || "#" + (s.src ? s.src[r] : r);' in PAGE
    assert '"_sa"' not in PAGE


def test_ctrl_or_cmd_adds_and_cap_is_200_cells():
    assert "const isMod = (e) => e.ctrlKey || e.metaKey;" in PAGE
    assert "additive: true" in PAGE
    assert re.search(r"const MAX_CELLS = 200;", PAGE)


def test_formula_cells_snap_to_the_column_and_mixed_offers_two_narrowings():
    assert 'kind: "formula", col: [...fcols][0]' in PAGE
    assert "只改其余的格子" in PAGE and "这一列的公式" in PAGE


def test_not_selectable_kinds_are_denied_with_a_reason():
    for k in ("numbering", "group", "subtotal", "merged", "derived", "totals", "too_many", "kind"):
        assert re.search(rf"\b{k}: ", PAGE), k


def test_host_messages_open_close_busy():
    assert 'm.type === "mengos.open" || m.type === "mengos.close" || m.type === "mengos.busy"' in PAGE


def test_header_click_selects_and_sorting_moved_to_the_arrow():
    assert 'data-sort="${j}"' in PAGE and 'closest("[data-sort]")' in PAGE
    assert 'closest("[data-col]")' not in PAGE.split("// ---------------------------------------------------------------- 选区")[0]


def test_rows_without_a_source_and_derive_are_judged_by_what_is_missing():
    """立法者 2026-11-19（第十一件）：判据按缺什么写，不认版本。
    行上没有 src 而这张表有分组或合并 ⟹ 行不能选（no_row_source，定稿原文）；表数据里有 derive ⟹ 按派生表拒。"""
    assert 'no_row_source: "这张表分了组，行对不回原表，不能单独选",' in PAGE
    assert 'if ((idx || td) && s.layout && !s.src) { e.preventDefault(); return deny("no_row_source", idx || td); }' in PAGE
    assert '(s.row_kind === "derived" || s.derive)' in PAGE
    assert "col_kinds ? " not in PAGE and "old_layout" not in PAGE                   # 不按版本标记认旧表


def test_views_made_by_2_2_0_lack_the_row_fields():
    """夹具 tests/fixtures/views_220 由 2.2.0 代码做（tools/make_views_220.py）；浏览器走查据此钉住：普通表能选、分组表行拒、派生行拒。"""
    import json
    base = Path(__file__).resolve().parent / "fixtures" / "views_220"
    for name, want in {"bom": (False, False), "grp": (True, False), "der": (False, True)}.items():
        out = json.loads((base / name / "out.json").read_text(encoding="utf-8"))
        vf = next(f for f in out["files"] if f["format"] == "view")
        v = json.loads((base / name / vf["path"]).read_text(encoding="utf-8"))
        for s in v["sheets"]:
            for k in ("src", "row_kind", "ids", "col_kinds", "layout_keys", "derived_keys"):
                assert k not in s, (name, k)
        assert (any("layout" in s for s in v["sheets"]), any("derive" in s for s in v["sheets"])) == want, name
