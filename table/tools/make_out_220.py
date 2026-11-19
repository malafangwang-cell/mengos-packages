"""录 2.2.0 产出金样（局部追问 r10 架构线补查 b：2.2.0 做出的旧表在 2.3.x 上逐字节不变）。
用法：python tools/make_out_220.py <table 2.2.0 包目录> <输出 json>
  对 golden_cases.json 里每条成功的 table.build、table.export，用 2.2.0 的 table_tool.py 经同一进程入口与信封跑一次，
  记下每件产出文件：xlsx 记逐格（公式与值），其余记 sha256（产出台数据按原样字节）。
  夹具只读当前包的 golden_cases.json 取入参；2.2.0 代码只用来出金样，不进本包。"""
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def run(pkg: Path, tool: str, payload, workdir: Path):
    env = {"tool": tool, "payload": payload, "workdir": str(workdir)}
    p = subprocess.run([sys.executable, str(pkg / "table_tool.py")], input=json.dumps(env, ensure_ascii=False).encode(),
                       capture_output=True, cwd=str(pkg), timeout=120)
    return json.loads(p.stdout.decode("utf-8"))


def xlsx_cells(data: bytes):
    import openpyxl
    wf, wv = openpyxl.load_workbook(io.BytesIO(data)), openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    out = {}
    for ws in wf.worksheets:
        out[ws.title] = {c.coordinate: [c.value if isinstance(c.value, str) and c.value.startswith("=") else None,
                                        (lambda v: v.isoformat() if hasattr(v, "isoformat") else v)(wv[ws.title][c.coordinate].value)]
                         for r in ws.iter_rows() for c in r if c.value is not None}
    return out


def record(pkg: Path):
    G = json.loads((HERE / "golden_cases.json").read_text(encoding="utf-8"))
    cases = G["cases"] if isinstance(G, dict) else G
    out = {}
    for c in cases:
        if c["tool"] not in ("table.build", "table.export"):
            continue
        with tempfile.TemporaryDirectory() as d:
            r = run(pkg, c["tool"], c["payload"], Path(d))
            if not r.get("ok"):
                continue
            files = {}
            for f in r["output"].get("files", []):
                data = (Path(d) / f["path"]).read_bytes()
                files[f["path"]] = {"format": f["format"], "xlsx": xlsx_cells(data)} if f["format"] == "xlsx" \
                    else {"format": f["format"], "sha256": hashlib.sha256(data).hexdigest()}
            out[c["id"]] = {"tool": c["tool"], "files": files}
    return out


if __name__ == "__main__":
    pkg, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    ver = json.loads((pkg / "mengos-package.json").read_text(encoding="utf-8"))["version"]
    body = {"source": f"table {ver}（{pkg.name}）tools/make_out_220.py", "cases": record(pkg)}
    dst.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(len(body["cases"]), "cases")
