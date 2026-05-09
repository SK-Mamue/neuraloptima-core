from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Sequence

from pydantic import BaseModel


class Tool(BaseModel):
    name: str
    description: str
    command: list[str]           # base argv; extra_args are appended at run time
    working_dir: str | None = None  # default cwd; overridable per call


@dataclass
class ToolResult:
    tool_name: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        """Raw combined stdout + stderr (not stripped) for regex parsing."""
        return self.stdout + self.stderr


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Tool not registered: {name!r}")
        return self._tools[name]

    def run(
        self,
        name: str,
        extra_args: Sequence[str] = (),
        cwd: str | None = None,
    ) -> ToolResult:
        tool = self.get(name)
        cmd = tool.command + list(extra_args)
        effective_cwd = cwd or tool.working_dir

        r = subprocess.run(cmd, capture_output=True, text=True, cwd=effective_cwd)
        return ToolResult(
            tool_name=name,
            returncode=r.returncode,
            stdout=r.stdout,
            stderr=r.stderr,
        )

    def list(self) -> list[Tool]:
        return list(self._tools.values())


# ------------------------------------------------------------------ #
# Default registry
# ------------------------------------------------------------------ #

registry = ToolRegistry()

registry.register(Tool(
    name="python_compile",
    description="Check all .py files in a directory for syntax errors.",
    command=["python3", "-m", "compileall"],
))

registry.register(Tool(
    name="app_import_check",
    description="Verify the FastAPI app can be imported without errors.",
    command=["python3", "-c", "from main import app; print('import ok')"],
))

registry.register(Tool(
    name="pip_install_requirements",
    description="Install dependencies listed in requirements.txt.",
    command=["pip", "install", "-r", "requirements.txt", "-q"],
))
