"""FastAPI API routes for the SAGE application."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from ..config import settings
from ..document_parser import parse_file
from ..essay_grader import grade_essay
from ..essay_splitter import split_essays
from ..llm_client import LLMConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/defaults")
async def get_defaults():
    """Return default LLM configuration from env vars."""
    return {
        "model_id": settings.openai_model_id,
        "base_url": settings.openai_base_url,
        "api_key_set": bool(settings.openai_api_key),
    }


@router.post("/grade")
async def grade_essays(
    rubric_file: UploadFile = File(...),
    essays_file: UploadFile = File(...),
    user_prompt: str = Form(...),
    model_id: str = Form(""),
    base_url: str = Form(""),
    api_key: str = Form(""),
):
    """Main grading endpoint – returns SSE stream with progress and results."""

    # Resolve LLM config: form values override env defaults
    config = LLMConfig(
        api_key=api_key or settings.openai_api_key,
        base_url=base_url or settings.openai_base_url,
        model_id=model_id or settings.openai_model_id,
    )

    if not config.api_key:
        return StreamingResponse(
            _error_stream("请配置 API Key 后再试。"),
            media_type="text/event-stream",
        )

    # Read uploaded files
    rubric_bytes = await rubric_file.read()
    essays_bytes = await essays_file.read()
    rubric_name = rubric_file.filename or "rubric.docx"
    essays_name = essays_file.filename or "essays.docx"

    return StreamingResponse(
        _grade_stream(
            rubric_bytes, rubric_name, essays_bytes, essays_name, user_prompt, config
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _error_stream(msg: str):
    yield f"data: {json.dumps({'type': 'error', 'message': msg}, ensure_ascii=False)}\n\n"


async def _grade_stream(
    rubric_bytes: bytes,
    rubric_name: str,
    essays_bytes: bytes,
    essays_name: str,
    user_prompt: str,
    config: LLMConfig,
):
    """Async generator that yields SSE events for the grading pipeline."""

    # --- Step 1: Parse files ---
    yield _sse({"type": "status", "message": "正在解析上传的文件..."})
    await asyncio.sleep(0)  # yield control

    try:
        rubric_text = parse_file(rubric_bytes, rubric_name)
        essays_text = parse_file(essays_bytes, essays_name)
    except Exception as exc:
        yield _sse({"type": "error", "message": f"文件解析失败：{exc}"})
        return

    yield _sse({"type": "status", "message": "文件解析完成。"})

    # --- Step 2: Split essays ---
    yield _sse({"type": "status", "message": "正在使用 AI 识别和拆分作文..."})
    await asyncio.sleep(0)

    try:
        essays = await split_essays(essays_text, config)
    except Exception as exc:
        yield _sse({"type": "error", "message": f"作文拆分失败：{exc}"})
        return

    total = len(essays)
    yield _sse(
        {
            "type": "split_complete",
            "total": total,
            "message": f"成功识别出 {total} 篇作文。",
        }
    )

    # --- Step 3: Grade each essay ---
    for i, essay in enumerate(essays, 1):
        title = essay.get("title", f"作文 {i}")
        author = essay.get("author", "未知")
        yield _sse(
            {
                "type": "grading",
                "current": i,
                "total": total,
                "message": f"正在批阅第 {i}/{total} 篇：《{title}》（{author}）...",
            }
        )
        await asyncio.sleep(0)

        try:
            report = await grade_essay(essay, rubric_text, user_prompt, config)
            yield _sse(
                {
                    "type": "report",
                    "current": i,
                    "total": total,
                    "index": report.index,
                    "title": report.title,
                    "author": report.author,
                    "report_markdown": report.report_markdown,
                }
            )
        except Exception as exc:
            logger.exception("Error grading essay #%d", i)
            yield _sse(
                {
                    "type": "report_error",
                    "current": i,
                    "total": total,
                    "title": title,
                    "author": author,
                    "message": f"批阅失败：{exc}",
                }
            )

    yield _sse({"type": "complete", "message": f"全部 {total} 篇作文批阅完成！"})


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
