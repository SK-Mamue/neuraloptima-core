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
