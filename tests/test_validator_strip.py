from __future__ import annotations

from core.validator import _strip_fences


class TestStripFences:
    def test_plain_code(self):
        assert _strip_fences("import os\n") == "import os\n"

    def test_python_fence(self):
        assert _strip_fences("```python\nimport os\n```") == "import os\n"

    def test_plain_fence(self):
        assert _strip_fences("```\nimport os\n```") == "import os\n"

    def test_trailing_fence_only(self):
        assert _strip_fences("import os\n```") == "import os\n"


class TestProseStripping:
    def test_leading_prose_before_import(self):
        raw = (
            "The error is that `models.py` is missing. I need to create it.\n\n"
            "import os\nfrom fastapi import FastAPI\n"
        )
        result = _strip_fences(raw)
        assert result.startswith("import os")
        assert "The error" not in result

    def test_repair_lm_reasoning_stripped(self):
        """Simulates the exact failure seen in the URL shortener run."""
        raw = (
            "The error is that `models.py` is missing. I need to create it. "
            "But the task says to return the corrected `main.py` file. "
            "However, the actual issue is a missing `models.py` file, not an error in `main.py` itself.\n\n"
            "Since I can only return the corrected `main.py` and the error is about a missing "
            "`models.py`, I'll create the models.py content as the fix.\n\n"
            "from sqlalchemy import Column, Integer, String\n"
            "from database import Base\n\n"
            "class URL(Base):\n"
            "    __tablename__ = 'urls'\n"
        )
        result = _strip_fences(raw)
        assert result.startswith("from sqlalchemy")
        assert "The error" not in result
        assert "Since I can" not in result

    def test_leading_prose_before_class(self):
        raw = "Here is the corrected class:\n\nclass Foo:\n    pass\n"
        result = _strip_fences(raw)
        assert result.startswith("class Foo")

    def test_leading_prose_before_comment(self):
        raw = "Sure! Here you go:\n\n# module comment\nimport os\n"
        result = _strip_fences(raw)
        assert result.startswith("# module comment")

    def test_no_prose_untouched(self):
        raw = "from __future__ import annotations\nimport os\n"
        result = _strip_fences(raw)
        assert result == "from __future__ import annotations\nimport os\n"

    def test_fence_then_prose_stripped(self):
        raw = "```python\nNote: install deps first.\n\nimport os\n```"
        result = _strip_fences(raw)
        assert result.startswith("import os")
        assert "Note:" not in result

    def test_entirely_prose_no_python_line(self):
        raw = "This file has no Python code at all."
        result = _strip_fences(raw)
        assert "no Python" in result
