"""FastAPI API routes for the SAGE application."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..config import settings
from ..document_parser import parse_file
from ..essay_grader import grade_essay
from ..essay_splitter import split_essays
from ..llm_client import LLMConfig
from ..report_exporter import export_docx, export_pdf
from ..task_manager import TaskStatus, task_manager

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
    """Create a grading task and run it in the background.

    Returns the task_id immediately so the client can track progress.
    """
    # Resolve LLM config
    config = LLMConfig(
        api_key=api_key or settings.openai_api_key,
        base_url=base_url or settings.openai_base_url,
        model_id=model_id or settings.openai_model_id,
    )

    if not config.api_key:
        return JSONResponse(
            status_code=400,
            content={"error": "请配置 API Key 后再试。"},
        )

    # Read uploaded files eagerly (before the request ends)
    rubric_bytes = await rubric_file.read()
    essays_bytes = await essays_file.read()
    rubric_name = rubric_file.filename or "rubric.docx"
    essays_name = essays_file.filename or "essays.docx"

    # Create task
    task = task_manager.create_task()

    # Launch background processing
    asyncio.create_task(
        _run_grading_pipeline(
            task.task_id,
            rubric_bytes, rubric_name,
            essays_bytes, essays_name,
            user_prompt, config,
        )
    )

    return {"task_id": task.task_id}


@router.get("/task/{task_id}")
async def get_task(task_id: str):
    """Get full task state including all events (for reconnection)."""
    task = task_manager.get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "任务不存在"})

    return {
        **task.to_summary(),
        "events": [{"timestamp": e.timestamp, "data": e.data} for e in task.events],
    }


@router.get("/task/{task_id}/stream")
async def stream_task(task_id: str, after: int = 0):
    """SSE stream for a task. Replays events from index `after`, then live-tails."""
    task = task_manager.get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "任务不存在"})

    return StreamingResponse(
        _task_sse_stream(task_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks")
async def list_tasks():
    """List recent tasks."""
    return {"tasks": task_manager.list_tasks()}


@router.post("/export/pdf")
async def export_report_pdf(request: Request):
    """Export a single report as PDF."""
    body = await request.json()
    md = body.get("markdown", "")
    title = body.get("title", "")
    author = body.get("author", "")
    if not md:
        return JSONResponse(status_code=400, content={"error": "缺少报告内容"})
    try:
        data = export_pdf(md, title=title, author=author)
    except Exception as exc:
        logger.exception("PDF export failed")
        return JSONResponse(status_code=500, content={"error": f"PDF 导出失败：{exc}"})
    filename = f"SAGE_批阅报告_{title or 'report'}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_encode_filename(filename)}"},
    )


@router.post("/export/docx")
async def export_report_docx(request: Request):
    """Export a single report as DOCX."""
    body = await request.json()
    md = body.get("markdown", "")
    title = body.get("title", "")
    author = body.get("author", "")
    if not md:
        return JSONResponse(status_code=400, content={"error": "缺少报告内容"})
    try:
        data = export_docx(md, title=title, author=author)
    except Exception as exc:
        logger.exception("DOCX export failed")
        return JSONResponse(status_code=500, content={"error": f"Word 导出失败：{exc}"})
    filename = f"SAGE_批阅报告_{title or 'report'}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_encode_filename(filename)}"},
    )


def _encode_filename(name: str) -> str:
    """Percent-encode a filename for Content-Disposition header."""
    from urllib.parse import quote
    return quote(name, safe="")


# ── Background pipeline ─────────────────────────────


async def _run_grading_pipeline(
    task_id: str,
    rubric_bytes: bytes,
    rubric_name: str,
    essays_bytes: bytes,
    essays_name: str,
    user_prompt: str,
    config: LLMConfig,
):
    """Run the full grading pipeline as a background task."""
    task = task_manager.get_task(task_id)
    if not task:
        return

    try:
        # --- Step 1: Parse files ---
        task.status = TaskStatus.PARSING
        _emit(task, "status", "正在解析上传的文件...")

        rubric_text = parse_file(rubric_bytes, rubric_name)
        essays_text = parse_file(essays_bytes, essays_name)

        rubric_chars = len(rubric_text)
        essays_chars = len(essays_text)
        _emit(task, "status",
              f"文件解析完成。评分细则 {rubric_chars} 字，作文文档 {essays_chars} 字。")
        logger.info("[Task %s] Parsed files: rubric=%d chars, essays=%d chars",
                    task_id, rubric_chars, essays_chars)

        # --- Step 2: Split essays ---
        task.status = TaskStatus.SPLITTING
        _emit(task, "status",
              f"正在识别和拆分 {essays_chars} 字的作文文档...")
        logger.info("[Task %s] Splitting %d chars of essay text...",
                    task_id, essays_chars)

        t0 = time.time()
        last_report = [0]  # chars at last progress report (mutable for closure)

        def on_split_chunk(total_chars: int, _chunk: str):
            """Emit progress events during LLM streaming to show tokens arriving."""
            if total_chars - last_report[0] >= 2000:
                elapsed = time.time() - t0
                _emit(task, "status",
                      f"AI 正在识别作文边界... "
                      f"已接收 {total_chars:,} 字符 | "
                      f"已耗时 {elapsed:.0f}s")
                last_report[0] = total_chars

        essays = await split_essays(essays_text, config, on_chunk=on_split_chunk)
        elapsed = time.time() - t0

        total = len(essays)
        task.total_essays = total
        method = "正则匹配" if elapsed < 1 else f"AI 分析（耗时 {elapsed:.1f}s）"
        _emit(task, "split_complete",
              f"拆分完成（{method}），成功识别出 {total} 篇作文。",
              total=total)
        logger.info("[Task %s] Split into %d essays in %.1fs",
                    task_id, total, elapsed)

        # --- Step 3: Grade each essay ---
        task.status = TaskStatus.GRADING

        for i, essay in enumerate(essays, 1):
            title = essay.get("title", f"作文 {i}")
            author = essay.get("author", "未知")
            task.current_essay = f"《{title}》（{author}）"
            task.graded_count = i - 1

            _emit(task, "grading",
                  f"正在批阅第 {i}/{total} 篇：《{title}》（{author}）...",
                  current=i, total=total)
            logger.info("[Task %s] Grading essay %d/%d: %s by %s",
                        task_id, i, total, title, author)

            try:
                t0 = time.time()
                report = await grade_essay(essay, rubric_text, user_prompt, config)
                elapsed = time.time() - t0

                _emit(task, "report",
                      f"第 {i}/{total} 篇批阅完成（耗时 {elapsed:.1f}s）",
                      current=i, total=total,
                      index=report.index, title=report.title,
                      author=report.author,
                      report_markdown=report.report_markdown)
                logger.info("[Task %s] Essay %d/%d graded in %.1fs",
                            task_id, i, total, elapsed)

            except Exception as exc:
                logger.exception("[Task %s] Error grading essay #%d", task_id, i)
                _emit(task, "report_error",
                      f"第 {i} 篇批阅失败：{exc}",
                      current=i, total=total,
                      title=title, author=author, error=str(exc))

        task.graded_count = total
        task.current_essay = ""
        task.status = TaskStatus.COMPLETED
        _emit(task, "complete", f"全部 {total} 篇作文批阅完成！")
        logger.info("[Task %s] All %d essays graded successfully", task_id, total)

    except Exception as exc:
        logger.exception("[Task %s] Pipeline failed", task_id)
        task.status = TaskStatus.FAILED
        task.error_message = str(exc)
        _emit(task, "error", f"任务失败：{exc}")


def _emit(task, event_type: str, message: str, **extra):
    """Record an event on the task."""
    data = {"type": event_type, "message": message, **extra}
    task.add_event(data)


# ── SSE streaming ────────────────────────────────────


async def _task_sse_stream(task_id: str, after: int):
    """Yield SSE events for a task, starting from event index `after`."""
    cursor = after

    while True:
        task = task_manager.get_task(task_id)
        if not task:
            yield _sse({"type": "error", "message": "任务不存在"})
            return

        # Emit any new events since cursor
        while cursor < len(task.events):
            evt = task.events[cursor]
            yield _sse(evt.data)
            cursor += 1

        # If the task is done, stop streaming
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            return

        # Wait briefly before checking for new events
        await asyncio.sleep(0.5)


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
