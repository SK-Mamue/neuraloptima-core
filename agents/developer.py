from __future__ import annotations

from core.logger import Logger
from core.models import Session, Task, TaskStatus


class DeveloperAgent:
    def __init__(self, session: Session):
        self.session = session
        self.logger = Logger(session.id)

    def run_task(self, task: Task) -> Task:
        task.status = TaskStatus.RUNNING

        self.logger.info(
            event="task_started",
            detail=task.title,
        )

        task.result_summary = "Task placeholder executed."

        task.status = TaskStatus.DONE

        self.logger.info(
            event="task_completed",
            detail=task.title,
        )

        return task
