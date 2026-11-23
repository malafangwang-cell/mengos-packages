# mengos-packages

mengos 工具包源码仓库。每个子目录是一个包：`cad`、`document`、`calc`、`mathdisc`、`table`、两个纯规范包与三个局部追问 pro 包。

- **出处**：2026-11-04 由 mengosv2 仓库 `dev-tools/ci-packages/` 里的现役发布压缩包解出作初始提交（原包仓库已找不到；立法者 11-04 定新建本仓库）。去掉了 `__MACOSX/`，其余逐字节保留。
  - `cad` 2.4.4 ← `91a1c06ba8c26e0c21eb0e8591f09999dea853ed71e3df3c93f75e1fa59964df.zip`
  - `document` 1.2.5 ← `927cebff9d6fa0e4b9598892c8f52e05b3ae7ac3fe724316eb61c4d761f86a3c.zip`
  - `calc` 2.2.1 ← `341977c5a687c4e99de7e9c86fed5180ef6441e1adca19f81fb37f020d26a215.zip`
  - `mathdisc` 1.1.0 ← `17b2438287af4b98a67ff3e46d2542e129ca8d5aa9a9473f94d3ac430a9cfdb6.zip`
- **count**：count 0.2.3 起迁至主仓（私有）；0.2.2 及以前的源码见本仓历史。
- **规范包**：`subcontract-bom`（分包分解单规范）带包内规范 `norms`；0.4.3 及以前是纯规范包，0.5.0 起另带排布计算工具 `rack.layout`（见该包 README）。0.1.0 于 2026-11-13 新增；0.2.0（同日，按通用性评审改 11 条、增 R6.6，写明适用范围）条文逐字取自 mengosv2 `docs/alignment/work交付/分解单规范-0.2.0/分解单规范/`；0.3.0（2026-11-17）按天门立库 DXF 实验改 14 条、增 D13 与 N4、R5.3 并入 R5.1，共 62 条；0.4.0（2026-11-18，以 0.2.0 为底加立库货架读图、推算、配套规则共 93 条，0.3.0 的改动退回）；0.4.1（2026-11-20，为选包改用包描述重新登记，内容不变）；现为 0.4.2（2026-11-20，依 DXF 端到端措辞修正实验给 10 条加归属句，条文数值不变）。核对方法见该包 README。
  - `subcontract-bom-generic`（分包分解单规范（通用版））0.1.0 于 2026-11-14 新增：同为纯规范包，64 条，不带企业的列名、编号格式与损耗系数，适用于货架、立库、钢平台、带构件表与节点详图的钢结构厂房；条文逐字取自 mengosv2 `docs/alignment/work交付/分解单规范-通用版-0.1.0/`。与企业版 `subcontract-bom` 不要同时启用（同时启用时每次任务只会选中一个包）。
  - `cad-part`（零件建模规范）0.1.0 于 2026-11-21 新增：纯规范包，4 条约束（L1–L4），title、summary 与条文逐字取自 mengosv2《逐字稿-零件建模四条约束与cad.check核验接入-2026-11-21》（立法者批定）。要与 `cad` 包一起启用。见该包 README。
- **局部追问 pro 包**：`table-pro`（表格追问Pro）、`document-pro`（文档追问Pro）、`cad-pro`（CAD追问Pro）0.1.0 于 2026-11-19 新增。三个都是空包，不带类型、工具和规范，只用来开通局部修改。引擎只看本工作区装没装、能不能用，不看启用（空包按 TL-31 E7 不能启用）。各自要配 `table`、`document`、`cad` 包才有用，单独安装没有作用（商店说明写明，立法者 2026-11-19 定稿）。见各包 README。
- **分工**：本仓库施工、预检、出包；mengosv2 只更新安装快照与读数（见 mengosv2 `docs/alignment/arch/设计-产出不受模型输出长度限制-2026-11-03.md` §六.2）。

## 提示词不公开（立法者 2026-11-10）

工具包里写给模型的提示词**不公开**，不在本仓库。它们存放在私有仓库 `malafangwang-cell/mengos-package-prompts`，每个包一个目录。**构建和测试带提示词的包，需要该私有仓库的访问权限。**

- **登记**：`prompts.lock.json` 只写每份提示词在私有仓库里的路径、在包里的路径和 sha256，不含原文。现有一份：mathdisc 的 `mathdisc/prompts/find_relations_v3.txt`。
- **不得提交**：`.gitignore` 挡住了所有 `prompts/` 目录和 `*.zip`。归档里含提示词原文，不要放进本仓库的工作区。
- **构建与测试**：一律在仓库根目录用 `tools/pkgbuild.py`。
  ```
  export MENGOS_PACKAGE_PROMPTS_DIR=/path/to/mengos-package-prompts   # 私有仓库的本地副本
  python tools/pkgbuild.py verify  mathdisc            # content_hash、lock_hash 与登记值一致
  python tools/pkgbuild.py test    mathdisc            # uv sync --frozen 后跑 pytest tests 和 tools/run_golden.py
  python tools/pkgbuild.py archive mathdisc <仓库外的目录>  # 确定性归档，文件名是它的 sha256
  python tools/pkgbuild.py regen   mathdisc            # 改源码后重生成 registration.json、mengos-package.json
  ```
  脚本先按 sha256 核对提示词，然后把包拷到工作区之外的临时目录，放入提示词，在那里调用包自带的脚本。跑完不论成败，临时目录都整个删掉，工作区里不留副本。包内文件一个不改，content_hash 和 lock hash 与原来相同。
- **缺提示词必须报错**：没设 `MENGOS_PACKAGE_PROMPTS_DIR`、私有仓库里缺文件、sha256 不符、工作区里残留提示词副本，脚本都会报错退出（退出码 2）。不会跳过，也不会放占位提示词。
- **不要在工作区直接跑包内的 `lock.py` 或 `tools/make_package.py`**：包内 `lock.py` 遇到缺文件时按空内容计算，会静默写出错误的 lock hash。这一处留待下一版修复。

## 待办（下一次升版时一起做）

这里登记已经定下、但不为它单独出版的改动。升版时照做，做完从这里删去。不在各包目录里登记：包目录里任何文件一改，content_hash 就变，要重新出包。

### document（现为 2.4.0，lock `addb4cae3d1502a3`）

立法者 2026-11-19 补裁 C2（mengosv2《设计-长文内置图表-2026-11-18》§10.1）：

1. **`chart` 说明改为定稿原文**（`document/tools/make_registration.py` 的 `CHART_DESC`，三件工具同步）：去掉开头的“chart：”，删掉末句“图里的数要与正文、表格里的一致。”。定稿原文：
   > 一张数据图。type 取 bar（柱状）、line（折线）、pie（饼）、combo（柱线组合）。categories 是横轴的类别（饼图是各项名称），年份、季度、月份要逐期写全。series 是一组或几组数据，每组有 name 和 values；values 只写数，个数与 categories 相同，没有数据的位置写 null。unit 是单位。组合图里每组另写 as（bar 或 line）和各自的 unit。从某一期起是预测时，写 forecast_from 为那一期。
2. **doc.build `examples` 第五条的 output**：现为“……图 1-3 柱线组合、图 1-4 饼图由你给的数据画出，带刻度、数值与图例”。改成完整一句，编号与输入对得上：输入先说“投资构成图”，再说“分年度投资图”。
3. 不改的：`doc` 说明里“图放进 figures……”那一句；`values` 的 schema 仍收文字（`["number", "null", "string"]`，立法者 11-18 裁定，由工具按原话退回）。

改的是给模型看的文字与登记，lock 会变，须重新认证并入册（照 2.4.0 先例）。
