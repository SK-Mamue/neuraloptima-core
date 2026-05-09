from __future__ import annotations

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
    def bootstrap_demo_session(cls) -> "Orchestrator":
        brief = ProjectBrief(
            title="FastAPI Todo API",
            description="Simple FastAPI API with SQLite backend",
            output_type=OutputType.API,
            tech_stack=["fastapi", "sqlite"],
            requirements=[
                "Create FastAPI app",
                "Create requirements.txt",
                "Create README.md",
            ],
            project_dir="./projects/fastapi-todo-api",
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
                    description="Generate Python requirements file",
                ),
                Task(
                    title="Create app.py",
                    description="Generate FastAPI entrypoint",
                ),
            ]
        )

        return cls(session)
