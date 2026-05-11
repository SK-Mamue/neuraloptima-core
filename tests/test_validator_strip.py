from __future__ import annotations

from pathlib import Path

import textwrap

from core.validator import (
    _assigns_field,
    _column_call_has_fk,
    _column_call_type,
    _enum_class_names,
    _enum_members,
    _field_numeric_constraint,
    _files_referencing_field,
    _has_numeric_guard,
    _history_model_names,
    _is_generic_update_func,
    _is_list_response_model,
    _is_orm_model_class_base,
    _references_member_in_files,
    _relationship_target,
    _route_body_returns_dict,
    _route_body_returns_list,
    _strip_fences,
)


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


# ── _field_numeric_constraint ─────────────────────────────────────────────────

import ast as _ast


def _parse_assign(src: str) -> _ast.AnnAssign:
    """Parse a single annotated assignment and return the AnnAssign node."""
    tree = _ast.parse(src)
    return tree.body[0]


class TestFieldNumericConstraint:
    def test_gt0_returns_gt(self):
        node = _parse_assign("quantity: int = Field(gt=0)")
        assert _field_numeric_constraint(node) == "gt"

    def test_ge0_returns_ge(self):
        node = _parse_assign("quantity: int = Field(ge=0)")
        assert _field_numeric_constraint(node) == "ge"

    def test_ge1_treated_as_gt(self):
        # ge=1 is equivalent to gt=0 for integers
        node = _parse_assign("quantity: int = Field(ge=1)")
        assert _field_numeric_constraint(node) == "gt"

    def test_no_field_returns_none(self):
        node = _parse_assign("quantity: int")
        assert _field_numeric_constraint(node) is None

    def test_literal_default_returns_none(self):
        node = _parse_assign("quantity: int = 0")
        assert _field_numeric_constraint(node) is None

    def test_field_no_numeric_kw_returns_none(self):
        node = _parse_assign('quantity: int = Field(description="qty")')
        assert _field_numeric_constraint(node) is None


# ── _has_numeric_guard ────────────────────────────────────────────────────────

def _parse_func(src: str) -> _ast.FunctionDef:
    tree = _ast.parse(textwrap.dedent(src))
    return tree.body[0]


class TestHasNumericGuard:
    def test_if_lte_zero_raise_passes(self):
        fn = _parse_func("""\
            def f(quantity: int):
                if quantity <= 0:
                    raise ValueError("bad")
        """)
        assert _has_numeric_guard(fn, "quantity") is True

    def test_if_lt_one_raise_passes(self):
        fn = _parse_func("""\
            def f(quantity: int):
                if quantity < 1:
                    raise ValueError("bad")
        """)
        assert _has_numeric_guard(fn, "quantity") is True

    def test_assert_gt_zero_passes(self):
        fn = _parse_func("""\
            def f(quantity: int):
                assert quantity > 0
        """)
        assert _has_numeric_guard(fn, "quantity") is True

    def test_no_guard_fails(self):
        fn = _parse_func("""\
            def f(quantity: int):
                x = quantity + 1
        """)
        assert _has_numeric_guard(fn, "quantity") is False

    def test_guard_on_different_param_not_counted(self):
        fn = _parse_func("""\
            def f(quantity: int, price: float):
                if price <= 0:
                    raise ValueError("bad price")
        """)
        assert _has_numeric_guard(fn, "quantity") is False

    def test_if_without_raise_not_counted(self):
        fn = _parse_func("""\
            def f(quantity: int):
                if quantity <= 0:
                    quantity = 1
        """)
        assert _has_numeric_guard(fn, "quantity") is False


# ── _check_numeric_constraints ────────────────────────────────────────────────

class TestCheckNumericConstraints:
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

    # ── Required test cases ──────────────────────────────────────────────────

    def test_field_gt0_quantity_request_schema_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel, Field
                class RestockRequest(BaseModel):
                    quantity: int = Field(gt=0)
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert not any("quantity" in m for m in msgs)

    def test_field_ge0_quantity_request_schema_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel, Field
                class RestockRequest(BaseModel):
                    quantity: int = Field(ge=0)
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert any("quantity" in m and "ge=0" in m for m in msgs)

    def test_missing_field_on_amount_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class PaymentCreate(BaseModel):
                    amount: float
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert any("amount" in m for m in msgs)

    def test_missing_field_on_price_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class ProductCreate(BaseModel):
                    price: float
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert any("price" in m for m in msgs)

    def test_stock_quantity_ge0_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel, Field
                class ProductCreate(BaseModel):
                    stock_quantity: int = Field(ge=0)
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert not any("stock_quantity" in m for m in msgs)

    def test_internal_function_no_guard_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "crud.py": textwrap.dedent("""\
                def add_stock_movement(db, product_id, quantity: int):
                    product.stock_quantity += quantity
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert any("quantity" in m and "add_stock_movement" in m for m in msgs)

    def test_internal_function_with_guard_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "crud.py": textwrap.dedent("""\
                def add_stock_movement(db, product_id, quantity: int):
                    if quantity <= 0:
                        raise ValueError("quantity must be positive")
                    product.stock_quantity += quantity
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert not any("add_stock_movement" in m for m in msgs)

    # ── Additional edge cases ────────────────────────────────────────────────

    def test_optional_quantity_field_skipped(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                from typing import Optional
                class ProductUpdate(BaseModel):
                    quantity: Optional[int] = None
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert not any("quantity" in m for m in msgs)

    def test_read_schema_skipped(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class StockMovementRead(BaseModel):
                    quantity: int
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert not any("quantity" in m for m in msgs)

    def test_route_handler_skipped(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "routers.py": textwrap.dedent("""\
                async def restock(quantity: int):
                    pass
                restock.__wrapped__ = True
            """),
        })
        # Not decorated with @router.post → will be flagged; decorate it to skip
        v2 = self._make_validator(tmp_path, {
            "routers.py": textwrap.dedent("""\
                from fastapi import APIRouter
                router = APIRouter()
                @router.post("/restock")
                async def restock(quantity: int):
                    pass
            """),
        })
        msgs2 = [m for m, _ in v2._check_numeric_constraints()]
        assert not any("restock" in m for m in msgs2)

    def test_error_message_contains_required_fields(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel, Field
                class SellRequest(BaseModel):
                    quantity: int = Field(ge=0)
            """),
        })
        pairs = v._check_numeric_constraints()
        assert pairs
        msg, path = pairs[0]
        assert "schemas.py" in msg          # file path
        assert "SellRequest" in msg         # class name
        assert "quantity" in msg            # field name
        assert "ge=0" in msg               # detected constraint
        assert "gt=0" in msg               # expected constraint
        assert "fix" in msg.lower()        # fix instruction
        assert path.name == "schemas.py"   # correct file queued for repair

    def test_stock_quantity_no_field_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class ProductCreate(BaseModel):
                    stock_quantity: int
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert any("stock_quantity" in m for m in msgs)

    def test_price_gt0_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel, Field
                class ProductCreate(BaseModel):
                    price: float = Field(gt=0)
            """),
        })
        msgs = [m for m, _ in v._check_numeric_constraints()]
        assert not any("price" in m for m in msgs)

    def test_crud_file_queued_for_repair(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "crud/products.py": textwrap.dedent("""\
                def sell(db, quantity: int):
                    pass
            """),
        })
        pairs = v._check_numeric_constraints()
        assert pairs
        _, path = pairs[0]
        assert "products.py" in path.name


# ── _history_model_names / _is_generic_update_func / _assigns_field ───────────

class TestAuditHelpers:
    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_stock_movement_detected(self, tmp_path):
        p = self._write(tmp_path, "models.py", textwrap.dedent("""\
            class StockMovement:
                pass
        """))
        assert "StockMovement" in _history_model_names(p)

    def test_audit_log_detected(self, tmp_path):
        p = self._write(tmp_path, "models.py", "class AuditLog:\n    pass\n")
        assert "AuditLog" in _history_model_names(p)

    def test_non_history_class_ignored(self, tmp_path):
        p = self._write(tmp_path, "models.py", "class Product:\n    pass\n")
        assert _history_model_names(p) == set()

    def test_syntax_error_returns_empty(self, tmp_path):
        p = self._write(tmp_path, "m.py", "class (\n")
        assert _history_model_names(p) == set()

    def test_generic_update_func_detected(self):
        assert _is_generic_update_func("update_product") is True
        assert _is_generic_update_func("patch_item") is True

    def test_movement_func_not_generic(self):
        assert _is_generic_update_func("restock_product") is False
        assert _is_generic_update_func("sell_product") is False
        assert _is_generic_update_func("update_stock_movement") is False

    def test_assigns_field_direct_assign(self):
        fn = _parse_func("""\
            def update_product(db, product, data):
                product.stock_quantity = data.stock_quantity
        """)
        assert _assigns_field(fn, "stock_quantity") is True

    def test_assigns_field_augassign(self):
        fn = _parse_func("""\
            def update_product(db, product, qty):
                product.stock_quantity += qty
        """)
        assert _assigns_field(fn, "stock_quantity") is True

    def test_assigns_field_different_attr_false(self):
        fn = _parse_func("""\
            def update_product(db, product, data):
                product.name = data.name
        """)
        assert _assigns_field(fn, "stock_quantity") is False


# ── _check_audit_trail_bypasses ───────────────────────────────────────────────

class TestCheckAuditTrailBypasses:
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

    # ── Required test cases ──────────────────────────────────────────────────

    def test_update_schema_with_stock_quantity_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class StockMovement:\n    pass\n",
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                from typing import Optional
                class ProductUpdate(BaseModel):
                    name: Optional[str] = None
                    stock_quantity: Optional[int] = None
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        msgs = [m for m, _ in pairs]
        assert any("stock_quantity" in m and "ProductUpdate" in m for m in msgs)

    def test_update_schema_without_stock_quantity_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class StockMovement:\n    pass\n",
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                from typing import Optional
                class ProductUpdate(BaseModel):
                    name: Optional[str] = None
                    description: Optional[str] = None
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        assert pairs == []

    def test_generic_update_func_assigning_stock_quantity_fails(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class StockMovement:\n    pass\n",
            "crud.py": textwrap.dedent("""\
                def update_product(db, product, data):
                    product.stock_quantity = data.stock_quantity
                    db.commit()
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        msgs = [m for m, _ in pairs]
        assert any("stock_quantity" in m and "update_product" in m for m in msgs)

    def test_dedicated_restock_sell_passes(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class StockMovement:\n    pass\n",
            "crud.py": textwrap.dedent("""\
                def restock_product(db, product, qty):
                    product.stock_quantity += qty
                    db.add(StockMovement(quantity=qty))
                    db.commit()

                def sell_product(db, product, qty):
                    product.stock_quantity -= qty
                    db.add(StockMovement(quantity=qty))
                    db.commit()
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        assert pairs == []

    # ── Additional edge cases ────────────────────────────────────────────────

    def test_no_history_model_no_violations(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                from typing import Optional
                class ProductUpdate(BaseModel):
                    stock_quantity: Optional[int] = None
            """),
        })
        # No movement/history class exists → no audit trail to enforce
        pairs = v._check_audit_trail_bypasses()
        assert pairs == []

    def test_error_message_contains_required_fields(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class StockMovement:\n    pass\n",
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                from typing import Optional
                class ProductUpdate(BaseModel):
                    stock_quantity: Optional[int] = None
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        assert pairs
        msg, path = pairs[0]
        assert "schemas.py" in msg          # file path
        assert "ProductUpdate" in msg       # class name
        assert "stock_quantity" in msg      # field name
        assert "bypass" in msg.lower()      # detected pattern
        assert "fix" in msg.lower()         # expected fix
        assert path.name == "schemas.py"    # correct file queued

    def test_audit_log_model_triggers_check(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class AuditLog:\n    pass\n",
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                from typing import Optional
                class ExpenseUpdate(BaseModel):
                    balance: Optional[float] = None
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        assert any("balance" in m for m, _ in pairs)

    def test_patch_schema_suffix_also_caught(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class InventoryMovement:\n    pass\n",
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                from typing import Optional
                class ProductPatch(BaseModel):
                    stock_quantity: Optional[int] = None
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        assert any("ProductPatch" in m for m, _ in pairs)

    def test_crud_file_queued_for_repair(self, tmp_path):
        v = self._make_validator(tmp_path, {
            "models.py": "class StockMovement:\n    pass\n",
            "crud/products.py": textwrap.dedent("""\
                def update_product(db, product, data):
                    product.stock_quantity = data.stock_quantity
            """),
        })
        pairs = v._check_audit_trail_bypasses()
        assert pairs
        _, path = pairs[0]
        assert "products.py" in path.name


# ── _is_orm_model_class_base / _column_call_has_fk / _column_call_type / _relationship_target ──

import ast as _ast2


def _parse_class(src: str) -> _ast2.ClassDef:
    tree = _ast2.parse(textwrap.dedent(src))
    return tree.body[0]


def _parse_call(src: str) -> _ast2.Call:
    tree = _ast2.parse(src)
    return tree.body[0].value


class TestReferentialHelpers:
    def test_bare_base_detected(self):
        cls = _parse_class("class Product(Base):\n    pass\n")
        assert _is_orm_model_class_base(cls.bases[0]) is True

    def test_declarative_base_detected(self):
        cls = _parse_class("class Product(DeclarativeBase):\n    pass\n")
        assert _is_orm_model_class_base(cls.bases[0]) is True

    def test_name_ending_in_base_detected(self):
        cls = _parse_class("class Product(AppBase):\n    pass\n")
        assert _is_orm_model_class_base(cls.bases[0]) is True

    def test_plain_class_not_detected(self):
        # "BaseModel" → doesn't end in "Base" (it ends in "Model"), not in _ORM_BASE_NAMES
        cls = _parse_class("class Product(BaseModel):\n    pass\n")
        assert _is_orm_model_class_base(cls.bases[0]) is False

    def test_column_with_fk_detected(self):
        call = _parse_call("Column(Integer, ForeignKey('products.id'))")
        assert _column_call_has_fk(call) is True

    def test_column_without_fk_not_detected(self):
        call = _parse_call("Column(Integer)")
        assert _column_call_has_fk(call) is False

    def test_column_type_integer(self):
        call = _parse_call("Column(Integer)")
        assert _column_call_type(call) == "Integer"

    def test_column_type_string(self):
        call = _parse_call("Column(String)")
        assert _column_call_type(call) == "String"

    def test_column_type_callable_form(self):
        # Column(String(255), ...) — type is called
        call = _parse_call("Column(String(255))")
        assert _column_call_type(call) == "String"

    def test_column_type_empty_returns_none(self):
        call = _parse_call("Column(primary_key=True)")
        assert _column_call_type(call) is None

    def test_relationship_target_string_arg(self):
        call = _parse_call("relationship('Product')")
        assert _relationship_target(call) == "Product"

    def test_relationship_target_non_relationship_returns_none(self):
        call = _parse_call("Column(Integer)")
        assert _relationship_target(call) is None

    def test_relationship_target_no_string_arg_returns_none(self):
        call = _parse_call("relationship(back_populates='items')")
        assert _relationship_target(call) is None


# ── _check_referential_integrity ──────────────────────────────────────────────

class TestCheckReferentialIntegrity:
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

    # ── Required test cases ──────────────────────────────────────────────────

    def test_expense_category_plain_string_fails(self, tmp_path):
        """Expense.category stored as Column(String) when Category model exists → error."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, String
                from database import Base

                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                    name = Column(String)

                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category = Column(String)
            """),
        })
        pairs = v._check_referential_integrity()
        msgs = [m for m, *_ in pairs]
        assert any("category" in m and "Expense" in m for m in msgs)

    def test_product_id_with_fk_passes(self, tmp_path):
        """product_id = Column(Integer, ForeignKey(...)) → no error."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey
                from database import Base

                class StockMovement(Base):
                    __tablename__ = "stock_movements"
                    id = Column(Integer, primary_key=True)
                    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"))
            """),
        })
        pairs = v._check_referential_integrity()
        msgs = [m for m, *_ in pairs]
        assert not any("product_id" in m for m in msgs)

    def test_association_table_without_fk_fails(self, tmp_path):
        """Association Table(...) with Column without ForeignKey → error."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, Table
                from database import Base

                product_tags = Table(
                    "product_tags",
                    Base.metadata,
                    Column("product_id", Integer),
                    Column("tag_id", Integer),
                )

                class Product(Base):
                    __tablename__ = "products"
                    id = Column(Integer, primary_key=True)
            """),
        })
        pairs = v._check_referential_integrity()
        msgs = [m for m, *_ in pairs]
        assert any("product_id" in m and "product_tags" in m for m in msgs)
        assert any("tag_id" in m and "product_tags" in m for m in msgs)

    def test_association_table_with_fk_cascade_passes(self, tmp_path):
        """Association Table with ForeignKey + ondelete=CASCADE → no error."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey, Table
                from database import Base

                product_tags = Table(
                    "product_tags",
                    Base.metadata,
                    Column("product_id", Integer, ForeignKey("products.id", ondelete="CASCADE")),
                    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE")),
                )

                class Product(Base):
                    __tablename__ = "products"
                    id = Column(Integer, primary_key=True)
            """),
        })
        pairs = v._check_referential_integrity()
        msgs = [m for m, *_ in pairs]
        assert not any("product_tags" in m for m in msgs)

    def test_relationship_without_fk_column_fails(self, tmp_path):
        """relationship('Product') with product_id = Column(Integer) (no FK) → error."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer
                from sqlalchemy.orm import relationship
                from database import Base

                class StockMovement(Base):
                    __tablename__ = "stock_movements"
                    id = Column(Integer, primary_key=True)
                    product_id = Column(Integer)
                    product = relationship("Product")
            """),
        })
        pairs = v._check_referential_integrity()
        msgs = [m for m, *_ in pairs]
        assert any("product_id" in m or "relationship" in m.lower() for m in msgs)

    def test_valid_orm_relation_graph_passes(self, tmp_path):
        """Properly structured FK + relationship → no error."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey
                from sqlalchemy.orm import relationship
                from database import Base

                class Product(Base):
                    __tablename__ = "products"
                    id = Column(Integer, primary_key=True)
                    movements = relationship("StockMovement", back_populates="product")

                class StockMovement(Base):
                    __tablename__ = "stock_movements"
                    id = Column(Integer, primary_key=True)
                    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"))
                    product = relationship("Product", back_populates="movements")
            """),
        })
        pairs = v._check_referential_integrity()
        assert pairs == []

    # ── Additional edge cases ────────────────────────────────────────────────

    def test_no_orm_models_returns_empty(self, tmp_path):
        """No ORM model classes → check is skipped entirely."""
        v = self._make_validator(tmp_path, {
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class ExpenseCreate(BaseModel):
                    category: str
            """),
        })
        pairs = v._check_referential_integrity()
        assert pairs == []

    def test_supplier_id_without_fk_fails(self, tmp_path):
        """supplier_id = Column(Integer) with no ForeignKey → error (Pattern 1)."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer
                from database import Base

                class Product(Base):
                    __tablename__ = "products"
                    id = Column(Integer, primary_key=True)
                    supplier_id = Column(Integer)
            """),
        })
        pairs = v._check_referential_integrity()
        msgs = [m for m, *_ in pairs]
        assert any("supplier_id" in m and "Product" in m for m in msgs)

    def test_error_message_contains_required_fields(self, tmp_path):
        """Error message must contain file path, class name, field name, fix hint."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer
                from database import Base

                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    product_id = Column(Integer)
            """),
        })
        pairs = v._check_referential_integrity()
        assert pairs
        msg, path, _extra = pairs[0]
        assert "models.py" in msg          # file path
        assert "Expense" in msg            # class name
        assert "product_id" in msg         # field name
        assert "ForeignKey" in msg         # expected fix
        assert path.name == "models.py"    # correct file queued for repair

    def test_relationship_on_parent_side_not_flagged(self, tmp_path):
        """Product.movements = relationship('StockMovement') is the parent side — no FK needed."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer
                from sqlalchemy.orm import relationship
                from database import Base

                class Product(Base):
                    __tablename__ = "products"
                    id = Column(Integer, primary_key=True)
                    movements = relationship("StockMovement")
            """),
        })
        pairs = v._check_referential_integrity()
        # "movements" != "stockmovement" → Pattern 3 is not triggered
        assert pairs == []

    def test_relationship_with_no_id_column_at_all_fails(self, tmp_path):
        """product = relationship('Product') with no product_id column → error (Pattern 3b)."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer
                from sqlalchemy.orm import relationship
                from database import Base

                class StockMovement(Base):
                    __tablename__ = "stock_movements"
                    id = Column(Integer, primary_key=True)
                    product = relationship("Product")
            """),
        })
        pairs = v._check_referential_integrity()
        msgs = [m for m, *_ in pairs]
        assert any("product" in m and "StockMovement" in m for m in msgs)

    def test_pycache_files_ignored(self, tmp_path):
        """__pycache__ files are not scanned."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey
                from database import Base

                class Product(Base):
                    __tablename__ = "products"
                    id = Column(Integer, primary_key=True)
                    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
            """),
        })
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "models.cpython-312.pyc").write_bytes(b"")
        pairs = v._check_referential_integrity()
        assert pairs == []


# ── _files_referencing_field / FK repair scope ────────────────────────────────

class TestFilesReferencingField:
    def _write(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_attribute_access_detected(self, tmp_path):
        """obj.category attribute access → file included."""
        f = self._write(tmp_path, "crud.py", "def get(db): return db.query(Expense).filter(Expense.category == 'x').all()\n")
        models = self._write(tmp_path, "models.py", "x = 1\n")
        result = _files_referencing_field([f, models], "category", models)
        assert f in result
        assert models not in result

    def test_name_in_annotation_detected(self, tmp_path):
        """category: str annotation → file included."""
        f = self._write(tmp_path, "schemas.py", "class ExpenseCreate:\n    category: str\n")
        models = self._write(tmp_path, "models.py", "x = 1\n")
        result = _files_referencing_field([f, models], "category", models)
        assert f in result

    def test_string_literal_detected(self, tmp_path):
        """'category' string literal → file included."""
        f = self._write(tmp_path, "crud.py", 'data = {"category": expense.category}\n')
        models = self._write(tmp_path, "models.py", "x = 1\n")
        result = _files_referencing_field([f, models], "category", models)
        assert f in result

    def test_unrelated_file_excluded(self, tmp_path):
        """File with no mention of the field → not included."""
        f = self._write(tmp_path, "utils.py", "def helper():\n    return 42\n")
        models = self._write(tmp_path, "models.py", "x = 1\n")
        result = _files_referencing_field([f, models], "category", models)
        assert f not in result

    def test_exclude_file_not_in_result(self, tmp_path):
        """The exclude file itself is never returned, even if it references the field."""
        models = self._write(tmp_path, "models.py", "category = Column(String)\n")
        result = _files_referencing_field([models], "category", models)
        assert models not in result

    def test_syntax_error_file_skipped(self, tmp_path):
        """Unparseable file is silently skipped."""
        bad = self._write(tmp_path, "bad.py", "class (\n")
        models = self._write(tmp_path, "models.py", "x = 1\n")
        result = _files_referencing_field([bad, models], "category", models)
        assert bad not in result


class TestFKRepairScope:
    """Verify that Pattern 2 violations include all dependent files in repair targets."""

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

    def test_pattern2_includes_models_schemas_crud(self, tmp_path):
        """Expense.category violation queues models.py + schemas.py + crud/expenses.py."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, String
                from database import Base
                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category = Column(String)
            """),
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class ExpenseCreate(BaseModel):
                    category: str
                    amount: float
            """),
            "crud/expenses.py": textwrap.dedent("""\
                def get_expenses(db, category: str):
                    return db.query(Expense).filter(Expense.category == category).all()
            """),
        })
        pairs = v._check_referential_integrity()
        assert pairs, "Expected at least one FK violation"
        p2 = [(m, pf, ex) for m, pf, ex in pairs if "category" in m and "Expense" in m]
        assert p2, "Pattern 2 violation for Expense.category not found"
        _, primary, extra = p2[0]
        all_targets = {primary} | set(extra)
        names = {p.name for p in all_targets}
        assert "models.py" in names
        assert "schemas.py" in names
        assert "expenses.py" in names

    def test_pattern2_does_not_target_unrelated_files(self, tmp_path):
        """Files that don't reference the old field are excluded from repair scope."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, String
                from database import Base
                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category = Column(String)
            """),
            "utils.py": "def health_check():\n    return True\n",
        })
        pairs = v._check_referential_integrity()
        p2 = [(m, pf, ex) for m, pf, ex in pairs if "category" in m and "Expense" in m]
        assert p2
        _, _primary, extra = p2[0]
        extra_names = {p.name for p in extra}
        assert "utils.py" not in extra_names

    def test_valid_fk_model_returns_no_repair_targets(self, tmp_path):
        """category_id = Column(Integer, ForeignKey(...)) → no violation, no repair targets."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey
                from sqlalchemy.orm import relationship
                from database import Base
                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"))
                    category = relationship("Category")
            """),
        })
        pairs = v._check_referential_integrity()
        assert pairs == []

    def test_pattern1_extra_files_empty(self, tmp_path):
        """Pattern 1 (_id field without FK) does not expand repair scope."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer
                from database import Base
                class Product(Base):
                    __tablename__ = "products"
                    id = Column(Integer, primary_key=True)
                    supplier_id = Column(Integer)
            """),
            "schemas.py": "supplier_id = 1\n",
        })
        pairs = v._check_referential_integrity()
        p1 = [(m, pf, ex) for m, pf, ex in pairs if "supplier_id" in m]
        assert p1
        _, _primary, extra = p1[0]
        assert extra == []  # Pattern 1 is a local fix — no rename, no extra files

    def test_pattern2_error_message_covers_all_files(self, tmp_path):
        """Pattern 2 error message must explicitly instruct repair of schemas and CRUD."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, String
                from database import Base
                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category = Column(String)
            """),
        })
        pairs = v._check_referential_integrity()
        p2 = [(m, pf, ex) for m, pf, ex in pairs if "category" in m and "Expense" in m]
        assert p2
        msg, _, _ = p2[0]
        assert "category_id" in msg        # new field name stated
        assert "category" in msg           # old field name stated
        assert "schemas" in msg.lower()    # schemas mentioned
        assert "crud" in msg.lower() or "route" in msg.lower()  # CRUD/routes mentioned


# ── _is_list_response_model / _route_body_returns_* ──────────────────────────

import ast as _ast3


def _parse_expr(src: str) -> _ast3.expr:
    return _ast3.parse(src, mode="eval").body


class TestApiContractHelpers:
    def test_list_subscript_detected(self):
        node = _parse_expr("List[ItemRead]")
        assert _is_list_response_model(node) is True

    def test_lowercase_list_subscript_detected(self):
        node = _parse_expr("list[ItemRead]")
        assert _is_list_response_model(node) is True

    def test_plain_name_not_list(self):
        node = _parse_expr("ItemRead")
        assert _is_list_response_model(node) is False

    def test_optional_not_list(self):
        node = _parse_expr("Optional[ItemRead]")
        assert _is_list_response_model(node) is False

    def test_route_body_returns_dict_true(self):
        fn = _parse_func("""\
            async def get_items():
                return {}
        """)
        assert _route_body_returns_dict(fn) is True

    def test_route_body_returns_dict_false_for_list(self):
        fn = _parse_func("""\
            async def get_items():
                return []
        """)
        assert _route_body_returns_dict(fn) is False

    def test_route_body_returns_list_true(self):
        fn = _parse_func("""\
            async def get_item():
                return []
        """)
        assert _route_body_returns_list(fn) is True

    def test_route_body_returns_list_comprehension(self):
        fn = _parse_func("""\
            async def list_items():
                return [x for x in items]
        """)
        assert _route_body_returns_list(fn) is True

    def test_route_body_returns_list_false_for_dict(self):
        fn = _parse_func("""\
            async def get_item():
                return {}
        """)
        assert _route_body_returns_list(fn) is False


# ── _check_api_contract_consistency ──────────────────────────────────────────

class TestCheckApiContractConsistency:
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

    # ── Required test cases ──────────────────────────────────────────────────

    def test_integrity_error_raises_400_fails(self, tmp_path):
        """Route catches IntegrityError but raises 400 — should be 409 Conflict."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter, HTTPException
                from sqlalchemy.exc import IntegrityError
                router = APIRouter()
                @router.post("/items/", response_model=dict)
                async def create_item(db):
                    try:
                        db.commit()
                    except IntegrityError:
                        raise HTTPException(status_code=400, detail="Duplicate")
            """),
        })
        pairs = v._check_api_contract_consistency()
        msgs = [m for m, _ in pairs]
        assert any("400" in m and "409" in m for m in msgs)

    def test_delete_204_with_response_model_fails(self, tmp_path):
        """DELETE 204 + response_model is a contract contradiction."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter
                router = APIRouter()
                @router.delete("/items/{item_id}", status_code=204, response_model=dict)
                async def delete_item(item_id: int, db):
                    pass
            """),
        })
        pairs = v._check_api_contract_consistency()
        msgs = [m for m, _ in pairs]
        assert any("204" in m and "delete_item" in m for m in msgs)

    def test_post_without_response_model_fails(self, tmp_path):
        """CRUD-style POST route with no response_model declared."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter
                router = APIRouter()
                @router.post("/items/")
                async def create_item(db):
                    pass
            """),
        })
        pairs = v._check_api_contract_consistency()
        msgs = [m for m, _ in pairs]
        assert any("create_item" in m and "response_model" in m for m in msgs)

    def test_category_str_field_with_orm_category_id_fails(self, tmp_path):
        """Schema has category: str but ORM has category_id FK → mismatch."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey
                from database import Base
                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category_id = Column(Integer, ForeignKey("categories.id"))
            """),
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class ExpenseCreate(BaseModel):
                    category: str
                    amount: float
            """),
        })
        pairs = v._check_api_contract_consistency()
        msgs = [m for m, _ in pairs]
        assert any("category" in m and "category_id" in m for m in msgs)

    def test_valid_crud_api_contract_passes(self, tmp_path):
        """Well-formed CRUD routes with correct status codes and response_models."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter
                from typing import List
                router = APIRouter()
                @router.get("/items/", response_model=List[dict])
                async def list_items(db):
                    return []
                @router.post("/items/", response_model=dict, status_code=201)
                async def create_item(db):
                    return {}
                @router.delete("/items/{item_id}", status_code=204)
                async def delete_item(item_id: int, db):
                    pass
            """),
        })
        pairs = v._check_api_contract_consistency()
        assert pairs == []

    def test_list_route_returning_dict_fails(self, tmp_path):
        """list_items route returns dict literal — should return a list."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter
                router = APIRouter()
                @router.get("/items/")
                async def list_items(db):
                    return {}
            """),
        })
        pairs = v._check_api_contract_consistency()
        msgs = [m for m, _ in pairs]
        assert any("list_items" in m or "dict" in m.lower() for m in msgs)

    def test_single_route_returning_list_fails(self, tmp_path):
        """get_item route returns list literal — should return a single object."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter
                router = APIRouter()
                @router.get("/items/{item_id}", response_model=dict)
                async def get_item(item_id: int, db):
                    return []
            """),
        })
        pairs = v._check_api_contract_consistency()
        msgs = [m for m, _ in pairs]
        assert any("get_item" in m or "list" in m.lower() for m in msgs)

    # ── Additional edge cases ────────────────────────────────────────────────

    def test_post_204_fails(self, tmp_path):
        """POST with status_code=204 should be 200 or 201."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter
                router = APIRouter()
                @router.post("/items/", status_code=204)
                async def create_item(db):
                    pass
            """),
        })
        pairs = v._check_api_contract_consistency()
        msgs = [m for m, _ in pairs]
        assert any("204" in m and "create_item" in m for m in msgs)

    def test_delete_204_without_response_model_passes(self, tmp_path):
        """DELETE 204 with no response_model is valid (intended No Content)."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter
                router = APIRouter()
                @router.delete("/items/{item_id}", status_code=204)
                async def delete_item(item_id: int, db):
                    pass
            """),
        })
        pairs = v._check_api_contract_consistency()
        # DELETE 204 without response_model is fine
        assert not any("delete_item" in m for m, _ in pairs)

    def test_integrity_error_raises_409_passes(self, tmp_path):
        """Route correctly raises 409 for IntegrityError — no violation."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter, HTTPException
                from sqlalchemy.exc import IntegrityError
                router = APIRouter()
                @router.post("/items/", response_model=dict, status_code=201)
                async def create_item(db):
                    try:
                        db.commit()
                    except IntegrityError:
                        raise HTTPException(status_code=409, detail="Conflict")
            """),
        })
        pairs = v._check_api_contract_consistency()
        assert pairs == []

    def test_error_message_contains_required_fields(self, tmp_path):
        """Error message must include file path, route name, issue, and fix hint."""
        v = self._make_validator(tmp_path, {
            "routes.py": textwrap.dedent("""\
                from fastapi import APIRouter, HTTPException
                from sqlalchemy.exc import IntegrityError
                router = APIRouter()
                @router.post("/items/", response_model=dict)
                async def create_item(db):
                    try:
                        db.commit()
                    except IntegrityError:
                        raise HTTPException(status_code=400, detail="Bad")
            """),
        })
        pairs = v._check_api_contract_consistency()
        assert pairs
        msg, path = pairs[0]
        assert "routes.py" in msg       # file path
        assert "create_item" in msg     # route name
        assert "400" in msg             # detected issue
        assert "409" in msg             # expected fix
        assert path.name == "routes.py" # correct file queued

    def test_read_schema_with_category_str_not_flagged(self, tmp_path):
        """Response/Read schemas with category: str are not flagged (they may denote names)."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey
                from database import Base
                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category_id = Column(Integer, ForeignKey("categories.id"))
            """),
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class ExpenseRead(BaseModel):
                    category: str
            """),
        })
        pairs = v._check_api_contract_consistency()
        # ExpenseRead is a read schema — skipped
        assert not any("ExpenseRead" in m for m, _ in pairs)

    def test_summary_schema_with_category_str_not_flagged(self, tmp_path):
        """Aggregate/summary schemas (SummaryItem) with category: str are not flagged."""
        v = self._make_validator(tmp_path, {
            "models.py": textwrap.dedent("""\
                from sqlalchemy import Column, Integer, ForeignKey
                from database import Base
                class Category(Base):
                    __tablename__ = "categories"
                    id = Column(Integer, primary_key=True)
                class Expense(Base):
                    __tablename__ = "expenses"
                    id = Column(Integer, primary_key=True)
                    category_id = Column(Integer, ForeignKey("categories.id"))
            """),
            "schemas.py": textwrap.dedent("""\
                from pydantic import BaseModel
                class SummaryItem(BaseModel):
                    category: str
                    total: float
            """),
        })
        pairs = v._check_api_contract_consistency()
        # SummaryItem contains "summary" — skipped as a response/aggregate schema
        assert not any("SummaryItem" in m for m, _ in pairs)
