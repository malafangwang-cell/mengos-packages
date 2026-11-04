"""产出文件能被第三方读回，且与 B-rep 一致。"""
import json
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pytest
import trimesh

from cad_tool import run



def _build(tmp_path, name, formats):
    from pathlib import Path
    plan = (Path(__file__).resolve().parents[1] / "samples" / f"{name}.cad").read_text(encoding="utf-8")
    res = run({"tool": "cad.build", "payload": {"plan": plan, "name": name, "formats": formats}, "workdir": str(tmp_path)})
    assert res["ok"], res
    return res["output"]


def _volume_3mf(path):
    """直接读 3MF 的网格算体积。trimesh 自带的 3MF 读入要 networkx，测试环境不另装依赖。"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("3D/3dmodel.model"))
    total = 0.0
    for mesh in root.iter():
        if not mesh.tag.endswith("}mesh"):
            continue
        v = np.array([[float(e.get(k)) for k in "xyz"] for e in mesh.iter() if e.tag.endswith("}vertex")])
        f = np.array([[int(e.get(k)) for k in ("v1", "v2", "v3")] for e in mesh.iter() if e.tag.endswith("}triangle")])
        total += trimesh.Trimesh(vertices=v, faces=f, process=False).volume
    return total


@pytest.mark.parametrize("name", ["base", "flange", "bracket", "box_pocket", "gear"])
def test_mesh_formats_roundtrip(tmp_path, name):
    out = _build(tmp_path, name, ["glb", "stl", "3mf"])
    vol = out["measure"]["volume_mm3"]
    stl = trimesh.load(tmp_path / f"{name}.stl")
    assert stl.is_watertight
    assert abs(stl.volume - vol) / vol < 2e-3                      # 弦高误差
    assert abs(_volume_3mf(tmp_path / f"{name}.3mf") - stl.volume) < 1e-3
    glb = trimesh.load(tmp_path / f"{name}.glb")
    gm = glb.to_mesh() if hasattr(glb, "to_mesh") else glb
    assert abs(abs(gm.volume) * 1e9 - stl.volume) / stl.volume < 1e-4   # GLB 以米为单位
    with zipfile.ZipFile(tmp_path / f"{name}.3mf") as z:
        assert "3D/3dmodel.model" in z.namelist()


def test_glb_nodes_are_features(tmp_path):
    out = _build(tmp_path, "flange", ["glb"])
    data = (tmp_path / "flange.glb").read_bytes()
    n = int.from_bytes(data[12:16], "little")
    gltf = json.loads(data[20:20 + n])
    names = [nd["name"] for nd in gltf["nodes"][1:]]
    feats = {f["id"] for f in out["features"] if f["faces"] > 0}
    assert set(names) - {"edges"} == feats
    assert all("line" in nd["extras"] for nd in gltf["nodes"][1:] if nd["name"] != "edges")


def test_step_roundtrip(tmp_path):
    from build123d import import_step
    out = _build(tmp_path, "bracket", ["step"])
    shape = import_step(str(tmp_path / "bracket.step"))
    assert abs(shape.volume - out["measure"]["volume_mm3"]) < 1e-3


def test_drawings(tmp_path):
    import ezdxf
    _build(tmp_path, "bracket", ["svg", "dxf"])
    svg = (tmp_path / "bracket.svg").read_text(encoding="utf-8")
    for w in ("主视图", "俯视图", "左视图", "第一角画法"):
        assert w in svg
    doc = ezdxf.readfile(tmp_path / "bracket.dxf")
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert {"visible", "hidden", "center", "text"} <= layers
