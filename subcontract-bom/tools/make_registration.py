"""生成 registration.json（17 TL-6）：签名与说明全部从 text.py 取，不在这里写进模型的句子。

顺序：改 text.py 或本文件 → python tools/make_registration.py → python lock.py → python tools/make_package.py。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import text  # noqa: E402

FAMILY_VERSION = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))["version"]


def _desc(name):
    return {"description": text.W2_INPUTS[name]}


INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["from_drawing"],
    "properties": {
        "from_drawing": {
            "type": "object",
            "additionalProperties": False,
            "x-mengos-count": True,
            "description": text.W2_INPUTS["from_drawing"],
            "properties": {
                "columns_read": _desc("columns_read"),
                "run_length": _desc("run_length"),
                "column_pitch": _desc("column_pitch"),
                "level_segments": _desc("level_segments"),
                "beam_clear": _desc("beam_clear"),
                "zones": {
                    "type": "object",
                    "description": text.W2_INPUTS["zones"],
                    "maxProperties": 20,
                    # 区名作对象键：排除 / ~ #，长 1–32（调度 2026-11-23 裁），引用串的指针不出歧义
                    "propertyNames": {"pattern": "^[^/~#]{1,32}$"},
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "pallets": _desc("pallets"),
                            "pallet_plan_a": _desc("pallet_plan_a"),
                            "pallet_plan_b": _desc("pallet_plan_b"),
                        },
                    },
                },
            },
        },
    },
    "description": text.W1_CARD,
}

_REF_INT = {"type": "integer", "x-mengos-ref": True}

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["computed", "not_computed", "steps", "assumptions"],
    "properties": {
        "computed": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "columns": _REF_INT,
                "frames_per_row": _REF_INT,
                "levels": _REF_INT,
                "zones": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {k: _REF_INT for k in ("pallets_per_cell", "rows", "groups", "aisles")},
                    },
                },
                "total": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {k: _REF_INT for k in ("rows", "groups", "aisles")},
                },
            },
        },
        "not_computed": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item", "reason", "needs"],
                "additionalProperties": False,
                "properties": {
                    "item": {"type": "string"},
                    "reason": {"type": "string"},
                    "needs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item", "clause", "formula", "operands", "result"],
                "additionalProperties": False,
                "properties": {
                    "item": {"type": "string"},
                    "clause": {"type": "string"},
                    "formula": {"type": "string"},
                    "operands": {"type": "object"},
                    "result": {},
                    "note": {"type": "string"},
                },
            },
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}

REGISTRATION = {
    "family": "rack",
    "family_version": FAMILY_VERSION,
    "lock_hash": "",
    "note": "字段严格按 kernel-spec 17 章 TL-6；族名在顶层 family。cost 的 latency 与 timeout 单位为毫秒。"
            "rack.layout 是本规范包 G2、G3、G5、G6 的可执行形态（设计-域包排布计算工具 r1–r3），与条文同包同 lock；"
            "入参在数量位置（from_drawing 标 x-mengos-count，17 TL-30c），出参只有 computed 之下的整数可引用（17 TL-30d）。",
    "units": [
        {
            "tool_id": "rack.layout",
            "version": "",
            "trust_claim": "T1",
            "effect": "none",
            "executor": {"kind": "process", "entry": "rack_tool.py", "mode": "sync"},
            "cost": {"latency": 100, "price": 0, "timeout": 10000},
            "input_example": {"from_drawing": {
                "level_segments": {"$ref": "<count 回执 id>#/count"},
                "beam_clear": {"$ref": "#/values/CE/value"},
            }},
            "signature": {"input_schema": INPUT_SCHEMA, "output_schema": OUTPUT_SCHEMA},
            "capability": {
                "ops": ["compute"],
                "in_types": [],
                "out_types": ["rack_layout_receipt"],
                "constraints": {"deterministic": True, "network": "none", "model_calls": 0, "max_zones": 20},
                "examples": text.W1_EXAMPLES,
                "non_goals": text.W1_NON_GOALS,
            },
        }
    ],
}


if __name__ == "__main__":
    path = ROOT / "registration.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    reg = json.loads(json.dumps(REGISTRATION))
    # 保留已算的 lock（由 lock.py 重写）
    if old.get("lock_hash"):
        reg["lock_hash"] = old["lock_hash"]
        for u in reg["units"]:
            u["version"] = old["lock_hash"]
    path.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 清单里进人或进模型的两处 W6 文字也从 text.py 取
    mp = ROOT / "mengos-package.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["tool_titles"] = {"rack.layout": text.W6_TOOL_TITLE}
    for t in m["types"]:
        if t["name"] == "rack_layout_receipt":
            t["note"] = text.W6_TYPE_NOTE
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("registration.json and manifest W6 written")
