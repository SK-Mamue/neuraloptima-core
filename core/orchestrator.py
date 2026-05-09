from __future__ import annotations

from agents.developer import DeveloperAgent
from core.models import ProjectBrief, Session, Task


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
            title="Demo Project",
            description="Simple orchestration test",
            project_dir="./projects/demo-project",
        )

        session = Session(brief=brief)

        session.tasks.append(
            Task(
                title="Create initial project structure",
                description="Bootstrap folders and files",
            )
        )

        return cls(session)
