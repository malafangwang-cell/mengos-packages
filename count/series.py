"""乘积串（左 * 右 = 合计）的解析与验算；首尾相接的区间连成链。只认列名，不认行业词。"""
from __future__ import annotations

import re
from decimal import Decimal

from ops import col_index, num_out, num_text, parse_num
from readers import BadInput

NUM = r"(\d+(?:\.\d+)?)"
PRODUCT_RE = re.compile(NUM + r"\s*[*×xX]\s*" + NUM + r"\s*[=＝]\s*" + NUM)


def product(rows, spec, columns, tol: Decimal):
    if not isinstance(spec, dict):
        raise BadInput("product 须为对象 {text, measure?}")
    text_cols = spec.get("text")
    if isinstance(text_cols, str):
        text_cols = [text_cols]
    if not isinstance(text_cols, list) or not text_cols:
        raise BadInput("product.text 须为列名或列名数组")
    tis = [(c, col_index(columns, c, "product.text")) for c in text_cols]
    mi = col_index(columns, spec["measure"], "product.measure") if spec.get("measure") is not None else None
    hits = []
    for rid, cells in rows:
        for c, i in tis:
            for m in PRODUCT_RE.finditer(cells[i].replace("（", "(").replace("）", ")")):
                left, right, total = (Decimal(g) for g in m.groups())
                prod = left * right
                h = {"row": rid, "col": c, "text": m.group(0), "left": num_out(left), "right": num_out(right),
                     "stated_total": num_out(total), "product": num_out(prod), "product_ok": abs(prod - total) <= tol}
                if mi is not None:
                    meas = parse_num(cells[mi])
                    h["measure"] = num_out(meas) if meas is not None else None
                    h["measure_ok"] = (abs(meas - total) <= tol) if meas is not None else None
                hits.append(h)
    return {"what": {"text": text_cols, **({"measure": spec["measure"]} if mi is not None else {})},
            "count": len(hits), "hits": hits,
            "inconsistent": sum(1 for h in hits if not h["product_ok"] or h.get("measure_ok") is False)}


def _point(s: str):
    parts = [p.strip() for p in s.split(",")]
    vals = [parse_num(p) for p in parts]
    if not parts or any(v is None for v in vals):
        return None
    return tuple(vals)


def chain(rows, spec, columns, tol: Decimal):
    if not isinstance(spec, dict):
        raise BadInput("chain 须为对象 {from, to, value, undirected?}")
    fi = col_index(columns, spec.get("from"), "chain.from")
    ti = col_index(columns, spec.get("to"), "chain.to")
    vi = col_index(columns, spec.get("value"), "chain.value")
    undirected = spec.get("undirected", False)
    if not isinstance(undirected, bool):
        raise BadInput("chain.undirected 须为布尔值")
    segs, bad = [], []
    for rid, cells in rows:
        a, b, v = _point(cells[fi]), _point(cells[ti]), parse_num(cells[vi])
        if a is None or b is None or v is None or len(a) != len(b):
            bad.append(rid)
            continue
        segs.append((rid, a, b, v))
    # 端点按容差并为节点（逐坐标差 ≤ tol）
    nodes: list[tuple] = []

    def node(p):
        for k, q in enumerate(nodes):
            if len(q) == len(p) and all(abs(x - y) <= tol for x, y in zip(p, q)):
                return k
        nodes.append(p)
        return len(nodes) - 1

    edges = [(rid, node(a), node(b), v) for rid, a, b, v in segs]
    outs: dict[int, list[int]] = {}
    ins: dict[int, list[int]] = {}
    for e, (_, u, w, _) in enumerate(edges):
        outs.setdefault(u, []).append(e)
        ins.setdefault(w, []).append(e)
        if undirected:
            outs.setdefault(w, []).append(e)
            ins.setdefault(u, []).append(e)

    def deg(n):
        if undirected:
            return len(outs.get(n, []))
        return (len(ins.get(n, [])), len(outs.get(n, [])))

    def internal(n):
        return deg(n) == 2 if undirected else deg(n) == (1, 1)

    used = set()
    chains = []

    def walk(start_node, first_edge):
        path = [first_edge]
        used.add(first_edge)
        cur = edges[first_edge][2] if (not undirected or edges[first_edge][1] == start_node) else edges[first_edge][1]
        ends = [start_node, cur]
        while internal(cur) and cur != start_node:
            nxt = [e for e in outs.get(cur, []) if e not in used]
            if len(nxt) != 1:
                break
            e = nxt[0]
            used.add(e)
            path.append(e)
            cur = edges[e][2] if (not undirected or edges[e][1] == cur) else edges[e][1]
            ends[1] = cur
        return path, ends

    # 先从非内部节点出发，再处理只剩环的部分
    order = sorted(range(len(edges)), key=lambda e: (nodes[edges[e][1]], nodes[edges[e][2]], edges[e][0]))
    for pass_ in (0, 1):
        for e in order:
            if e in used:
                continue
            u = edges[e][1]
            if pass_ == 0 and internal(u):
                if not undirected:
                    continue
                w = edges[e][2]
                if internal(w):
                    continue
                u = w
            path, ends = walk(u, e)
            chains.append((path, ends))
    out_chains, singles = [], 0
    for path, (s, t) in chains:
        if len(path) < 2:
            singles += 1
            continue
        vals = [edges[e][3] for e in path]
        uniform = all(abs(v - vals[0]) <= tol for v in vals)
        out_chains.append({
            "segments": len(path), "values": [num_out(v) for v in vals], "uniform": uniform,
            "pitch": num_out(vals[0]) if uniform else None, "total": num_out(sum(vals, Decimal(0))),
            "closed": s == t,
            "start": ",".join(num_text(x) for x in nodes[s]), "end": ",".join(num_text(x) for x in nodes[t]),
            "rows": [edges[e][0] for e in path],
        })
    out_chains.sort(key=lambda c: (c["start"], c["end"], c["rows"][0]))
    return {"what": {"from": spec["from"], "to": spec["to"], "value": spec["value"], "undirected": undirected},
            "count": len(out_chains), "chains": out_chains, "single_segments": singles,
            "rows_used": len(segs), "rows_unparsed": len(bad), "unparsed_ids": bad[:50]}
