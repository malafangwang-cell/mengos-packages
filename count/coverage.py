"""数苹果：清单 + 已贴标记 → 未贴清单、未贴数。只认 id。"""
from __future__ import annotations

from ops import col_index, parse_num
from readers import BadInput, read_source

STATUSES = ("done", "empty")


def inventory_items(inv, max_rows):
    if not isinstance(inv, dict):
        raise BadInput("inventory 须为对象：{items} 或 {source, id_col?, label_col?}")
    if ("items" in inv) == ("source" in inv):
        raise BadInput("inventory 须且只须给 items 或 source 之一")
    if "items" in inv:
        items = inv["items"]
        if not isinstance(items, list):
            raise BadInput("inventory.items 须为数组")
        if max_rows is not None and len(items) > max_rows:
            raise BadInput(f"清单 {len(items)} 条超过上限 {max_rows}")
        out = []
        for it in items:
            if isinstance(it, str):
                it = {"id": it}
            if not isinstance(it, dict) or not isinstance(it.get("id"), str) or not it["id"]:
                raise BadInput("清单每项须为非空 id 字符串或 {id, label?}")
            out.append((it["id"], it.get("label") if isinstance(it.get("label"), str) else None))
        return out, {"form": "items", "reader": None}
    table = read_source(inv["source"], max_rows)
    ic = col_index(table.columns, inv["id_col"], "inventory.id_col") if inv.get("id_col") is not None else None
    lc = col_index(table.columns, inv["label_col"], "inventory.label_col") if inv.get("label_col") is not None else None
    out = []
    for rid, cells in table.rows:
        iid = cells[ic].strip() if ic is not None else rid
        if not iid:
            raise BadInput(f"清单行 {rid} 的 id 为空")
        out.append((iid, cells[lc] if lc is not None else None))
    src = dict(table.source)
    src["id_col"] = inv.get("id_col")
    return out, src


def coverage(payload, max_rows):
    items, src = inventory_items(payload.get("inventory"), max_rows)
    if not items:
        raise BadInput("清单为空，不放行")
    ids = [i for i, _ in items]
    dup_inv = sorted({i for i in ids if ids.count(i) > 1})
    if dup_inv:
        raise BadInput("清单里 id 重复：" + "、".join(dup_inv[:20]))
    expected = payload.get("expected_total")
    total_ok = None
    if expected is not None:
        n = parse_num(expected)
        if n is None or n != n.to_integral_value() or n < 0:
            raise BadInput("expected_total 须为非负整数")
        total_ok = int(n) == len(items)
        if not total_ok:
            raise BadInput(f"清单 {len(items)} 条，与 expected_total {int(n)} 不符，不放行")
    marks = payload.get("marks", [])
    if not isinstance(marks, list):
        raise BadInput("marks 须为数组")
    if max_rows is not None and len(marks) > max_rows * 2:
        raise BadInput(f"标记 {len(marks)} 条超过上限 {max_rows * 2}")
    known = set(ids)
    seen: dict[str, str] = {}
    duplicate, unknown = [], []
    counts = {s: 0 for s in STATUSES}
    for m in marks:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not m["id"]:
            raise BadInput("每条标记须为 {id, status, note?}")
        if m.get("status") not in STATUSES:
            raise BadInput("标记的 status 须为 done 或 empty")
        i = m["id"]
        if i not in known:
            unknown.append(i)
            continue
        if i in seen:
            duplicate.append(i)
            continue
        seen[i] = m["status"]
        counts[m["status"]] += 1
    unmarked = [{"id": i, **({"label": lab} if lab is not None else {})} for i, lab in items if i not in seen]
    return {
        "total": len(items), "marked": len(seen), "unmarked_count": len(unmarked), "unmarked": unmarked,
        "status_counts": counts, "unknown_marks": sorted(set(unknown)), "duplicate_marks": sorted(set(duplicate)),
        "total_ok": total_ok, "expected_total": expected,
        "source": {"mode": "inline", **src},
        "assumptions": ["清单与标记由调用方给出，程序未与原文或产出核对"],
    }
