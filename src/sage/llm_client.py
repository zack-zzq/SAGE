"""Async wrapper around the OpenAI Python SDK for LLM calls."""

from __future__ import annotations

import logging
from collections.abc import Callable
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
    on_chunk: Callable[[int, str], None] | None = None,
) -> str:
    """Send a chat completion request and return the assistant message content.

    If ``on_chunk`` is provided, uses **streaming** mode and calls
    ``on_chunk(total_chars_so_far, latest_chunk_text)`` for every received
    token chunk.  This allows the caller to emit real-time progress events.
    """
    client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)

    kwargs: dict = {
        "model": config.model_id,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    if on_chunk is not None:
        # ── Streaming mode ──
        kwargs["stream"] = True
        chunks: list[str] = []
        total_chars = 0

        async for event in await client.chat.completions.create(**kwargs):
            delta = event.choices[0].delta if event.choices else None
            if delta and delta.content:
                chunks.append(delta.content)
                total_chars += len(delta.content)
                on_chunk(total_chars, delta.content)

        content = "".join(chunks)
        logger.info(
            "LLM streaming response complete – model=%s, chars=%d",
            config.model_id,
            total_chars,
        )
        return content

    else:
        # ── Non-streaming mode ──
        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        logger.info(
            "LLM response received – model=%s, tokens=%s",
            config.model_id,
            response.usage,
        )
        return content
