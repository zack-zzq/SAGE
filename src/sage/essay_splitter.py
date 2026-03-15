"""Split a multi-essay document into individual essays.

Strategy:
1. **Regex-based splitting** (fast, reliable) — looks for common markers
   like "作文 1", "作文1", "作文一", "Essay 1", numbered headings, etc.
2. **LLM-based splitting** (fallback) — if regex finds ≤ 1 essay, uses the
   LLM to identify essay *boundaries* (NOT full content) and then slices
   the original text accordingly.
"""

from __future__ import annotations

import json
import logging
import re

from .llm_client import LLMConfig, chat_completion

logger = logging.getLogger(__name__)


# ── Regex-based splitter (primary) ──────────────────


# Patterns that mark the start of a new essay
_ESSAY_MARKERS = re.compile(
    r"^(?:"
    r"作文\s*(\d+)"       # 作文 1, 作文1
    r"|作文\s*[（(]\s*(\d+)\s*[）)]"  # 作文（1）
    r"|第\s*(\d+)\s*篇"   # 第1篇
    r"|(\d+)\s*[、.．]\s*" # 1、 or 1.
    r")",
    re.MULTILINE,
)


def _split_by_regex(full_text: str) -> list[dict]:
    """Try to split essays using common delimiter patterns."""
    lines = full_text.split("\n")
    essay_starts: list[tuple[int, int]] = []  # (line_index, essay_number)

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = _ESSAY_MARKERS.match(stripped)
        if m:
            # Extract the essay number from whichever group matched
            num = next((int(g) for g in m.groups() if g is not None), len(essay_starts) + 1)
            essay_starts.append((i, num))

    if len(essay_starts) <= 1:
        return []  # Not enough markers found, fall back to LLM

    # Slice the text between markers
    essays = []
    for idx, (start_line, num) in enumerate(essay_starts):
        end_line = essay_starts[idx + 1][0] if idx + 1 < len(essay_starts) else len(lines)
        block_lines = lines[start_line + 1 : end_line]  # skip the marker line itself

        # Try to extract title and author from the first non-empty lines
        title, author, content_start = _extract_title_author(block_lines)

        content = "\n".join(block_lines[content_start:]).strip()
        essays.append({
            "index": num,
            "title": title or f"作文 {num}",
            "author": author or "未知",
            "content": content,
        })

    return essays


def _extract_title_author(lines: list[str]) -> tuple[str, str, int]:
    """Heuristic: extract title and author from the first few lines of an essay block.

    Returns (title, author, content_start_line_index).
    """
    title = ""
    author = ""
    content_start = 0

    non_empty = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped:
            non_empty.append((i, stripped))
        if len(non_empty) >= 3:
            break

    if not non_empty:
        return title, author, 0

    # Usually: first non-empty line is the title, but it may contain author too
    first_line = non_empty[0][1]

    # Check for "题目：..." or just a short title line
    title_match = re.match(r"(?:题目[：:]\s*)?(.+)", first_line)
    if title_match:
        title = title_match.group(1).strip()
        content_start = non_empty[0][0] + 1

    # Check for author in second line or embedded in title
    # Patterns: "作者：张三", "——张三", "张三（高一1班）"
    if len(non_empty) >= 2:
        second_line = non_empty[1][1]
        author_match = re.match(
            r"(?:作者[：:]?\s*|——\s*|—\s*)?([\u4e00-\u9fff]{2,4})"
            r"(?:\s*[（(].*?[）)])?$",
            second_line,
        )
        if author_match and len(second_line) < 30:
            author = second_line.strip()
            content_start = non_empty[1][0] + 1

    return title, author, content_start


# ── LLM-based splitter (fallback) ───────────────────

LLM_SPLIT_PROMPT = """\
你是一个文本分割助手。用户将提供一份包含多篇学生作文的文档文本。
你的任务是识别每篇作文的边界，并以 JSON 数组返回结果。

⚠️ 重要：不要返回作文正文内容！只返回元数据和定位信息。

每篇作文应包含以下字段：
- "index": 作文编号（整数）
- "title": 作文标题（字符串）
- "author": 作者姓名（字符串）
- "start_marker": 该篇作文开头的前20个字（字符串，用于定位）
- "end_marker": 该篇作文结尾的后20个字（字符串，用于定位）

只返回 JSON 数组，不要有其他文字。示例：
```json
[
  {"index": 1, "title": "标题一", "author": "张三", "start_marker": "自然是瞬息万变的，那么规", "end_marker": "正是规矩与自然的和谐统一。"},
  {"index": 2, "title": "标题二", "author": "李四", "start_marker": "古人云，无规矩不成方圆", "end_marker": "在规矩中寻找自我的真谛。"}
]
```
"""


async def _split_by_llm(
    full_text: str,
    config: LLMConfig,
    on_chunk: callable | None = None,
) -> list[dict]:
    """Use LLM to identify essay boundaries, then slice original text."""
    messages = [
        {"role": "system", "content": LLM_SPLIT_PROMPT},
        {"role": "user", "content": f"请识别以下文档中每篇作文的边界：\n\n{full_text}"},
    ]

    raw = await chat_completion(config, messages, temperature=0.1, on_chunk=on_chunk)
    json_str = _extract_json(raw)

    try:
        boundaries = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse LLM boundary JSON: %s\nRaw: %s", exc, raw[:500])
        raise ValueError("LLM 返回的作文边界信息无法解析，请重试。") from exc

    if not isinstance(boundaries, list) or len(boundaries) == 0:
        raise ValueError("未能从文档中识别出任何作文，请检查上传的文件。")

    # Use start_markers to locate each essay in the original text
    essays = []
    for i, b in enumerate(boundaries):
        start_marker = b.get("start_marker", "")
        start_pos = full_text.find(start_marker) if start_marker else -1

        # Determine end position
        if i + 1 < len(boundaries):
            next_marker = boundaries[i + 1].get("start_marker", "")
            end_pos = full_text.find(next_marker) if next_marker else -1
            if end_pos == -1:
                end_pos = len(full_text)
        else:
            end_pos = len(full_text)

        if start_pos == -1:
            start_pos = 0

        content = full_text[start_pos:end_pos].strip()
        essays.append({
            "index": b.get("index", i + 1),
            "title": b.get("title", f"作文 {i + 1}"),
            "author": b.get("author", "未知"),
            "content": content,
        })

    return essays


# ── Public API ──────────────────────────────────────


async def split_essays(
    full_text: str,
    config: LLMConfig,
    on_chunk: callable | None = None,
) -> list[dict]:
    """Split a multi-essay document into individual essays.

    Tries regex-based splitting first (fast), falls back to LLM if needed.

    Args:
        full_text: The full document text.
        config: LLM configuration.
        on_chunk: Optional callback ``(total_chars, chunk)`` for streaming progress.

    Returns a list of dicts with keys: index, title, author, content.
    """
    # Strategy 1: Regex
    essays = _split_by_regex(full_text)
    if essays:
        logger.info("Regex split found %d essays (no LLM call needed)", len(essays))
        return essays

    # Strategy 2: LLM (boundary detection only — NOT full content echo)
    logger.info("Regex split found ≤1 essay, falling back to LLM boundary detection")
    essays = await _split_by_llm(full_text, config, on_chunk=on_chunk)
    logger.info("LLM boundary detection found %d essays", len(essays))
    return essays


def _extract_json(text: str) -> str:
    """Extract JSON array from LLM response, stripping markdown fences if present."""
    # Try to find ```json ... ``` block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try to find bare JSON array (greedy — find the largest match)
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return match.group(0).strip()

    return text.strip()
