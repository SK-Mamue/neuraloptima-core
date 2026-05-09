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

_REVIEW_FILES = ["requirements.txt", "schemas.py", "database.py", "models.py", "crud.py", "main.py", "README.md"]
_REVIEW_SUBDIRS = ("crud", "routers")
_MAX_FILE_CHARS = 3_000  # per-file cap to stay under rate limits


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
                prompt=self._build_prompt(files),
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

    def _build_prompt(self, files: dict[str, str]) -> str:
        brief = self.session.brief
        parts = [
            f"Project: {brief.title}",
            f"Description: {brief.description}",
            "",
            "Review the following generated project files:",
            "",
        ]
        for fname, content in files.items():
            parts.append(f"--- {fname} ---\n{content}\n")

        parts += [
            "Return a JSON object with these exact fields:",
            '  "architecture_notes": [strings — architecture observations]',
            '  "bugs_found": [strings — obvious bugs or logic errors]',
            '  "missing_files": [strings — files that should exist but are absent]',
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
