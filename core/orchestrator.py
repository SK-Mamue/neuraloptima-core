from __future__ import annotations

from pathlib import Path

from agents.developer import DeveloperAgent
from core.logger import Logger
from core.models import OutputType, ProjectBrief, Session
from core.task_generator import generate_tasks_from_brief
from core.validator import ProjectValidator


class Orchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.agent = DeveloperAgent(session)
        self._logger = Logger(session.id)

    def run(self) -> Session:
        for task in self.session.tasks:
            self.agent.run_task(task)

        self._validate_and_repair()

        self.session.complete()
        return self.session

    def _validate_and_repair(self) -> None:
        project_dir = Path(self.session.brief.project_dir).expanduser().resolve()
        validator = ProjectValidator(project_dir, self.session, self._logger)

        print("\n=== VALIDATION ===")
        result = validator.run()

        if result.success:
            print("All checks passed.\n")
            self.session.add_log(event="validation", detail="passed")
            return

        print(f"Validation failed — attempting repair of {len(result.failed_files or ['main.py'])} file(s).\n")
        self.session.add_log(event="validation", detail="failed, repairing")

        repaired = validator.repair(result)

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
