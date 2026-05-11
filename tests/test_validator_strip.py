from __future__ import annotations

from pathlib import Path

import textwrap

from core.validator import _enum_class_names, _enum_members, _references_member_in_files, _strip_fences


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


# ── _enum_class_names ──────────────────────────────────────────────────────

class TestEnumClassNames:
    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_bare_enum_base(self, tmp_path):
        p = self._write(tmp_path, "m.py", "from enum import Enum\nclass Status(Enum):\n    A='a'\n")
        assert _enum_class_names(p) == ["Status"]

    def test_str_pydantic_enum_base(self, tmp_path):
        p = self._write(tmp_path, "m.py", "class T(str, PyEnum):\n    X='x'\n")
        assert _enum_class_names(p) == ["T"]

    def test_dotted_enum_base(self, tmp_path):
        p = self._write(tmp_path, "m.py", "import enum\nclass S(enum.Enum):\n    A=1\n")
        assert _enum_class_names(p) == ["S"]

    def test_non_enum_class_ignored(self, tmp_path):
        p = self._write(tmp_path, "m.py", "class Foo:\n    pass\n")
        assert _enum_class_names(p) == []

    def test_syntax_error_returns_empty(self, tmp_path):
        p = self._write(tmp_path, "m.py", "class (\n")
        assert _enum_class_names(p) == []


# ── _check_duplicate_enums ─────────────────────────────────────────────────

class TestCheckDuplicateEnums:
    def _make_validator(self, tmp_path: Path, files: dict[str, str]):
        from core.logger import Logger
        from core.models import OutputType, ProjectBrief, Session
        from core.validator import ProjectValidator
        for fname, content in files.items():
            p = tmp_path / fname
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        brief = ProjectBrief(
            title="T", description="d", output_type=OutputType.API,
            tech_stack=[], requirements=[], project_dir=str(tmp_path),
        )
        session = Session(brief=brief)
        return ProjectValidator(tmp_path, session, Logger(session.id))

    def test_duplicate_enum_models_schemas_detected(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "from enum import Enum\nclass MovementType(str, Enum):\n    RESTOCK='restock'\n    SELL='sell'\n",
            "schemas.py": "from enum import Enum\nclass MovementType(str, Enum):\n    RESTOCK='restock'\n    SELL='sell'\n",
        })
        errors = v._check_duplicate_enums()
        assert len(errors) == 1
        assert "MovementType" in errors[0]
        assert "models.py" in errors[0]
        assert "schemas.py" in errors[0]

    def test_single_definition_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "from enum import Enum\nclass MovementType(str, Enum):\n    RESTOCK='restock'\n",
            "schemas.py": "from models import MovementType\n",
        })
        errors = v._check_duplicate_enums()
        assert errors == []

    def test_error_message_contains_fix_hint(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "from enum import Enum\nclass Status(Enum):\n    A='a'\n",
            "schemas.py": "from enum import Enum\nclass Status(Enum):\n    A='a'\n",
        })
        errors = v._check_duplicate_enums()
        assert errors
        assert "import" in errors[0].lower()
        assert "models.py" in errors[0]

    def test_pycache_files_ignored(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "from enum import Enum\nclass T(Enum):\n    A=1\n",
        })
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "models.cpython-312.pyc").write_bytes(b"")
        errors = v._check_duplicate_enums()
        assert errors == []


# ── _enum_members ─────────────────────────────────────────────────────────────

class TestEnumMembers:
    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_members_with_string_values(self, tmp_path):
        p = self._write(tmp_path, "m.py", textwrap.dedent("""\
            from enum import Enum
            class MovementType(str, Enum):
                RESTOCK = 'restock'
                SALE = 'sale'
                ADJUSTMENT = 'adjustment'
        """))
        result = _enum_members(p)
        assert "MovementType" in result
        members = result["MovementType"]
        assert ("RESTOCK", "restock") in members
        assert ("SALE", "sale") in members
        assert ("ADJUSTMENT", "adjustment") in members

    def test_non_enum_class_ignored(self, tmp_path):
        p = self._write(tmp_path, "m.py", "class Foo:\n    bar = 1\n")
        assert _enum_members(p) == {}

    def test_dunder_members_skipped(self, tmp_path):
        p = self._write(tmp_path, "m.py", textwrap.dedent("""\
            from enum import Enum
            class S(Enum):
                __doc__ = 'ignored'
                ACTIVE = 'active'
        """))
        result = _enum_members(p)
        names = [n for n, _ in result.get("S", [])]
        assert "ACTIVE" in names
        assert "__doc__" not in names

    def test_syntax_error_returns_empty(self, tmp_path):
        p = self._write(tmp_path, "m.py", "class (\n")
        assert _enum_members(p) == {}

    def test_dotted_enum_base(self, tmp_path):
        p = self._write(tmp_path, "m.py", textwrap.dedent("""\
            import enum
            class Status(enum.Enum):
                OPEN = 'open'
        """))
        result = _enum_members(p)
        assert ("OPEN", "open") in result["Status"]


# ── _references_member_in_files ───────────────────────────────────────────────

class TestReferencesMemberInFiles:
    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_attribute_access_detected(self, tmp_path):
        f = self._write(tmp_path, "r.py", "x = MovementType.RESTOCK\n")
        assert _references_member_in_files([f], "RESTOCK", "restock") is True

    def test_string_value_detected(self, tmp_path):
        f = self._write(tmp_path, "r.py", 'movement_type = "restock"\n')
        assert _references_member_in_files([f], "RESTOCK", "restock") is True

    def test_case_insensitive_string_match(self, tmp_path):
        f = self._write(tmp_path, "r.py", 'mt = "RESTOCK"\n')
        assert _references_member_in_files([f], "RESTOCK", "restock") is True

    def test_no_reference_returns_false(self, tmp_path):
        f = self._write(tmp_path, "r.py", "x = 1\n")
        assert _references_member_in_files([f], "ADJUSTMENT", "adjustment") is False

    def test_empty_file_list_returns_false(self):
        assert _references_member_in_files([], "RESTOCK", "restock") is False

    def test_empty_member_value_skips_string_check(self, tmp_path):
        # member_value == "" → no string check, attribute check still works
        f = self._write(tmp_path, "r.py", 'x = ""\n')
        assert _references_member_in_files([f], "RESTOCK", "") is False

    def test_partial_string_does_not_match(self, tmp_path):
        # "restock_items" is not exactly "restock"
        f = self._write(tmp_path, "r.py", 'label = "restock_items"\n')
        assert _references_member_in_files([f], "RESTOCK", "restock") is False


# ── _check_dead_enum_variants ─────────────────────────────────────────────────

class TestCheckDeadEnumVariants:
    def _make_validator(self, tmp_path: Path, files: dict[str, str]):
        from core.logger import Logger
        from core.models import OutputType, ProjectBrief, Session
        from core.validator import ProjectValidator
        for fname, content in files.items():
            p = tmp_path / fname
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        brief = ProjectBrief(
            title="T", description="d", output_type=OutputType.API,
            tech_stack=[], requirements=[], project_dir=str(tmp_path),
        )
        session = Session(brief=brief)
        return ProjectValidator(tmp_path, session, Logger(session.id))

    def test_dead_adjustment_variant_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from enum import Enum
                class MovementType(str, Enum):
                    RESTOCK = 'restock'
                    SALE = 'sale'
                    ADJUSTMENT = 'adjustment'
            """),
            "routers.py": textwrap.dedent("""\
                from models import MovementType
                def restock_product():
                    return MovementType.RESTOCK
                def sell_product():
                    return MovementType.SALE
            """),
        })
        errors = v._check_dead_enum_variants()
        assert len(errors) == 1
        assert "ADJUSTMENT" in errors[0]
        assert "MovementType" in errors[0]

    def test_restock_sale_only_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from enum import Enum
                class MovementType(str, Enum):
                    RESTOCK = 'restock'
                    SALE = 'sale'
            """),
            "routers.py": textwrap.dedent("""\
                from models import MovementType
                def restock_product():
                    return MovementType.RESTOCK
                def sell_product():
                    return MovementType.SALE
            """),
        })
        errors = v._check_dead_enum_variants()
        assert errors == []

    def test_member_used_in_route_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from enum import Enum
                class MovementType(str, Enum):
                    ADJUSTMENT = 'adjustment'
            """),
            "crud.py": textwrap.dedent("""\
                from models import MovementType
                def adjust_stock():
                    return MovementType.ADJUSTMENT
            """),
        })
        errors = v._check_dead_enum_variants()
        assert errors == []

    def test_member_used_via_string_value_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from enum import Enum
                class MovementType(str, Enum):
                    RESTOCK = 'restock'
            """),
            "main.py": 'movement_type = "restock"\n',
        })
        errors = v._check_dead_enum_variants()
        assert errors == []

    def test_error_message_contains_required_fields(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from enum import Enum
                class Status(str, Enum):
                    DEAD = 'dead_value'
            """),
            "main.py": "x = 1\n",
        })
        errors = v._check_dead_enum_variants()
        assert errors
        msg = errors[0]
        # enum class name
        assert "Status" in msg
        # unused member name and value
        assert "DEAD" in msg
        assert "dead_value" in msg
        # files inspected
        assert "main.py" in msg
        # expected fix
        assert "remove" in msg.lower() or "fix" in msg.lower()

    def test_no_other_files_all_members_dead(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from enum import Enum
                class Color(Enum):
                    RED = 'red'
                    BLUE = 'blue'
            """),
        })
        errors = v._check_dead_enum_variants()
        member_names = {e.split(".")[1].split("'")[0].strip() for e in errors}
        assert "RED" in member_names
        assert "BLUE" in member_names

    def test_pycache_files_ignored(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from enum import Enum
                class MovementType(str, Enum):
                    RESTOCK = 'restock'
            """),
        })
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "models.cpython-312.pyc").write_bytes(b"")
        # pycache files ignored — RESTOCK is still dead (no other .py files)
        errors = v._check_dead_enum_variants()
        assert any("RESTOCK" in e for e in errors)
