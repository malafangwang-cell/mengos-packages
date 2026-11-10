"""mathdisc.discover（1.2.0）专项。

整套不调模型：检查门前的 ρ 一律用手写回放；真模型读数在部署后另跑（见 README）。
第一组是静态与信封层，不需要数学库；第二组回放循环，需要 lock 里的四库（缺库时这些用例报 ImportError，不静默通过）。
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
M = json.loads((ROOT / "mengos-package.json").read_text(encoding="utf-8"))
REG = json.loads((ROOT / M["tools"]).read_text(encoding="utf-8"))
UNIT = next(u for u in REG["units"] if u["tool_id"] == "mathdisc.discover")
LOCK = json.loads((ROOT / "mathdisc.lock").read_text(encoding="utf-8"))
GOLDENS = ROOT / "tests" / "goldens"


# ---------------------------------------------------------------- 静态与信封层（不需要数学库）
def test_registration_fields():
    assert [u["tool_id"] for u in REG["units"]].count("mathdisc.discover") == 1
    assert UNIT["trust_claim"] == "T3" and UNIT["effect"] == "none"
    assert UNIT["executor"]["mode"] == "async" and UNIT["executor"]["credential_ref"] == "DASHSCOPE_API_KEY"
    assert UNIT["cost"] == {"latency": 120000, "price": 10, "timeout": 600000}
    assert UNIT["capability"]["out_types"] == ["math_relation"]
    ng = UNIT["capability"]["non_goals"]
    assert "不给出证明" in ng and "exhausted 不等于不存在规律" in ng


def test_receipt_schema_keeps_old_fields_and_adds_relation_receipts():
    props = UNIT["signature"]["output_schema"]["properties"]
    assert {"stop_reason", "relations", "assumptions", "cost"} <= set(props)
    assert "relation_receipts" in props
    item = props["relation_receipts"]["items"]
    assert {"expr", "verdict", "evidence", "assumptions"} <= set(item["required"]) and "validity" in item["properties"]


def test_input_schema_has_no_mock_and_is_closed():
    sch = UNIT["signature"]["input_schema"]
    assert sch["additionalProperties"] is False and "mock" not in sch["properties"]
    assert not any("mock" in str(v).lower() for v in sch["properties"].values())


def _call(env, extra_env=None):
    import os
    e = {k: v for k, v in os.environ.items() if k not in ("MATHDISC_RHO_MOCK", "DASHSCOPE_API_KEY")}
    e.update(extra_env or {})
    p = subprocess.run([sys.executable, str(ROOT / "md_tool.py")], input=(json.dumps(env) + "\n").encode(),
                       capture_output=True, timeout=60, cwd=str(ROOT), env=e)
    return json.loads(p.stdout)


def test_mock_field_in_input_is_rejected_before_anything_runs():
    """DX-4：入参带 mock 即拒，不起循环、不碰模型。"""
    out = _call({"tool": "mathdisc.discover", "payload": {"f_task": "formula", "data": {"x": [1, 2, 3, 4], "y": [1, 2, 3, 4]}, "mock": True}})
    assert out["ok"] is False and out["error"]["code"] == "BAD_INPUT" and "mock" in out["error"]["message"]


def test_bad_inputs_rejected():
    ok = {"x": [1, 2, 3, 4], "y": [2, 4, 6, 8]}
    for payload in ({"f_task": "prove", "data": ok}, {"f_task": "formula", "data": {"x": [1, 2, 3, 4]}},
                    {"f_task": "formula", "data": ok, "budget": 99}, {"f_task": "recurrence", "data": [1, 2.5, 3]},
                    {"f_task": "formula", "data": ok, "ops": ["sqrt"]}):
        out = _call({"tool": "mathdisc.discover", "payload": payload})
        assert out["ok"] is False and out["error"]["code"] == "BAD_INPUT", payload


def test_manifest_names_only_dashscope_and_key_name_only():
    assert M["runtime"]["process"]["network"] == "dashscope.aliyuncs.com"
    rm = LOCK["rho_model"]
    assert rm["base_url"].startswith("https://dashscope.aliyuncs.com/")
    assert rm["api_key_env"] == "DASHSCOPE_API_KEY" and not any(k in rm for k in ("api_key", "key", "token"))


def test_lock_model_binding():
    """DX-9 包侧：模型与思考模式（引擎侧另有一条对模型目录的核对）。"""
    rm = LOCK["rho_model"]
    assert rm["model_id"] == "qwen3.8-max-0902" and rm["thinking"] == "disabled" and rm["dialect"] == "dashscope"


def test_no_secrets_in_package_files():
    pats = [re.compile(r"sk-[A-Za-z0-9]{16,}"), re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
            re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*[\"'][A-Za-z0-9._-]{16,}[\"']"),
            re.compile(r"AKIA[0-9A-Z]{16}")]
    for p in ROOT.rglob("*"):
        if p.is_file() and not {".git", "__pycache__", ".venv"} & set(p.parts) and p.name != "uv.lock":
            try:
                t = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pat in pats:
                assert not pat.search(t), (str(p), pat.pattern)


def test_prompt_version_matches_lock():
    sys.path.insert(0, str(ROOT))
    assert (ROOT / "mathdisc" / "prompts" / f"{LOCK['prompt_v']}.txt").is_file()


def test_missing_credential_is_structured_failure_not_exhausted():
    """没有钥匙时如实报错，不降级为空 ρ、不冒充“没找到”。"""
    out = _call({"tool": "mathdisc.discover", "payload": {"f_task": "formula", "data": {"x": [1, 2, 3, 4], "y": [2, 4, 6, 8]}}})
    assert out["ok"] is False and out["error"]["code"] == "INTERNAL" and "DASHSCOPE_API_KEY" in out["error"]["message"]


def test_only_env_variable_opens_empty_rho():
    """空 ρ 只由环境变量打开；打开时管道自检为 exhausted、回执形状合规。"""
    pl = {"f_task": "formula", "data": {"x": [1, 2, 3, 4, 5, 6, 7, 8], "y": [2, 4, 6, 8, 10, 12, 14, 16]}}
    out = _call({"tool": "mathdisc.discover", "payload": pl}, {"MATHDISC_RHO_MOCK": "1"})
    assert out["ok"] is True and out["output"]["stop_reason"] == "exhausted"
    assert out["output"]["relations"] == [] and out["output"]["relation_receipts"] == []
    assert set(out["output"]) == {"stop_reason", "relations", "assumptions", "cost", "relation_receipts"}


# ---------------------------------------------------------------- 回放金样（需要四库；ρ 为手写回放，不调模型）
class Replay:
    """逐轮返回脚本里的候选；脚本用尽后返回空。"""

    def __init__(self, script):
        self.script, self.calls = script, 0

    def __call__(self, V, T, sig, f_task, dead, n_max):
        out = self.script[self.calls] if self.calls < len(self.script) else []
        self.calls += 1
        return out


def _discover(payload, script, timeout_ms=None):
    import md_tool
    rho = Replay(script)
    env = {"tool": "mathdisc.discover", "payload": payload}
    if timeout_ms:
        env["budget"] = {"timeout_ms": timeout_ms}
    with mock.patch("mathdisc.discover.make_rho_from_env", lambda: rho):
        return md_tool.run(env), rho


def _probe(pid):
    return next(p for p in json.loads((GOLDENS / "ln_noise_probes.json").read_text(encoding="utf-8"))["probes"] if p["id"] == pid)


ALL_OPS = ["+", "-", "*", "/", "**"]


def test_negative_control_noise_sequence():
    """阴性对照（发布判据）：随机数列，模型宁编不空——7 条以上像模像样的递推全被检查门拦下。"""
    p = _probe("ln-seq")
    script = [["a[n-1]+5", "a[n-1]*2", "a[n-1]+n"], ["a[n-2]+a[n-1]", "a[n-1]*3-1", "a[n-1]+a[n-2]+n"], ["a[n-1]*n-a[n-2]"], []]  # 末轮模型交空：exhausted（与主仓库同探针的停机一致）
    out, _ = _discover({"f_task": "recurrence", "data": p["data"], "ops": ALL_OPS, "budget": 4}, script)
    r = out["output"]
    assert r["stop_reason"] == p["expected"]["stop"] and r["relations"] == [] and r["relation_receipts"] == []


def test_negative_control_noise_formula():
    """阴性对照：y 与 x 独立随机，过拟合的多项式、凑数常数共 6 条，留出盲测全拦。"""
    p = _probe("ln-formula")
    cands = ["c1*x**5+c2*x**4+c3*x**3+c4", "c1*x**3+c2*x**2+c3*x+c4", "c1*x**2+c2*x+c3", "c1*x+c2", "c1*x**c2+c3", "c1/x+c2"]
    out, _ = _discover({"f_task": "formula", "data": p["data"], "ops": ALL_OPS, "budget": 3}, [cands[:3], cands[3:], []])
    r = out["output"]
    assert r["stop_reason"] == p["expected"]["stop"] and r["relations"] == [] and r["relation_receipts"] == []


def test_negative_control_unreachable_reach_gate_directly():
    """构造性不可达（1,1,1,1 经 + − 到 24）：reach 不在 discover 的 f_task 里，这条在循环层回放同一探针。"""
    from mathdisc.loop.solve import solve
    p = _probe("ln-reach")
    rho = Replay([["1+1+1+1", "1+1-1+1", "1+1+1-1"], ["1-1+1+1", "1+1+1+1+1", "1+1+1+1-1"], []])
    r = solve(V=p["V"], T=p["T"], f_task="reach", target=p["target"], budget=3, rho=rho)
    assert r.stop == "exhausted" and r.relations == []


def test_v1_failures_replay():
    """d5_v1_failures.json 里的 v1 事故样本，经检查门判定如金样所记。"""
    from fractions import Fraction
    from mathdisc.check.identity import check_identity
    from mathdisc.check.recurrence import check_recurrence
    from mathdisc.expr.grammar import parse
    cases = json.loads((GOLDENS / "d5_v1_failures.json").read_text(encoding="utf-8"))["cases"]
    seen = 0
    for c in cases:
        if c["id"] == "g-sqrt2":
            r = check_identity(parse(c["expr_lhs"]), parse(c["expr_rhs"]), declared_dps=50)
            assert r.verdict == "established" and r.verdict != "refuted"
            seen += 1
        elif c["id"] == "g-factorial":
            r = check_recurrence(relation=c["relation"], known=c["sequence"], holdout=c["holdout"])
            assert r.verdict == c["expected"]["verdict"]
            seen += 1
    assert seen == 2


KEPLER_X = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]


def _kepler_y():
    cases = json.loads((ROOT / "golden_cases.json").read_text(encoding="utf-8"))
    return next(c for c in cases if c["id"] == "fm-kepler")["payload"]["columns"]["y"]


def test_positive_replay_formula_solved_with_range_and_assumptions():
    """阳性：录下的候选回放，停机 solved；回执带 verified_on_data 与 data_range，假设逐条在场。"""
    data = {"x": KEPLER_X, "y": _kepler_y()}
    out, _ = _discover({"f_task": "formula", "data": data, "ops": ALL_OPS, "budget": 3}, [["c1*x+c2", "c1*x**c2"]])
    r = out["output"]
    assert r["stop_reason"] == "solved" and r["relations"] == ["c1*x**c2"]
    assert r["cost"] == {"rounds": 1, "rho_calls": 1}
    rr = r["relation_receipts"]
    assert len(rr) == 1 and rr[0]["expr"] == r["relations"][0] and rr[0]["verdict"] == "established"
    assert rr[0]["evidence"]["grade"] == "verified_on_data"
    assert rr[0]["validity"]["basis"] == "data_range" and rr[0]["validity"]["core"][0]["name"] == "x"
    # 假设按 ta_projection.json 逐条在场：总表与逐条一致
    table = json.loads((ROOT / "mathdisc" / "ta_projection.json").read_text(encoding="utf-8"))["rules"]
    tpl = next(x["template"] for x in table if x["match"] == "verified_on_data")
    assert r["assumptions"] == [{"statement": tpl, "source": "c1*x**c2"}] and rr[0]["assumptions"] == [tpl]


def test_positive_replay_recurrence_exact_has_no_assumption():
    """精确算术级（exact）无需假设：assumptions 空，relation_receipts 仍给逐条回执，且不伪造 validity 以外的字段。"""
    out, _ = _discover({"f_task": "recurrence", "data": {"known": [1, 2, 6, 24, 120, 720, 5040, 40320], "holdout": [362880, 3628800]},
                        "ops": ALL_OPS, "budget": 2}, [["a[n-1]+1", "a[n-1]*n"]])
    r = out["output"]
    assert r["stop_reason"] == "solved" and r["relations"] == ["a[n-1]*n"] and r["assumptions"] == []
    assert r["relation_receipts"][0]["assumptions"] == [] and r["relation_receipts"][0]["evidence"]["grade"] == "exact"


def test_relation_receipt_evidence_is_copied_not_recomputed():
    """relation_receipts[i].evidence 与检查门回执里的 evidence 同一份。"""
    from mathdisc.check.formula import check_formula
    n = len(KEPLER_X)
    cut = max(1, int(n * 0.75))
    y = _kepler_y()
    direct = check_formula(form="c1*x**c2", data={"x": KEPLER_X[:cut], "y": y[:cut]},
                           holdout=({"x": KEPLER_X[cut:]}, y[cut:]), seed=0)
    out, _ = _discover({"f_task": "formula", "data": {"x": KEPLER_X, "y": y}, "ops": ALL_OPS, "budget": 1}, [["c1*x**c2"]])
    import md_tool
    assert out["output"]["relation_receipts"][0]["evidence"] == md_tool._jsonable(direct.evidence)


def test_timeout_returns_undetermined_not_error():
    """超时：回执为 undetermined，不是异常；模型客户端的重试吞不掉到点。
    先预载循环用到的重模块，保证到点发生在回放 ρ 里（而不是 import 期间），并断言 ρ 确实被调用过。"""
    import mathdisc.discover, mathdisc.forensics.signature, mathdisc.loop.solve  # noqa: F401, E401
    called = []

    def slow(V, T, sig, f_task, dead, n_max):
        called.append(1)
        for _ in range(100):
            try:
                time.sleep(0.05)
            except Exception:  # 模型客户端的重试逻辑就是这样 catch Exception 的
                pass
        return []

    import md_tool
    env = {"tool": "mathdisc.discover", "budget": {"timeout_ms": 400},
           "payload": {"f_task": "formula", "data": {"x": [1, 2, 3, 4, 5, 6, 7, 8], "y": [2, 4, 6, 8, 10, 12, 14, 16]}}}
    with mock.patch("mathdisc.discover.make_rho_from_env", lambda: slow):
        out = md_tool.run(env)
    assert called, "回放 ρ 没有被调用：到点发生在循环之外"
    assert out["ok"] is True and out["output"]["stop_reason"] == "undetermined" and out["output"]["relations"] == []


# ---------------------------------------------------------------- 架构线补裁二：锁对齐、validity 同源、四态、最外层超时
def test_verify_lock_passes_in_package_env():
    """mathdisc.lock 的四库版本、文法版、prompt 版与包环境（uv sync --frozen）实际一致。"""
    from mathdisc.lock_verify import verify_lock
    assert verify_lock()["deps"] == LOCK["deps"]


def test_capability_states_four_stop_reasons_and_f_task_scope():
    text = UNIT["signature"]["input_schema"]["description"]
    assert "四种停机状态" in text and "三种" not in text
    assert "时限内没有得出结论，不等于没有规律" in text and "relations 为空" in text
    assert UNIT["signature"]["input_schema"]["properties"]["f_task"]["enum"] == ["formula", "recurrence"]
    ng = " ".join(UNIT["capability"]["non_goals"])
    for t in ("mathdisc.identity", "mathdisc.reach", "mathdisc.counterexample"):
        assert t in ng
    assert UNIT["signature"]["output_schema"]["properties"]["stop_reason"]["enum"] == ["solved", "exhausted", "budget", "undetermined"]


def _sync(tool, payload):
    import md_tool
    return md_tool.run({"tool": tool, "payload": payload})["output"]


def test_validity_equals_sync_formula_validity_field_by_field():
    """同一数据同一式子：discover 的 relation_receipts[i].validity 与同步 mathdisc.formula 回执的 validity 逐字段相同。"""
    y = _kepler_y()
    cols = {"x": KEPLER_X, "y": y}
    sync = _sync("mathdisc.formula", {"form": "c1*x**c2", "columns": cols, "holdout_ratio": 0.25})
    assert sync["verdict"] == "established"
    out, _ = _discover({"f_task": "formula", "data": cols, "ops": ALL_OPS, "holdout": 0.25, "budget": 1}, [["c1*x**c2"]])
    got = out["output"]["relation_receipts"][0]
    assert got["validity"] == sync["validity"]
    assert got["evidence"] == sync["evidence"] and got["verdict"] == sync["verdict"]


def test_validity_equals_sync_recurrence_validity_field_by_field():
    known, hold = [1, 2, 6, 24, 120, 720, 5040, 40320], [362880, 3628800]
    sync = _sync("mathdisc.recurrence", {"relation": "a[n-1]*n", "known": known, "holdout": hold})
    assert sync["verdict"] == "established"
    out, _ = _discover({"f_task": "recurrence", "data": {"known": known, "holdout": hold}, "ops": ALL_OPS, "budget": 1}, [["a[n-1]*n"]])
    got = out["output"]["relation_receipts"][0]
    assert got["validity"] == sync["validity"]
    assert got["evidence"] == sync["evidence"] and got["verdict"] == sync["verdict"]


def test_timeout_outermost_is_undetermined_and_process_exits_cleanly():
    """最外层：到点信号在循环里（回放 ρ 内吞 Exception 的重试中）触发，进程仍以退出码 0 写出一行 undetermined 回执。
    driver 先预载循环用到的重模块再进 md_tool.main()，保证到点发生在 ρ 里，而不是 import 期间；
    ρ 被调用的证据是它先往 stderr 写一行标记，本测试断言该标记在场。"""
    driver = (
        "import sys, time\n"
        "sys.path.insert(0, %r)\n"
        "from unittest import mock\n"
        "import mathdisc.discover, mathdisc.loop.solve, mathdisc.forensics.signature, mathdisc.adapter_projection\n"
        "import md_tool\n"
        "def slow(V, T, sig, f_task, dead, n_max):\n"
        "    sys.stderr.write('RHO_CALLED\\n'); sys.stderr.flush()\n"
        "    while True:\n"
        "        try:\n"
        "            time.sleep(0.05)\n"
        "        except Exception:\n"
        "            pass\n"
        "with mock.patch('mathdisc.discover.make_rho_from_env', lambda: slow):\n"
        "    sys.exit(md_tool.main())\n" % str(ROOT)
    )
    env = {"tool": "mathdisc.discover", "budget": {"timeout_ms": 400},
           "payload": {"f_task": "formula", "data": {"x": [1, 2, 3, 4, 5, 6, 7, 8], "y": [2, 4, 6, 8, 10, 12, 14, 16]}}}
    p = subprocess.run([sys.executable, "-c", driver], input=(json.dumps(env) + "\n").encode(),
                       capture_output=True, timeout=30, cwd=str(ROOT))
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")[-300:]
    assert b"RHO_CALLED" in p.stderr, "回放 ρ 没有被调用：到点发生在循环之外，测试没测到它声称的东西"
    lines = p.stdout.decode().strip().splitlines()
    assert len(lines) == 1
    out = json.loads(lines[0])
    assert out["ok"] is True and out["output"]["stop_reason"] == "undetermined" and out["output"]["relations"] == []


def test_client_host_comes_only_from_lock_and_no_legacy_env():
    """出网主机只能是 lock 里的 dashscope：环境里放任何 *_BASE_URL 都不改变 client 的 base_url。"""
    from mathdisc.llm.client import client_from_lock
    c = client_from_lock(env={"DASHSCOPE_API_KEY": "x", "DEEPSEEK_BASE_URL": "https://evil.example/v1", "OPENAI_BASE_URL": "https://evil.example/v1"})
    assert c._base_url == LOCK["rho_model"]["base_url"].rstrip("/")
    for rel in M["tools_lock"]["covers"]:
        if rel.endswith(".py"):
            assert "deepseek" not in (ROOT / rel).read_text(encoding="utf-8").lower(), rel


def test_async_executor_declares_async_ops():
    """安装器 TL-9：mode=async 必带 async_ops；discover 登记的 async_ops 字面如下，其余 executor 字段不变。"""
    ex = UNIT["executor"]
    assert ex["mode"] == "async"
    assert ex["async_ops"] == {"submit": "POST /api/v1/jobs", "status": "GET /api/v1/jobs/{job_id}"}
    assert {k: v for k, v in ex.items() if k != "async_ops"} == {
        "kind": "process", "entry": "md_tool.py", "mode": "async", "credential_ref": "DASHSCOPE_API_KEY"}
    for u in REG["units"]:
        if u["executor"]["mode"] == "async":
            assert "async_ops" in u["executor"], u["tool_id"]
        else:
            assert "async_ops" not in u["executor"], u["tool_id"]


def test_capability_ops_are_controlled_verbs():
    """安装器 TL-17：capability.ops 是受控动词闭集的非空子集；discover 的 ops 逐字为 ["generate"]。"""
    verbs = {"compute", "check", "retrieve", "execute", "generate", "convert"}
    assert len(REG["units"]) == 7
    for u in REG["units"]:
        ops = u["capability"]["ops"]
        assert ops and set(ops) <= verbs, (u["tool_id"], ops)
    assert UNIT["capability"]["ops"] == ["generate"]


def test_discover_inputs_are_any_of_and_checkers_still_need_both():
    """1.2.1（执行令 11-10 §四 P1）：discover 收数据表或数列，有一样即可（in_any）；
    formula、recurrence 两件核验工具的输入仍是两样都要（in_types），不跟着改。"""
    cap = UNIT["capability"]
    assert cap["in_types"] == [] and cap["in_any"] == ["math_table", "math_sequence"]
    by_id = {u["tool_id"]: u["capability"] for u in REG["units"]}
    assert by_id["mathdisc.formula"]["in_types"] == ["math_relation", "math_table"]
    assert by_id["mathdisc.recurrence"]["in_types"] == ["math_relation", "math_sequence"]
    for tid, c in by_id.items():
        if tid != "mathdisc.discover":
            assert "in_any" not in c, tid
