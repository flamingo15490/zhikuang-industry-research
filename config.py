"""配置加载：LLM 连接参数（OpenAI 兼容接口）。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str


def load_llm_config() -> LLMConfig:
    return LLMConfig(
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", "deepseek-chat"),
    )


def create_llm_client():
    """带宽松超时与重试的 LLM 客户端。

    默认 connect 超时仅 5s，代理（Clash）握手稍慢即报 APITimeoutError；
    这里把超时放宽到 120s，并启用 3 次重试，扛过代理偶发抖动。
    """
    from openai import OpenAI

    cfg = load_llm_config()
    return OpenAI(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        timeout=120.0,
        max_retries=3,
    )
