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
