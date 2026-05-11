from __future__ import annotations

import ast
import difflib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from core.llm import ask_claude, compute_cost
from core.logger import Logger
from core.models import Session
from core.tool_registry import registry
from tools.filesystem import read_file, write_file


REPAIR_SYSTEM = """\
You are a senior Python engineer fixing broken code.
Return ONLY the corrected file content — no markdown fences, no explanation.
The output will be written directly to the file.
"""

_TRACEBACK_FILE_RE = re.compile(r'File "([^"]+\.py)"')
_COMPILEALL_FILE_RE = re.compile(r"Compiling '([^']+\.py)'")


@dataclass
class ValidationResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    failed_files: list[Path] = field(default_factory=list)


class ProjectValidator:
    def __init__(self, project_dir: Path, session: Session, logger: Logger):
        self.project_dir = project_dir
        self.session = session
        self.logger = logger

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def run(self) -> ValidationResult:
        errors: list[str] = []
        failed: set[Path] = set()

        # 1) syntax check
        r = registry.run("python_compile", extra_args=[str(self.project_dir)])
        if not r.success:
            errors.append(f"compileall failed:\n{r.output.strip()}")
            failed.update(self._find_files(r.output))

        # 2) install project dependencies so the import check can resolve them
        req = self.project_dir / "requirements.txt"
        if req.exists():
            registry.run("pip_install_requirements", cwd=str(self.project_dir))

        # 3) import check (cwd = project dir so relative imports resolve)
        r = registry.run("app_import_check", cwd=str(self.project_dir))
        if not r.success:
            errors.append(f"import check failed:\n{r.output.strip()}")
            failed.update(self._find_files(r.output))

        # 4) duplicate enum check — deterministic; no LLM call needed
        for msg in self._check_duplicate_enums():
            errors.append(msg)
            # schemas.py is the file to repair (it should import, not redefine)
            schemas = self.project_dir / "schemas.py"
            if schemas.exists():
                failed.add(schemas)

        # 5) dead enum variant check — deterministic; no LLM call needed
        for msg in self._check_dead_enum_variants():
            errors.append(msg)
            # models.py is where enum definitions live; repair removes the dead member
            models = self.project_dir / "models.py"
            if models.exists():
                failed.add(models)

        # 6) numeric constraint check — deterministic; no LLM call needed
        for msg, src_file in self._check_numeric_constraints():
            errors.append(msg)
            if src_file.exists():
                failed.add(src_file)

        # 7) audit-trail bypass check — deterministic; no LLM call needed
        for msg, src_file in self._check_audit_trail_bypasses():
            errors.append(msg)
            if src_file.exists():
                failed.add(src_file)

        # 8) referential integrity check — deterministic; no LLM call needed
        for msg, src_file, extra_files in self._check_referential_integrity():
            errors.append(msg)
            if src_file.exists():
                failed.add(src_file)
            # Pattern 2 (field-rename) repairs require consistent changes across
            # models + schemas + CRUD — queue all files that reference the old field.
            for f in extra_files:
                if f.exists():
                    failed.add(f)

        if errors:
            self.logger.warning(
                event="validation_failed",
                detail=f"{len(errors)} check(s) failed",
                extra={"files": [str(f) for f in failed]},
            )
        else:
            self.logger.info(event="validation_passed", detail="all checks passed")

        return ValidationResult(
            success=not errors,
            errors=errors,
            failed_files=list(failed),
        )

    def repair(self, result: ValidationResult) -> ValidationResult:
        """Patch each broken file with Claude, then re-validate once."""
        targets = result.failed_files or [self.project_dir / "main.py"]

        for target in targets:
            if target.exists():
                self._repair_file(target, result.errors)

        return self.run()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _find_files(self, output: str) -> list[Path]:
        """Extract .py files from error output that live in project_dir."""
        found: set[Path] = set()
        for pattern in (_TRACEBACK_FILE_RE, _COMPILEALL_FILE_RE):
            for m in pattern.finditer(output):
                raw = Path(m.group(1))
                # absolute path already in project dir
                if raw.is_absolute() and raw.parent.resolve() == self.project_dir:
                    found.add(raw.resolve())
                # relative or just a name — try resolving against project dir
                candidate = (self.project_dir / raw.name).resolve()
                if candidate.exists():
                    found.add(candidate)
        return list(found)

    def _repair_file(self, target: Path, errors: list[str]) -> None:
        original = read_file(str(target))
        context = self._collect_context(target)
        error_block = "\n\n".join(errors)

        prompt = (
            f"The following Python file has errors.\n\n"
            f"File: {target.name}\n\n"
            f"```python\n{original}\n```\n\n"
            f"Errors:\n{error_block}\n"
        )
        if context:
            prompt += "\n\nOther project files for context:\n"
            for name, content in context.items():
                prompt += f"\n--- {name} ---\n{content}\n"
        prompt += "\n\nReturn ONLY the corrected file content. No markdown fences."

        self.logger.info(event="repair_attempt", detail=target.name)

        try:
            raw, usage = ask_claude(prompt=prompt, system=REPAIR_SYSTEM)
            fixed = _strip_fences(raw)
            self.session.total_cost_usd += compute_cost(usage)
            self.logger.info(
                event="repair_tokens",
                detail=target.name,
                extra={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens},
            )
        except Exception as exc:
            self.logger.error(event="repair_llm_error", detail=str(exc))
            return

        diff = _unified_diff(original, fixed, target.name)
        if diff:
            print(f"\n=== REPAIR DIFF: {target.name} ===\n{diff}")
            self.logger.info(event="repair_applied", detail=target.name, extra={"diff": diff[:800]})
            write_file(str(target), fixed)
        else:
            self.logger.warning(event="repair_no_change", detail=target.name)

    def _check_duplicate_enums(self) -> list[str]:
        """Return one error string per enum class name defined in more than one file."""
        _SKIP = {"__pycache__", ".venv", ".git"}
        locations: dict[str, list[str]] = defaultdict(list)
        for py_file in sorted(self.project_dir.rglob("*.py")):
            rel = py_file.relative_to(self.project_dir)
            if any(part in _SKIP for part in rel.parts):
                continue
            for name in _enum_class_names(py_file):
                locations[name].append(str(rel))

        errors = []
        for name, files in sorted(locations.items()):
            if len(files) > 1:
                locs = ", ".join(files)
                errors.append(
                    f"Duplicate enum '{name}' defined in multiple files: {locs}. "
                    f"Define it exactly once in models.py and import it everywhere else "
                    f"(e.g. 'from models import {name}' in schemas.py)."
                )
        return errors

    def _check_dead_enum_variants(self) -> list[str]:
        """Return one error string per enum member defined but never referenced in other files."""
        _SKIP = {"__pycache__", ".venv", ".git"}
        all_py: list[Path] = [
            f for f in sorted(self.project_dir.rglob("*.py"))
            if not any(part in _SKIP for part in f.relative_to(self.project_dir).parts)
        ]

        # First occurrence of each class name wins (duplicate check handles the rest)
        enum_defs: dict[str, tuple[Path, list[tuple[str, str]]]] = {}
        for py_file in all_py:
            for class_name, members in _enum_members(py_file).items():
                if class_name not in enum_defs:
                    enum_defs[class_name] = (py_file, members)

        errors: list[str] = []
        for class_name, (defining_file, members) in sorted(enum_defs.items()):
            other_files = [f for f in all_py if f.resolve() != defining_file.resolve()]
            rel_others = [str(f.relative_to(self.project_dir)) for f in other_files]

            for member_name, member_value in members:
                if _references_member_in_files(other_files, member_name, member_value):
                    continue
                errors.append(
                    f"Dead enum variant: '{class_name}.{member_name}' "
                    f"(value={member_value!r}) is defined in "
                    f"{defining_file.relative_to(self.project_dir)!s} "
                    f"but never referenced in any route handler, CRUD function, "
                    f"request schema, or business logic. "
                    f"Files inspected: {', '.join(rel_others) or 'none'}. "
                    f"Fix: remove '{class_name}.{member_name}' from "
                    f"{defining_file.relative_to(self.project_dir)!s}, "
                    f"or add a matching API endpoint or business logic path "
                    f"if the project brief requires it."
                )
        return errors

    def _check_numeric_constraints(self) -> list[tuple[str, Path]]:
        """
        Return (error_msg, file_path) pairs for numeric constraint violations in
        Pydantic schema fields and internal CRUD function parameters.
        """
        _SKIP = {"__pycache__", ".venv", ".git"}
        results: list[tuple[str, Path]] = []

        for py_file in sorted(self.project_dir.rglob("*.py")):
            rel = py_file.relative_to(self.project_dir)
            if any(part in _SKIP for part in rel.parts):
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            rel_str = str(rel)

            # --- Schema class field checks ---
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                # Skip read/response/out schemas — aggregates can legitimately be zero
                if any(node.name.lower().endswith(s) for s in _READ_SCHEMA_KEYWORDS):
                    continue
                for item in node.body:
                    if not isinstance(item, ast.AnnAssign):
                        continue
                    if not isinstance(item.target, ast.Name):
                        continue
                    field_name = item.target.id
                    if field_name not in _ALL_NUMERIC_FIELDS:
                        continue
                    if _is_optional_annotation(item.annotation):
                        continue
                    # PositiveInt/PositiveFloat already enforce gt=0 at the type level
                    if isinstance(item.annotation, ast.Name) and item.annotation.id in _POSITIVE_ANNOTATIONS:
                        continue

                    constraint = _field_numeric_constraint(item)
                    ctx = f"{rel_str} (class {node.name})"

                    if field_name in _GE0_OK_FIELDS:
                        if constraint in ("ge", "gt"):
                            continue
                        results.append((
                            f"Numeric constraint error in {ctx}: "
                            f"field '{field_name}' has no non-negative constraint "
                            f"(detected: none). "
                            f"Expected: Field(ge=0) — {field_name} can be zero but not negative. "
                            f"Fix: add Field(ge=0) to the field definition.",
                            py_file,
                        ))
                    else:
                        # _STRICT_GT0_FIELDS and _PRICE_FIELDS must be strictly positive
                        if constraint == "gt":
                            continue
                        if constraint == "ge":
                            results.append((
                                f"Numeric constraint error in {ctx}: "
                                f"field '{field_name}' uses Field(ge=0) "
                                f"but must use Field(gt=0) — "
                                f"{field_name} must be strictly positive (zero not allowed). "
                                f"Fix: change Field(ge=0) to Field(gt=0).",
                                py_file,
                            ))
                        else:
                            results.append((
                                f"Numeric constraint error in {ctx}: "
                                f"field '{field_name}' has no Field constraint "
                                f"(detected: none). "
                                f"Expected: Field(gt=0) — {field_name} must be strictly positive. "
                                f"Fix: add Field(gt=0) to the field definition.",
                                py_file,
                            ))

            # --- Internal function parameter checks (module-level only) ---
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _is_route_handler(node):
                    continue
                for arg in node.args.args:
                    if arg.arg not in _STRICT_GT0_FIELDS:
                        continue
                    ann = arg.annotation
                    if ann is None:
                        continue
                    if not (isinstance(ann, ast.Name) and ann.id in ("int", "float")):
                        continue
                    if _has_numeric_guard(node, arg.arg):
                        continue
                    results.append((
                        f"Numeric constraint error in {rel_str} "
                        f"(function {node.name}): "
                        f"parameter '{arg.arg}: {ann.id}' has no zero/negative guard "
                        f"(detected: none). "
                        f"Expected: guard rejecting values <= 0. "
                        f"Fix: add "
                        f"'if {arg.arg} <= 0: raise ValueError(\"{arg.arg} must be positive\")' "
                        f"at the start of the function.",
                        py_file,
                    ))
                    break  # one error per function is enough

        return results

    def _check_audit_trail_bypasses(self) -> list[tuple[str, Path]]:
        """
        Return (error_msg, file_path) pairs when audited/derived fields are mutated
        outside of dedicated movement/history endpoints.

        Two bypass patterns are detected:
        1. An Update/Patch schema contains an audited field (schema-level bypass).
        2. A generic update function directly assigns an audited field (code-level bypass).
        """
        _SKIP = {"__pycache__", ".venv", ".git"}
        all_py: list[Path] = [
            f for f in sorted(self.project_dir.rglob("*.py"))
            if not any(part in _SKIP for part in f.relative_to(self.project_dir).parts)
        ]

        # Discover history/movement model names across the whole project first.
        history_names: set[str] = set()
        for py_file in all_py:
            history_names.update(_history_model_names(py_file))

        if not history_names:
            return []  # No audit trail — nothing to check

        results: list[tuple[str, Path]] = []
        history_ctx = ", ".join(sorted(history_names))

        for py_file in all_py:
            rel_str = str(py_file.relative_to(self.project_dir))
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            # Pattern 1: Update/Patch schema contains an audited field.
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not any(node.name.lower().endswith(s) for s in ("update", "patch")):
                    continue
                for item in node.body:
                    if not isinstance(item, ast.AnnAssign):
                        continue
                    if not isinstance(item.target, ast.Name):
                        continue
                    field_name = item.target.id
                    if field_name not in _AUDITED_FIELDS:
                        continue
                    results.append((
                        f"Audit trail bypass in {rel_str} (class {node.name}): "
                        f"audited field '{field_name}' is present in an Update schema "
                        f"(detected: direct field inclusion). "
                        f"Stock/balance fields must only change through dedicated movement "
                        f"endpoints, not through generic update payloads. "
                        f"History model(s) detected: {history_ctx}. "
                        f"Fix: remove '{field_name}' from {node.name}; all mutations of "
                        f"this field must go through the dedicated movement/restock/sell "
                        f"endpoints that create a corresponding history record.",
                        py_file,
                    ))

            # Pattern 2: Generic update function directly assigns an audited field.
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not _is_generic_update_func(node.name):
                    continue
                for field_name in _AUDITED_FIELDS:
                    if not _assigns_field(node, field_name):
                        continue
                    results.append((
                        f"Audit trail bypass in {rel_str} (function {node.name}): "
                        f"directly assigns audited field '{field_name}' "
                        f"(detected: attribute assignment outside movement function). "
                        f"All mutations of stock/balance fields must go through dedicated "
                        f"movement functions that create a history record. "
                        f"History model(s) detected: {history_ctx}. "
                        f"Fix: remove the direct assignment of '{field_name}' from "
                        f"{node.name} and route all mutations through the dedicated "
                        f"movement/restock/sell endpoint.",
                        py_file,
                    ))
                    break  # one error per function

        return results

    def _check_referential_integrity(self) -> list[tuple[str, Path, list[Path]]]:
        """
        Return (error_msg, primary_file, extra_repair_targets) triples.

        extra_repair_targets is non-empty only for Pattern 2 (field-rename violations):
        those repairs require consistent changes across models + schemas + CRUD, so all
        files that reference the old field name are included in the repair scope.

        Pattern 1 — ORM class field ending in _id with no ForeignKey(...)
        Pattern 2 — ORM class field whose name matches an existing model class but is
                    stored as a plain String/Integer with no ForeignKey (field-rename)
        Pattern 3 — relationship("Target") where the expected FK column exists in the
                    same class but has no ForeignKey, or is entirely absent
        Pattern 4 — module-level association Table(...) columns ending in _id with no FK
        """
        _SKIP = {"__pycache__", ".venv", ".git"}
        all_py: list[Path] = [
            f for f in sorted(self.project_dir.rglob("*.py"))
            if not any(part in _SKIP for part in f.relative_to(self.project_dir).parts)
        ]

        # First pass: collect all ORM model class names across the project.
        orm_class_names: set[str] = set()
        for py_file in all_py:
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and any(
                    _is_orm_model_class_base(b) for b in node.bases
                ):
                    orm_class_names.add(node.name)

        if not orm_class_names:
            return []  # No ORM models — nothing to check

        results: list[tuple[str, Path, list[Path]]] = []

        for py_file in all_py:
            rel_str = str(py_file.relative_to(self.project_dir))
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            # Patterns 1–3: inspect ORM model class bodies
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if not any(_is_orm_model_class_base(b) for b in node.bases):
                    continue
                class_name = node.name

                # field_name → has_fk
                columns: dict[str, bool] = {}
                # (field_name, target_class_name)
                relationships: list[tuple[str, str]] = []

                for item in node.body:
                    if not isinstance(item, ast.Assign):
                        continue
                    for target in item.targets:
                        if not isinstance(target, ast.Name):
                            continue
                        field_name = target.id
                        if not isinstance(item.value, ast.Call):
                            continue
                        call = item.value

                        rel_target = _relationship_target(call)
                        if rel_target is not None:
                            relationships.append((field_name, rel_target))
                            continue

                        # Only process Column(...) assignments
                        func = call.func
                        if not (
                            (isinstance(func, ast.Name) and func.id == "Column") or
                            (isinstance(func, ast.Attribute) and func.attr == "Column")
                        ):
                            continue

                        has_fk = _column_call_has_fk(call)
                        col_type = _column_call_type(call)
                        columns[field_name] = has_fk

                        # Pattern 1: _id field with no ForeignKey — add FK in-place, no rename
                        if field_name.endswith("_id") and not has_fk and col_type in _FK_INTEGER_TYPES:
                            results.append((
                                f"Referential integrity error in {rel_str} "
                                f"(class {class_name}): "
                                f"field '{field_name}' appears to be a foreign key "
                                f"but is Column({col_type}) with no ForeignKey(...) "
                                f"(detected: plain {col_type} column, no referential constraint). "
                                f"Invalid IDs can be persisted and deletes will not cascade. "
                                f"Fix: change to "
                                f"Column({col_type}, ForeignKey(\"<table>.id\", ondelete=\"CASCADE\")).",
                                py_file,
                                [],  # no rename → only this file needs repair
                            ))

                        # Pattern 2: field name matches an existing model — FK field-rename
                        # This repair requires consistent changes in models + schemas + CRUD,
                        # so all files referencing the old field name are queued.
                        elif (
                            not has_fk
                            and col_type in ("String", "Integer", None)
                            and field_name.lower() in _FK_REFERENCE_NAMES
                        ):
                            matching_model = next(
                                (m for m in orm_class_names if m.lower() == field_name.lower()),
                                None,
                            )
                            if matching_model:
                                extra = _files_referencing_field(all_py, field_name, py_file)
                                results.append((
                                    f"Referential integrity error in {rel_str} "
                                    f"(class {class_name}): "
                                    f"field '{field_name}' is stored as "
                                    f"Column({col_type or 'String'}) "
                                    f"but a '{matching_model}' model exists in this project "
                                    f"(detected: plain column with no ForeignKey). "
                                    f"A plain {col_type or 'String'} column allows orphaned "
                                    f"references — no integrity constraint enforces that the "
                                    f"value matches a real {matching_model} row. "
                                    f"This fix requires consistent changes across ALL files: "
                                    f"(1) In {rel_str}: rename '{field_name}' to "
                                    f"'{field_name}_id = Column(Integer, ForeignKey("
                                    f"\"{matching_model.lower()}s.id\", ondelete=\"CASCADE\"))' "
                                    f"and add '{field_name} = relationship(\"{matching_model}\")'. "
                                    f"(2) In schemas: change '{field_name}: str' to "
                                    f"'{field_name}_id: int' in Create/Update schemas. "
                                    f"(3) In CRUD/route files: replace any reference to "
                                    f"'.{field_name}' with '.{field_name}_id' and join "
                                    f"{matching_model} when the human-readable name is needed.",
                                    py_file,
                                    extra,  # schemas.py + crud/*.py that reference old field
                                ))

                # Pattern 3: relationship where the FK column should be on this class — no rename
                for rel_field, rel_target in relationships:
                    # Only flag when field name equals target name (lowercase):
                    # product = relationship("Product") → this class owns the FK.
                    # movements = relationship("StockMovement") → parent side, no FK needed.
                    if rel_field.lower() != rel_target.lower():
                        continue
                    expected_fk = f"{rel_target.lower()}_id"
                    if expected_fk in columns:
                        if not columns[expected_fk]:
                            results.append((
                                f"Referential integrity error in {rel_str} "
                                f"(class {class_name}): "
                                f"relationship('{rel_target}') via '{rel_field}' "
                                f"is backed by column '{expected_fk}' "
                                f"but that column has no ForeignKey(...) "
                                f"(detected: Column without ForeignKey cannot resolve the join). "
                                f"Fix: add ForeignKey(\"{rel_target.lower()}s.id\") to the "
                                f"'{expected_fk}' column definition.",
                                py_file,
                                [],  # no rename → only this file needs repair
                            ))
                    else:
                        results.append((
                            f"Referential integrity error in {rel_str} "
                            f"(class {class_name}): "
                            f"relationship('{rel_target}') via '{rel_field}' "
                            f"has no matching '{expected_fk}' ForeignKey column "
                            f"(detected: relationship with no FK column in this class). "
                            f"SQLAlchemy requires a ForeignKey column to resolve the join. "
                            f"Fix: add "
                            f"'{expected_fk} = Column(Integer, ForeignKey(\"{rel_target.lower()}s.id\"))' "
                            f"to class {class_name}.",
                            py_file,
                            [],  # no rename → only this file needs repair
                        ))

            # Pattern 4: module-level association Table(...) assignments — no rename
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if not isinstance(node.value, ast.Call):
                    continue
                call = node.value
                func = call.func
                if not (
                    (isinstance(func, ast.Name) and func.id == "Table") or
                    (isinstance(func, ast.Attribute) and func.attr == "Table")
                ):
                    continue

                table_name = (
                    call.args[0].value
                    if call.args and isinstance(call.args[0], ast.Constant)
                    else "unknown"
                )
                var_name = next(
                    (t.id for t in node.targets if isinstance(t, ast.Name)),
                    str(table_name),
                )

                # Column(...) args start at index 2 (after table name + metadata)
                for arg in call.args[2:]:
                    if not isinstance(arg, ast.Call):
                        continue
                    arg_func = arg.func
                    if not (
                        (isinstance(arg_func, ast.Name) and arg_func.id == "Column") or
                        (isinstance(arg_func, ast.Attribute) and arg_func.attr == "Column")
                    ):
                        continue
                    if not arg.args or not isinstance(arg.args[0], ast.Constant):
                        continue
                    col_name = str(arg.args[0].value)
                    if not col_name.endswith("_id"):
                        continue
                    if _column_call_has_fk(arg):
                        continue
                    results.append((
                        f"Referential integrity error in {rel_str} "
                        f"(association table '{var_name}'): "
                        f"column '{col_name}' has no ForeignKey(...) "
                        f"(detected: plain Column without referential constraint). "
                        f"Association tables must use ForeignKey and ondelete=\"CASCADE\" "
                        f"so rows are removed when parent rows are deleted. "
                        f"Fix: change to Column(\"{col_name}\", Integer, "
                        f"ForeignKey(\"<table>.id\", ondelete=\"CASCADE\")).",
                        py_file,
                        [],  # no rename → only this file needs repair
                    ))

        return results

    def _collect_context(self, exclude: Path) -> dict[str, str]:
        context: dict[str, str] = {}
        for p in sorted(self.project_dir.glob("*.py")):
            if p.resolve() == exclude.resolve():
                continue
            try:
                context[p.name] = read_file(str(p))
            except Exception:
                pass
        return context


# ------------------------------------------------------------------ #
# Helpers (module-level, no state)
# ------------------------------------------------------------------ #

_ENUM_BASE_NAMES = frozenset({"Enum", "PyEnum", "IntEnum", "StrEnum", "Flag", "IntFlag"})


def _enum_class_names(path: Path) -> list[str]:
    """Return names of all classes that inherit from an Enum base in a .py file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            # bare name: Enum, PyEnum, IntEnum …
            if isinstance(base, ast.Name) and base.id in _ENUM_BASE_NAMES:
                names.append(node.name)
                break
            # attribute: enum.Enum, enum.IntEnum …
            if isinstance(base, ast.Attribute) and base.attr in _ENUM_BASE_NAMES:
                names.append(node.name)
                break
    return names


def _enum_members(path: Path) -> dict[str, list[tuple[str, str]]]:
    """Return {ClassName: [(MEMBER_NAME, value_str), ...]} for every enum class in a .py file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return {}
    result: dict[str, list[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_enum = False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in _ENUM_BASE_NAMES:
                is_enum = True
                break
            if isinstance(base, ast.Attribute) and base.attr in _ENUM_BASE_NAMES:
                is_enum = True
                break
        if not is_enum:
            continue
        members: list[tuple[str, str]] = []
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for target in item.targets:
                if not (isinstance(target, ast.Name) and not target.id.startswith("_")):
                    continue
                value = str(item.value.value) if isinstance(item.value, ast.Constant) else ""
                members.append((target.id, value))
        if members:
            result[node.name] = members
    return result


def _references_member_in_files(
    files: list[Path], member_name: str, member_value: str
) -> bool:
    """Return True if any file references the enum member by attribute access or string value."""
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            # EnumClass.MEMBER_NAME attribute access
            if isinstance(node, ast.Attribute) and node.attr == member_name:
                return True
            # Exact string constant matching the member value (e.g. "restock")
            if (
                member_value
                and isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.lower() == member_value.lower()
            ):
                return True
    return False


# ── Numeric constraint helpers ─────────────────────────────────────────────

# Fields whose request-schema use must be strictly positive (gt=0).
_STRICT_GT0_FIELDS = frozenset({"quantity", "amount"})
# Fields where ge=0 is acceptable (stock levels can be zero).
_GE0_OK_FIELDS = frozenset({"stock_quantity", "count", "balance"})
# Monetary / rate fields — must be gt=0 in non-read contexts.
_PRICE_FIELDS = frozenset({"price", "cost", "rate", "total", "subtotal"})
_ALL_NUMERIC_FIELDS = _STRICT_GT0_FIELDS | _GE0_OK_FIELDS | _PRICE_FIELDS
# Pydantic types that implicitly enforce gt=0 at the type level.
_POSITIVE_ANNOTATIONS = frozenset({"PositiveInt", "PositiveFloat"})
# Read/response schema name suffixes — aggregates may legitimately be zero.
_READ_SCHEMA_KEYWORDS = ("read", "response", "out")


def _field_numeric_constraint(assign: ast.AnnAssign) -> str | None:
    """
    Return 'gt', 'ge', or None for the numeric constraint in a Pydantic AnnAssign.
    None means: no Field() call, or Field() without a numeric bound.
    'gt' is also returned for Field(ge=N) when N > 0 (equivalent for integers).
    """
    if assign.value is None or not isinstance(assign.value, ast.Call):
        return None
    func = assign.value.func
    if not (
        (isinstance(func, ast.Name) and func.id == "Field")
        or (isinstance(func, ast.Attribute) and func.attr == "Field")
    ):
        return None
    for kw in assign.value.keywords:
        if kw.arg == "gt":
            return "gt"
        if kw.arg == "ge":
            # ge=1 is equivalent to gt=0 for integers — treat as gt
            if (
                isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, (int, float))
                and kw.value.value > 0
            ):
                return "gt"
            return "ge"
    return None


def _is_optional_annotation(ann: ast.expr) -> bool:
    """Return True for Optional[X], Union[X, None], or X | None annotations."""
    if isinstance(ann, ast.Subscript):
        if isinstance(ann.value, ast.Name) and ann.value.id in ("Optional", "Union"):
            return True
    if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
        left, right = ann.left, ann.right
        if isinstance(right, ast.Constant) and right.value is None:
            return True
        if isinstance(left, ast.Constant) and left.value is None:
            return True
    return False


def _is_route_handler(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function has an HTTP method decorator (@router.get, etc.)."""
    _HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
    for dec in func_node.decorator_list:
        node = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(node, ast.Attribute) and node.attr in _HTTP_METHODS:
            return True
    return False


def _compare_involves(cmp: ast.Compare, name: str) -> bool:
    """Return True if the Compare node directly references the named variable."""
    if isinstance(cmp.left, ast.Name) and cmp.left.id == name:
        return True
    return any(isinstance(c, ast.Name) and c.id == name for c in cmp.comparators)


def _has_numeric_guard(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, param_name: str
) -> bool:
    """Return True if the function body guards param_name against zero/negative values."""
    for node in ast.walk(func_node):
        # assert quantity > 0  /  assert quantity >= 1
        if isinstance(node, ast.Assert):
            if any(
                isinstance(child, ast.Compare) and _compare_involves(child, param_name)
                for child in ast.walk(node.test)
            ):
                return True
        # if quantity <= 0: raise ...  /  if quantity < 1: raise ...
        if isinstance(node, ast.If):
            cmp_found = any(
                isinstance(child, ast.Compare) and _compare_involves(child, param_name)
                for child in ast.walk(node.test)
            )
            if cmp_found and any(isinstance(s, (ast.Raise, ast.Return)) for s in node.body):
                return True
    return False


# ── Audit-trail bypass helpers ─────────────────────────────────────────────

# Fields whose values are derived exclusively from history/movement records.
_AUDITED_FIELDS = frozenset({
    "stock_quantity", "quantity_on_hand", "balance", "total_stock",
})

# Substrings that mark a class as a history/movement model.
_HISTORY_CLASS_KEYWORDS = frozenset({
    "movement", "auditlog", "inventorymovement", "transactionlog",
    "history", "audit", "transaction",
})

# Function name fragments that mark a function as a dedicated movement handler.
_MOVEMENT_FUNC_WORDS = frozenset({
    "restock", "sell", "refund", "movement", "stock_in", "stock_out",
    "adjust", "receive", "ship", "transfer", "add_stock", "remove_stock",
})

# Function name fragments that mark a function as a generic update handler.
_GENERIC_UPDATE_WORDS = frozenset({"update", "patch", "edit", "modify"})


def _history_model_names(path: Path) -> set[str]:
    """Return names of classes whose names contain history/movement keywords."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            lower = node.name.lower()
            if any(kw in lower for kw in _HISTORY_CLASS_KEYWORDS):
                names.add(node.name)
    return names


def _is_generic_update_func(func_name: str) -> bool:
    """Return True if the function name looks like a generic update (not a dedicated movement)."""
    lower = func_name.lower()
    if any(word in lower for word in _MOVEMENT_FUNC_WORDS):
        return False
    return any(word in lower for word in _GENERIC_UPDATE_WORDS)


def _assigns_field(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, field_name: str
) -> bool:
    """Return True if the function directly assigns or augments an attribute named field_name."""
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == field_name:
                    return True
        if isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Attribute) and node.target.attr == field_name:
                return True
    return False


# ── Referential integrity helpers ─────────────────────────────────────────────

# Field names that semantically suggest a FK to a related entity (no _id suffix).
_FK_REFERENCE_NAMES = frozenset({
    "category", "supplier", "product", "user", "order", "customer",
    "department", "vendor", "employee", "manager", "project", "tag",
    "group", "role", "author", "owner", "parent", "client", "account",
})

# Integer-like column types that should carry ForeignKey when ending in _id.
_FK_INTEGER_TYPES = frozenset({"Integer", "BigInteger", "SmallInteger"})

_ORM_BASE_NAMES = frozenset({"Base", "DeclarativeBase", "SQLModel"})


def _files_referencing_field(files: list[Path], field_name: str, exclude: Path) -> list[Path]:
    """Return all files (except exclude) that reference field_name via AST.

    Catches attribute access (obj.field_name), variable/annotation names, and
    string literals — the three common ways a renamed field appears in dependent files.
    """
    refs: list[Path] = []
    exclude_resolved = exclude.resolve()
    for py_file in files:
        if py_file.resolve() == exclude_resolved:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == field_name:
                refs.append(py_file)
                break
            if isinstance(node, ast.Name) and node.id == field_name:
                refs.append(py_file)
                break
            if isinstance(node, ast.Constant) and node.value == field_name:
                refs.append(py_file)
                break
    return refs


def _is_orm_model_class_base(base_node: ast.expr) -> bool:
    """Return True if a class base looks like a SQLAlchemy/SQLModel declarative base."""
    if isinstance(base_node, ast.Name):
        return base_node.id in _ORM_BASE_NAMES or base_node.id.endswith("Base")
    if isinstance(base_node, ast.Attribute):
        return base_node.attr in _ORM_BASE_NAMES or base_node.attr.endswith("Base")
    return False


def _column_call_has_fk(call_node: ast.Call) -> bool:
    """Return True if a Column(...) call contains a ForeignKey(...) positional argument."""
    for arg in call_node.args:
        if isinstance(arg, ast.Call):
            func = arg.func
            if (isinstance(func, ast.Name) and func.id == "ForeignKey") or (
                isinstance(func, ast.Attribute) and func.attr == "ForeignKey"
            ):
                return True
    return False


def _column_call_type(call_node: ast.Call) -> str | None:
    """Return the column type name from the first positional arg of Column(...)."""
    if not call_node.args:
        return None
    first = call_node.args[0]
    if isinstance(first, ast.Name):
        return first.id
    if isinstance(first, ast.Attribute):
        return first.attr
    if isinstance(first, ast.Call):
        func = first.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _relationship_target(call_node: ast.Call) -> str | None:
    """Return the target model name from a relationship(...) call, or None."""
    func = call_node.func
    if not (
        (isinstance(func, ast.Name) and func.id == "relationship") or
        (isinstance(func, ast.Attribute) and func.attr == "relationship")
    ):
        return None
    if (
        call_node.args
        and isinstance(call_node.args[0], ast.Constant)
        and isinstance(call_node.args[0].value, str)
    ):
        return call_node.args[0].value
    return None


# Matches the first line that looks like valid Python — used to drop leading
# prose the repair LLM may emit before the actual code.
_FIRST_PY_LINE_RE = re.compile(
    r"^(from |import |#|class |def |\"\"\"|\'\'\'"
    r"|__[a-z_]"
    r"|[A-Z_]{2,} *=)",
    re.MULTILINE,
)


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    for fence in ("```python", "```txt", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
            break
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    m = _FIRST_PY_LINE_RE.search(text)
    if m and m.start() > 0:
        text = text[m.start():]
    return text + "\n"


def _unified_diff(before: str, after: str, filename: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    ))
