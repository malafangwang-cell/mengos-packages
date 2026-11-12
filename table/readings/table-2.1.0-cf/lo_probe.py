"""LibreOffice 无头读回 cf-probe.xlsx（C2）：打开 → 全部重算 → 导出 PDF；再把 B3 改成 50 → 重算 → 导出第二份 PDF。

要用带 uno 的系统 Python 运行（/usr/bin/python3），LibreOffice 以 --headless 起在本地管道上。
用法：/usr/bin/python3 lo_probe.py <cf-probe.xlsx> <输出目录>
产出：<输出目录>/lo-1.pdf（原样）、lo-2.pdf（B3=50 之后）、lo-version.txt
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue

src, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
prof = out / "lo-profile"
pipe = "mengos_cf_probe"
proc = subprocess.Popen(["soffice", "--headless", "--invisible", "--nologo", "--norestore",
                         f"-env:UserInstallation=file://{prof}", f"--accept=pipe,name={pipe};urp;"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prop(n, v):
    p = PropertyValue()
    p.Name, p.Value = n, v
    return p


try:
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(120):
        try:
            ctx = resolver.resolve(f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext")
            break
        except Exception:
            time.sleep(0.5)
    else:
        raise SystemExit("LibreOffice 没有起来")
    smgr = ctx.ServiceManager
    desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
    doc = desktop.loadComponentFromURL(uno.systemPathToFileUrl(str(src)), "_blank", 0, (prop("Hidden", True),))
    doc.calculateAll()
    pdf = (prop("FilterName", "calc_pdf_Export"),)
    doc.storeToURL(uno.systemPathToFileUrl(str(out / "lo-1.pdf")), pdf)
    sheet = doc.Sheets.getByIndex(0)
    sheet.getCellRangeByName("B3").setValue(50)
    doc.calculateAll()
    doc.storeToURL(uno.systemPathToFileUrl(str(out / "lo-2.pdf")), pdf)
    doc.close(True)
    prov = smgr.createInstanceWithContext("com.sun.star.configuration.ConfigurationProvider", ctx)
    node = prov.createInstanceWithArguments("com.sun.star.configuration.ConfigurationAccess",
                                            (prop("nodepath", "/org.openoffice.Setup/Product"),))
    (out / "lo-version.txt").write_text(f"{node.ooName} {node.ooSetupVersionAboutBox}\n", encoding="utf-8")
    try:
        desktop.terminate()
    except Exception:
        pass
finally:
    time.sleep(1)
    proc.kill()
    subprocess.run(["rm", "-rf", str(prof)])
