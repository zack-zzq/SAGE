"""Use the LLM to intelligently split a multi-essay document into individual essays."""

from __future__ import annotations

import json
import logging
import re

from .llm_client import LLMConfig, chat_completion

logger = logging.getLogger(__name__)

SPLIT_SYSTEM_PROMPT = """\
你是一个文本分割助手。用户将提供一份包含多篇学生作文的文档文本。
你的任务是将该文档拆分为独立的作文，并以 JSON 数组的形式返回结果。

每篇作文应包含以下字段：
- "index": 作文编号（整数）
- "title": 作文标题（字符串）
- "author": 作者姓名（字符串）
- "content": 作文正文（字符串，保留原始换行）

注意事项：
1. 仔细识别每篇作文的边界，通常会有"作文 X"或类似的标记
2. 标题和作者信息可能在正文开头，需要准确提取
3. 不要遗漏任何一篇作文
4. 不要修改或总结作文内容，原样保留
5. 只返回 JSON 数组，不要有其他文字说明

输出格式示例：
```json
[
  {"index": 1, "title": "标题一", "author": "张三", "content": "正文内容..."},
  {"index": 2, "title": "标题二", "author": "李四", "content": "正文内容..."}
]
```
"""


async def split_essays(full_text: str, config: LLMConfig) -> list[dict]:
    """Split a multi-essay document into individual essays using the LLM.

    Returns a list of dicts with keys: index, title, author, content.
    """
    # If the text is very long, we may need to split it into chunks for the LLM.
    # For now, send the entire text (most models support 128k+ context).
    messages = [
        {"role": "system", "content": SPLIT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"请将以下文档中的所有作文拆分出来：\n\n{full_text}",
        },
    ]

    raw = await chat_completion(config, messages, temperature=0.1)

    # Extract JSON from the response (handle markdown code blocks)
    json_str = _extract_json(raw)

    try:
        essays = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse essay split JSON: %s\nRaw: %s", exc, raw[:500])
        raise ValueError("LLM 返回的作文拆分结果无法解析，请重试。") from exc

    if not isinstance(essays, list) or len(essays) == 0:
        raise ValueError("未能从文档中识别出任何作文，请检查上传的文件。")

    logger.info("Successfully split document into %d essays", len(essays))
    return essays


def _extract_json(text: str) -> str:
    """Extract JSON array from LLM response, stripping markdown fences if present."""
    # Try to find ```json ... ``` block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try to find bare JSON array
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return match.group(0).strip()

    return text.strip()
