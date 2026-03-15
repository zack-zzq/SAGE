"""Grade individual essays against a rubric using the LLM."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .llm_client import LLMConfig, chat_completion

logger = logging.getLogger(__name__)


@dataclass
class GradingReport:
    """Structured grading report for a single essay."""

    index: int
    title: str
    author: str
    report_markdown: str


GRADING_SYSTEM_PROMPT = """\
你是一位资深的语文教师和作文批阅专家。你将根据用户提供的评分细则，为学生作文撰写详细的批阅报告。

## 评分细则
{rubric}

## 批阅要求
{user_prompt}

## 输出格式
请为这篇作文生成一份约1000字的详细批阅报告，包含以下几个部分（使用 Markdown 格式）：

### 1. 基本信息
- 作文标题
- 作者姓名
- **综合评分**：X 分（满分60分）
- 评分等级：X等

### 2. 审题立意
- **优点**：（具体分析）
- **不足**：（具体指出问题）
- **修改建议**：（附具体修改范例）

### 3. 语言表达
- **优点**：（具体分析）
- **不足**：（具体指出问题）
- **修改建议**：（附具体修改范例）

### 4. 议论文特征分析
- **优点**：（论点、论据、论证方法等方面的分析）
- **不足**：（具体指出问题）
- **修改建议**：（附具体修改范例）

### 5. 总体评价与升格建议
- 总体评价（简要概括该作文的整体水平）
- 升格建议（指出提升空间和具体改进方向，附生动具体的修改范例）

⚠️ 重要：
- 优缺点分析必须具体，引用原文中的句子或段落
- 修改建议要有生动具体的范例，直接给出修改后的示例文字
- 评分必须严格参照评分细则中的等级标准
- 报告使用中文撰写
"""


async def grade_essay(
    essay: dict,
    rubric_text: str,
    user_prompt: str,
    config: LLMConfig,
) -> GradingReport:
    """Grade a single essay and return a structured report."""
    index = essay.get("index", 0)
    title = essay.get("title", "未知标题")
    author = essay.get("author", "未知作者")
    content = essay.get("content", "")

    system_prompt = GRADING_SYSTEM_PROMPT.format(
        rubric=rubric_text, user_prompt=user_prompt
    )

    user_message = f"""请批阅以下作文：

**作文编号**：第 {index} 篇
**标题**：{title}
**作者**：{author}

**正文**：
{content}
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    report_md = await chat_completion(config, messages, temperature=0.5)

    logger.info("Essay #%d (%s by %s) graded successfully", index, title, author)

    return GradingReport(
        index=index,
        title=title,
        author=author,
        report_markdown=report_md,
    )
