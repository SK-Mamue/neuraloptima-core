from __future__ import annotations

import time
import traceback
from pathlib import Path

from core.agent_registry import registry as agent_registry
from core.llm import ask_claude, compute_cost
from core.logger import Logger
from core.models import Session, Task, TaskStatus, utc_now
from tools.filesystem import ensure_dir, read_file, write_file


SYSTEM_PROMPT = """\
You are a senior software engineer generating production-quality Python code.
Return ONLY the raw file content — no markdown fences, no explanation, no commentary.
The output will be written directly to a file.
"""

# (keywords, output filename) — matched against task TITLE only, first match wins
_FILENAME_MAP = [
    (["readme", "documentation"], "README.md"),
    (["requirements", "dependencies"], "requirements.txt"),
    (["gitignore"], ".gitignore"),
    (["schema", "pydantic"], "schemas.py"),
    (["database", "sqlite", "db", "initialization"], "database.py"),
    (["model", "sqlalchemy"], "models.py"),
    # main.py before crud.py: titles like "Build FastAPI app with CRUD endpoints" must
    # land in main.py, not crud.py. "error"/"exception" cross-cutting tasks also go here.
    (["main", "fastapi", "endpoint", "application", "error", "exception"], "main.py"),
    (["crud", "repository", "data access"], "crud.py"),
    (["test", "testing", "validation"], "TESTING.md"),
]

# Files worth injecting as context so Claude understands the project shape
_CONTEXT_FILES = ["requirements.txt", "schemas.py", "database.py", "models.py", "crud.py", "main.py"]


class DeveloperAgent:
    def __init__(self, session: Session):
        self.session = session
        self.logger = Logger(session.id)

    def run_task(self, task: Task) -> Task:
        task.status = TaskStatus.RUNNING
        task.started_at = utc_now()
        self.logger.info(event="task_started", detail=task.title,
                         extra={"assigned_agent": task.assigned_agent})

        project_dir = ensure_dir(self.session.brief.project_dir)
        filename = self._resolve_filename(task)

        if filename is None:
            task.result_summary = f"No filename mapping for task: {task.title}"
            task.status = TaskStatus.DONE
            task.completed_at = utc_now()
            task.duration_seconds = (task.completed_at - task.started_at).total_seconds()
            self.logger.warning(event="task_skipped", detail=task.title)
            return task

        last_exc: Exception | None = None
        last_tb: str = ""

        for attempt in range(task.max_retries + 1):
            task.attempts_made = attempt + 1
            try:
                prompt = self._build_prompt(task, filename, project_dir)
                raw, usage = ask_claude(prompt=prompt, system=SYSTEM_PROMPT)
                code = self._extract_code(raw)
                self._write(project_dir, filename, code, task)

                task.tokens_used["input_tokens"]  = (task.tokens_used.get("input_tokens",  0) + usage.input_tokens)
                task.tokens_used["output_tokens"] = (task.tokens_used.get("output_tokens", 0) + usage.output_tokens)
                self.session.total_cost_usd += compute_cost(usage)

                self.logger.info(
                    event="task_completed",
                    detail=task.title,
                    extra={
                        "file": filename,
                        "bytes": len(code),
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "attempt": attempt + 1,
                    },
                )
                last_exc = None
                break  # success

            except Exception as exc:
                last_exc = exc
                last_tb = traceback.format_exc()
                if attempt < task.max_retries:
                    delay = task.retry_delay_s * (2 ** attempt)
                    self.logger.warning(
                        event="task_retry",
                        detail=task.title,
                        extra={"attempt": attempt + 1, "of": task.max_retries + 1, "delay_s": delay},
                    )
                    time.sleep(delay)
                else:
                    self.logger.error(
                        event="task_failed",
                        detail=str(exc),
                        extra={"task": task.title, "attempts": task.attempts_made},
                    )

        if last_exc is not None:
            task.status = TaskStatus.FAILED
            task.error = last_tb
            task.completed_at = utc_now()
            task.duration_seconds = (task.completed_at - task.started_at).total_seconds()
            return task

        task.status = TaskStatus.DONE
        task.completed_at = utc_now()
        task.duration_seconds = (task.completed_at - task.started_at).total_seconds()
        return task

    # ------------------------------------------------------------------ #

    def _resolve_filename(self, task: Task) -> str | None:
        title = task.title.lower()
        for keywords, filename in _FILENAME_MAP:
            if any(kw in title for kw in keywords):
                return filename
        return None

    def _build_prompt(self, task: Task, filename: str, project_dir: Path) -> str:
        brief = self.session.brief
        context = self._collect_context(project_dir, filename)

        parts = [
            f"Project: {brief.title}",
            f"Description: {brief.description}",
            "",
            f"Task: {task.title}",
            f"Details: {task.description}",
            "",
        ]

        try:
            spec = agent_registry.get(task.assigned_agent)
            parts += [
                f"You are acting as: {spec.role}",
                f"Your focus: {spec.description}",
                f"Your capabilities: {', '.join(spec.capabilities)}",
                "",
            ]
        except KeyError:
            pass  # unknown agent — no extra context injected

        parts.append(f"Generate the file: {filename}")

        if context:
            parts.append("\nExisting project files for context:\n")
            for fname, content in context.items():
                parts.append(f"--- {fname} ---\n{content}\n")

        parts.append("\nReturn ONLY the raw file content. No markdown fences, no explanation.")
        return "\n".join(parts)

    def _collect_context(self, project_dir: Path, current_file: str) -> dict[str, str]:
        """Read already-generated sibling files so Claude has full project context."""
        context: dict[str, str] = {}
        for fname in _CONTEXT_FILES:
            if fname == current_file:
                continue
            path = project_dir / fname
            if path.exists():
                try:
                    context[fname] = read_file(str(path))
                except Exception:
                    pass
        return context

    def _extract_code(self, raw: str) -> str:
        """Strip any markdown code fences the model might have added despite instructions."""
        text = raw.strip()
        for fence in ("```python", "```txt", "```markdown", "```bash", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
                break
        if text.endswith("```"):
            text = text[:-3]
        return text.strip() + "\n"

    def _write(self, project_dir: Path, filename: str, content: str, task: Task) -> None:
        path = project_dir / filename
        write_file(str(path), content)
        task.files_created.append(str(path))
        task.result_summary = f"{filename} generated via LLM."
