from __future__ import annotations

import pytest

from agents.developer import SYSTEM_PROMPT, DeveloperAgent
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
    # ── static map (flat files) ───────────────────────────────────────────

    def test_utils_utility(self):
        assert _agent()._resolve_filename(_task("Create short code utility")) == "utils.py"

    def test_utils_utilities(self):
        assert _agent()._resolve_filename(_task("Create utilities module")) == "utils.py"

    def test_utils_helper(self):
        assert _agent()._resolve_filename(_task("Create helper functions")) == "utils.py"

    def test_utils_helpers(self):
        assert _agent()._resolve_filename(_task("Create helpers")) == "utils.py"

    def test_database(self):
        assert _agent()._resolve_filename(_task("Create database configuration")) == "database.py"

    def test_schemas(self):
        assert _agent()._resolve_filename(_task("Create Pydantic schemas")) == "schemas.py"

    def test_readme(self):
        assert _agent()._resolve_filename(_task("Create README.md")) == "README.md"

    def test_main_wins_over_structural(self):
        # static map must win: "application" → main.py, even though "routes" is
        # also in the title and would otherwise trigger the routers/ subdir path
        assert _agent()._resolve_filename(_task("Create FastAPI application and routes")) == "main.py"

    def test_unknown_returns_none(self):
        assert _agent()._resolve_filename(_task("Do something unknown")) is None

    def test_structure_maps_to_gitignore(self):
        assert _agent()._resolve_filename(_task("Create project structure")) == ".gitignore"

    def test_structure_with_requirements_maps_to_requirements(self):
        # "requirements" must win over "structure" because it comes first in _FILENAME_MAP
        assert _agent()._resolve_filename(
            _task("Create project structure and requirements.txt")
        ) == "requirements.txt"

    # ── explicit .py path in title (flat and subdirectory) ───────────────

    def test_explicit_crud_py(self):
        assert _agent()._resolve_filename(_task("Implement crud.py")) == "crud.py"

    def test_explicit_database_py(self):
        assert _agent()._resolve_filename(_task("Implement database.py")) == "database.py"

    def test_explicit_utils_py(self):
        assert _agent()._resolve_filename(_task("Implement utils.py")) == "utils.py"

    def test_explicit_crud_subdir_path(self):
        # "Create crud/products.py" must preserve the subdirectory prefix.
        assert _agent()._resolve_filename(_task("Create crud/products.py")) == "crud/products.py"

    def test_explicit_routers_subdir_path(self):
        assert _agent()._resolve_filename(_task("Create routers/products.py")) == "routers/products.py"

    def test_explicit_flat_basename(self):
        assert _agent()._resolve_filename(_task("Implement products.py")) == "products.py"

    def test_traversal_path_returns_none(self):
        # "../evil.py" — the regex matches "evil" at position 3, but the text
        # before the match ("../") contains "..", so the whole match is rejected
        # and the function must return None (not "evil.py").
        assert _agent()._resolve_filename(_task("../evil.py")) is None

    def test_explicit_hyphenated_subdir_path(self):
        # Hyphens are valid in directory and file names.
        assert _agent()._resolve_filename(
            _task("Create api-routes/products.py")
        ) == "api-routes/products.py"

    # ── structural detection — no domain → flat fallback ─────────────────

    def test_crud_no_domain(self):
        assert _agent()._resolve_filename(_task("Create CRUD operations")) == "crud.py"

    def test_repository_no_domain(self):
        assert _agent()._resolve_filename(_task("Create repository layer")) == "crud.py"

    # ── structural detection — with domain → subdirectory ─────────────────

    def test_crud_categories(self):
        assert _agent()._resolve_filename(_task("Create categories CRUD operations")) == "crud/categories.py"

    def test_crud_expenses(self):
        assert _agent()._resolve_filename(_task("Create expenses CRUD operations")) == "crud/expenses.py"

    def test_crud_items(self):
        assert _agent()._resolve_filename(_task("Create items CRUD operations")) == "crud/items.py"

    def test_router_categories(self):
        assert _agent()._resolve_filename(_task("Create categories router")) == "routers/categories.py"

    def test_router_expenses(self):
        assert _agent()._resolve_filename(_task("Create expenses router")) == "routers/expenses.py"

    def test_router_users(self):
        assert _agent()._resolve_filename(_task("Create users router")) == "routers/users.py"

    def test_routes_categories(self):
        assert _agent()._resolve_filename(_task("Create categories routes")) == "routers/categories.py"

    def test_repository_users(self):
        assert _agent()._resolve_filename(_task("Create users repository")) == "crud/users.py"

    def test_endpoints_plural_does_not_map_to_main(self):
        # "endpoints" (plural) must NOT match the singular "endpoint" keyword in _FILENAME_MAP.
        # With both "crud" and "router" in the title, "router" (last match) wins → routers/.
        # Domain words are drawn from before "crud" (first subdir keyword): ["product"].
        assert _agent()._resolve_filename(
            _task("Implement product CRUD and stock endpoints router")
        ) == "routers/product.py"

    def test_endpoint_singular_still_maps_to_main(self):
        # "endpoint" as a standalone word still triggers the main.py static entry.
        assert _agent()._resolve_filename(
            _task("Create main application endpoint")
        ) == "main.py"


# ── _build_file_tree ───────────────────────────────────────────────────────

class TestBuildFileTree:
    def test_empty_dir(self, tmp_path):
        assert _agent()._build_file_tree(tmp_path) == ""

    def test_flat_files_listed(self, tmp_path):
        (tmp_path / "main.py").write_text("")
        (tmp_path / "database.py").write_text("")
        tree = _agent()._build_file_tree(tmp_path)
        assert "main.py" in tree
        assert "database.py" in tree

    def test_subdir_files_listed(self, tmp_path):
        (tmp_path / "crud").mkdir()
        (tmp_path / "crud" / "categories.py").write_text("")
        tree = _agent()._build_file_tree(tmp_path)
        assert "crud/categories.py" in tree or "crud\\categories.py" in tree

    def test_pycache_excluded(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "main.cpython-312.pyc").write_text("")
        tree = _agent()._build_file_tree(tmp_path)
        assert "__pycache__" not in tree

    def test_non_code_files_excluded(self, tmp_path):
        (tmp_path / "todos.db").write_text("")
        (tmp_path / "main.py").write_text("")
        tree = _agent()._build_file_tree(tmp_path)
        assert "todos.db" not in tree
        assert "main.py" in tree


# ── _build_prompt layout rules ─────────────────────────────────────────────

class TestBuildPromptLayoutRules:
    def _prompt(self, title: str = "Create main app", filename: str = "main.py",
                project_dir=None) -> str:
        from pathlib import Path
        import tempfile
        project_dir = project_dir or Path(tempfile.mkdtemp())
        agent = _agent()
        task = Task(title=title, description="build it", status=TaskStatus.PENDING)
        return agent._build_prompt(task, filename, project_dir)

    def test_no_app_prefix_rule_present(self):
        prompt = self._prompt()
        assert "app/" not in prompt.split("IMPORT RULES")[0]  # not before the rules section
        assert "NO 'app/' package" in prompt or "no 'app/' package" in prompt.lower()

    def test_import_examples_present(self):
        prompt = self._prompt()
        assert "from database import" in prompt
        assert "from crud.categories import" in prompt
        assert "from routers.categories import" in prompt

    def test_target_filename_in_prompt(self):
        prompt = self._prompt(filename="routers/expenses.py")
        assert "routers/expenses.py" in prompt

    def test_file_tree_included_when_files_exist(self, tmp_path):
        (tmp_path / "database.py").write_text("")
        (tmp_path / "schemas.py").write_text("")
        prompt = self._prompt(project_dir=tmp_path)
        assert "database.py" in prompt
        assert "schemas.py" in prompt

    def test_file_tree_absent_when_empty(self, tmp_path):
        prompt = self._prompt(project_dir=tmp_path)
        assert "Current project file tree" not in prompt

    def test_app_prefix_ignore_instruction_present(self):
        prompt = self._prompt()
        assert "app/" in prompt  # the rule *mentions* app/ to tell Claude to avoid it
        assert "ignore the 'app/' prefix" in prompt


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


# ── SYSTEM_PROMPT quality rules ────────────────────────────────────────────

class TestDeveloperSystemPrompt:
    def test_no_bare_return_rule(self):
        assert "bare 'return'" in SYSTEM_PROMPT

    def test_raise_http_exception_rule(self):
        assert "HTTPException" in SYSTEM_PROMPT

    def test_route_paths_match_brief_rule(self):
        assert "brief" in SYSTEM_PROMPT and "sku" in SYSTEM_PROMPT.lower()

    def test_static_before_parameterised_routes_rule(self):
        # Must mention ordering static routes before parameterised ones
        assert "/summary" in SYSTEM_PROMPT or "static route" in SYSTEM_PROMPT.lower()
        assert "/{" in SYSTEM_PROMPT

    def test_no_duplicate_routes_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "same" in lower and ("path" in lower or "method" in lower)

    def test_no_undocumented_features_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "draft" in lower or "unpublished" in lower

    def test_imports_match_real_files_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "import" in lower and "file tree" in lower

    def test_no_circular_schema_references_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "circular" in lower

    def test_atomic_db_writes_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "atomic" in lower or "one db.commit()" in lower or "single commit" in lower

    def test_no_string_order_by_rule(self):
        assert "order_by" in SYSTEM_PROMPT
        lower = SYSTEM_PROMPT.lower()
        assert "string literal" in lower or "string expression" in lower

    def test_datetime_utcnow_deprecated_rule(self):
        assert "utcnow" in SYSTEM_PROMPT
        assert "timezone.utc" in SYSTEM_PROMPT

    def test_no_aiosqlite_unless_async_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "aiosqlite" in lower

    def test_sku_immutable_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "immutable" in lower or "sku" in lower

    def test_integrity_error_handling_rule(self):
        assert "IntegrityError" in SYSTEM_PROMPT
        assert "409" in SYSTEM_PROMPT
        assert "rollback" in SYSTEM_PROMPT.lower()

    def test_schema_dependency_order_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "dependency order" in lower or "declared after" in lower

    def test_no_dead_enum_variants_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "enum" in lower and ("unused" in lower or "no route" in lower or "dead" in lower)

    def test_no_redundant_column_default_override_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "default" in lower and ("redundant" in lower or "manual" in lower or "do not also set" in lower)

    def test_no_unused_imports_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "unused import" in lower

    def test_quantity_field_ge_rule(self):
        assert "ge=0" in SYSTEM_PROMPT

    def test_price_field_gt_rule(self):
        assert "gt=0" in SYSTEM_PROMPT

    def test_audit_trail_no_direct_update_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "audit" in lower
        assert "movement" in lower or "derived" in lower

    def test_no_orm_dynamic_attribute_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "dynamic" in lower
        assert "refresh" in lower or "expires" in lower or "expire" in lower

    def test_cascade_delete_rule(self):
        assert "cascade" in SYSTEM_PROMPT
        assert "delete-orphan" in SYSTEM_PROMPT

    def test_sqlite_server_default_datetime_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "sqlite" in lower
        assert "server_default" in SYSTEM_PROMPT
        assert "func.now()" in SYSTEM_PROMPT

    def test_pydantic_v2_no_class_config_rule(self):
        assert "orm_mode" in SYSTEM_PROMPT
        assert "class Config" in SYSTEM_PROMPT

    def test_pydantic_v2_configdict_from_attributes_rule(self):
        assert "ConfigDict" in SYSTEM_PROMPT
        assert "from_attributes=True" in SYSTEM_PROMPT

    def test_pydantic_v2_model_dump_not_dict_rule(self):
        assert "model_dump()" in SYSTEM_PROMPT
        assert ".dict()" in SYSTEM_PROMPT

    def test_pydantic_v2_model_validate_not_from_orm_rule(self):
        assert "model_validate" in SYSTEM_PROMPT
        assert "from_orm" in SYSTEM_PROMPT

    def test_pydantic_v2_use_enum_values_rule(self):
        assert "use_enum_values" in SYSTEM_PROMPT

    def test_db_enum_column_type_rule(self):
        assert "Column(Enum(" in SYSTEM_PROMPT
        assert "Column(String)" in SYSTEM_PROMPT or "Column(String" in SYSTEM_PROMPT

    def test_db_enum_single_definition_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "one place" in lower or "never define the same enum twice" in lower or "shared" in lower

    def test_db_enum_sqlite_check_constraint_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "check constraint" in lower or "check" in lower
        assert "sqlite" in lower
