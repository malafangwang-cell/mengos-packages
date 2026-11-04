"""开销基准：每次调用都起一个新进程（与 process 执行器一致），各 5 次。"""
import json, statistics, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent
CASES = {
    "evaluate·有理数快路": {"tool": "calc.evaluate", "payload": {"expr": "2^n + n^2", "bindings": {"n": 7}}},
    "evaluate·符号路": {"tool": "calc.evaluate", "payload": {"expr": "sqrt(8) + sin(30°)"}},
    "check_equal·有理数": {"tool": "calc.check_equal", "payload": {"left": "2^n+n^2", "right": "177", "bindings": {"n": 7}}},
    "algebra·solve": {"tool": "calc.algebra", "payload": {"op": "solve", "expr": "x^2-5x+6=0"}},
}
for name, env in CASES.items():
    line = json.dumps(env).encode()
    ts = []
    for _ in range(5):
        t = time.perf_counter()
        subprocess.run([sys.executable, str(ROOT / "calc_tool.py")], input=line, capture_output=True, check=True)
        ts.append((time.perf_counter() - t) * 1000)
    print(f"{name:<20} 首次 {ts[0]:6.0f} ms   热均 {statistics.mean(ts[1:]):6.0f} ms")
