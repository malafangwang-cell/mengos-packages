// 表格渲染器选区走查（2.3.1）：真浏览器里点格、拖选、点行号、点列头、点合计、Ctrl / ⌘ 加选，核对渲染器发出的 mengos.select / select_denied，
// 以及宿主回发 mengos.open / busy 后的描边。用法：先用 table.build 跑出夹具目录（每个子目录含 out.json 与视图文件，另放 renderer.html），
//   node tools/check_renderer_select.cjs <夹具目录>     需要 playwright（不在包的依赖里，只给施工方本机用）。
const { chromium } = require(process.env.PLAYWRIGHT || "playwright");
const fs = require("fs"), path = require("path");
const D = process.argv[2] || __dirname;
const results = []; const ok = (n, c) => results.push(`${c ? "过" : "败"} ${n}`);
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 800 } });
  const errs = []; p.on("pageerror", (e) => errs.push(String(e)));
  async function load(name) {
    const out = JSON.parse(fs.readFileSync(path.join(D, name, "out.json"), "utf8"));
    const vf = out.files.find((f) => f.format === "view");
    const bytes = [...fs.readFileSync(path.join(D, name, vf.path))];
    const html = fs.readFileSync(path.join(D, "renderer.html"), "utf8");
    await p.setContent(`<!doctype html><body style="margin:0"><iframe id="f" style="width:1180px;height:760px;border:0"></iframe><script>
      window.msgs = [];
      addEventListener("message", (e) => { const m = e.data; window.msgs.push(m); if (m.type === "mengos.ready") {
        const ab = new Uint8Array(${JSON.stringify(bytes)}).buffer;
        document.getElementById("f").contentWindow.postMessage({ type: "mengos.render", contract: "0.1", view: "full", theme: "light", object: { output: ${JSON.stringify(out)} }, files: [{ path: ${JSON.stringify(vf.path)}, role: "table.view", bytes: ab }], formats: [] }, "*"); } });
      document.getElementById("f").srcdoc = ${JSON.stringify(html).replace(/<\//g, "<\\/")};
    </script></body>`);
    await p.waitForFunction(() => document.getElementById("f").contentDocument?.querySelector("#grid table"), null, { timeout: 5000 });
    return p.frameLocator("#f");
  }
  const last = async (type) => { await p.waitForTimeout(150); return p.evaluate((t) => [...window.msgs].reverse().find((m) => m.type === t), type); };
  const clear = () => p.evaluate(() => { window.msgs = []; });
  let f = await load("bom");
  // 单格
  await f.locator('td[data-r="1"][data-c="2"]').click();
  let m = await last("mengos.select");
  ok("单格：cells，句柄 cell:_sa/_rb/qty", m && m.kind === "cells" && JSON.stringify(m.handles) === '["cell:_sa/_rb/qty"]' && m.sheet_id === "_sa" && m.anchor);
  // Ctrl 加选
  await f.locator('td[data-r="2"][data-c="3"]').click({ modifiers: ["Control"] });
  m = await last("mengos.select");
  ok("Ctrl 加选：两格，带 additive", m.handles.length === 2 && m.additive === true);
  // 拖选含公式列 ⟹ 收窄按钮
  await clear();
  await f.locator('td[data-r="0"][data-c="3"]').hover(); await p.mouse.down();
  await f.locator('td[data-r="1"][data-c="4"]').hover(); await p.mouse.up();
  ok("拖选含公式列：出收窄按钮", await f.locator("#pick:not([hidden])").count() === 1 && !(await last("mengos.select")));
  await f.locator('[data-pick="in"]').click();
  m = await last("mengos.select");
  ok("只改其余的格子：只剩输入格（2 格）", m.kind === "cells" && m.handles.length === 2 && m.handles.every((h) => h.endsWith("/price")));
  // 公式列一格 ⟹ 吸附成列定义
  await f.locator('td[data-r="0"][data-c="4"]').click();
  m = await last("mengos.select");
  ok("公式列的格：吸附成 column_def", m.kind === "column_def" && m.handles[0] === "col:_sa/amt");
  // 编号列
  await clear(); await f.locator('td[data-r="0"][data-c="0"]').click();
  m = await last("mengos.select_denied");
  ok("编号列：select_denied numbering", m && m.why_not === "numbering" && m.message.includes("编号"));
  // 合计
  await f.locator('td[data-total="4"]').click();
  m = await last("mengos.select");

  ok("合计：totals_def", m && m.kind === "totals_def" && m.handles[0] === "totals:_sa/amt");
  // 列头 = 列定义；排序在小箭头
  await f.locator('th[data-th="1"] button[data-col]').click();
  m = await last("mengos.select");
  ok("点列头：column_def", m.kind === "column_def" && m.col === "name");
  await f.locator('button[data-sort="2"]').click();
  ok("小箭头排序", (await f.locator('th[data-th="2"]').getAttribute("aria-sort")) === "ascending");
  // 行号拖选
  await f.locator('td.idx[data-row="0"]').hover(); await p.mouse.down(); await f.locator('td.idx[data-row="2"]').hover(); await p.mouse.up();
  m = await last("mengos.select");
  ok("行号拖选：rows 3 行", m.kind === "rows" && m.rows.length === 3);
  // 加选不同种 ⟹ 拒
  await clear(); await f.locator('td[data-r="0"][data-c="1"]').click({ modifiers: ["Meta"] });
  m = await last("mengos.select_denied");
  ok("⌘ 加选不同种：select_denied kind", m && m.why_not === "kind");
  // 宿主回发 open / busy
  await p.evaluate(() => document.getElementById("f").contentWindow.postMessage({ type: "mengos.open", contract: "0.1", handles: ["cell:_sa/_rc/qty"] }, "*"));
  await p.waitForTimeout(100);
  ok("mengos.open：聚光那一格", await f.locator('td[data-r="2"][data-c="2"].sel').count() === 1);
  await p.evaluate(() => document.getElementById("f").contentWindow.postMessage({ type: "mengos.busy", contract: "0.1", handles: ["cell:_sa/_rc/qty"] }, "*"));
  await p.waitForTimeout(100);
  ok("mengos.busy：那一格呼吸", await f.locator('td[data-r="2"][data-c="2"].busy').count() === 1);
  // 分组表：组头、小计
  f = await load("grp");
  await clear(); await f.locator('tr[data-gen="g"] td').nth(2).click();
  m = await last("mengos.select_denied");
  ok("生成的组头：select_denied group", m && m.why_not === "group");
  await f.locator('tr[data-gen="s"] td').nth(2).click();
  ok("小计：select_denied subtotal", (await last("mengos.select_denied")).why_not === "subtotal");
  // 派生表
  f = await load("der");
  const tabs = f.locator("#tabs button"); const n = await tabs.count();
  for (let i = 0; i < n; i++) { await tabs.nth(i).click(); if (await f.locator('td[data-r="0"]').count()) { await clear(); await f.locator('td[data-r="0"][data-c="1"]').click(); const d = await last("mengos.select_denied"); if (d && d.why_not === "derived") { ok("派生表的行：select_denied derived", true); break; } } if (i === n - 1) ok("派生表的行：select_denied derived", false); }
  ok("页面无报错", errs.length === 0);
  console.log(results.join("\n")); if (errs.length) console.log(errs.join("\n"));
  await b.close();
  process.exit(results.some((r) => r.startsWith("败")) || errs.length ? 1 : 0);
})();
