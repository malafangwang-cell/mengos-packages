# mathdisc 1.2.0 · 数学核对与发现工具包

> 1.2.0：新增第七件工具 `mathdisc.discover`（发现循环，从数据里找规律）。形态：`executor.kind = process`、`mode = async`、`trust_claim = T3`、`effect = none`；出网只有 `dashscope.aliyuncs.com`（`runtime.process.network`），凭据名 `DASHSCOPE_API_KEY` 经 `executor.credential_ref` 由平台注入，包内不存任何密钥。回执是 `{stop_reason, relations, assumptions, cost, relation_receipts}`：前四项是原投影（`ta_projection.json` 逐条把证据等级映射成假设，丢一条即违例），`relation_receipts[]` 只增不删，每条关系一项 `{expr, verdict, evidence, validity?, assumptions}`，`evidence` 取自检查门回执原样；`validity` 由 `md_tool.py` 按检查门实际用的拆分与同步判定工具同一口径算出（formula 为 `data_range`，recurrence 为 `index_range`），门回执本身不带就不带。入参不含 `mock`（`additionalProperties: false`）；空 ρ 只由环境变量 `MATHDISC_RHO_MOCK=1` 打开，供管道自检，发布档由平台拒启。ρ 模型锁在 `mathdisc.lock`（`qwen3.8-max-0902`，思考模式关）。随包公开的是 mathdisc 自带的提示词 `mathdisc/prompts/find_relations_v3.txt` 与 `mathdisc/llm/`。到点未跑完回 `stop_reason = undetermined`，不报错。离线回放金样见 `tests/test_discover.py`（阳性、阴性对照、v1 事故、超时），不调模型；真模型读数在部署后另跑。

> 1.1.1（mengosv2 执行令-2026-11-05-PLAN声明书与F环清单交互 支 T）：包清单加显示名 `title`「数学猜想核验」与 `tool_titles`（`mathdisc.identity`「核验两式恒等」、`mathdisc.formula`「拟合并盲测数据公式」、`mathdisc.recurrence`「核验数列递推式」、`mathdisc.reach`「核验算式等于目标值」、`mathdisc.counterexample`「核验素数猜想反例」、`mathdisc.solve_closed`「穷举凑出目标整数」）。两字段只供界面显示（声明书、商店），不进工具选择，也不进给模型看的任何文字；不在 `tools_lock.covers` 内，lock 不变（工具版本与认证继承），只有 content_hash 变。工具代码与 registration.json 未改（其中 `family_version` 仍写 1.1.0）。

> 1.1.0：六件工具给模型看的说明按“这件工具是做什么的”重写，并逐件对照工具代码核准（草稿 `描述实验/`，立法者 2026-10-13 审定）。mathdisc 是数学结论的裁判：结论由调用方提出，工具不经模型判定，回执是这条结论的证据。改正了与代码不符之处：恒等式的数值路只在一处取值比对（原写“多处”）；递推只收整数与 + − × ÷；凑数核对只收整数，可用 factorial 与完全平方数的 sqrt；反例只认“总是素数”一种猜想；恒等式第三条场景例的证据等级。工具代码未改；registration 改了，lock 变，须重新认证。

mathdisc 的七件工具，按工具包通用安装通道（17 TL-25、WP-W6 §2）安装。前六件确定性、零模型调用，T1；第七件 `mathdisc.discover` 见下。

| tool_id | 做什么 | 产出 |
|---|---|---|
| `mathdisc.identity` | 两个表达式是否恒等：两式之差化简为零或是多项式、有理式时符号判定，否则在一处固定取值上高精度比对并在加倍精度上复检 | 三值回执 |
| `mathdisc.formula` | 含参数的公式能否解释一张数据表：拟合 + 训练残差、参数上限、奇点扫描、留出残差四查 | 三值回执 |
| `mathdisc.recurrence` | 递推式能否精确复现已知项并盲测保留项（分数全程精确） | 三值回执 |
| `mathdisc.reach` | 只含数字的算式是否恰好等于目标值（分数精确） | 三值回执 |
| `mathdisc.counterexample` | 一个取值是不是 `isprime(...)` 型全称猜想的反例，给出质因数 | 三值回执 |
| `mathdisc.solve_closed` | 给定整数与四则运算，穷举找出等于目标的算式；穷举无解即证明 | math_solution |
| `mathdisc.discover` | 从数据里找规律：模型多轮提候选，每条过上面的检查门才交出（T3，异步，出网） | 候选关系 + 逐条回执 |

三值回执：`{verdict, method_complete, evidence, versions, assumptions}`，verdict ∈ established / refuted / undetermined / rejected。
- 证据等级不是证明级（`verified@N`、`verified_on_data`、递推的序列级）时，`assumptions` 逐条写明（17 TL-22a）。
- refuted 以精度自证为前提（D-2：√2²=2 永不 refuted，金样 `id-sqrt2-never-refuted`、`id-sqrt2-2000`）。
- 只在有限范围内核验过的成立结论带适用范围 `validity`（产出台规范 §3）：formula 给拟合与保留行的逐变量取值范围和误差（范围外是外推，离开越远越不可信）；identity 走数值路时给采样点；recurrence 给核验到第几项。假设句把范围写进去。
- 判定类工具到预算八成未判完，回 `undetermined`，不报错。

## 与源码库的关系

- 执行体源码来自 `docs/alignment/wp/素材包-2026-10-03/mathdisc`（mathdisc/v0.1.0），只取 T1 需要的模块：`expr/`、`check/`、`forensics/`、`loop/solve_closed.py`。
- 新入口 `md_tool.py`：process 信封（与 probe、cad、calc、document 相同），入参校验、错误码、假设与适用范围投影都在这里。源码只改一处：`check/identity.py` 数值路把采样点记进证据。
- 1.2.0 起发现循环并入本包：`loop/solve.py`、`loop/rho.py`、`llm/`、`prompts/`、`forensics/`、`adapter_projection.py`、`ta_projection.json`，以及自 cli 的 run-solve 路径摘出的 `discover.py`（同步单元 `check.*`、`eval`、`validate`、`service/` 不随入）。本包出网只有 `llm/client.py` 一个出口，测试 `test_network_path_only_in_llm_client` 白盒核对。

## 替换（TL-24）

| 旧（引擎适配器 mathdisc-spawn） | 新 |
|---|---|
| check.identity / check.formula / check.recurrence / check.reach / check.counterexample / solve_closed | mathdisc.identity / .formula / .recurrence / .reach / .counterexample / .solve_closed |
| eval.evaluate | **calc.evaluate**（能力相同：符号代入、精确分数；不在本包重复登记，免得选型时两件撞车） |
| validate.grammar | 不进工具册：它是发布门内部用的文法检查，由施工方在引擎侧处理 |
| discover | mathdisc.discover（1.2.0 并入） |

## 认证材料

- `golden_cases.json`：37 条，每件工具都有成立、反驳与 BAD_INPUT 用例；含 v1 事故转来的永久金样（√2²=2、`x+x` 冒充开普勒、阶乘 `n` 分词、费马数 F5）。
- `selection_cases.json`：每件 3 正 3–4 负；语义负例标 `stage: model`。
- `tools/run_golden.py`：按与引擎相同的进程信封调用；断言写成 `{path, eq|ne|in|contains|approx(+tol)|nonempty}`。

本地（无 sympy/scipy，PyPI 不可达）只能跑静态测试与纯算术三件的金样：
`pytest tests` 19 过；`reach`、`recurrence`、`solve_closed` 金样 14/14（以占位模块代 sympy 跑）。
`identity`、`formula`、`counterexample` 需要真库，在安装区由 certify 跑。

## 版本

改源码后依次：`python tools/make_registration.py` → `python lock.py` → `python tools/make_package.py` → `python tools/make_archive.py <输出目录>`（确定性归档，文件名为其 sha256）。
