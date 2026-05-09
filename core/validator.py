from __future__ import annotations

import difflib
import re
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
