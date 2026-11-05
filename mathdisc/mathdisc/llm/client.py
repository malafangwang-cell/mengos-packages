"""LLM 客户端.

OpenAI 兼容 HTTP (stdlib urllib, 零 SDK 依赖);
唯一网络出口; Protocol 注入 mock (全循环离线可测);
超时/重试策略显式配置。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Protocol


class LLMClient(Protocol):
    """ρ 唯一依赖面 (测试注入点)."""

    def complete(self, prompt: str) -> str:
        """prompt → 模型文本回包."""
        ...


class OpenAICompatClient:
    """OpenAI 兼容 HTTP 客户端 (唯一网络出口)."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout_s: float = 180.0, max_retries: int = 3,
                 thinking_type: str = "disabled", max_tokens: int | None = None,
                 dialect: str = "openai"):
        # 超时/重试显式配置
        # thinking_type: lock ρ绑定字段 (部分模型始终思考、拒绝 disabled, 档位以 lock 为真源)
        # max_tokens: lock ρ绑定字段 (有的接入点缺省 max_tokens 会 400 —— 有值才入载荷)
        # dialect: lock ρ绑定字段:
        #   "openai" = thinking{"type":...} 方言;
        #   "dashscope" = 百炼 compatible-mode 方言 enable_thinking 布尔, 不带 thinking 键
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
            payload["enable_thinking"] = self._thinking_type != "disabled"
        else:
            # 思考模式档位 (lock ρ绑定; 有的模型默认开启思考, disabled 关闭,
            #   有的仅接受 low/high/max)
            payload["thinking"] = {"type": self._thinking_type}
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        body = json.dumps(payload).encode("utf-8")
        last_err: Exception | None = None
        # base_url 拼接兼容: base_url 已含 /v1 段时不再重复拼 /v1
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


def client_from_lock(env: dict | None = None) -> OpenAICompatClient:
    """从 mathdisc.lock 的 ρ绑定构造客户端.

    model 与 base_url 只取自 lock（不吃任何环境覆盖，出网主机因此只能是 lock 里写的主机）;
    api_key 经 lock 里 api_key_env 所指的环境变量注入（不落盘）;
    key 缺席 → 显式上抛, 不静默降级 mock。
    """
    import os

    from ..lock_verify import load_lock

    binding = load_lock()["rho_model"]
    model_id = binding.get("model_id", "")
    if not model_id:
        raise RuntimeError("[mathdisc] lock ρ绑定 model_id 为空, 真ρ不可用")
    environ = os.environ if env is None else env
    key_env = binding.get("api_key_env", "DASHSCOPE_API_KEY")
    key = environ.get(key_env, "")
    if not key:
        raise RuntimeError(f"[mathdisc] {key_env} 未注入 (ρ绑定纪律: key 不落盘, 不静默降级)")
    base_url = binding["base_url"]
    return OpenAICompatClient(
        base_url=base_url,
        api_key=key, model=model_id,
        thinking_type=binding.get("thinking", "disabled"),
        max_tokens=binding.get("max_tokens"),
        timeout_s=float(binding.get("timeout_s", 180.0)),
        dialect=binding.get("dialect", "openai"))
