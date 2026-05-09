from __future__ import annotations

from pydantic import BaseModel


class AgentSpec(BaseModel):
    name: str
    role: str
    description: str
    capabilities: list[str]


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        self._agents[spec.name] = spec

    def get(self, name: str) -> AgentSpec:
        if name not in self._agents:
            raise KeyError(f"Agent not registered: {name!r}")
        return self._agents[name]

    def list(self) -> list[AgentSpec]:
        return list(self._agents.values())


# ------------------------------------------------------------------ #
# Default registry
# ------------------------------------------------------------------ #

registry = AgentRegistry()

registry.register(AgentSpec(
    name="planner",
    role="Task Planner",
    description="Breaks a project brief into an ordered list of concrete tasks.",
    capabilities=["brief_parsing", "task_decomposition", "dependency_ordering"],
))

registry.register(AgentSpec(
    name="developer",
    role="Code Generator",
    description="Implements individual tasks by generating source files via LLM.",
    capabilities=["code_generation", "file_writing", "context_injection"],
))

registry.register(AgentSpec(
    name="reviewer",
    role="Code Reviewer",
    description="Reviews generated code for correctness, style, and security issues.",
    capabilities=["code_review", "static_analysis", "feedback_generation"],
))

registry.register(AgentSpec(
    name="qa",
    role="QA Engineer",
    description="Validates generated projects by running compile checks and import tests.",
    capabilities=["syntax_validation", "import_check", "auto_repair"],
))

registry.register(AgentSpec(
    name="devops",
    role="DevOps Engineer",
    description="Manages dependencies, environment setup, and deployment configuration.",
    capabilities=["dependency_install", "env_config", "docker_support"],
))
