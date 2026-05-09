from __future__ import annotations

from pathlib import Path

from agents.developer import DeveloperAgent
from core.models import OutputType, ProjectBrief, Session, Task


class Orchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.agent = DeveloperAgent(session)

    def run(self) -> Session:
        for task in self.session.tasks:
            self.agent.run_task(task)

        self.session.complete()

        return self.session

    @classmethod
    def from_brief_file(cls, path: str) -> "Orchestrator":
        brief_text = Path(path).read_text(encoding="utf-8")

        title = "Generated Project"

        first_line = brief_text.strip().splitlines()[0]

        if first_line:
            title = first_line.replace("Build", "").strip().title()

        brief = ProjectBrief(
            title=title,
            description=brief_text,
            output_type=OutputType.API,
            tech_stack=["fastapi", "sqlite"],
            requirements=[
                "Create README.md",
                "Create requirements.txt",
                "Create app.py",
            ],
            project_dir="./projects/generated-project",
        )

        session = Session(brief=brief)

        session.tasks.extend(
            [
                Task(
                    title="Create README",
                    description="Generate project README",
                ),
                Task(
                    title="Create requirements.txt",
                    description="Generate requirements",
                ),
                Task(
                    title="Create app.py",
                    description="Generate FastAPI app",
                ),
            ]
        )

        return cls(session)
