"""In-memory task manager for background grading jobs.

Tasks run independently of SSE connections, so users can close the browser
and come back later to see results.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    SPLITTING = "splitting"
    GRADING = "grading"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskEvent:
    """A single progress event stored in the task log."""
    timestamp: float
    data: dict


@dataclass
class GradingTask:
    """Represents a background grading job."""
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Progress
    total_essays: int = 0
    graded_count: int = 0
    current_essay: str = ""

    # Event log (SSE events stored for replay)
    events: list[TaskEvent] = field(default_factory=list)

    # Error
    error_message: str = ""

    def add_event(self, data: dict):
        """Append an event and update timestamp."""
        self.events.append(TaskEvent(timestamp=time.time(), data=data))
        self.updated_at = time.time()

    def to_summary(self) -> dict:
        """Return a lightweight summary (no full event log)."""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_essays": self.total_essays,
            "graded_count": self.graded_count,
            "current_essay": self.current_essay,
            "error_message": self.error_message,
        }


class TaskManager:
    """Manages background grading tasks in memory."""

    def __init__(self, max_tasks: int = 50):
        self._tasks: dict[str, GradingTask] = {}
        self._max_tasks = max_tasks

    def create_task(self) -> GradingTask:
        """Create a new task and return it."""
        # Evict old tasks if at capacity
        if len(self._tasks) >= self._max_tasks:
            oldest_id = min(self._tasks, key=lambda k: self._tasks[k].created_at)
            del self._tasks[oldest_id]

        task_id = uuid.uuid4().hex[:12]
        task = GradingTask(task_id=task_id)
        self._tasks[task_id] = task
        logger.info("Created task %s", task_id)
        return task

    def get_task(self, task_id: str) -> GradingTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[dict]:
        """Return summaries of all tasks, newest first."""
        tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return [t.to_summary() for t in tasks]


# Global singleton
task_manager = TaskManager()
