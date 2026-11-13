# subcontract-bom（分包分解单规范）

纯规范平台包：只带包内规范（`norms`，17 TL-31），不带类型、渲染器和工具（`types: []`、`tools: []`、`tools_lock.covers: []`）。不走工具认证；装上后要等组织管理员签字启用才生效。`stage` 为 `beta`。

- **条目**：`mengos-package.json` 的 `norms`，共 60 条（定义 10、约束 44、形态 6），体例“[定义|约束|形态] 正文”。条文由 work 侧交付，逐字照搬，打包时不改；各版改了哪几条见 `变更说明.md`。
- **出处**：mengosv2 `docs/alignment/work交付/分解单规范-0.1.0/分解单规范/`（`norms.txt`、`meta.json`、`变更说明.md`）。评测材料（打分程序、案例与基线）不进本仓库。
- **核对条文**：`norms` 按序用换行连接、末尾加一个换行，即与来源 `norms.txt` 逐字节相同：
  ```
  python3 -c "import json,sys,hashlib; m=json.load(open('subcontract-bom/mengos-package.json',encoding='utf-8')); print(hashlib.sha256(('\n'.join(m['norms'])+'\n').encode()).hexdigest())"
  ```
  0.1.0 应得 `04633d56a1ecee296217d781e68e747894577f38525eb56abffff2da320bbfce`。
- **content_hash**：口径同安装器（WP-W6 §2，mengosv2 `engine/tools/package-hash.ts`）与其他包的 `tools/make_package.py`；清单计入，所以改任何一条都会换 content_hash，须发新版本。
- **改条文**：任何一字都要发新版本，重新入册、安装核对，各组织重新签字启用。
