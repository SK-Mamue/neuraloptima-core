from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from agents.developer import DeveloperAgent
from core.logger import Logger
from core.models import OutputType, ProjectBrief, Session, Task
from core.task_generator import generate_tasks_from_brief
from core.validator import ProjectValidator


def _topo_sort(tasks: list[Task]) -> list[Task]:
    """
    Kahn's algorithm over task titles.
    Falls back to original order if a cycle is detected or depends_on titles are unknown.
    """
    by_title = {t.title: t for t in tasks}

    # in-degree and reverse adjacency (who gets unblocked when this task finishes)
    in_degree: dict[str, int] = {t.title: 0 for t in tasks}
    unlocks: dict[str, list[str]] = {t.title: [] for t in tasks}

    for task in tasks:
        for dep in task.depends_on:
            if dep not in by_title:
                continue  # unknown dependency — ignore safely
            in_degree[task.title] += 1
            unlocks[dep].append(task.title)

    # seed queue with tasks that have no prerequisites
    queue: deque[Task] = deque(
        t for t in tasks if in_degree[t.title] == 0
    )
    result: list[Task] = []

    while queue:
        task = queue.popleft()
        result.append(task)
        for dependent_title in unlocks[task.title]:
            in_degree[dependent_title] -= 1
            if in_degree[dependent_title] == 0:
                queue.append(by_title[dependent_title])

    if len(result) != len(tasks):
        # cycle detected — fall back to original order
        return tasks

    return result


class Orchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.agent = DeveloperAgent(session)
        self._logger = Logger(session.id)

    def run(self) -> Session:
        self.session.tasks = _topo_sort(self.session.tasks)

        print("\n=== EXECUTION ORDER ===")
        for i, task in enumerate(self.session.tasks, 1):
            deps = f"  (after: {', '.join(task.depends_on)})" if task.depends_on else ""
            print(f"  {i}. {task.title}{deps}")
        print()

        for task in self.session.tasks:
            self.agent.run_task(task)

        self._validate_and_repair()

        self._print_timing_summary()
        self._print_cost_summary()

        self.session.complete()
        return self.session

    def _print_cost_summary(self) -> None:
        total_in  = sum(t.tokens_used.get("input_tokens",  0) for t in self.session.tasks)
        total_out = sum(t.tokens_used.get("output_tokens", 0) for t in self.session.tasks)
        cost = self.session.total_cost_usd

        print("=== COST SUMMARY ===")
        print(f"  Input tokens : {total_in:,}")
        print(f"  Output tokens: {total_out:,}")
        print(f"  Total cost   : ${cost:.4f}")
        print()

    def _print_timing_summary(self) -> None:
        W = 46  # title column width
        print("=== TIMING SUMMARY ===")
        task_total = 0.0
        for task in self.session.tasks:
            dur = task.duration_seconds or 0.0
            task_total += dur
            title = task.title if len(task.title) <= W else task.title[:W - 1] + "…"
            print(f"  {title:<{W}} {dur:>6.1f}s")

        val_dur = self.session.validation_duration_seconds
        if val_dur is not None:
            print(f"  {'Validation + repair':<{W}} {val_dur:>6.1f}s")

        grand_total = task_total + (val_dur or 0.0)
        print(f"  {'─' * (W + 9)}")
        print(f"  {'Total':<{W}} {grand_total:>6.1f}s")
        print()

    def _validate_and_repair(self) -> None:
        project_dir = Path(self.session.brief.project_dir).expanduser().resolve()
        validator = ProjectValidator(project_dir, self.session, self._logger)

        print("\n=== VALIDATION ===")
        t0 = time.monotonic()

        result = validator.run()

        if result.success:
            print("All checks passed.\n")
            self.session.add_log(event="validation", detail="passed")
            self.session.validation_duration_seconds = time.monotonic() - t0
            return

        print(f"Validation failed — attempting repair of {len(result.failed_files or ['main.py'])} file(s).\n")
        self.session.add_log(event="validation", detail="failed, repairing")

        repaired = validator.repair(result)
        self.session.validation_duration_seconds = time.monotonic() - t0

        if repaired.success:
            print("Repair succeeded — all checks pass.\n")
            self.session.add_log(event="repair", detail="succeeded")
        else:
            remaining = "\n".join(repaired.errors)
            print(f"Repair did not fully resolve errors:\n{remaining}\n")
            self.session.add_log(event="repair", detail="failed", level="warning")

    @classmethod
    def from_brief_file(cls, path: str) -> "Orchestrator":
        brief_text = Path(path).read_text(encoding="utf-8")
        first_line = brief_text.strip().splitlines()[0]
        title = first_line.replace("Build", "").strip().title() if first_line else "Generated Project"

        brief = ProjectBrief(
            title=title,
            description=brief_text,
            output_type=OutputType.API,
            tech_stack=[],
            requirements=[],
            project_dir="./projects/generated-project",
        )

        session = Session(brief=brief)
        session.tasks = generate_tasks_from_brief(brief_text)

        return cls(session)
