"""行读取器：把一段来源变成“列名 + 带稳定序号的行”。

读取器按数据格式分，不按行业分（设计-确定性计数工具 §11.2）。调用方给出原文的三种：
  - rows：调用方直接给列名与行（每行是单元格数组）；
  - mengos-cad-v1：图纸解析单元的节（竖线分隔，节头带列名，多数带“共 N 条/组”，按行块再切时带“本块第 a–b 条”）；
  - gfm：GFM 表格（首行表头、次行分隔，续块重复表头）。
认不出的文本一律报 BadInput，不猜。按文件读（source.file，引擎交附件文件本身）见 file_source.py。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field


class BadInput(Exception):
    pass


@dataclass
class Table:
    columns: list[str]
    rows: list[tuple[str, list[str]]]          # (稳定序号, 单元格)
    source: dict = field(default_factory=dict)  # 回执 source 段
    checks: list[dict] = field(default_factory=list)


# 节头：#名称（列|列|…）[共 N 条|组][｜本块第 a–b 条]
SECTION_RE = re.compile(r"^#(?P<name>[^（#]+)（(?P<cols>[^）]*\|[^）]*)）(?:共 (?P<n>\d+) (?:条|组))?(?:｜本块第 (?P<a>\d+)–(?P<b>\d+) 条)?\s*$")
HEAD_RE = re.compile(r"^#(?:mengos-cad v\d+|单元 |分块 |表 )")
CHUNK_RE = re.compile(r"^#分块 (?P<k>\d+)/(?P<n>\d+)(?:｜表行 (?P<a>\d+)–(?P<b>\d+))?\s*$")
TABLE_HEAD_RE = re.compile(r"^#表 (?P<label>[^｜]+)｜.*｜(?P<nr>\d+)×(?P<nc>\d+)(?:｜|$)")


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def source_hash(src) -> str:
    return hashlib.sha256(canonical(src).encode("utf-8")).hexdigest()


def cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        raise BadInput("单元格不能是布尔值")
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return repr(v) if isinstance(v, float) else str(v)
    if isinstance(v, str):
        return v
    raise BadInput("单元格只能是字符串、数或 null")


def _unit_short(unit_line: str) -> str:
    name = unit_line[len("#单元 "):].split("｜", 1)[0].strip()
    m = re.match(r"^图幅 (S\d+)$", name)
    if m:
        return m.group(1)
    return re.sub(r"\s+", "", name.replace("图框外·", ""))


def _check_limit(n: int, max_rows) -> None:
    if max_rows is not None and n > max_rows:
        raise BadInput(f"来源行数 {n} 超过上限 {max_rows}（调用方给出的行；行多的来源要等引擎按引用取原文）")


# ───────── rows：调用方给的列与行 ─────────

def read_rows(spec: dict, max_rows) -> Table:
    cols = spec.get("columns")
    rows = spec.get("rows")
    if not isinstance(cols, list) or not cols or not all(isinstance(c, str) and c for c in cols):
        raise BadInput("columns 须为非空字符串数组")
    if len(set(cols)) != len(cols):
        raise BadInput("columns 里有重名列")
    if not isinstance(rows, list):
        raise BadInput("rows 须为数组")
    _check_limit(len(rows), max_rows)
    label = spec.get("label") or "行"
    out = []
    for i, r in enumerate(rows, 1):
        if not isinstance(r, list) or len(r) != len(cols):
            raise BadInput(f"第 {i} 行的单元格数与列数 {len(cols)} 不符")
        out.append((f"{label}/{i}", [cell_text(v) for v in r]))
    declared = spec.get("declared")
    checks = []
    if declared is not None:
        checks.append({"name": "rows_read_eq_declared", "ok": declared == len(out)})
        if declared != len(out):
            raise BadInput(f"读到 {len(out)} 行，与声明的 {declared} 行不符，不出数")
    return Table(list(cols), out, {"form": "rows", "reader": "rows", "section": None, "unit": None,
                                    "rows_declared": declared, "rows_read": len(out), "chunks": None}, checks)


# ───────── mengos-cad-v1 ─────────

def _split_cells(line: str, n: int) -> list[str] | None:
    cells = line.split("|", n - 1)
    return cells if len(cells) == n else None


def parse_cad_unit(texts: list[str]) -> dict:
    """一个单元的各段（同一单元的若干分块）→ {unit, found, order, total_chunks, given, chunks_complete}；不取节。"""
    chunks = []
    unit_line = None
    for ci, t in enumerate(texts):
        lines = t.replace("\r\n", "\n").split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        if not lines or lines[0].strip() != "#mengos-cad v1":
            raise BadInput(f"第 {ci + 1} 段不是 mengos-cad v1 解析单元（首行须为 #mengos-cad v1）")
        u = next((l for l in lines if l.startswith("#单元 ")), None)
        if u is None:
            raise BadInput(f"第 {ci + 1} 段没有 #单元 行")
        if unit_line is None:
            unit_line = u
        elif u != unit_line:
            raise BadInput("各段不属于同一个单元（#单元 行不同）")
        k = n = None
        for l in lines:
            m = CHUNK_RE.match(l)
            if m:
                k, n = int(m.group("k")), int(m.group("n"))
                break
        chunks.append({"k": k, "n": n, "lines": lines})
    # 分块次序：有 #分块 时按 k 排，k 重复或块数不一致 ⟹ 失败
    if any(c["k"] is not None for c in chunks):
        if any(c["k"] is None for c in chunks):
            raise BadInput("有的段带 #分块、有的不带")
        ns = {c["n"] for c in chunks}
        if len(ns) != 1:
            raise BadInput("各段 #分块 的总块数不一致")
        ks = [c["k"] for c in chunks]
        if len(set(ks)) != len(ks):
            raise BadInput("同一分块给了两次")
        chunks.sort(key=lambda c: c["k"])
        total_chunks = ns.pop()
        chunks_complete = sorted(ks) == list(range(1, total_chunks + 1))
    else:
        if len(chunks) > 1:
            raise BadInput("给了多段但都没有 #分块 标记")
        total_chunks = 1
        chunks_complete = True

    # 逐段收集各节
    found: dict[str, dict] = {}
    order: list[str] = []
    for c in chunks:
        cur = None
        for l in c["lines"]:
            m = SECTION_RE.match(l)
            if m:
                name = m.group("name").strip()
                cols = m.group("cols").split("|")
                n_decl = int(m.group("n")) if m.group("n") is not None else None
                a = int(m.group("a")) if m.group("a") else None
                b = int(m.group("b")) if m.group("b") else None
                sec = found.get(name)
                if sec is None:
                    sec = found[name] = {"columns": cols, "declared": n_decl, "parts": []}
                    order.append(name)
                elif sec["columns"] != cols or sec["declared"] != n_decl:
                    raise BadInput(f"节“{name}”在各块的表头不一致")
                cur = {"a": a, "b": b, "rows": []}
                sec["parts"].append(cur)
                continue
            if CHUNK_RE.match(l):
                continue          # #分块 行在头部之后、节头之前或之后都可能出现，不打断当前节
            if HEAD_RE.match(l):
                cur = None
                continue
            if l.startswith("#") and cur is None:
                continue          # 其他头部行（标题栏等）
            if cur is not None:
                cur["rows"].append(l)
    return {"unit": _unit_short(unit_line), "found": found, "order": order, "total_chunks": total_chunks,
            "given": len(chunks), "chunks_complete": chunks_complete}


def cad_section_rows(pu: dict, section: str, max_rows) -> tuple[list[str], list[tuple[str, list[str]]], int | None, list[dict]]:
    """从 parse_cad_unit 的结果里取一节 → (列名, 行, 声明条数, 核对项)；读到条数与声明不符、分块不连续或不全 ⟹ BadInput。"""
    sec = pu["found"][section]
    cols = sec["columns"]
    declared = sec["declared"]
    unit = pu["unit"]
    rows: list[tuple[str, list[str]]] = []
    contiguous = True
    expect_a = 1
    for p in sec["parts"]:
        a = p["a"] if p["a"] is not None else expect_a
        if p["a"] is not None:
            if p["a"] != expect_a or p["b"] - p["a"] + 1 != len(p["rows"]):
                contiguous = False
        for j, line in enumerate(p["rows"]):
            cells = _split_cells(line, len(cols))
            if cells is None:
                raise BadInput(f"节“{section}”第 {a + j} 行的列数与表头不符：{line[:80]}")
            rows.append((f"{unit}/{section}/{a + j}", cells))
        expect_a = a + len(p["rows"])
    _check_limit(len(rows), max_rows)
    checks = []
    if declared is not None:
        ok = len(rows) == declared
        checks.append({"name": "rows_read_eq_declared", "ok": ok})
        checks.append({"name": "chunks_contiguous", "ok": contiguous})
        if not ok:
            raise BadInput(f"节“{section}”读到 {len(rows)} 行，与节头声明的 {declared} 行不符（分块不全？），不出数")
        if not contiguous:
            raise BadInput(f"节“{section}”的分块行号不连续，不出数")
    else:
        checks.append({"name": "chunks_complete", "ok": pu["chunks_complete"]})
        if not pu["chunks_complete"]:
            raise BadInput(f"节“{section}”没有声明条数，分块又不全（{pu['total_chunks']} 块只给了 {pu['given']} 块），无法核对完整，不出数")
    return cols, rows, declared, checks


def read_cad(texts: list[str], section: str | None, max_rows) -> Table:
    pu = parse_cad_unit(texts)
    found, order = pu["found"], pu["order"]
    if not found:
        raise BadInput("单元里没有认得出的节")
    if section is None:
        with_rows = [n for n in order if any(p["rows"] for p in found[n]["parts"])]
        if len(with_rows) != 1:
            raise BadInput("单元里有多个节，须用 section 指定：" + "、".join(order))
        section = with_rows[0]
    if section not in found:
        raise BadInput(f"单元里没有节“{section}”；有：" + "、".join(order))
    cols, rows, declared, checks = cad_section_rows(pu, section, max_rows)
    return Table(cols, rows, {"form": "text", "reader": "mengos-cad-v1", "section": section, "unit": pu["unit"],
                              "rows_declared": declared, "rows_read": len(rows),
                              "chunks": {"given": pu["given"], "total": pu["total_chunks"]}}, checks)


# ───────── gfm ─────────

def _gfm_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    cells, cur, i = [], [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|"); i += 2; continue
        if ch == "|":
            cells.append("".join(cur).strip()); cur = []; i += 1; continue
        cur.append(ch); i += 1
    cells.append("".join(cur).strip())
    return cells


SEP_CELL = re.compile(r"^:?-{1,}:?$")


def read_gfm(texts: list[str], max_rows) -> Table:
    header = None
    unit = None
    declared = None
    rows: list[tuple[str, list[str]]] = []
    chunk_marks = []
    for ci, t in enumerate(texts):
        lines = [l for l in t.replace("\r\n", "\n").split("\n") if l.strip()]
        tlines = []
        for l in lines:
            if l.lstrip().startswith("|"):
                tlines.append(l)
                continue
            m = TABLE_HEAD_RE.match(l)
            if m:
                lab = m.group("label").strip()
                if unit is not None and unit != lab:
                    raise BadInput("各段不属于同一张表")
                unit = lab
                declared = int(m.group("nr")) - 1
            m = CHUNK_RE.match(l)
            if m:
                chunk_marks.append((int(m.group("k")), int(m.group("n"))))
        if len(tlines) < 2:
            raise BadInput(f"第 {ci + 1} 段里没有 GFM 表格（首行表头、次行分隔）")
        h = _gfm_cells(tlines[0])
        if not all(SEP_CELL.match(c) for c in _gfm_cells(tlines[1])):
            raise BadInput(f"第 {ci + 1} 段表头下一行不是分隔行")
        if header is None:
            header = h
        elif h != header:
            raise BadInput("各段表头不一致")
        body = tlines[2:]
        for line in body:
            cells = _gfm_cells(line)
            if len(cells) != len(header):
                raise BadInput(f"表格一行的格数 {len(cells)} 与表头 {len(header)} 不符：{line[:80]}")
            rows.append((f"{unit or '表'}/{len(rows) + 1}", cells))
    if not header or any(c == "" for c in header) or len(set(header)) != len(header):
        raise BadInput("表头列名须非空且不重名")
    _check_limit(len(rows), max_rows)
    checks = []
    if chunk_marks:
        ns = {n for _, n in chunk_marks}
        ks = sorted(k for k, _ in chunk_marks)
        complete = len(ns) == 1 and ks == list(range(1, ns.pop() + 1))
        checks.append({"name": "chunks_complete", "ok": complete})
        if not complete and declared is None:
            raise BadInput("表格分块不全且没有声明行数，无法核对完整，不出数")
    if declared is not None:
        ok = declared == len(rows)
        checks.append({"name": "rows_read_eq_declared", "ok": ok})
        if not ok:
            raise BadInput(f"表格读到 {len(rows)} 行，与表头声明的 {declared} 行不符，不出数")
    return Table(header, rows, {"form": "text", "reader": "gfm", "section": None, "unit": unit,
                                "rows_declared": declared, "rows_read": len(rows),
                                "chunks": {"given": len(texts), "total": (chunk_marks[0][1] if chunk_marks else len(texts))}}, checks)


# ───────── 入口 ─────────

ASSUMPTION_TRANSCRIBED = "来源行由调用方转录，程序未与原文逐字核对"


def read_source(src, max_rows, workdir=None) -> Table:
    if not isinstance(src, dict):
        raise BadInput("source 须为对象")
    if sum(k in src for k in ("rows", "text", "file")) != 1:
        raise BadInput("source 须且只须给 rows（列与行）、text（解析单元或表格原文）、file（附件）之一")
    if "file" in src:
        extra = set(src) - {"file", "section", "unit"}
        if extra:
            raise BadInput("按文件读时 source 只认 file、section、unit；多了：" + "、".join(sorted(extra)))
        from file_source import read_file_source
        return read_file_source(src, workdir)
    if "unit" in src:
        raise BadInput("unit 只在按文件读（source.file）时用")
    if "rows" in src:
        t = read_rows(src, max_rows)
    else:
        texts = src["text"]
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or not texts or not all(isinstance(x, str) and x for x in texts):
            raise BadInput("text 须为非空字符串或非空字符串数组")
        reader = src.get("reader")
        if reader == "mengos-cad-v1":
            t = read_cad(texts, src.get("section"), max_rows)
        elif reader == "gfm":
            if src.get("section") is not None:
                raise BadInput("gfm 读取器不认 section")
            t = read_gfm(texts, max_rows)
        else:
            raise BadInput("reader 须为 mengos-cad-v1 或 gfm")
    t.source = {"mode": "inline", **t.source, "columns": t.columns, "source_sha256": source_hash(src)}
    return t


def assumptions_of(table: Table) -> list[str]:
    """按文件读的来源由引擎交文件、程序核过哈希与条数，不挂转录假设；调用方给的来源照旧挂。"""
    return [ASSUMPTION_TRANSCRIBED] if table.source.get("mode") == "inline" else []
