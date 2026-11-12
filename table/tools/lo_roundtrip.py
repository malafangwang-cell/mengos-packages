"""Excel 往返核对（执行令 table 包 2.1.0 §三；#710 §6.0 验收）：

对每个 table.build 的入参：经进程入口跑一遍，取导出的 xlsx，交 LibreOffice 无头重算（tools/lo_recalc.py），
再用 openpyxl 读回重算后的值，与表模型逐格比（数据行与合计行；数按十进制比，文字照字比，空对空）。
入参取自 golden_cases.json 里全部成功的 table.build 金样，另加 --cases 给的 JSON 文件（[{id, payload}]）。

用法：.venv/bin/python tools/lo_roundtrip.py [--cases 文件] [--out 目录] [--keep]
标准输出：一行 JSON {"libreoffice": 版本, "cases": n, "cells": n, "mismatches": [...]}；有不一致时退出码 1。
没有 soffice 或系统 Python 没有 uno 时退出码 2（本核对要 LibreOffice，不能装作通过）。
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SYS_PY = "/usr/bin/python3"


def build(payload, wd):
    env = {"tool": "table.build", "payload": {**payload, "formats": ["xlsx"]}, "workdir": str(wd)}
    p = subprocess.run([sys.executable, str(ROOT / "table_tool.py")], input=json.dumps(env, ensure_ascii=False).encode(),
                       capture_output=True, cwd=str(ROOT), timeout=120)
    r = json.loads(p.stdout)
    if not r["ok"]:
        return None
    files = {f["format"]: wd / f["path"] for f in r["output"]["files"]}
    return json.loads(files["json"].read_text(encoding="utf-8")), files["xlsx"]


def _dec(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return Decimal(repr(x)).quantize(Decimal("1e-9")) if isinstance(x, float) else Decimal(x)
    return x


def compare(model, path):
    wb = openpyxl.load_workbook(path, data_only=True)
    bad, n = [], 0
    for sh in model["sheets"]:
        ws = wb[sh["name"]]
        cols = sh["columns"]
        rows = [r if isinstance(r, list) else [r.get(c["key"]) for c in cols] for r in sh["rows"]]
        tot = {t["column"]: t for t in sh.get("totals", [])}
        lines = [(i + 2, r) for i, r in enumerate(rows)]
        if tot:
            lines.append((len(rows) + 2, [tot[c["key"]]["value"] if c["key"] in tot else None for c in cols]))
        for excel_row, r in lines:
            is_total = excel_row == len(rows) + 2 and tot
            for j, c in enumerate(cols):
                if is_total and c["key"] not in tot:
                    continue
                want = r[j]
                got = ws.cell(row=excel_row, column=j + 1).value
                n += 1
                if not _same(c, want, got):
                    bad.append({"sheet": sh["name"], "cell": f"{openpyxl.utils.get_column_letter(j + 1)}{excel_row}",
                                "column": c["title"], "model": want, "libreoffice": got if not hasattr(got, "isoformat") else got.isoformat()})
    return n, bad


def _same(c, want, got):
    if want is None:
        return got is None or got == ""
    if c["type"] == "date":
        return hasattr(got, "date") and got.date().isoformat() == want
    if c["type"] == "bool":
        return got is (want is True or want == "true")
    if c["type"] in ("integer", "number", "money", "percent"):
        if not isinstance(got, (int, float)) or isinstance(got, bool):
            return False
        return abs(Decimal(repr(float(got))) - Decimal(want)) <= Decimal("1e-9") * max(Decimal(1), abs(Decimal(want)))
    return str(got) == str(want)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases")
    ap.add_argument("--out")
    ap.add_argument("--pdf", action="store_true")
    a = ap.parse_args()
    if not shutil.which("soffice") or subprocess.run([SYS_PY, "-c", "import uno"], capture_output=True).returncode:
        print(json.dumps({"error": "没有 LibreOffice（soffice）或系统 Python 没有 uno，做不了往返核对"}, ensure_ascii=False))
        return 2
    cases = [{"id": c["id"], "payload": c["payload"]} for c in json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
             if c["tool"] == "table.build" and not any(k.startswith("error.") for k in c["expect"])]
    if a.cases:
        cases += json.loads(Path(a.cases).read_text(encoding="utf-8"))
    tmp = Path(a.out) if a.out else Path(tempfile.mkdtemp())
    tmp.mkdir(parents=True, exist_ok=True)
    built = {}
    for c in cases:
        wd = tmp / c["id"]
        wd.mkdir(exist_ok=True)
        b = build(c["payload"], wd)
        if b is not None:
            x = tmp / f"{c['id']}.xlsx"
            shutil.copy(b[1], x)
            built[c["id"]] = (b[0], x)
    p = subprocess.run([SYS_PY, str(ROOT / "tools" / "lo_recalc.py"), str(tmp / "lo"), *[str(x) for _, x in built.values()]]
                       + (["--pdf"] if a.pdf else []), capture_output=True, timeout=1800)
    version = p.stdout.decode().strip().splitlines()[-1] if p.stdout else ""
    total, bad = 0, []
    for cid, (model, x) in built.items():
        n, b = compare(model, tmp / "lo" / f"{cid}.lo.xlsx")
        total += n
        bad += [{"case": cid, **m} for m in b]
    print(json.dumps({"libreoffice": version, "cases": len(built), "cells": total, "mismatches": bad}, ensure_ascii=False))
    if not a.out:
        shutil.rmtree(tmp)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
