"""渲染器页面自检（2.6.2：按需绘制、上下文丢失可恢复、不取外网资源）。只读页面文本，不起浏览器。"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "renderer" / "index.html").read_text(encoding="utf-8")
BEGIN, END = "<!-- vendor:begin -->", "<!-- vendor:end -->"


def _own_code() -> str:
    """页面里除内联库以外的部分。"""
    b, e = PAGE.index(BEGIN), PAGE.index(END)
    return PAGE[:b] + PAGE[e:]


def test_no_external_resources():
    # 字体、样式表、脚本都不从外网取：连不上时外链样式表会挡住发 mengos.ready 的脚本，外链脚本会让三维区空白
    own = _own_code()
    assert not re.search(r"<link\b", own, re.I)
    assert not re.search(r"""\b(?:src|href)\s*=\s*["']?(?:https?:)?//""", own, re.I)
    assert not re.search(r"@import|url\(\s*[\"']?(?:https?:)?//", own, re.I)
    assert 'type="importmap"' not in own
    for host in ("googleapis", "gstatic", "jsdelivr", "cdnjs", "unpkg"):
        assert host not in own, host


def test_ready_is_posted_before_any_other_script():
    first_script = PAGE.index("<script")
    assert PAGE.index('type: "mengos.ready"') < PAGE.index("</script>", first_script)


def test_render_on_demand():
    own = _own_code()
    assert "function loop()" not in own and "requestAnimationFrame(loop)" not in own
    # 只有 requestRender（合并同帧请求）和悬停拾取这两处用 requestAnimationFrame
    assert own.count("requestAnimationFrame(") == 2
    assert 'controls.addEventListener("change", requestRender)' in own
    assert "preserveDrawingBuffer: true" not in own


def test_context_loss_is_handled():
    own = _own_code()
    assert 'addEventListener("webglcontextlost", onContextLost)' in own
    assert 'addEventListener("webglcontextrestored", onContextRestored)' in own
    assert re.search(r"function onContextLost\(e\) \{\s*e\.preventDefault\(\);", own)


def test_vendor_block_matches_its_recorded_hashes():
    b, e = PAGE.index(BEGIN), PAGE.index(END)
    block = PAGE[b:e]
    scripts = re.findall(r"<script>(.*?)</script>", block, re.S)
    assert len(scripts) == 2
    jszip, three = scripts
    assert f"jszip {hashlib.sha256(jszip.encode()).hexdigest()}" in block
    assert f"three {hashlib.sha256(three.encode()).hexdigest()}" in block
    assert "three@0.170.0" in three and "JSZip v3.10.1" in jszip
