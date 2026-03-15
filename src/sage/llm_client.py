"""Async wrapper around the OpenAI Python SDK for LLM calls."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """Runtime LLM configuration (may differ from global defaults)."""

    api_key: str
    base_url: str
    model_id: str


async def chat_completion(
    config: LLMConfig,
    messages: list[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> str:
    """Send a chat completion request and return the assistant message content."""

    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

    kwargs: dict = {
        "model": config.model_id,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    logger.info(
        "LLM response received – model=%s, tokens=%s",
        config.model_id,
        response.usage,
    )
    return content
