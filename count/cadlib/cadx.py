#!/usr/bin/env python3
"""mengos-cad 命令行外壳 (存储服务以子进程方式调用; 解析逻辑全在 mengos_cad.core)。
承 设计-附件按引用由工具读取-2026-11-19 §21.3 “可导入的核加命令行入口”; 由 vetc/src/cadx.py 迁入, 命令行形状与行为不变。
调用: cadx.py IN.dxf OUTDIR [--fid ID] [--emax N] [--imax N] [--rlimit-as-mb N] [--max-out-bytes N] [--parsed]
       cadx.py --library   (stdout 一行解析库版本 JSON, 不读图)
  成功: OUTDIR/units.json (单元列表, 每个单元一个切片); 带 --parsed 另写 OUTDIR/parsed.json (完整解析结构, ../SPEC.md); stdout 一行摘要 JSON; 退出码 0。
  失败: stdout 一行 JSON {"code","message"}; 退出码 3 = 422 类 (CAD_*), 4 = 内存 (CAD_RESOURCE_EXCEEDED); 失败不留产物。
  限额 (emax/imax/rlimit/max-out-bytes) 由外壳 cad-extract.ts 按部署配置传入。
"""
import json, os, sys


def _out(obj):
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


# ───────── 命令行 (固定形状, 无实验开关) ─────────
def _parse(argv):
    if len(argv) < 3:
        print(json.dumps({"code": "CAD_PARSE_FAILED", "message": "用法: cadx.py IN.dxf OUTDIR"}, ensure_ascii=False)); os._exit(3)
    o = {"dxf": argv[1], "outdir": argv[2], "fid": "X", "emax": 25_000_000, "imax": 500_000, "rlimit_as_mb": 0, "max_out_bytes": 64 * 1024 * 1024, "parsed": False}
    i = 3
    while i < len(argv):
        k = argv[i]
        if k == "--parsed":
            o["parsed"] = True; i += 1; continue
        if k in ("--fid",): o["fid"] = argv[i + 1]
        elif k == "--emax": o["emax"] = int(argv[i + 1])
        elif k == "--imax": o["imax"] = int(argv[i + 1])
        elif k == "--rlimit-as-mb": o["rlimit_as_mb"] = int(argv[i + 1])
        elif k == "--max-out-bytes": o["max_out_bytes"] = int(argv[i + 1])
        else:
            print(json.dumps({"code": "CAD_PARSE_FAILED", "message": f"未知参数 {k}"}, ensure_ascii=False)); os._exit(3)
        i += 2
    return o


def _fail(outdir, code, msg, rc):
    import shutil
    shutil.rmtree(outdir + ".partial", ignore_errors=True)
    _out({"code": code, "message": msg})
    os._exit(rc)


if __name__ == "__main__":
    if sys.argv[1:] == ["--library"]:
        from mengos_cad import library
        _out(library()); sys.exit(0)
    o = _parse(sys.argv)
    if o["rlimit_as_mb"]:
        import resource
        _lim = o["rlimit_as_mb"] * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (_lim, _lim))   # 必须在导入 numpy/ezdxf (即解析核) 之前
    try:
        from mengos_cad import core
    except MemoryError:
        _fail(o["outdir"], "CAD_RESOURCE_EXCEEDED", "处理该图纸所需内存超过上限", 4)
    try:
        r = core.run(o["dxf"], o["outdir"], fid=o["fid"], emax=o["emax"], imax=o["imax"], max_out_bytes=o["max_out_bytes"], parsed=o["parsed"])
    except core.CadFail as f:
        _out({"code": f.code, "message": f.message})
        os._exit(f.rc)
    except MemoryError:
        _fail(o["outdir"], "CAD_RESOURCE_EXCEEDED", "处理该图纸所需内存超过上限", 4)
    print(json.dumps(r, ensure_ascii=False, default=core._jd))
