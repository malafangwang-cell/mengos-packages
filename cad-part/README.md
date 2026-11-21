# cad-part（零件建模规范）

纯规范平台包：只带包内规范（`norms`，17 TL-31），不带类型、渲染器和工具（`types: []`、`tools: []`、`tools_lock.covers: []`）。不走工具认证；装上后要等组织管理员签字启用才生效。`stage` 为 `beta`。

## 前提与适用范围

要与 `cad` 包一起启用。适用于产出单个零件三维模型的任务，不覆盖多个零件的装配。范围写在包说明（`summary`）里，不是条目。

## 说明

- **条目**：`mengos-package.json` 的 `norms`，共 4 条（约束 4：L1–L4），体例“[约束] （编号）正文”。title、条文与 0.1.0 的 summary 逐字取自 mengosv2 `docs/alignment/arch/逐字稿-零件建模四条约束与cad.check核验接入-2026-11-21.md`（立法者批定；§1.3 清单、§二 条文），打包时不改；summary 自 0.1.1 起按立法者 2026-11-21 批的改句（见 `变更说明.md`）。
- **核对条文**：`norms` 按序用换行连接、末尾加一个换行：
  ```
  python3 -c "import json,sys,hashlib; m=json.load(open('cad-part/mengos-package.json',encoding='utf-8')); print(hashlib.sha256(('\n'.join(m['norms'])+'\n').encode()).hexdigest())"
  ```
  0.1.0 应得 `e223b709d678568d5e6abb5c41568fe5dd9f3637c4884dba4ec3fd45c714bec3`。
- **content_hash**：口径同安装器（WP-W6 §2，mengosv2 `engine/tools/package-hash.ts`）与其他包的 `tools/make_package.py`；清单计入，所以改任何一条都会换 content_hash，须发新版本。
- **改条文**：任何一字都要发新版本，重新入册、安装核对，各组织重新签字启用。
