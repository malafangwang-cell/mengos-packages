// 生成 renderer/index.html 里 <!-- vendor:begin --> 与 <!-- vendor:end --> 之间的内联库（cad 2.6.2 起）。
//
// 渲染器以 srcdoc 装进不透明源的 sandbox iframe，浏览器缓存用不上，公共 CDN 在部分网络下连不上；
// 所以 three.js 与 JSZip 随页内联，固定版本，按 npm 发布包的 sha256 核对后再打包。
//   · three 0.170.0（MIT）：只打包本页用到的 THREE.* 名字（从页面脚本里扫出来）+ GLTFLoader + OrbitControls，
//     esbuild 压缩成一个函数 window.__cadLib()。函数体在调用前只做预解析，嵌入视图不付编译三维库的代价。
//   · JSZip 3.10.1（MIT 或 GPLv3）：原样内联发布包里的 dist/jszip.min.js。
//
// 用法（不在包的运行时里执行，安装与渲染都不调用本文件）：
//   npm pack three@0.170.0 jszip@3.10.1           # 得到两个 .tgz
//   npm i esbuild@0.24.0                          # 任意目录
//   node renderer/build_vendor.mjs --three three-0.170.0.tgz --jszip jszip-3.10.1.tgz --esbuild <esbuild 可执行文件>
//   加 --check：只核对 index.html 里现有的内联段与重新生成的逐字节相同，不写文件。
// 改了页面脚本里用到的 THREE.* 名字之后要重跑本脚本。改完再依次跑 tools/make_package.py 更新 content_hash。
import { readFileSync, writeFileSync, mkdtempSync, rmSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const PINS = {
  three: { version: "0.170.0", sha256: "4a608a355dcaba72e0e5383cdc814303f5b6060b43c238cdf6932dceb699238d" },
  jszip: { version: "3.10.1", sha256: "5117f4a2a645aeb307bf3b829c575ad58135cc97e75291e594532ab5b5b21b23" },
  esbuild: "0.24.0",
};
const HERE = dirname(fileURLToPath(import.meta.url));
const PAGE = join(HERE, "index.html");
const BEGIN = "<!-- vendor:begin -->";
const END = "<!-- vendor:end -->";

const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
const check = args.includes("--check");
const sha256 = (b) => createHash("sha256").update(b).digest("hex");
const die = (m) => { console.error(m); process.exit(2); };

const threeTgz = opt("--three"), jszipTgz = opt("--jszip"), esbuild = opt("--esbuild");
if (!threeTgz || !jszipTgz || !esbuild) die("需要 --three <tgz> --jszip <tgz> --esbuild <路径>");
for (const [name, p] of [["three", threeTgz], ["jszip", jszipTgz]]) {
  const got = sha256(readFileSync(p));
  if (got !== PINS[name].sha256) die(`${name} 发布包 sha256 是 ${got}，与固定值 ${PINS[name].sha256} 不符`);
}
const ev = execFileSync(esbuild, ["--version"]).toString().trim();
if (ev !== PINS.esbuild) die(`esbuild 版本是 ${ev}，要 ${PINS.esbuild}（不同版本输出字节不同）`);

const page = readFileSync(PAGE, "utf8");
const b = page.indexOf(BEGIN), e = page.indexOf(END, b);
if (b < 0 || e < 0) die("index.html 里找不到 vendor 段标记");
const moduleScript = page.slice(page.indexOf('<script type="module">', e));
const names = [...new Set([...moduleScript.matchAll(/\bTHREE\.([A-Za-z_$][\w$]*)/g)].map((m) => m[1]))].sort();
if (!names.length) die("页面脚本里没扫到 THREE.* 名字");

const tmp = mkdtempSync(join(tmpdir(), "cad-vendor-"));
try {
  const nm = join(tmp, "node_modules");
  mkdirSync(join(nm, "three"), { recursive: true });
  mkdirSync(join(tmp, "jszip"), { recursive: true });
  execFileSync("tar", ["xzf", threeTgz, "-C", join(nm, "three"), "--strip-components=1"]);
  execFileSync("tar", ["xzf", jszipTgz, "-C", join(tmp, "jszip"), "--strip-components=1"]);
  const entry = join(tmp, "entry.js");
  writeFileSync(entry, [
    `import { ${names.join(", ")} } from "three";`,
    `import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";`,
    `import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";`,
    `export const THREE = { ${names.join(", ")} };`,
    `export { GLTFLoader, OrbitControls };`,
    "",
  ].join("\n"));
  const out = join(tmp, "lib.js");
  execFileSync(esbuild, [entry, "--bundle", "--minify", "--format=iife", "--global-name=__lib", "--target=es2020",
    "--legal-comments=none", "--charset=ascii", "--log-level=warning", `--outfile=${out}`], { cwd: tmp });
  const lib = readFileSync(out, "utf8").trim();
  const jszip = readFileSync(join(tmp, "jszip/dist/jszip.min.js"), "utf8").trim();
  for (const [n, t] of [["three", lib], ["jszip", jszip]]) if (/<\/script|<!--|<script/i.test(t)) die(`${n} 里有会截断内联脚本的序列`);
  const threeJs = `/*! three.js r170 (npm three@${PINS.three.version}) | MIT License | Copyright 2010-2024 three.js authors | 只含 ${names.length} 个名字 + GLTFLoader + OrbitControls */\n`
    + `window.__cadLib = function () {\n${lib}\nreturn __lib;\n};`;
  const block = [
    BEGIN,
    `<!-- 由 renderer/build_vendor.mjs 生成，勿手改。three ${PINS.three.version} 发布包 sha256 ${PINS.three.sha256}；`
      + `jszip ${PINS.jszip.version} 发布包 sha256 ${PINS.jszip.sha256}；esbuild ${PINS.esbuild}。`
      + `内联正文 sha256：jszip ${sha256(jszip)}，three ${sha256(threeJs)} -->`,
    `<script>${jszip}</script>`,
    `<script>${threeJs}</script>`,
    END,
  ].join("\n");
  const next = page.slice(0, b) + block + page.slice(e + END.length);
  if (check) {
    if (next !== page) die("index.html 的内联段与重新生成的不一致");
    console.log("一致");
  } else {
    writeFileSync(PAGE, next);
    console.log(`写入 vendor 段：three ${threeJs.length} 字节（${names.length} 个名字），jszip ${jszip.length} 字节`);
    console.log(`three 正文 sha256 ${sha256(threeJs)}\njszip 正文 sha256 ${sha256(jszip)}`);
  }
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
