# 承: mathdisc设计文档v1§2 · mathdisc工程文档v1§1/§2 · 层: 工具·环0 · 版本: mathdisc-llm/v0.1.0
"""LLM 客户端 (承工程文档§1 llm/client.py).

OpenAI 兼容 HTTP (stdlib urllib, 零 SDK 依赖, 承设计§2 选型定案);
唯一网络出口 (承工程文档§2 llm-I1); Protocol 注入 mock (全循环离线可测);
超时/重试策略显式配置 (承 I1)。
"""
# impl: mathdisc-D4 | 承mathdisc设计文档v1§2 + 工程文档§2 llm-I1
from __future__ import annotations

import json
import urllib.request
from typing import Protocol


# impl: mathdisc-D4 | 承工程文档§1 llm/client.py (Protocol 注入 mock)
class LLMClient(Protocol):
    """ρ 唯一依赖面 (mock 注入点, 承工程文档§2 loop-I3 同纪律)."""

    def complete(self, prompt: str) -> str:
        """prompt → 模型文本回包."""
        ...


# impl: mathdisc-D4 | 承mathdisc设计文档v1§2 (OpenAI兼容HTTP, stdlib urllib)
class OpenAICompatClient:
    """OpenAI 兼容 HTTP 客户端 (唯一网络出口, 承 llm-I1)."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout_s: float = 180.0, max_retries: int = 3,
                 thinking_type: str = "disabled", max_tokens: int | None = None,
                 dialect: str = "openai"):
        # 超时/重试显式配置 (承 llm-I1)
        # thinking_type: 承 lock ρ绑定字段 (2026-09-01 glm5.3 接入点实测:
        #   该模型始终思考、拒绝 disabled, 仅接受 low/high/max —— 档位以 lock 为真源)
        # max_tokens: 承 lock ρ绑定字段 (同日实测: glm 接入点缺省 max_tokens → 400,
        #   DeepSeek 后端无此约束 —— 有值才入载荷, 缺省保持旧行为)
        # dialect: 承 lock ρ绑定字段 (2026-09-07 qwen3.8-max 接入实测:
        #   "openai"=万擎/DeepSeek 方言 thinking{"type":...};
        #   "dashscope"=阿里百炼 compatible-mode 方言 enable_thinking布尔, 不带thinking键)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._thinking_type = thinking_type
        self._max_tokens = max_tokens
        self._dialect = dialect

    def complete(self, prompt: str) -> str:
        payload: dict = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._dialect == "dashscope":
            # impl: mathdisc-D4 | 立法者指令2026-09-05/2026-09-07 (qwen enable_thinking=false, 承 engine dashscope-media.ts 实测)
            payload["enable_thinking"] = self._thinking_type != "disabled"
        else:
            # 思考模式档位 (承 lock ρ绑定; DeepSeek V4 默认开启思考, disabled 关闭,
            #   glm5.3 仅接受 low/high/max —— 承 engine/tools/provider/deepseek.ts 同纪律 +
            #   api-docs.deepseek.com/zh-cn/guides/thinking_mode)
            payload["thinking"] = {"type": self._thinking_type}
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        body = json.dumps(payload).encode("utf-8")
        last_err: Exception | None = None
        # ★base_url 拼接兼容 (2026-08-23 万擎网关接入, 承 deepseek.ts 同纪律):
        #   base_url 已含 /v1 段(如万擎 .../api/gateway/v1/endpoints) 时不再重复拼 /v1
        url = (f"{self._base_url}/chat/completions" if "/v1" in self._base_url
               else f"{self._base_url}/v1/chat/completions")
        for _ in range(self._max_retries + 1):
            try:
                req = urllib.request.Request(
                    url, data=body,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {self._api_key}"})
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except Exception as e:  # 网络/超时/形状 —— 重试计数内容忍, 用尽上抛
                last_err = e
        raise RuntimeError(f"LLM 调用失败(重试 {self._max_retries} 次用尽): {last_err}")


# impl: mathdisc-D7 | 承QD1裁决2026-08-18 (与平台主池同串)
def client_from_lock(env: dict | None = None) -> OpenAICompatClient:
    """从 mathdisc.lock 的 ρ绑定构造客户端 (QD1 已裁: 与平台主池同串).

    model/base_url 以 lock 为真源; api_key 经环境变量 DEEPSEEK_API_KEY 注入
    (不落盘, 承 lock note); key 缺席 → 显式上抛, 不静默降级 mock (承 GR-R7)。
    """
    import os

    from ..lock_verify import load_lock

    binding = load_lock()["rho_model"]
    model_id = binding.get("model_id", "")
    if not model_id:
        raise RuntimeError("[mathdisc] lock ρ绑定 model_id 为空 (QD1 未裁遗留), 真ρ不可用")
    environ = os.environ if env is None else env
    key_env = binding.get("api_key_env", "DEEPSEEK_API_KEY")
    key = environ.get(key_env, "")
    if not key:
        raise RuntimeError(f"[mathdisc] {key_env} 未注入 (ρ绑定纪律: key 不落盘, 承 GR-R7 不静默降级)")
    # ★2026-09-19 实证修复 (job-4766e67e-ed0 403 Forbidden): DEEPSEEK_BASE_URL 环境覆盖
    #   是 2026-08-23 万擎网关接入期的 DeepSeek 遗产; 09-07 ρ 已切 dashscope 方言
    #   (base_url+api_key_env 均以 lock 为真源), 旧覆盖变量会把 dashscope 请求劫持到
    #   万擎网关 ⟹ 网关拒 DASHSCOPE 钥匙 403。方言=dashscope 时 lock base_url 唯一真源,
    #   不吃 DeepSeek 遗产覆盖; openai 方言维持旧行为 (网关覆盖仍有效)。
    dialect = binding.get("dialect", "openai")
    base_url = (binding["base_url"] if dialect == "dashscope"
                else environ.get("DEEPSEEK_BASE_URL", binding["base_url"]))
    return OpenAICompatClient(
        base_url=base_url,
        api_key=key, model=model_id,
        thinking_type=binding.get("thinking", "disabled"),
        max_tokens=binding.get("max_tokens"),
        timeout_s=float(binding.get("timeout_s", 180.0)),
        dialect=binding.get("dialect", "openai"))
