# calc v2（计算工具族的替换包）

> 2.2.2（mengosv2 执行令-2026-11-05-PLAN声明书与F环清单交互 支 T）：包清单加显示名 `title`「精确计算」与 `tool_titles`（`calc.evaluate`「算式精确求值」、`calc.algebra`「代数与微积分运算」、`calc.check_equal`「判断两式是否相等」）。两字段只供界面显示（声明书、商店），不进工具选择，也不进给模型看的任何文字；不在 `tools_lock.covers` 内，lock 不变（工具版本与认证继承），只有 content_hash 变。工具代码与 registration.json 未改（其中 `family_version` 仍写 2.2.1）。

> 2.2.1（W-11，17 TL-16c v0.2.32）：calc.algebra 的输入类型改为“或”：`in_types: []`、`in_any: [math_expression, equation]`——它收一个式子（expr）或一组方程（exprs），二者有一即可（input_schema 只 required op）。calc.check_equal 的 `[math_expression, number]` 两边都要，不变。工具代码未改；registration 改了，lock 变（ecbbbd50de6a4d29），须重新认证。本容器无 sympy，执行类测试未跑；登记与包自检 15 项过。

> 2.2.0：三件工具给模型看的说明按“这件工具是做什么的”重写，并逐件对照工具代码核准（草稿 `描述实验/`，立法者 2026-10-13 审定）。calc 是调用方的计算器，收平常的数学写法；check_equal 是判卷：给了取值按取值比，没给取值就把两式之差做符号化简来比，所以也能判恒等。说明里不再出现工具名（evaluate 的 expr、check_equal 的 bindings 原先写“由 calc.algebra 求解”“同 calc.evaluate”）。工具代码未改；registration 改了，lock 变，须重新认证。

> 2.1.4：给模型看的参数说明改成只写能做什么（17 TL-16b）：去掉"不接受等式""不执行任何代码"这类句子，等式归 calc.algebra 的说明改为正面写法。registration 改了，lock 变，须重新认证。
> 2.1.3（检查点 O 后，只改包、不改工具版本）：加金样运行入口 `tools/run_golden.py`（WP-W6 §2），certify 的 ③ 不再 SKIPPED。工具版本不变。
>

> 状态：**安装包 2.1.2，已自测**（96 项通过）。2.1.2（检查点 G 后）修包侧两处：content_hash 的文件口径与安装器对齐，不计 `.DS_Store` 等系统杂项（WP-W6 §2）；README 的自测命令改为 `--frozen`。工具版本（lock hash）仍是 e36db5722860f0ec，认证不受影响。2.1.1 只加了一项自检（给模型看的文字只写目标、不写实现），工具版本（lock hash）与 2.1.0 相同，认证不受影响。登记资产严格按 TL-6 的字段：族名在顶层；cost 全为数值（毫秒）；入参写法写在 input_schema 的 description 里；选择金样在 `selection_cases.json`。按 `mengos-package.json` 交付，由安装器装入（TL-25），在服务层 S1 替换旧的 calc 族（TL-24）。施工方不改包内文件，包内问题报工具侧。
> 依据：kernel-spec v0.2.22 17 章（TL-6 登记资产、TL-8 执行器、TL-10 引擎与执行体分工、TL-12 认证自检、TL-20 审核工具、TL-22a 非证明级结论以假设声明、TL-24 以包替换、TL-25 安装单位）。

## 1 现在的 calc 能不能通过验收

要分两层看。

**作为工具，能过。**
- 38 条族金样通过，认证里的确定性双跑也通过（15k）。
- 竣工取证的 T1 里，`calc.solver.arithmetic` 算出了 177，回执进入了 V_ref。

**作为模型能用起来的计算器，不行。** 毛病不在算力，而在入参契约：
- `calc.solver.arithmetic` 要求模型写一棵嵌套的 AST JSON。模型要同时做对三件事：树形结构、JSON 转义、锚点引用，错一处就整条被拒。历次冒烟里的记录：
  - 首轮冒烟 15 轮零派单；
  - WP-05b 的 T3 冒烟里，入参不是合法 JSON 的有 7 次；
  - WP-17 T4 出现单引号键。
- `calc.solver.symbolic` 执行的是一行 sympy 代码。模型要写的是代码而不是数学，容易写成多行或带 import；而且执行任意代码本身就要沙箱，违背 T1"同输入同输出、无副作用"的意图。
- T1 的终点核验最后用的是 mathdisc 的 `eval.evaluate`，不是 calc。

结论：**问题出在模型很难把计算请求写成工具要的形状。** 给计算器加更多能力解决不了这个问题。

## 2 选型

| 方案 | 结论 | 理由 |
|---|---|---|
| sympy + 自写安全解析器 | **采用** | sympy（BSD）做精确与符号计算；解析器自己写，只认白名单语法，不碰 eval。沿用 calc 现有的 Python + process 执行器形态，替换成本最小 |
| sympy 的 `parse_expr` / `sympify` | 否决 | 内部用 eval，喂不可信字符串可以执行任意代码（[sympy issue #10805](https://github.com/sympy/sympy/issues/10805)，[一例 RCE 分析](https://dev.to/kyb8801/sympyparseexpr-will-run-ossystem-if-you-let-it-heres-the-ast-gate-that-stopped-me-from-1nbe)） |
| mathjs（TS，module 执行器） | 暂不用 | 解析器安全，但没有通用的方程求解；更关键的是 module 在引擎进程内运行，一个 `9^9^9` 就能卡住引擎的事件循环。计算类工具应该放在可以被杀掉的子进程里（S11） |
| libqalculate 的 `qalc` | 留作以后 | 计算器能力最强（单位、货币、精确值、解方程），但许可证是 GPL（[Qalculate!](https://en.wikipedia.org/wiki/Qalculate!)），且要装外部二进制。以后需要单位换算时，可作为另一族工具登记 |
| 保留 AST JSON 契约 | 否决 | 就是本节第 1 条说的病根 |

## 3 calc v2 是什么

一个执行体，三件工具，全部为 T1，effect = none，执行器为 process。

| 工具 | 用途 | 入参（举例） |
|---|---|---|
| `calc.evaluate` | 求精确值 | `{"expr": "2^n + n^2", "bindings": {"n": 7}}` → `177` |
| `calc.algebra` | 化简、展开、因式分解、代入、求导、积分、极限、解方程（组） | `{"op": "solve", "expr": "x^2 - 5x + 6 = 0"}` → `[2, 3]` |
| `calc.check_equal` | 核验两式是否相等（审核工具，`review_coverage.by_predicate = value_eq_answer`） | `{"left": "2^n + n^2", "right": "y = 177", "bindings": {"n": 7}}` → `equal = true` |

**入参就是模型本来就会写的数学记法。**
- `^`、`**` 都是乘方；`×` `÷` `·` `−` 和全角括号自动规范化；`x²` 这类上标照常识别。
- `2x`、`2(x+1)`、`(a+b)(a-b)` 按隐式乘法处理。
- `%` 是百分号，`°` 是角度；`ln` 是自然对数，`lg` 是常用对数，`log(x, b)` 表示以 b 为底。
- 常见 LaTeX 也认，例如 `\frac{1}{3}`、`\sqrt{2}`、`2^{10}`、`\cdot`。
- `y = 2^7 + 7^2` 这种带标签的写法，只算右边。

**计算是精确的。**
- 小数字面量按十进制精确转成有理数，所以 `0.1 + 0.2` 的结果是 `3/10`。
- 结果同时给出精确值 `value` 和十进制近似 `approx`。

**分快慢两条路。**
- 只涉及有理数运算时，用 Python 的 int 和 Fraction 直接算，不导入 sympy。
- 遇到根式、常数、三角、对数时才导入 sympy。

**安全上有四道限制。**
- 全程没有 eval、exec、属性访问，测试会扫源码确认这一点。
- 标识符只接受白名单函数和普通变量名。
- 有规模上限：表达式最长 4000 字符；结果最多 10 万位；数字字面量的指数不超过 10000；阶乘参数不超过 5000；`9^9^9` 这类会在计算前被拒绝。
- 收到引擎下发的 budget 后，在超时的九成处自行返回结构化的 TIMEOUT，引擎的计时照常生效（TL-10）。

**错误是结构化的。** 错误码分五类：BAD_INPUT、UNSUPPORTED、RESOURCE_LIMIT、TIMEOUT、INTERNAL。错误信息用中文写明错在哪里，例如"有未绑定的变量：x（请在 bindings 中给出，或改用 calc.algebra）"，可以直接回注给模型。

**输出是确定的。** JSON 按键排序、紧凑输出，同一输入逐字节相同；测试在不同哈希种子的进程之间核对过。

**达不到证明级的结论会如实声明**（TL-22a，v0.2.22 新增）：

| 情形 | 结果 |
|---|---|
| check_equal 判"不等"靠的是 60 位精度下差值非零 | `method = numeric-nonzero`，带假设"数值判定……未经符号证明" |
| check_equal 判"不等"靠的是 sympy.equals（可能在随机点做数值检验） | `method = sympy-equals`，带假设 |
| solve 的方程不是多项式（三角、指数、对数等） | `complete = false`，带假设"解集可能不完备"。例如 `sin(x) = 0` 只返回主值 0 与 pi |
| solve 在实数域里有解无法判定是否为实数 | 带假设"部分解是否为实数无法判定" |

判"相等"（`symbolic`、`exact-rational`）是证明级，不带假设。引擎把 `assumptions` 挂成随行假设，审核结论因此是"带假设成立"；引擎不读 `method` 字段。

## 4 自测结果（本机沙箱，sympy 1.14.0）

- `uv sync --frozen && .venv/bin/python -m pytest tests -q -p no:cacheprovider`：**96 项全部通过**，包括：
  - 69 条金样，其中 11 条是应当被拒的反例，4 条是非证明级用例（带出假设）；
  - 安装包清单自检：只有值类型、entry 相对包目录、lock 覆盖范围、替换映射、content_hash；
  - 5 组跨进程确定性检查；
  - 登记资产自检：入参示例过 input_schema，输出过 output_schema，lock hash 与源文件一致；
  - 超时用例；
  - 源码中不得出现 eval 的扫描；
  - 6000 次模糊输入，没有一次出现 INTERNAL。
不要用不带 `--frozen` 的 `uv sync` / `uv run`：环境变量里配了别的索引（例如国内镜像）时，uv 会重新解析并改写 `uv.lock`，工具版本（lock hash）与 content_hash 随之失配。安装区里只用环境解释器跑，不运行 uv。

- 开销：每次调用都起一个新进程，与 process 执行器一致，各跑 5 次：

| 场景 | 首次 | 热均 |
|---|---|---|
| evaluate，有理数路（T1 那道题） | 27 ms | 27 ms |
| check_equal，有理数路 | 24 ms | 23 ms |
| evaluate，符号路（`sqrt(8) + sin(30°)`） | 435 ms | 426 ms |
| algebra solve | 448 ms | 433 ms |

对照 15j 在仓库机器上测得的旧 calc：arithmetic 首次 419 ms、热均 267 ms；symbolic 首次 251 ms、热均 249 ms。两边机器不同，这些数只能作参考，接入时要在同一台机器上重测。可以预期：有理数路明显更快；符号路因为整包导入 sympy，可能比旧 symbolic 慢。

## 5 已知边界

- 没有单位换算、统计与数据表运算、矩阵；需要时另立工具族，例如 qalc。
- `(-8)^(1/3)` 按主值给出复数结果；要实数立方根请用 `cbrt(-8)`。
- `log(x)` 按自然对数处理，这一点写进了 input_domain。
- `%` 只表示百分号；取模写 `mod(a, b)`。
- check_equal 判定不了时返回 `equal = null`、`covered = false`，含义是"不在覆盖范围"，不是失败（TL-22）。

## 6 安装与替换（服务层 S1）

1. **平台审批**（TL-26）：执行器为 process；不出网；效应为 none；没有凭据；新类型三个，都是值类型。
2. **安装**：安装器校验 content_hash，按 `uv.lock` 建隔离环境（sympy 1.14.0），在一个事务里依次入册类型与三件工具。命令为 ⟨包环境的 python⟩ ⟨包目录⟩/calc_tool.py。
3. **类型**：`number`、`verdict` 是平台类型，本包只引用。如果注册表里已有同名的 `math_expression`、`equation` 或 `solution_set`，安装器报给工具侧，由工具侧改包，不在注册表里打补丁。
4. **核验器**：`calc.check_equal` 的 `review_coverage.by_predicate = [value_eq_answer]`。W0 的 P7 改造后，它接 goal_point 核验位，取代引擎内谓词表里 value_eq_answer 的现有配对。
5. **替换**（TL-24）：
   - 旧 `calc.solver.arithmetic` → `calc.evaluate`；
   - 旧 `calc.solver.symbolic` → `calc.algebra`（清单 `replaces` 一节）。

   引用旧 tool_id 的 manifest 与 agent 资产在同一次替换中改过去。入参形状变了：旧的是 AST JSON 或 sympy 代码，新的是数学记法字符串。工具卡由登记资产渲染，模型侧自动跟随，不另改提示词。
6. **冒烟**：T1 路必须仍以 `t1_target_achieved` 结束。对照指标：派单次数、入参被拒次数，与 WP-17 和竣工取证的记录比较。
7. **摘旧族**：旧两件摘册，旧 tool_id 不复用；引擎内旧 calc 的装配与引用作为引擎侧变更单独合并。
8. **签字**：替换完成后，立法者对三件新工具的版本逐件人签（TL-13）。

改了源码之后：先运行 `python lock.py`（重写工具 version），再运行 `python tools/make_package.py`（重写包的 content_hash）。

## 7 文件

| 文件 | 内容 |
|---|---|
| `calc_tool.py` | process 入口：读一行信封，写一行回执 |
| `expr_parser.py` | 记法规范化、分词、递归下降解析，产出白名单语法树 |
| `evaluator.py` | 有理数快路、sympy 路、三件工具的实现 |
| `registration.json` | 三件工具的登记资产（TL-6 字段），version 等于 lock hash |
| `mengos-package.json` | 安装包清单：类型、工具、lock 覆盖范围、运行环境、替换映射 |
| `golden_cases.json` | 69 条金样，可直接作为认证 ③ 的金样材料 |
| `selection_cases.json` | 选择金样（认证 ⑥），每件应选与不应选各 3 条 |
| `lock.py` | 计算 lock hash（覆盖执行体、依赖与登记资产）并写回登记资产 |
| `tools/make_package.py` | 计算并写入包的 content_hash |
| `bench.py` | 开销基准 |
| `tests/` | 金样、确定性、登记资产自检、安装包自检、超时、无 eval 扫描、模糊测试 |
