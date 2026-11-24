"""从 design/tables.json 生成：条文 F1（排布事实的算式，短写法）与核对项清单。改算式只改 tables.json，然后跑本脚本。
用法: python tools/gen_pack.py [核对项输出文件]"""
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
T = json.loads((ROOT / "design" / "tables.json").read_text(encoding="utf-8"))
MP = ROOT / "mengos-package.json"
M = json.loads(MP.read_text(encoding="utf-8"))

def short(f):
    """算式的短写法：排布事实/名/值 → 名；* → ×；/ → ÷。"""
    s = re.sub(r"排布事实/([^/\s(),]+)/值", r"\1", f)
    return s.replace(" * ", " × ").replace(" / ", " ÷ ")

def line(kind, cell, rhs, hint=None):
    return f"{kind} {cell} = {rhs}" + (f" # 提示：{hint}" if hint else "")

checks = []
for f in T["facts_formulas"]:
    checks.append(line("cell", f["cell"], f["formula"]))
    for s in T["self_checks"]:                       # 自检紧跟在它所核的那一格的算式后面
        if s["cell"] == f["cell"] or (s["clause"] == "G3" and f["cell"].endswith("/横梁层数/值")):
            if line("cell", s["cell"], s["formula"], s["hint"]) not in checks:
                checks.append(line("cell", s["cell"], s["formula"], s["hint"]))
for s in T["self_checks"]:
    if line("cell", s["cell"], s["formula"], s["hint"]) not in checks:
        checks.append(line("cell", s["cell"], s["formula"], s["hint"]))
for r in T["reading_checks"]:
    checks.append(line("cell", r["cell"], r["formula"], r.get("hint")))
for q in T["quantity_formulas"]:
    if not q.get("pending"):                         # 口径待客户定的行不生成核对项
        checks.append(line("cell", q["cell"], q["formula"]))
for t in T["text_templates"]:
    checks.append(line("text", t["cell"], t["template"]))

f1 = "[约束] （F1）立库货架排布事实表里的推算量，各按下面的算式得出（算式里的名字指排布事实表里同名那一行的值）：" + "；".join(
    f"{f['cell'].split('/')[1]} = {short(f['formula'])}" for f in T["facts_formulas"])
norms = [n for n in M["norms"] if "（F1）" not in n]
i = next(k for k, n in enumerate(norms) if "（D13）" in n)
norms.insert(i + 1, f1)
M["norms"] = norms
M["checks"] = [{"for": "table", "expect": checks}]
MP.write_text(json.dumps(M, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text("\n".join(checks) + "\n", encoding="utf-8")
print("checks", len(checks), "F1", len(f1))
