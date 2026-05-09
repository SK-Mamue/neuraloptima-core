from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class OutputType(str, Enum):
    API = "api"
    WEBSITE = "website"
    DASHBOARD = "dashboard"
    SCRAPER = "scraper"
    AUTOMATION = "automation"
    CRM = "crm"
    DEPLOYMENT = "deployment"
    OTHER = "other"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProjectBrief(BaseModel):
    id: str = Field(default_factory=lambda: new_id("brief"))
    title: str
    description: str
    output_type: OutputType = OutputType.OTHER
    tech_stack: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    project_dir: str
    created_at: datetime = Field(default_factory=utc_now)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    title: str
    description: str
    depends_on: list[str] = Field(default_factory=list)  # titles of tasks that must run first
    max_retries: int = 1        # extra attempts on transient failure (1 = 2 total attempts)
    retry_delay_s: float = 2.0  # initial sleep before first retry; doubles each attempt
    status: TaskStatus = TaskStatus.PENDING
    attempts_made: int = 0      # populated at runtime for observability
    result_summary: str = ""
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    error: str = ""
    assigned_agent: str = "developer"
    tokens_used: dict[str, int] = Field(default_factory=dict)  # input_tokens, output_tokens
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None


class LogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    level: str = "info"
    task_id: str | None = None
    event: str
    detail: str


class Session(BaseModel):
    id: str = Field(default_factory=lambda: new_id("session"))
    brief: ProjectBrief
    tasks: list[Task] = Field(default_factory=list)
    log: list[LogEntry] = Field(default_factory=list)
    git_commit_message: str = ""
    status: str = "running"
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    total_cost_usd: float = 0.0
    validation_duration_seconds: float | None = None

    def add_log(self, event: str, detail: str, level: str = "info", task_id: str | None = None) -> None:
        self.log.append(LogEntry(level=level, task_id=task_id, event=event, detail=detail))

    def complete(self) -> None:
        self.status = "completed"
        self.completed_at = utc_now()


def ensure_project_dir(path: str) -> Path:
    project_path = Path(path).expanduser().resolve()
    project_path.mkdir(parents=True, exist_ok=True)
    return project_path
