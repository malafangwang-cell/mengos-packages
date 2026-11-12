"""LibreOffice 无头重算（执行令 table 包 2.1.0 §三 Excel 往返）：打开 xlsx → calculateAll() → 另存为 xlsx（与可选的 PDF）。

要用带 uno 的系统 Python 运行（/usr/bin/python3）；一次起一个 LibreOffice，逐个处理。
用法：/usr/bin/python3 tools/lo_recalc.py <输出目录> <a.xlsx> [<b.xlsx> …] [--pdf]
产出：<输出目录>/<名>.lo.xlsx（重算后的值写在缓存里），--pdf 时另出 <名>.lo.pdf；末行打印 LibreOffice 版本。
"""
import subprocess
import sys
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


def prop(n, v):
    p = PropertyValue()
    p.Name, p.Value = n, v
    return p


def main(argv):
    pdf = "--pdf" in argv
    argv = [a for a in argv if a != "--pdf"]
    out, files = Path(argv[0]).resolve(), [Path(a).resolve() for a in argv[1:]]
    out.mkdir(parents=True, exist_ok=True)
    prof = out / ".lo-profile"
    pipe = f"mengos_lo_{int(time.time() * 1000)}"
    proc = subprocess.Popen(["soffice", "--headless", "--invisible", "--nologo", "--norestore",
                             f"-env:UserInstallation=file://{prof}", f"--accept=pipe,name={pipe};urp;"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        for _ in range(240):
            try:
                ctx = resolver.resolve(f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise SystemExit("LibreOffice 没有起来")
        smgr = ctx.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        for f in files:
            doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(str(f)), "_blank", 0, (prop("Hidden", True),))
            doc.calculateAll()
            stem = f.name[:-5] if f.name.endswith(".xlsx") else f.stem
            doc.storeToURL(uno.systemPathToFileUrl(str(out / f"{stem}.lo.xlsx")), (prop("FilterName", "Calc MS Excel 2007 XML"),))
            if pdf:
                doc.storeToURL(uno.systemPathToFileUrl(str(out / f"{stem}.lo.pdf")), (prop("FilterName", "calc_pdf_Export"),))
            doc.close(True)
        prov = smgr.createInstanceWithContext("com.sun.star.configuration.ConfigurationProvider", ctx)
        node = prov.createInstanceWithArguments("com.sun.star.configuration.ConfigurationAccess",
                                                (prop("nodepath", "/org.openoffice.Setup/Product"),))
        print(f"{node.ooName} {node.ooSetupVersionAboutBox}")
        try:
            desktop.terminate()
        except Exception:
            pass
    finally:
        time.sleep(0.5)
        proc.kill()
        subprocess.run(["rm", "-rf", str(prof)])


if __name__ == "__main__":
    main(sys.argv[1:])
