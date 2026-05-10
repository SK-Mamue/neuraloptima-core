from __future__ import annotations

import json
import time
from pathlib import Path

from core.llm import ask_claude, compute_cost
from core.logger import Logger
from core.models import ReviewResult, Session


SYSTEM_PROMPT = """\
You are a senior code reviewer. Analyze the provided project files and return a JSON review.
Return ONLY valid JSON — no markdown fences, no explanation.
"""

_REVIEW_FILES = ["requirements.txt", "schemas.py", "database.py", "models.py", "utils.py", "crud.py", "main.py", "README.md"]
_REVIEW_SUBDIRS = ("crud", "routers")
_MAX_FILE_CHARS = 6_000  # per-file cap to stay under rate limits


class ReviewAgent:
    def __init__(self, session: Session):
        self.session = session
        self.logger = Logger(session.id)

    def review(self) -> ReviewResult:
        project_dir = Path(self.session.brief.project_dir).expanduser().resolve()
        files = self._collect_files(project_dir)

        if not files:
            result = ReviewResult(summary="No files to review.", severity="ok")
            self.session.review_result = result
            self.session.add_log(event="review", detail="skipped — no files")
            return result

        t0 = time.monotonic()
        try:
            raw, usage = ask_claude(
                prompt=self._build_prompt(files, project_dir),
                system=SYSTEM_PROMPT,
            )
            result = self._parse(raw)
            result.tokens_used = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
            }
            result.duration_seconds = time.monotonic() - t0
            self.session.total_cost_usd += compute_cost(usage)

            log_fn = (
                self.logger.error   if result.severity == "severe"  else
                self.logger.warning if result.severity == "warning" else
                self.logger.info
            )
            log_fn(
                event="review_completed",
                detail=result.summary,
                extra={"severity": result.severity},
            )
        except Exception as exc:
            result = ReviewResult(summary=f"Review failed: {exc}", severity="warning")
            result.duration_seconds = time.monotonic() - t0
            self.logger.error(event="review_failed", detail=str(exc))

        self.session.review_result = result
        self.session.add_log(event="review", detail=result.severity)
        return result

    # ------------------------------------------------------------------ #

    def _file_tree(self, project_dir: Path) -> str:
        _SKIP = {"__pycache__", ".git", ".venv", "manifest.json"}
        _EXTS = {".py", ".txt", ".md", ".env", ".cfg", ".toml", ".ini"}
        lines: list[str] = []
        for p in sorted(project_dir.rglob("*")):
            if any(part in _SKIP for part in p.relative_to(project_dir).parts):
                continue
            if p.is_file() and p.suffix in _EXTS:
                lines.append(f"  {p.relative_to(project_dir)}")
        return "\n".join(lines)

    def _collect_files(self, project_dir: Path) -> dict[str, str]:
        files: dict[str, str] = {}
        for fname in _REVIEW_FILES:
            path = project_dir / fname
            if path.exists():
                try:
                    files[fname] = self._read_capped(path)
                except Exception:
                    pass

        for subdir in _REVIEW_SUBDIRS:
            subpath = project_dir / subdir
            if not subpath.is_dir():
                continue
            for p in sorted(subpath.glob("*.py")):
                if p.name == "__init__.py":
                    continue
                key = f"{subdir}/{p.name}"
                try:
                    files[key] = self._read_capped(p)
                except Exception:
                    pass

        return files

    def _read_capped(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        if len(text) > _MAX_FILE_CHARS:
            text = text[:_MAX_FILE_CHARS] + f"\n... [truncated — {len(text)} chars total]"
        return text

    def _build_prompt(self, files: dict[str, str], project_dir: Path | None = None) -> str:
        brief = self.session.brief
        parts = [
            f"Project: {brief.title}",
            f"Description: {brief.description}",
            "",
        ]

        if project_dir is not None:
            tree = self._file_tree(project_dir)
            if tree:
                parts += [
                    "Complete list of files present in this project (ground truth — do NOT",
                    "report any file listed here as missing):",
                    tree,
                    "",
                ]

        parts += [
            "Review the following generated project files:",
            "",
        ]
        for fname, content in files.items():
            parts.append(f"--- {fname} ---\n{content}\n")

        parts += [
            "NOTE: Some files may end with '... [truncated — N chars total]'. This means",
            "the file content was cut off due to length limits. Do NOT report bugs, missing",
            "logic, or 'cannot verify' findings based solely on content that was not shown.",
            "Only report issues that are clearly visible in the provided excerpt.",
            "",
            "PYDANTIC API CONSISTENCY: Flag as a bug any file that mixes Pydantic v1 and",
            "v2 APIs. The following are v1 patterns that must NOT appear alongside v2 code:",
            "  - 'class Config: orm_mode = True'  (v2: model_config = ConfigDict(from_attributes=True))",
            "  - '.dict()'                         (v2: .model_dump())",
            "  - 'Model.from_orm(obj)'             (v2: Model.model_validate(obj))",
            "  - 'parse_obj()' / 'parse_raw()'    (v2: model_validate())",
            "Report a bug if any of these v1 patterns appear anywhere in the project files.",
            "",
            "DB ENUM ENFORCEMENT: Flag as a bug any SQLAlchemy model column that stores an",
            "enum value but is typed as String instead of Enum(MyEnum). A plain String column",
            "has no CHECK constraint and allows invalid values to be persisted. Also flag:",
            "  - Enum members defined in Python but not reflected in the DB column type",
            "  - DB column accepting values that the API schema rejects (or vice versa)",
            "  - The same enum defined twice with different names/values across files",
            "",
            "ENUM SINGLE-SOURCE-OF-TRUTH: Flag as a bug any project where the same enum",
            "class (e.g. MovementType, StatusEnum) is defined more than once across files.",
            "This includes identical-looking copies — two independent classes with matching",
            "values today will diverge over time, causing the DB and API to enforce different",
            "value sets silently. The canonical definition belongs in models.py; all other",
            "files must import from there. Flag if schemas.py defines its own copy of an enum",
            "that also appears in models.py, even if the values currently match.",
            "",
            "Return a JSON object with these exact fields:",
            '  "architecture_notes": [strings — architecture observations]',
            '  "bugs_found": [strings — obvious bugs or logic errors]',
            '  "missing_files": [strings — files that MUST exist for the project to work',
            '                    but are absent from the file list above]',
            '  "security_issues": [strings — security vulnerabilities]',
            '  "production_notes": [strings — production-readiness recommendations]',
            '  "severity": "ok" | "warning" | "severe"',
            '  "summary": "one-sentence overall assessment"',
            "",
            "severity: ok = no significant issues; warning = minor issues; severe = critical bugs or security vulnerabilities.",
        ]
        return "\n".join(parts)

    def _parse(self, raw: str) -> ReviewResult:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        data = json.loads(text.strip())
        return ReviewResult(
            architecture_notes=data.get("architecture_notes", []),
            bugs_found=data.get("bugs_found", []),
            missing_files=data.get("missing_files", []),
            security_issues=data.get("security_issues", []),
            production_notes=data.get("production_notes", []),
            severity=data.get("severity", "ok"),
            summary=data.get("summary", ""),
        )
