"""
LLM API 统一封装（DeepSeek / OpenAI）
直接从 config.py 读取配置
"""
from openai import OpenAI
from typing import Optional
import time
import config


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
OPENAI_BASE_URL = "https://api.openai.com/v1"


_USAGE_EVENTS: list[dict] = []


def reset_usage_metrics() -> None:
    _USAGE_EVENTS.clear()


def get_usage_metrics(start_call: int = 0) -> dict:
    """Return aggregate usage, optionally for events after a call index."""
    events = [dict(event) for event in _USAGE_EVENTS[max(0, start_call):]]
    roles = sorted({event.get("role", "unknown") for event in events})
    return {
        "calls": len(events),
        "successful_calls": sum(1 for event in events if event.get("ok")),
        "failed_calls": sum(1 for event in events if not event.get("ok")),
        "prompt_tokens": sum(int(event.get("prompt_tokens", 0) or 0) for event in events),
        "completion_tokens": sum(int(event.get("completion_tokens", 0) or 0) for event in events),
        "total_tokens": sum(int(event.get("total_tokens", 0) or 0) for event in events),
        "latency_seconds": round(sum(float(event.get("latency_seconds", 0) or 0) for event in events), 3),
        "by_role": {
            role: {
                "calls": sum(1 for event in events if event.get("role", "unknown") == role),
                "total_tokens": sum(
                    int(event.get("total_tokens", 0) or 0)
                    for event in events if event.get("role", "unknown") == role
                ),
                "latency_seconds": round(sum(
                    float(event.get("latency_seconds", 0) or 0)
                    for event in events if event.get("role", "unknown") == role
                ), 3),
            }
            for role in roles
        },
        "events": events,
    }


def _record_usage(provider: str, model: str, role: str, started: float, response=None, error: Exception | None = None) -> None:
    usage = getattr(response, "usage", None)
    _USAGE_EVENTS.append({
        "provider": provider,
        "model": model,
        "role": role,
        "ok": error is None,
        "error_type": type(error).__name__ if error else "",
        "latency_seconds": round(time.perf_counter() - started, 3),
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    })


class LLMClient:
    """统一 LLM 调用接口"""

    def __init__(self, provider: str = "deepseek", model: Optional[str] = None, role: str = "general"):
        """
        provider: "deepseek" | "openai"
        model: 模型名，None 则使用默认
        """
        self.provider = provider
        self.role = role
        if provider == "deepseek":
            if not config.DEEPSEEK_API_KEY:
                raise RuntimeError("DEEPSEEK_API_KEY is not configured")
            self.client = OpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
                timeout=config.LLM_TIMEOUT,
                max_retries=0,
            )
            self.model = model or config.SPEC_MODEL
        elif provider == "openai":
            if not config.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY is not configured")
            self.client = OpenAI(
                api_key=config.OPENAI_API_KEY,
                base_url=OPENAI_BASE_URL,
                timeout=config.LLM_TIMEOUT,
                max_retries=0,
            )
            self.model = model or "gpt-4o"
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def chat(
        self,
        system: str,
        user: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """单轮对话"""
        last_error = None
        for attempt in range(config.LLM_RETRIES + 1):
            started = time.perf_counter()
            try:
                request = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
                }
                token_limit = config.LLM_MAX_TOKENS if max_tokens is None else max_tokens
                if token_limit > 0:
                    request["max_tokens"] = token_limit
                resp = self.client.chat.completions.create(
                    **request,
                )
                _record_usage(self.provider, self.model, self.role, started, response=resp)
                return resp.choices[0].message.content or ""
            except Exception as exc:
                _record_usage(self.provider, self.model, self.role, started, error=exc)
                last_error = exc
                if attempt >= config.LLM_RETRIES:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise last_error

    def chat_with_history(self, messages: list, temperature: Optional[float] = None) -> str:
        """多轮对话（messages 已包含 role/content）"""
        last_error = None
        for attempt in range(config.LLM_RETRIES + 1):
            started = time.perf_counter()
            try:
                request = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
                }
                if config.LLM_MAX_TOKENS > 0:
                    request["max_tokens"] = config.LLM_MAX_TOKENS
                resp = self.client.chat.completions.create(**request)
                _record_usage(self.provider, self.model, self.role, started, response=resp)
                return resp.choices[0].message.content or ""
            except Exception as exc:
                _record_usage(self.provider, self.model, self.role, started, error=exc)
                last_error = exc
                if attempt >= config.LLM_RETRIES:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise last_error


# -------- 快捷创建函数 --------
def spec_llm() -> LLMClient:
    """Create the configured specification model adapter."""
    return LLMClient(provider=config.SPEC_PROVIDER, model=config.SPEC_MODEL, role="specification")


def code_llm() -> LLMClient:
    """Create the configured candidate-generation model adapter."""
    return LLMClient(provider=config.CODE_PROVIDER, model=config.CODE_MODEL, role="generation")


def repair_llm() -> LLMClient:
    """Create the configured candidate-repair model adapter."""
    return LLMClient(provider=config.REPAIR_PROVIDER, model=config.REPAIR_MODEL, role="repair")


def requirement_llm() -> LLMClient:
    """Create the requirement-analysis model adapter."""
    return LLMClient(provider=config.REQUIREMENT_PROVIDER, model=config.REQUIREMENT_MODEL, role="requirement")


def planner_llm() -> LLMClient:
    """Create the spec-guided planning model adapter."""
    return LLMClient(provider=config.PLANNER_PROVIDER, model=config.PLANNER_MODEL, role="planning")


def diagnosis_llm() -> LLMClient:
    """Create the failure-attribution model adapter."""
    return LLMClient(provider=config.DIAGNOSIS_PROVIDER, model=config.DIAGNOSIS_MODEL, role="diagnosis")


def critic_llm() -> LLMClient:
    """Create a fresh semantic critic client behind an experiment interface."""
    return LLMClient(provider=config.CRITIC_PROVIDER, model=config.CRITIC_MODEL, role="critic")


def semantic_probe_llm() -> LLMClient:
    """Fresh NL-only probe generator, independently configurable from Critic."""
    return LLMClient(
        provider=config.CRITIC_PROBE_PROVIDER,
        model=config.CRITIC_PROBE_MODEL,
        role="semantic_probe",
    )
