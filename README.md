# mengos-packages

mengos 工具包源码仓库。每个子目录是一个包：`cad`、`document`、`calc`、`mathdisc`。

- **出处**：2026-11-04 由 mengosv2 仓库 `dev-tools/ci-packages/` 里的现役发布压缩包解出作初始提交（原包仓库已找不到；立法者 11-04 定新建本仓库）。去掉了 `__MACOSX/`，其余逐字节保留。
  - `cad` 2.4.4 ← `91a1c06ba8c26e0c21eb0e8591f09999dea853ed71e3df3c93f75e1fa59964df.zip`
  - `document` 1.2.5 ← `927cebff9d6fa0e4b9598892c8f52e05b3ae7ac3fe724316eb61c4d761f86a3c.zip`
  - `calc` 2.2.1 ← `341977c5a687c4e99de7e9c86fed5180ef6441e1adca19f81fb37f020d26a215.zip`
  - `mathdisc` 1.1.0 ← `17b2438287af4b98a67ff3e46d2542e129ca8d5aa9a9473f94d3ac430a9cfdb6.zip`
- **纯规范包**：`subcontract-bom`（分包分解单规范）只带包内规范 `norms`，不带类型和工具，不走工具认证。0.1.0 于 2026-11-13 新增；现为 0.2.0（同日，按通用性评审改 11 条、增 R6.6，写明适用范围），条文逐字取自 mengosv2 `docs/alignment/work交付/分解单规范-0.2.0/分解单规范/`。核对方法见该包 README。
  - `subcontract-bom-generic`（分包分解单规范（通用版））0.1.0 于 2026-11-14 新增：同为纯规范包，64 条，不带企业的列名、编号格式与损耗系数，适用于货架、立库、钢平台、带构件表与节点详图的钢结构厂房；条文逐字取自 mengosv2 `docs/alignment/work交付/分解单规范-通用版-0.1.0/`。与企业版 `subcontract-bom` 不要同时启用（同时启用时每次任务只会选中一个包）。
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
