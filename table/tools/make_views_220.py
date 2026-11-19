"""录 tests/fixtures/views_220（立法者 2026-11-19 第十一件）：用 table 2.2.0 代码做普通表、分组小计表、派生汇总表各一份，
存 out.json 与产出台数据。用法：python tools/make_views_220.py <table 2.2.0 包目录> tests/fixtures/views_220
（只留 out.json 与 *.view.json；renderer.html 一行不用）。"""
import json, sys, shutil
from pathlib import Path
pkg = Path(sys.argv[1]); out = Path(sys.argv[2])   # pkg = table 2.2.0 包目录
sys.path.insert(0, str(pkg)); sys.path.insert(0, str(pkg / "tests"))
import table_tool
G = json.loads((pkg / "golden_cases.json").read_text(encoding="utf-8"))
G = {c["id"]: c for c in (G["cases"] if isinstance(G, dict) else G)}
bom = {"title": "物料", "columns": [{"key": "no", "title": "序号", "numbering": "seq"}, {"key": "name", "title": "名称"},
       {"key": "qty", "title": "数量", "type": "integer"}, {"key": "price", "title": "单价", "type": "money"},
       {"key": "amt", "title": "金额", "type": "money", "formula": "数量 * 单价"}],
       "rows": [{"名称": "输入轴", "数量": 1, "单价": 860}, {"名称": "齿轮", "数量": 2, "单价": 1250.5}, {"名称": "轴承", "数量": 4, "单价": 95}], "totals": ["金额"]}
cases = {"bom": bom, "grp": G["t3_07_group_subtotal"]["payload"]["table"], "der": G["t6_04_derive_summary"]["payload"]["table"]}
for name, t in cases.items():
    w = out / name
    shutil.rmtree(w, ignore_errors=True); w.mkdir(parents=True)
    r = table_tool.run({"tool": "table.build", "payload": {"table": t, "formats": []}, "workdir": str(w)})
    assert r["ok"], r
    (w / "out.json").write_text(json.dumps(r["output"], ensure_ascii=False), encoding="utf-8")
for w in out.iterdir():
    if w.is_dir():
        for f in w.iterdir():
            if f.name != "out.json" and not f.name.endswith(".view.json"):
                f.unlink()
print("ok")
