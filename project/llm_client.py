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


class LLMClient:
    """统一 LLM 调用接口"""

    def __init__(self, provider: str = "deepseek", model: Optional[str] = None):
        """
        provider: "deepseek" | "openai"
        model: 模型名，None 则使用默认
        """
        self.provider = provider
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

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        """单轮对话"""
        last_error = None
        for attempt in range(config.LLM_RETRIES + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=temperature,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_error = exc
                if attempt >= config.LLM_RETRIES:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise last_error

    def chat_with_history(self, messages: list, temperature: float = 0.2) -> str:
        """多轮对话（messages 已包含 role/content）"""
        last_error = None
        for attempt in range(config.LLM_RETRIES + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_error = exc
                if attempt >= config.LLM_RETRIES:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise last_error


# -------- 快捷创建函数 --------
def spec_llm() -> LLMClient:
    """Spec Agent 用弱模型省钱"""
    return LLMClient(provider="deepseek", model=config.SPEC_MODEL)


def code_llm() -> LLMClient:
    """Code Agent 用强模型"""
    return LLMClient(provider="deepseek", model=config.CODE_MODEL)


def repair_llm() -> LLMClient:
    """Repair Agent 用强模型"""
    return LLMClient(provider="deepseek", model=config.REPAIR_MODEL)
