from __future__ import annotations

import pytest

from agents.developer import DeveloperAgent
from core.models import OutputType, ProjectBrief, Session, Task, TaskStatus


def _agent() -> DeveloperAgent:
    brief = ProjectBrief(
        title="T", description="d", output_type=OutputType.API,
        tech_stack=[], requirements=[], project_dir="/tmp/x",
    )
    return DeveloperAgent(Session(brief=brief))


# ── filename mapper ────────────────────────────────────────────────────────

def _task(title: str) -> Task:
    return Task(title=title, description="", status=TaskStatus.PENDING)


class TestFilenameMapper:
    def test_utils_utility(self):
        assert _agent()._resolve_filename(_task("Create short code utility")) == "utils.py"

    def test_utils_utilities(self):
        assert _agent()._resolve_filename(_task("Create utilities module")) == "utils.py"

    def test_utils_helper(self):
        assert _agent()._resolve_filename(_task("Create helper functions")) == "utils.py"

    def test_utils_helpers(self):
        assert _agent()._resolve_filename(_task("Create helpers")) == "utils.py"

    def test_utils_does_not_clobber_main(self):
        # "utility function endpoint" — utility wins because it appears first in the map
        # but a plain "Create FastAPI application" should still go to main.py
        assert _agent()._resolve_filename(_task("Create FastAPI application")) == "main.py"

    def test_database(self):
        assert _agent()._resolve_filename(_task("Create database configuration")) == "database.py"

    def test_schemas(self):
        assert _agent()._resolve_filename(_task("Create Pydantic schemas")) == "schemas.py"

    def test_crud(self):
        assert _agent()._resolve_filename(_task("Create CRUD operations")) == "crud.py"

    def test_readme(self):
        assert _agent()._resolve_filename(_task("Create README.md")) == "README.md"

    def test_unknown_returns_none(self):
        assert _agent()._resolve_filename(_task("Do something unknown")) is None


# ── fence stripping (existing behaviour, regression guard) ─────────────────

class TestFenceStripping:
    def test_python_fence(self):
        raw = "```python\nimport os\n```"
        assert _agent()._extract_code(raw, "main.py") == "import os\n"

    def test_plain_fence(self):
        raw = "```\nfastapi\nuvicorn\n```"
        assert _agent()._extract_code(raw, "requirements.txt") == "fastapi\nuvicorn\n"

    def test_no_fence(self):
        raw = "import os\nprint('hi')"
        assert _agent()._extract_code(raw, "main.py") == "import os\nprint('hi')\n"

    def test_trailing_fence_only(self):
        raw = "import os\n```"
        assert _agent()._extract_code(raw, "main.py") == "import os\n"


# ── prose stripping for .py files (new behaviour) ─────────────────────────

class TestProseStripping:
    def test_leading_prose_before_import(self):
        raw = (
            "The error is simply that fastapi is not installed. "
            "Please install it first.\n\n"
            "import os\nfrom fastapi import FastAPI\n"
        )
        result = _agent()._extract_code(raw, "main.py")
        assert result.startswith("import os")
        assert "The error" not in result

    def test_leading_prose_before_from_import(self):
        raw = "Here is the corrected file:\n\nfrom __future__ import annotations\nimport os\n"
        result = _agent()._extract_code(raw, "main.py")
        assert result.startswith("from __future__")
        assert "Here is" not in result

    def test_leading_prose_before_class(self):
        raw = "Sure, here is the class:\n\nclass Foo:\n    pass\n"
        result = _agent()._extract_code(raw, "models.py")
        assert result.startswith("class Foo")

    def test_leading_prose_before_def(self):
        raw = "Certainly!\n\ndef greet():\n    return 'hi'\n"
        result = _agent()._extract_code(raw, "utils.py")
        assert result.startswith("def greet")

    def test_leading_prose_before_hash_comment(self):
        raw = "Note: this file needs a shebang.\n\n#!/usr/bin/env python3\nimport sys\n"
        result = _agent()._extract_code(raw, "script.py")
        assert result.startswith("#!/usr/bin/env python3")

    def test_leading_prose_before_docstring(self):
        raw = 'Explanation goes here.\n\n"""Module docstring."""\nimport os\n'
        result = _agent()._extract_code(raw, "module.py")
        assert result.startswith('"""Module docstring.')

    def test_leading_prose_before_dunder(self):
        raw = "Here you go:\n\n__all__ = ['Foo']\nimport os\n"
        result = _agent()._extract_code(raw, "pkg.py")
        assert result.startswith("__all__")

    def test_no_prose_untouched(self):
        raw = "import os\nimport sys\n"
        result = _agent()._extract_code(raw, "main.py")
        assert result == "import os\nimport sys\n"

    def test_prose_strip_does_not_apply_to_non_py(self):
        """requirements.txt or README.md prose should NOT be stripped."""
        raw = "Here are the requirements:\nfastapi\nuvicorn\n"
        result = _agent()._extract_code(raw, "requirements.txt")
        assert "Here are the requirements" in result

    def test_prose_strip_does_not_apply_to_md(self):
        raw = "Here is the readme:\n# My Project\n"
        result = _agent()._extract_code(raw, "README.md")
        assert "Here is the readme" in result

    def test_fence_then_prose_stripped(self):
        """Fence removed first, then leading prose stripped from the result."""
        raw = "```python\nNote: install deps first.\n\nimport os\n```"
        result = _agent()._extract_code(raw, "main.py")
        assert result.startswith("import os")
        assert "Note:" not in result

    def test_entirely_prose_no_python_line(self):
        """If no Python line found, return content as-is (don't crash)."""
        raw = "This file has no Python in it at all."
        result = _agent()._extract_code(raw, "main.py")
        assert "no Python" in result
