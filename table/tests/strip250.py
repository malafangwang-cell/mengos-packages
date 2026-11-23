"""2.5.0 的反向对照：把合并的行 schema 换回 2.4.0 的 oneOf 两支、去掉 $count 保留键与 $count 说明句，供各版逐键对照用。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _mr():
    spec = importlib.util.spec_from_file_location("mr250", ROOT / "tools" / "make_registration.py")
    mr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mr)
    return mr


def strip_250(schema):
    mr = _mr()

    def walk(n):
        if isinstance(n, list):
            return [walk(x) for x in n]
        if not isinstance(n, dict):
            return n
        if n.get("type") == ["array", "object"] and "items" in n and "$count" in n.get("properties", {}):
            props = {k: walk(v) for k, v in n["properties"].items() if k != "$count"}
            return {"oneOf": [{"type": "array", "maxItems": n["maxItems"], "items": walk(n["items"])},
                              {"type": "object", "properties": props, "additionalProperties": walk(n["additionalProperties"])}]}
        out = {}
        for k, v in n.items():
            if k == "description" and isinstance(v, str):
                for x in mr.ADD_250:
                    v = v.replace(x, "")
                out[k] = v
            else:
                out[k] = walk(v)
        return out
    return walk(json.loads(json.dumps(schema, ensure_ascii=False)))
