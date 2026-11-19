"""cad.assemble 第 1 阶段读数（立项 §九 第 1 阶段验收 7、8、10 与 §七 风险 1、2、3、5、12、19）。

用法：.venv/bin/python tools/assembly_readings.py [次数=3] > readings.json
每道题跑 N 次（进程内，全部格式），耗时取中位数；另做三项专门读数：
  · 不用包围盒预筛、全部零件对都求公共体积的耗时（风险 1）；
  · 已判为“接触”的零件对，公共体积的最大值（定干涉阈值用）；
  · 啮合齿轮对偏离正确相位 0.01°–半个齿距时的公共体积（风险 2，定啮合阈值用）。
耗时只是本机读数，不进产出记录。
"""
import json
import math
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import assembly  # noqa: E402

ALL = ["step", "glb", "csv", "svg", "dxf"]


def _flat(t, prefix=""):
    out = {}
    for k, v in t.items():
        if isinstance(v, dict):
            out.update(_flat(v, prefix + k + "."))
        else:
            out[prefix + k] = v
    return out


def timed_runs(doc, n):
    rows, last = [], None
    for _ in range(n):
        d = tempfile.mkdtemp()
        r = assembly.run({"tool": "cad.assemble", "payload": dict(doc, formats=ALL), "workdir": d})
        assert r["ok"], r
        rows.append(_flat(assembly.LAST_TIMINGS))
        last = (r["output"], d, sorted(assembly.PAIR_TIMES, reverse=True))
    keys = rows[0].keys()
    med = {k: round(statistics.median(r[k] for r in rows), 3) for k in keys}
    mx = {k: round(max(r[k] for r in rows), 3) for k in keys}
    return med, mx, last


def contact_and_full_pairs(doc):
    parts = assembly._build_parts(doc["parts"])
    L = assembly._layout(parts, doc["layout"])
    insts = L.insts
    boxes = [assembly._bbox(i.shape) for i in insts]
    t = time.perf_counter()
    vols = []
    for i in range(len(insts)):
        for j in range(i + 1, len(insts)):
            v, _, _ = assembly._common(insts[i].shape, insts[j].shape)
            vols.append((v, assembly._overlap(boxes[i], boxes[j]), insts[i].row, insts[j].row))
    full = time.perf_counter() - t
    mesh = {frozenset((a, b)) for a, b, _ in L.mesh_pairs}
    contact = [v for v, ov, a, b in vols if ov and frozenset((a, b)) not in mesh]
    return {"pairs_all": len(vols), "seconds_all_pairs_no_prefilter": round(full, 3),
            "pairs_bbox_overlap": sum(1 for _, ov, _, _ in vols if ov),
            "contact_pairs": len(contact), "contact_common_max_mm3": max(contact) if contact else 0.0,
            "pairs_outside_bbox_with_volume": sum(1 for v, ov, _, _ in vols if not ov and v > 0)}


def mesh_sensitivity(doc, row, other, z):
    """把从动轮在啮合相位上再转 δ（度），读公共体积。"""
    parts = assembly._build_parts(doc["parts"])
    L = assembly._layout(parts, doc["layout"])
    rot = next(c for c in L.table if c["row"] == row)["mesh_rotation_deg"]
    line = next(ln for ln in doc["layout"].splitlines() if ln.startswith(row + ":"))
    pitch = 360 / z
    out = []
    for frac_deg in (0.0, 0.01, 0.05, 0.1, 0.5, 1.0, pitch / 4, pitch / 2):
        lay = doc["layout"].replace(line, line.replace(f"mesh={other}", f"angle={rot + frac_deg:.6f}"))
        L2 = assembly._layout(parts, lay)
        a = next(i for i in L2.insts if i.row == other)
        b = next(i for i in L2.insts if i.row == row)
        t = time.perf_counter()
        v, _, _ = assembly._common(a.shape, b.shape)
        out.append({"offset_deg": round(frac_deg, 4), "common_mm3": round(v, 6), "seconds": round(time.perf_counter() - t, 3)})
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    report = {"machine": {"python": platform.python_version(), "cpu_count": os.cpu_count(), "platform": platform.platform()},
              "runs_per_case": n, "cases": {}}
    for name in ("vise", "reducer"):
        doc = json.loads((ROOT / "samples" / "assembly" / f"{name}.json").read_text(encoding="utf-8"))
        med, mx, (out, d, pairs) = timed_runs(doc, n)
        rec = json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        no_files = {k: v for k, v in out.items() if k != "files"}
        case = {
            "parts": out["measure"]["parts"], "instances": out["measure"]["instances"],
            "layout_rows": len([ln for ln in doc["layout"].splitlines() if ln.strip() and not ln.strip().startswith("#")]),
            "plan_chars": sum(len(p["plan"]) for p in doc["parts"]) + len(doc["layout"]),
            "seconds_median": med, "seconds_max": mx,
            "receipt_chars": len(rec), "receipt_bytes_utf8": len(rec.encode("utf-8")),
            "receipt_chars_without_files": len(json.dumps(no_files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
            "triangles": out.get("triangles"),
            "files": {f["format"]: f["bytes"] for f in out["files"]},
            "interference": {k: out["interference"][k] for k in ("pairs_total", "pairs_checked", "count")},
            "slowest_pairs": [[round(t, 3), a, b] for t, a, b in pairs[:6]],
            "mesh": out["mesh"],
            "bbox_size": out["measure"]["bbox"]["size"], "mass_g": out["measure"]["mass_g"],
        }
        case["pairs"] = contact_and_full_pairs(doc)
        if name == "reducer":
            case["mesh_sensitivity"] = {"g1-g2 (z2=70)": mesh_sensitivity(doc, "g2", "g1", 70),
                                        "g3-g4 (z4=72)": mesh_sensitivity(doc, "g4", "g3", 72)}
        report["cases"][name] = case
    json.dump(report, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
