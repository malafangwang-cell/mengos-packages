"""数苹果：清单 + 已贴标记 → 未贴清单、未贴数。只认 id。

0.2.0：清单可取自按文件读的行（inventory.source.file，见 file_source.py）；标记可取自一段产出内容加字段名
（marks = {content, field}：content 多由判据核验入参的 $best 换成当前产出，程序在其中按字段名收集处理记录）。"""
from __future__ import annotations

from ops import col_index, parse_num
from readers import BadInput, read_source

STATUSES = ("done", "empty")


def inventory_items(inv, max_rows, workdir=None):
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
    table = read_source(inv["source"], max_rows, workdir)
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


def marks_from_content(content, field):
    """在产出内容里按字段名收集处理记录：凡键名等于 field 的值（对象逐层、数组逐项，按原有次序），
    是数组则逐条取、是对象则取这一条。找不到 ⟹ 空（交空表即不达成，由清单与谓词判）。"""
    if not isinstance(field, str) or not field:
        raise BadInput("marks.field 须为非空字符串")
    found: list = []
    hits = 0

    def walk(v):
        nonlocal hits
        if isinstance(v, dict):
            for k, x in v.items():
                if k == field:
                    hits += 1
                    found.extend(x if isinstance(x, list) else [x])
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(content)
    return found, hits


def coverage(payload, max_rows, workdir=None):
    items, src = inventory_items(payload.get("inventory"), max_rows, workdir)
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
    marks_from = None
    if isinstance(marks, dict):
        if set(marks) != {"content", "field"}:
            raise BadInput("marks 写成对象时须为 {content, field}")
        marks, hits = marks_from_content(marks["content"], marks["field"])
        marks_from = {"form": "content", "field": payload["marks"]["field"], "fields_found": hits, "marks_found": len(marks)}
    elif not isinstance(marks, list):
        raise BadInput("marks 须为数组，或 {content, field}")
    elif max_rows is not None and len(marks) > max_rows * 2:
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
    source = {"mode": "inline", **src}
    if marks_from is not None:
        source["marks"] = marks_from
    assumptions = []
    if source["mode"] == "inline":
        assumptions.append("清单由调用方给出，程序未与原文核对")
    if marks_from is None:
        assumptions.append("标记由调用方给出，程序未与产出核对")
    if source["mode"] == "inline" and marks_from is None:
        assumptions = ["清单与标记由调用方给出，程序未与原文或产出核对"]
    return {
        "total": len(items), "marked": len(seen), "unmarked_count": len(unmarked), "unmarked": unmarked,
        "status_counts": counts, "unknown_marks": sorted(set(unknown)), "duplicate_marks": sorted(set(duplicate)),
        "total_ok": total_ok, "expected_total": expected,
        "source": source,
        "assumptions": assumptions,
    }
