"""按文件读取的来源（source.file，mode = "file"）。

承 kernel-spec 17 TL-9d（附件文件本身作工具入参）与 设计-附件按引用由工具读取-2026-11-19 §6.2、§二十一。
模型在 source.file 只写附件引用；引擎派单时把原件（与存储服务入库时存下的完整解析结构）放进本次调用工作目录下的
只读输入子目录，把该位置换成 {path, sha256, bytes, media_type, parsed?: {path, sha256, parser}}，path 相对工作目录。

- 默认读完整解析结构（不重新解析）；结构里标“未存”的明细节、或没有解析结构时，用包里带的同一份解析库（cadlib/）
  打开原件读出：两条路出的行是同一份代码产生的。
- 核对：原件与解析结构各核 sha256 与字节数；解析结构的解析库（引擎原样转交的 parser 串与结构里记的 library）
  须与本包带的解析库是同一版；逐节核“读到条数 = 声明条数”。任一不过 ⟹ BadInput，不出数。
- 解析规格不覆盖、结构里标“未解析”的特性，如实列在回执 unparsed 里；查询的节正落在这类上 ⟹ 答“拿不到”，不出数。
- 文件内容不进回执；回执只记哈希、字节数、解析库版本与读了什么。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys

from readers import BadInput, SECTION_RE, Table, _unit_short, cad_section_rows, parse_cad_unit

HERE = os.path.dirname(os.path.abspath(__file__))
CADLIB = os.path.join(HERE, "cadlib")
PARSED_FORMAT = "mengos-cad-parsed"
DETAIL_SECTIONS = ("线段明细", "嵌套插入", "未插入图块文字")
UNIT_COL = "单元"
FILE_KEYS = {"path", "sha256", "bytes", "media_type", "parsed"}
PARSED_KEYS = {"path", "sha256", "parser"}
ORIGINAL_OUT = ".count-original"      # 回原件读时解析库的输出目录（工作目录内，读完即删，不留产出）


def own_library() -> dict:
    """本包带的解析库版本 {name, spec, version, sha256}（只用标准库，不导入解析核）。"""
    if CADLIB not in sys.path:
        sys.path.insert(0, CADLIB)
    from mengos_cad import library
    return library()


def parser_string(lib: dict) -> str:
    """与存储服务记在文件上的解析核串同一写法（vetc cad-extract：名@版本+sha256:哈希）。"""
    return f"{lib['name']}@{lib['version']}+sha256:{lib['sha256']}"


def unit_key(name: str) -> str:
    """单元名的比较键：去空白；“图幅k”与“S k”同指（图幅目录序号写 图幅k，单元头写 图幅 Sk）。"""
    s = "".join(str(name).split())
    if s.startswith("图幅S"):
        s = "S" + s[3:]
    elif s.startswith("图幅") and s[2:].isdigit():
        s = "S" + s[2:]
    return s


def _resolve(workdir, rel: str, what: str) -> str:
    if not isinstance(workdir, str) or not workdir:
        raise BadInput(f"{what}：调用没有工作目录，读不到附件文件")
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        raise BadInput(f"{what}：path 须为相对工作目录的路径")
    norm = os.path.normpath(rel)
    if norm == ".." or norm.startswith(".." + os.sep):
        raise BadInput(f"{what}：path 不得出工作目录")
    root = os.path.realpath(workdir)
    p = os.path.join(root, norm)
    cur = root
    for part in norm.split(os.sep):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise BadInput(f"{what}：路径里有符号链接，不读")
    try:
        st = os.stat(p)
    except OSError:
        raise BadInput(f"{what}：工作目录里没有这个文件") from None
    if not stat.S_ISREG(st.st_mode):
        raise BadInput(f"{what}：不是普通文件")
    return p


def _read_checked(path: str, sha256, nbytes, what: str) -> bytes:
    with open(path, "rb") as f:
        data = f.read()
    if not isinstance(sha256, str) or hashlib.sha256(data).hexdigest() != sha256:
        raise BadInput(f"{what}：文件字节与入参的 sha256 不符（被改动或截断），不出数")
    if nbytes is not None and nbytes != len(data):
        raise BadInput(f"{what}：文件字节数 {len(data)} 与入参的 {nbytes} 不符，不出数")
    return data


def _parse_original(dxf_path: str, workdir: str, fid: str) -> dict:
    """用本包带的解析库打开原件，出完整解析结构（与存储服务入库同一份代码；明细不设体量上限，全部留存）。"""
    if CADLIB not in sys.path:
        sys.path.insert(0, CADLIB)
    from mengos_cad import core
    out = os.path.join(os.path.realpath(workdir), ORIGINAL_OUT)
    shutil.rmtree(out, ignore_errors=True)
    cap = dict(core.DETAIL_CAP)
    core.DETAIL_CAP.update({k: sys.maxsize for k in cap})
    try:
        core.run(dxf_path, out, fid=fid, parsed=True)
        with open(os.path.join(out, "parsed.json"), "rb") as f:
            return json.loads(f.read())
    except core.CadFail as e:
        raise BadInput(f"原件读不了（{e.code}：{e.message}），不出数") from None
    finally:
        core.DETAIL_CAP.clear()
        core.DETAIL_CAP.update(cap)
        shutil.rmtree(out, ignore_errors=True)
        shutil.rmtree(out + ".partial", ignore_errors=True)


class Doc:
    """完整解析结构的读面：单元（按单元名归并分块）、明细节、未解析清单。"""

    def __init__(self, d: dict):
        if not isinstance(d, dict) or d.get("format") != PARSED_FORMAT:
            raise BadInput(f"解析结构不是 {PARSED_FORMAT}，不出数")
        self.raw = d
        groups: dict[str, list[str]] = {}
        for u in d.get("units") or []:
            pu_text = u.get("text") if isinstance(u, dict) else None
            if not isinstance(pu_text, str):
                raise BadInput("解析结构的单元缺文本，不出数")
            groups.setdefault(self._head(pu_text), []).append(pu_text)
        self.units = []                       # [(单元名, 解析后的单元)]，次序同解析结构
        for head, texts in groups.items():
            if head.startswith("#表 "):       # 表单元是 GFM 表格，不分节：只列名，按节读时记在“没有这一节”的单元里
                self.units.append((head[len("#表 "):].split("｜", 1)[0].strip(), {"order": [], "found": {}}))
                continue
            pu = parse_cad_unit(texts)
            # 图幅目录的单元头自带列名（#单元 图幅目录（序号|…）），它是单元头不是节：单元名取“（”之前，不当节读
            for name in [n for n in pu["order"] if n.startswith("单元 ")]:
                pu["order"].remove(name)
                del pu["found"][name]
            self.units.append((pu["unit"].split("（", 1)[0], pu))
        self.details = []                     # [(单元名或 "", 节名, 列名, 声明条数, 行, stored)]
        for x in d.get("details") or []:
            m = SECTION_RE.match(x.get("header", ""))
            if m is None or m.group("name").strip() != x.get("section"):
                raise BadInput("解析结构的明细节头认不出，不出数")
            unit = _unit_short("#单元 " + x["unit"]) if x.get("unit") else ""
            self.details.append((unit, x["section"], m.group("cols").split("|"), int(m.group("n")), x.get("lines") or [], bool(x.get("stored"))))
        self.unparsed = [u for u in d.get("unparsed") or [] if isinstance(u, dict)]

    @staticmethod
    def _head(text: str) -> str:
        for line in text.split("\n"):
            if line.startswith("#单元 "):
                return line
            if line.startswith("#表 "):
                return line.split("｜", 1)[0]
        raise BadInput("解析结构的单元没有 #单元 行，不出数")

    def sections_available(self) -> dict:
        out: dict[str, list[str]] = {}
        for _, pu in self.units:
            for name in pu["order"]:
                out.setdefault(name, pu["found"][name]["columns"])
        for _, name, cols, *_ in self.details:
            out.setdefault(name, cols)
        return out

    def unit_names(self) -> list[str]:
        return [u for u, _ in self.units]

    def needs_original(self, section: str) -> bool:
        return any(name == section and not stored for _, name, _, _, _, stored in self.details)


def _unparsed_summary(unparsed: list, unit: str | None) -> list:
    agg: dict[str, int] = {}
    for u in unparsed:
        if unit is not None and unit_key(u.get("unit") or "") != unit_key(unit):
            continue
        agg[u.get("kind", "")] = agg.get(u.get("kind", ""), 0) + int(u.get("count", 0))
    return [{"kind": k, "count": agg[k]} for k in sorted(agg)]


def read_file_source(src: dict, workdir) -> Table:
    f = src.get("file")
    if not isinstance(f, dict) or "attachment" in f:
        raise BadInput("source.file 没有换成附件文件（引擎未交文件），读不到")
    extra = set(f) - FILE_KEYS
    if extra or not {"path", "sha256", "bytes"} <= set(f):
        raise BadInput("source.file 须为 {path, sha256, bytes, media_type, parsed?}")
    section = src.get("section")
    if not isinstance(section, str) or not section:
        raise BadInput("按文件读须写 section（读哪一节）")
    unit_req = src.get("unit")
    if unit_req is not None and (not isinstance(unit_req, str) or not unit_req):
        raise BadInput("unit 须为非空字符串")
    lib = own_library()
    checks = []
    orig_path = _resolve(workdir, f["path"], "原件")
    orig = _read_checked(orig_path, f["sha256"], f.get("bytes"), "原件")
    p = f.get("parsed")
    doc = None
    read_from = "original"
    if p is not None:
        if not isinstance(p, dict) or set(p) - PARSED_KEYS or not PARSED_KEYS <= set(p):
            raise BadInput("source.file.parsed 须为 {path, sha256, parser}")
        if p["parser"] != parser_string(lib):
            raise BadInput(f"这份文件入库时用的解析库是 {p['parser']}，与工具所带的 {parser_string(lib)} 不同，不出数")
        pdata = _read_checked(_resolve(workdir, p["path"], "解析结构"), p["sha256"], None, "解析结构")
        try:
            raw = json.loads(pdata)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BadInput("解析结构不是合法 JSON，不出数") from None
        if raw.get("library") != lib:
            raise BadInput("解析结构里记的解析库与工具所带的不同，不出数")
        doc = Doc(raw)
        read_from = "parsed"
    checks += [{"name": "sha256_eq", "ok": True}, {"name": "parser_eq_ingest", "ok": True}]
    if doc is None or doc.needs_original(section):
        fid = doc.raw.get("fid", "X") if doc is not None else "X"
        doc = Doc(_parse_original(orig_path, workdir, fid if isinstance(fid, str) else "X"))
        read_from = "original"
        if doc.raw.get("library") != lib:
            raise BadInput("回原件读出的解析库版本与工具所带的不同，不出数")

    available = doc.sections_available()
    units = doc.unit_names()
    scope_unit = None
    if unit_req is not None:
        hit = [u for u in units if unit_key(u) == unit_key(unit_req)]
        if not hit:
            raise BadInput(f"这份附件里没有单元“{unit_req}”；有：" + "、".join(units))
        scope_unit = hit[0]
    if section not in available:
        lost = [u for u in doc.unparsed if section and (u.get("kind") == section or str(u.get("kind", "")).startswith(section))]
        if lost:
            n = sum(int(u.get("count", 0)) for u in lost)
            raise BadInput(f"“{section}”拿不到：这份附件里这一类标为未解析，共 {n} 处，解析规格不覆盖，不出数")
        raise BadInput(f"这份附件里没有节“{section}”；有：" + "、".join(available))

    cols = available[section]
    rows: list[tuple[str, list[str]]] = []
    declared = 0
    units_read, without = 0, []
    if section in DETAIL_SECTIONS:
        for unit, name, dcols, n, lines, _ in doc.details:
            if name != section or (scope_unit is not None and unit_key(unit) != unit_key(scope_unit)):
                continue
            if dcols != cols:
                raise BadInput(f"节“{section}”在各单元的列名不一致，不出数")
            if len(lines) != n:
                raise BadInput(f"节“{section}”（{unit or '不属任何单元'}）读到 {len(lines)} 行，与声明的 {n} 行不符，不出数")
            for j, line in enumerate(lines, 1):
                cells = line.split("|", len(cols) - 1)
                if len(cells) != len(cols):
                    raise BadInput(f"节“{section}”第 {j} 行的列数与表头不符：{line[:80]}")
                rows.append((f"{unit or '-'}/{section}/{j}", [unit] + cells))
            declared += n
            units_read += 1
        with_sec = {unit_key(u) for u, name, *_ in doc.details if name == section}
        without = [u for u in units if unit_key(u) not in with_sec]
    else:
        for unit, pu in doc.units:
            if scope_unit is not None and unit != scope_unit:
                continue
            if section not in pu["found"]:
                without.append(unit)
                continue
            ucols, urows, n, _ = cad_section_rows(pu, section, None)
            if ucols != cols:
                raise BadInput(f"节“{section}”在各单元的列名不一致，不出数")
            rows += [(rid, [unit] + cells) for rid, cells in urows]
            declared += n if n is not None else len(urows)
            units_read += 1
    checks.append({"name": "rows_read_eq_declared", "ok": len(rows) == declared})
    if len(rows) != declared:
        raise BadInput(f"节“{section}”读到 {len(rows)} 行，与声明的 {declared} 行不符，不出数")
    source = {
        "mode": "file", "read_from": read_from,
        "file": {"sha256": f["sha256"], "bytes": len(orig)},
        "parser": lib, "scope": "unit" if scope_unit is not None else "whole",
        "unit": scope_unit, "section": section,
        "unparsed": _unparsed_summary(doc.unparsed, scope_unit),
        "units_read": units_read, "rows_declared": declared, "rows_read": len(rows),
        "columns": [UNIT_COL] + cols,
        "sections_available": available,
        "units_without_section": without,
    }
    return Table([UNIT_COL] + cols, rows, source, checks)
