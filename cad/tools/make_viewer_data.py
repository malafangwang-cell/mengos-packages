"""为 renderer/index.html 生成样件数据（与已发布的"CAD 产出物台"页面同一份做法）。

用法：python tools/make_viewer_data.py renderer
预览环境只托管网页类文件，所以 GLB、STL、3MF 另存为 base64 文本（*.b64.txt），页面取用时还原。
接入表面层后不需要这一步：文件直接来自 ObjectStore。
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = {
    "bracket": ("L 形支架", "bbox 120 60 50\nholes 4 d=8.5\nhole d=8.5 cbore=(14,5) at=(20,25) through\nhole d=8.5 cbore=(14,5) at=(100,25) through\nfits 150 80 60\nmass max=300\nvalid\nwatertight"),
    "flange": ("法兰", "bbox 120 120 30\nholes 6 d=10\nhole d=30 axis=z at=(0,0) through\nmass 1.254 kg rtol=0.01\nfeature boss\nvalid\nwatertight"),
    "base": ("带孔底座", "bbox 80 50 20\nholes 1 d=20\nhole d=20 axis=z at=(40,25) through\nmass 199 g rtol=0.01\nvalid\nwatertight"),
    "box_pocket": ("抽壳盒", "bbox 100 60 40\nfits 220 220 250\nmass max=50\nfeature win\nvalid\nwatertight"),
    "gear": ("直齿轮 m2 z30", "bbox 64 64 12 tol=0.25\nholes 1 d=12\nhole d=12 axis=z at=(0,0) through\nmass 252 g rtol=0.01\nvalid\nwatertight"),
}


def call(tool, payload, wd=None):
    env = {"tool": tool, "payload": payload}
    if wd:
        env["workdir"] = str(wd)
    p = subprocess.run([sys.executable, str(ROOT / "cad_tool.py")], input=json.dumps(env), capture_output=True, text=True)
    out = json.loads(p.stdout)
    assert out["ok"], out
    return out["output"]


def main(dest):
    reg = json.loads((ROOT / "registration.json").read_text(encoding="utf-8"))
    index = []
    for name, (title, expect) in META.items():
        plan = (ROOT / "samples" / f"{name}.cad").read_text(encoding="utf-8")
        d = Path(dest) / "parts" / name
        d.mkdir(parents=True, exist_ok=True)
        b = call("cad.build", {"plan": plan, "name": name, "formats": ["step", "glb", "stl", "3mf", "svg", "dxf"]}, d.resolve())
        c = call("cad.check", {"plan": plan, "expect": expect})
        for f in b["files"]:
            if f["format"] in ("glb", "stl", "3mf"):
                p = d / f["path"]
                (d / (f["path"] + ".b64.txt")).write_text(base64.b64encode(p.read_bytes()).decode())
                p.unlink()
        (d / "part.json").write_text(json.dumps({"name": name, "title": title, "plan": plan, "expect": expect, "build": b,
                                                 "check": c, "tool_version": reg["lock_hash"]}, ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")
        index.append({"name": name, "title": title, "verdict": c["verdict"]})
        print(name, c["verdict"])
    (Path(dest) / "parts" / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "renderer")
