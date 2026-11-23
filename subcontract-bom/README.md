# subcontract-bom（分包分解单规范）

规范平台包：带包内规范（`norms`，17 TL-31），自 0.5.0 起另带一件确定性工具 `rack.layout`（G2、G3、G5、G6 的排布推算）与一个值类型 `rack_layout_receipt`。工具与条文同包、同 lock，走工具认证；装上后要等组织管理员签字启用才生效。`stage` 为 `beta`。

## 适用范围

适用于按标准构件目录、阵列排布、以焊接结构件加紧固件为主的产品（如货架、立库）。本版**不覆盖输送线类装配产品**（下级件为装配件的），**不覆盖三级以上层级**（只有主件与其下一级）。条目全部出自一个案例，尚未经第二对样本验证，不称通用。范围写在包说明里，不是条目。

## 说明

- **条目**：`mengos-package.json` 的 `norms`，共 93 条（定义 11、约束 76、形态 6），体例“[定义|约束|形态] 正文”。条文由 work 侧交付，逐字照搬，打包时不改；各版改了哪几条见 `变更说明.md`。
- **出处**：0.2.0 条文取自 mengosv2 `docs/alignment/work交付/分解单规范-0.2.0/分解单规范/`（`norms.txt`、`meta.json`、`变更说明.md`）；0.3.0 在其上按调度 2026-11-17 草案（立法者批准）改 14 条、增 2 条、删 1 条；0.4.0 以 0.2.0 为底按调度 2026-11-18 草案（立法者批准）加立库货架读图、推算、配套规则，0.3.0 的改动退回；0.4.1 只升版本号重新登记（选包改用包描述），条文与说明不变；0.4.2 依 DXF 端到端措辞修正实验给 10 条加归属句，数值不变，见 `变更说明.md`。评测材料（打分程序、案例与基线）不进本仓库。
- **核对条文**：`norms` 按序用换行连接、末尾加一个换行，即与来源 `norms.txt` 逐字节相同：
  ```
  python3 -c "import json,sys,hashlib; m=json.load(open('subcontract-bom/mengos-package.json',encoding='utf-8')); print(hashlib.sha256(('\n'.join(m['norms'])+'\n').encode()).hexdigest())"
  ```
  0.4.3 与 0.4.2 同为 `0c88f5768fba916960127e9cfe96a30bade3ee811f3f2410c1756dc30cd752d0`（0.4.3 只加 `for`，条文未改）；0.4.2 应得 `0c88f5768fba916960127e9cfe96a30bade3ee811f3f2410c1756dc30cd752d0`（0.4.1、0.4.0 为 `34f95dd869dab0eddcc689a7381702aefe751621c0f0019103e474c079c7ac04`，0.3.0 为 `fdb36418436c25bb5abe44b5ce853cad880ebc30c8695aff931e6088e599cb82`，0.2.0 为 `ea5d1747daa40c18f88d9c7fc1202c4ed61629c9c949c2fe4a2f63bf11500ad5`，0.1.0 为 `04633d56a1ecee296217d781e68e747894577f38525eb56abffff2da320bbfce`）。
- **for**：自 0.4.3 起清单写 `"for": ["table"]`，声明本包规范管哪类产物（立法者 2026-11-21 批）。
- **content_hash**：口径同安装器（WP-W6 §2，mengosv2 `engine/tools/package-hash.ts`）与其他包的 `tools/make_package.py`；清单计入，所以改任何一条都会换 content_hash，须发新版本。
- **排布计算工具**：`rack_tool.py`（进程入口）、`layout.py`（算法）、`text.py`（进模型文字唯一来源）。只用标准库，不出网，不调模型。改动后依次运行 `python tools/make_registration.py`、`python lock.py`、`python tools/make_package.py`；测试 `uv run --frozen pytest tests`，金样 `python tools/run_golden.py`（每条标所对条文）。条文与 lock 同算，改任一条条文工具 version 随变、须重新认证。
- **改条文**：任何一字都要发新版本，重新入册、安装核对，各组织重新签字启用。
