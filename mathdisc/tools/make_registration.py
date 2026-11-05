"""生成 registration.json（TL-6 登记资产）。给模型看的文字只写能做出什么、输入什么、产出什么（17 TL-16b）；
non_goals 只留在登记资产里，不渲染给模型。改完运行：python3 tools/make_registration.py && python3 lock.py && python3 tools/make_package.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPR = "表达式写法：数字、变量名、+ - * / ** %、括号，乘方写成 **；函数 sqrt sin cos tan exp log abs zeta factorial；常数 pi、e。乘号要写出来（2*x）。"

RECEIPT = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "method_complete", "evidence", "versions", "assumptions"],
    "properties": {
        "verdict": {"enum": ["established", "refuted", "undetermined", "rejected"]},
        "method_complete": {"type": "boolean"},
        "evidence": {"type": "object"},
        "versions": {"type": "object"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "split": {"type": "object"},
        "validity": {"type": "object", "required": ["basis", "outside"],
                     "properties": {"basis": {"enum": ["data_range", "sample_points", "index_range"]},
                                    "core": {}, "checked": {}, "points": {"type": "array"}, "rows": {"type": "object"},
                                    "error": {"type": "object"}, "outside": {"type": "string"}, "note": {"type": "string"}}},
    },
}

COST = {"latency": 500, "price": 0, "timeout": 30000}


def unit(tool_id, ops, in_types, out_types, input_schema, output_schema, example, constraints, examples, non_goals, review=None, cost=None,
         trust="T1", executor=None):
    u = {
        "tool_id": tool_id, "trust_claim": trust, "effect": "none",
        "executor": executor or {"kind": "process", "entry": "md_tool.py", "mode": "sync"},
        "cost": cost or COST,
        "input_example": example,
        "capability": {"ops": ops, "in_types": in_types, "out_types": out_types,
                       "constraints": constraints, "examples": examples, "non_goals": non_goals},
        "signature": {"input_schema": input_schema, "output_schema": output_schema},
    }
    if review:
        u["review_coverage"] = {"by_predicate": review}
    return u


UNITS = [
    unit("mathdisc.identity", ["check"], ["math_relation"], ["verdict"],
         {"type": "object", "additionalProperties": False, "required": ["lhs", "rhs"],
          "description": "你认为两个式子恒等、需要一个可以当证据的判定时用。你写出两边，它不经模型判定，回执写明证据有多强：两式之差能化简为零或是多项式、有理式时，给出符号证明（成立或不成立）；否则只在一处取值上（变量按名字顺序取 2/7、3/7…）高精度比对——不一致即不成立，一致只说明该处相等，回执附适用范围与假设，不算证明。",
          "properties": {
              "lhs": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "lhs：左边的表达式。" + EXPR},
              "rhs": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "rhs：右边的表达式，写法同 lhs。"},
              "digits": {"type": "integer", "minimum": 16, "maximum": 2000, "description": "digits：数值比对的十进制位数，缺省 50。"},
              "try_symbolic": {"type": "boolean", "description": "try_symbolic：先做符号判定，缺省 true。"}}},
         RECEIPT, {"lhs": "(a+b)**2", "rhs": "a**2+2*a*b+b**2"},
         {"verdicts": ["established", "refuted", "undetermined"], "digits": [16, 2000],
          "proof_grades": ["proven_symbolic", "verified@N"], "zero_model_calls": True},
         [{"input": "核验 (a+b)² 与 a²+2ab+b² 是否相等", "output": "established，proven_symbolic（多项式范围内符号判定）"},
          {"input": "只做数值比对：核验 sin(x)²+cos(x)² 是否恒等于 1", "output": "established，verified@50，适用范围：只在 x = 2/7 处比对过，附假设：数值验证，未经符号证明"},
          {"input": "核验 π 与 22/7 是否相等", "output": "refuted，proven_symbolic（两式之差是非零常数）"}],
         ["不给出证明过程", "不处理含积分或求和号的表达式"],
         review=["verdict_eq_established"]),
    unit("mathdisc.formula", ["check"], ["math_relation", "math_table"], ["verdict"],
         {"type": "object", "additionalProperties": False, "required": ["form", "columns"],
          "description": "你从一张数据表里猜出一条公式、要判定它能不能解释这些数据时用。公式由你提出，系数待定（写作 c1、c2…）；它拟合系数，再用没参与拟合的末尾几行盲测，不经模型判定。回执给出成立与否、拟合出的系数，以及适用范围：只在数据覆盖的取值区间内核验过，区间外是外推，离得越远越不可信。",
          "properties": {
              "form": {"type": "string", "minLength": 1, "maxLength": 500,
                       "description": "form：候选公式，只写右边。待拟合的参数写作 c1、c2…；变量名取自 columns 里的列名。" + EXPR},
              "columns": {"type": "object", "minProperties": 2, "maxProperties": 9,
                          "additionalProperties": {"type": "array", "minItems": 4, "maxItems": 2000, "items": {"type": "number"}},
                          "description": "columns：数据表，按列给出。变量列用变量名作键；响应列的键是 y。各列等长、按行对齐。"},
              "holdout_ratio": {"type": "number", "minimum": 0.1, "maximum": 0.5, "description": "holdout_ratio：末尾留作盲测的行所占比例，缺省 0.25。"},
              "k_max": {"type": "integer", "minimum": 0, "maximum": 8, "description": "k_max：参数个数上限；超出时回执为 rejected。"},
              "seed": {"type": "integer", "description": "seed：拟合的随机种子，缺省 0；同输入同种子同结果。"}}},
         RECEIPT, {"form": "c1*x**c2", "columns": {"x": [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4], "y": [0.354, 1.002, 1.844, 2.842, 3.972, 5.218, 6.566, 8.007]}},
         {"verdicts": ["established", "refuted", "rejected", "undetermined"], "rows": [4, 2000], "variables": [1, 8],
          "proof_grades": ["verified_on_data"], "deterministic_given_seed": True},
         [{"input": "这组行星数据符不符合 T = c1·a^c2", "output": "established，c2≈1.5，适用范围：拟合用的 a 的取值区间与保留行区间；区间外是外推，可信度随距离下降"},
          {"input": "气体数据能不能用 y = c1·T/V 解释", "output": "established，c1≈2.0"},
          {"input": "y = x + x 能不能解释这组数据", "output": "refuted，训练残差不达标"}],
         ["不自己提出候选公式", "不做外推担保"],
         review=["verdict_eq_established"]),
    unit("mathdisc.recurrence", ["check"], ["math_relation", "math_sequence"], ["verdict"],
         {"type": "object", "additionalProperties": False, "required": ["relation", "known"],
          "description": "你从一个整数数列的前几项猜出递推关系、要判定它时用。递推式由你提出；它从起始项按递推式用精确分数推出后面各项，与已知项逐项比对，再盲测你留出的项，不经模型判定。回执给出成立与否，以及核验到第几项（之后未核验）。",
          "properties": {
              "relation": {"type": "string", "minLength": 1, "maxLength": 500,
                           "description": "relation：a[n] 的右边，用 a[n-1]、a[n-2]… 引用前项，用 n 表示当前下标；由整数、+ - * /、括号写成，乘方写成连乘（a[n-1]*a[n-1]）。例：a[n-1]*n、a[n-1]*3/2。"},
              "known": {"type": "array", "minItems": 2, "maxItems": 200, "items": {"type": "integer"},
                        "description": "known：已知项 a[1], a[2], …，都是整数（下标从 1 起）。前若干项作种子，个数等于 relation 回看的最大步数。"},
              "holdout": {"type": "array", "maxItems": 50, "items": {"type": "integer"},
                          "description": "holdout：紧接已知项之后的保留项（整数），用来盲测。"}}},
         RECEIPT, {"relation": "a[n-1]*n", "known": [1, 2, 6, 24, 120], "holdout": [720, 5040]},
         {"verdicts": ["established", "refuted"], "exact_arithmetic": True, "proof_grades": ["exact"]},
         [{"input": "1, 2, 6, 24, 120 是不是满足 a[n] = n·a[n-1]", "output": "established，保留项 720、5040 也对上，适用范围：已核验到第 7 项"},
          {"input": "1, 2, 4, 8 之后是 15、32，a[n] = 2a[n-1] 成立吗", "output": "refuted，第 5 项不符"},
          {"input": "斐波那契递推对 1,1,2,3,5,8 成立吗", "output": "established"}],
         ["不自己猜递推式"],
         review=["verdict_eq_established"]),
    unit("mathdisc.reach", ["check"], ["math_relation"], ["verdict"],
         {"type": "object", "additionalProperties": False, "required": ["expr", "target"],
          "description": "你写出一个只含整数的算式、说它等于某个目标值（如凑 24 点的答案），要一个可以当证据的判定时用。它按精确分数求值，不经模型；回执给出达到与否和算式的精确值。",
          "properties": {
              "expr": {"type": "string", "minLength": 1, "maxLength": 1000,
                       "description": "expr：由整数、+ - * /、**（整数指数）、括号写成的算式，也可以用 factorial(n) 与完全平方数的 sqrt；例 8/(3-8/3)。"},
              "target": {"description": "target：目标值，整数或 'p/q' 形式的分数。", "oneOf": [{"type": "integer"}, {"type": "string", "pattern": "^-?[0-9]+(/[0-9]+)?$"}]}}},
         RECEIPT, {"expr": "8/(3-8/3)", "target": 24},
         {"verdicts": ["established", "refuted"], "exact_arithmetic": True},
         [{"input": "8/(3-8/3) 是不是等于 24", "output": "established，值为 24"},
          {"input": "3×8 等于 25 吗", "output": "refuted，值为 24"},
          {"input": "核对 (1+1/2)×4 = 6", "output": "established"}],
         ["不处理含变量的表达式"],
         review=["solved_eq_target", "verdict_eq_established"]),
    unit("mathdisc.counterexample", ["check"], ["math_relation", "math_witness"], ["verdict"],
         {"type": "object", "additionalProperties": False, "required": ["conjecture", "witness"],
          "description": "有一条“某个整数表达式总是素数”的猜想，你找到一个可能推翻它的取值时用。取值由你提出；它把取值代入、做素性判定：不是素数即推翻，回执附质因数作证据；是素数则这个取值不构成反例。",
          "properties": {
              "conjecture": {"type": "string", "minLength": 1, "maxLength": 500,
                             "description": "conjecture：猜想，写成 isprime(<整数表达式>)，意为“对所有取值，括号里都是素数”。整数表达式由整数、变量、+ - * **、能整除的 /、factorial 写成。例：isprime(2**(2**n)+1)。"},
              "witness": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "integer"},
                          "description": "witness：候选反例，变量名到整数的取值，例 {\"n\": 5}。"}}},
         RECEIPT, {"conjecture": "isprime(2**(2**n)+1)", "witness": {"n": 5}},
         {"verdicts": ["refuted", "rejected"], "predicates": ["isprime"]},
         [{"input": "n=5 是不是“2^(2^n)+1 都是素数”的反例", "output": "refuted，因数含 641"},
          {"input": "n=0 是不是同一猜想的反例", "output": "rejected，3 是素数，这个取值不构成反例"},
          {"input": "检验 n=40 是否推翻“n²+n+41 都是素数”", "output": "refuted"}],
         ["不自己搜索反例"],
         review=["verdict_eq_refuted"]),
    unit("mathdisc.solve_closed", ["compute"], ["math_sequence"], ["math_solution"],
         {"type": "object", "additionalProperties": False, "required": ["numbers", "target"],
          "description": "要回答“这几个整数（至多 6 个）能不能经加减乘除凑出目标整数”时用（如 24 点，每个数恰用一次）。它穷举所有算式：凑得出就给一个算式；凑不出就回报无解——穷举完即是无解的证明。",
          "properties": {
              "numbers": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "integer"}, "description": "numbers：参与运算的整数，每个恰用一次，至多 6 个。"},
              "ops": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": ["+", "-", "*", "/"]}, "description": "ops：可用的运算符，缺省四则全用。"},
              "target": {"type": "integer", "description": "target：目标整数。"}}},
         {"type": "object", "additionalProperties": False, "required": ["solvable", "expr", "proof"],
          "properties": {"solvable": {"type": "boolean"}, "expr": {"type": ["string", "null"]}, "proof": {"type": "string"}}},
         {"numbers": [3, 3, 8, 8], "target": 24},
         {"max_numbers": 6, "ops": ["+", "-", "*", "/"], "exhaustive": True, "zero_model_calls": True},
         [{"input": "用 3、3、8、8 算出 24", "output": "solvable，8/(3-8/3)"},
          {"input": "1、1、1、1 能不能算出 24", "output": "不可解，穷举为证"},
          {"input": "用 4、7、8、8 加减乘除得 24", "output": "solvable，给出一个算式"}],
         ["不处理多于 6 个数的组合"]),
]

DISCOVER_RECEIPT = {
    "type": "object", "additionalProperties": False,
    "required": ["stop_reason", "relations", "assumptions", "cost", "relation_receipts"],
    "properties": {
        "stop_reason": {"enum": ["solved", "exhausted", "budget", "undetermined"]},
        "relations": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "object", "required": ["statement", "source"],
                                                   "properties": {"statement": {"type": "string"}, "source": {"type": "string"}}}},
        "cost": {"type": "object", "properties": {"rounds": {"type": ["integer", "null"]}, "rho_calls": {"type": ["integer", "null"]}}},
        "relation_receipts": {"type": "array", "items": {
            "type": "object", "required": ["expr", "verdict", "evidence", "assumptions"],
            "properties": {"expr": {"type": "string"}, "verdict": {"type": "string"}, "evidence": {"type": "object"},
                           "validity": {"type": "object"}, "assumptions": {"type": "array", "items": {"type": "string"}}}}},
    },
}

UNITS.append(unit(
    "mathdisc.discover", ["discover"], ["math_table", "math_sequence"], ["math_relation"],
    {"type": "object", "additionalProperties": False, "required": ["f_task", "data"],
     "description": "你手上有一批观测数据、想找出背后的数学关系（经验公式或数列递推）、但还没有候选时用。它让模型多轮提出候选关系，每条候选都要过计算器的判定（拟合加盲测，或精确递推）才会交出；模型的话不算数。要分钟级时间，提交后取结果。交出的是候选：formula 的候选只是数据级验证（拟合加盲测），附适用范围与假设，不是证明；recurrence 的候选在给出的各项上逐项精确复现，附适用范围，给出的项之外未核验。回报四种停机状态：solved（找到）、exhausted（候选全被判不成立，不等于不存在规律）、budget（轮数用尽）、undetermined（时限内没有得出结论，不等于没有规律；此时 relations 为空）。",
     "properties": {
         "f_task": {"enum": ["formula", "recurrence"], "description": "f_task：要找哪一种关系。formula 是数据表里响应列 y 随变量变化的公式；recurrence 是整数数列的递推式。"},
         "data": {"description": "data：数据。formula 时是按列给出的数据表，变量列用变量名作键，响应列的键是 y，各列等长；recurrence 时是整数数列，或 {known: 已知项, holdout: 紧接其后的保留项}。",
                  "oneOf": [{"type": "object", "minProperties": 1, "maxProperties": 9},
                            {"type": "array", "minItems": 3, "maxItems": 200, "items": {"type": "integer"}}]},
         "vars": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1, "maxLength": 32},
                  "description": "vars：变量名；formula 时缺省取 data 里除 y 外的各列名。"},
         "holdout": {"type": "number", "minimum": 0.1, "maximum": 0.5, "description": "holdout：末尾留作盲测的行所占比例，缺省 0.25。"},
         "ops": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": ["+", "-", "*", "/", "**"]}, "description": "ops：候选里允许用的运算符，缺省 + - * / ** 全用。"},
         "n_max": {"type": "integer", "minimum": 1, "maximum": 8, "description": "n_max：每轮最多交几条候选，缺省 4。"},
         "budget": {"type": "integer", "minimum": 1, "maximum": 24, "description": "budget：最多几轮，缺省 6。"}}},
    DISCOVER_RECEIPT,
    {"f_task": "formula", "data": {"x": [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4], "y": [0.354, 1.002, 1.844, 2.842, 3.972, 5.218, 6.566, 8.007]}, "budget": 6},
    {"stop_reasons": ["solved", "exhausted", "budget", "undetermined"], "f_task": ["formula", "recurrence"], "rows": [4, 2000], "variables": [1, 8], "budget": [1, 24],
     "proof_grades": ["verified_on_data", "exact"], "model_calls": "每轮一次，由模型提出候选，判定不经模型"},
    [{"input": "给一批 (x, y) 数据，找出 y 随 x 变化的公式", "output": "solved，交出通过拟合与盲测的候选公式，每条附适用范围与假设：只是数据级验证，未经证明"},
     {"input": "一串整数 1, 2, 6, 24, 120, 720，找出递推式", "output": "solved，交出 a[n-1]*n 一类候选，在给出的各项上逐项精确复现，附适用范围：给出的项之外未核验"},
     {"input": "对一组彼此无关的随机数找规律", "output": "exhausted，候选全被判不成立，relations 为空"}],
    ["不给出证明", "exhausted 不等于不存在规律", "不核验自己手写的候选", "不做外推担保", "恒等式核验、算式等于目标值核验、素数猜想反例核验不走本件，用同步单件工具 mathdisc.identity、mathdisc.reach、mathdisc.counterexample"],
    cost={"latency": 120000, "price": 10, "timeout": 600000},
    trust="T3",
    executor={"kind": "process", "entry": "md_tool.py", "mode": "async", "credential_ref": "DASHSCOPE_API_KEY",
              "async_ops": {"submit": "POST /api/v1/jobs", "status": "GET /api/v1/jobs/{job_id}"}}))

TYPES_NOTE = {"math_relation": "表达式、公式、递推式或猜想的文字", "math_table": "按列给出的数据表",
              "math_sequence": "整数数列", "math_witness": "变量到整数的取值", "math_solution": "封闭求解的结果"}

if __name__ == "__main__":
    reg = {"family": "mathdisc", "family_version": "1.2.0", "lock_hash": "",
           "note": "mathdisc 的七件工具：六件确定性判定（零模型调用，T1）与发现循环 discover（异步、出网调用模型、T3，产物是候选）。代入求值另有计算工具承担，本包不重复登记。",
           "units": UNITS}
    for u in reg["units"]:
        u["version"] = ""
    (ROOT / "registration.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(len(UNITS))
