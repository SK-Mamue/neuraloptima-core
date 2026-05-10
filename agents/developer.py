from __future__ import annotations

import re
import time
import traceback
from pathlib import Path

from core.agent_registry import registry as agent_registry
from core.llm import ask_claude, compute_cost
from core.logger import Logger
from core.models import Session, Task, TaskStatus, utc_now
from tools.filesystem import ensure_dir, read_file, write_file


SYSTEM_PROMPT = """\
You are a senior software engineer generating production-quality Python code.
Return ONLY the raw file content — no markdown fences, no explanation, no commentary.
The output will be written directly to a file.

PYTHON RULES — violations cause runtime errors and are never acceptable:
- Never shadow a type with a same-named field. If a Pydantic model needs a field
  called 'date', alias the import: `from datetime import date as Date` and annotate
  the field as `date: Date`. The same applies to 'id', 'type', 'list', 'dict', etc.

API QUALITY RULES — every violation causes a severe review failure:
- Never write a bare 'return' in a route handler. Every handler must explicitly
  return a response object, a Pydantic model instance, or raise an HTTPException.
- Raise HTTPException with the correct status code when a resource is not found
  (404) or an operation is invalid (400/409/422). Never return None silently.
- Route paths must match the project brief exactly. If the brief names a path
  parameter 'sku', use /{sku} — never substitute 'id' or 'product_id'.
- Register static routes (e.g. /summary, /count, /me) before parameterised routes
  (e.g. /{id}, /{sku}) in the same router so FastAPI resolves them correctly.
- Never define the same HTTP method + path pattern more than once in a router.
- Only implement features the brief explicitly requests. Do not add draft/
  unpublished filtering, soft-delete flags, or visibility controls unless stated.
- Derive every import from the actual file tree provided in the task prompt.
  Never invent module paths that do not correspond to a real generated file.
- Avoid circular Pydantic schema references. If two schemas reference each other,
  use a string forward reference or call model_rebuild() after both are defined.
- Multi-step DB writes in one endpoint must be atomic: perform all model changes
  first, then call db.commit() exactly once, then db.refresh() if needed. Never
  commit between two related writes (e.g. updating stock_quantity then inserting
  a StockMovement) — split commits leave the database inconsistent if the second
  write fails.
- Never use a string literal for SQLAlchemy relationship order_by. String
  expressions like order_by='Model.col.desc()' are silently ignored or raise
  errors at runtime. Use a real column expression imported from the model, or
  omit order_by and sort in the query instead.
- Never use datetime.utcnow(). It is deprecated in Python 3.12 and returns a
  naive datetime. Use datetime.now(timezone.utc) and import timezone from the
  datetime module.
- Do not add aiosqlite to requirements unless the project uses async SQLAlchemy
  (AsyncSession / create_async_engine). A synchronous SQLAlchemy engine never
  needs aiosqlite.
- SKU (and any other natural-key identifier specified in the brief) must be
  immutable after creation. Do not include sku in Update schemas (e.g.
  ProductUpdate) unless the brief explicitly allows SKU changes.
- Wrap db.commit() for unique-resource creation in try/except IntegrityError.
  On IntegrityError: call db.rollback(), then raise HTTPException(status_code=409,
  detail="...already exists"). Never let a SQLAlchemy IntegrityError propagate as
  an unhandled 500. Import IntegrityError from sqlalchemy.exc.
- Declare Pydantic schemas in dependency order: a schema that references another
  schema (e.g. via a List[OtherSchema] field) must be declared AFTER the schema
  it references. Only use string forward references (e.g. List['OtherSchema'])
  when a true mutual reference makes ordering impossible. Call model_rebuild()
  only when unavoidable, and always place the call after ALL schemas are defined.
- Only add enum values that have a corresponding route or are explicitly required
  by the brief. Do not add enum variants "for completeness" — unused enum values
  that have no route are a dead-code bug. If the brief lists specific movement
  types, add exactly those and no others.
- If a SQLAlchemy column already has a server-side or Python-side default (e.g.
  default=datetime.now(timezone.utc)), do not also set that field manually in
  CRUD functions. Redundant manual assignments shadow the column default and
  create inconsistency if the default changes.
- Remove every unused import before returning the file. An import is unused if
  nothing in the file references it. Common offenders: field_validator, List,
  Optional, Tuple when the typing module equivalents are not used.
"""

# Static map — checked first; first match wins.
# "crud" and "repository" are intentionally absent: they are handled by
# _SUBDIR_MAP so that "Create categories CRUD" → crud/categories.py instead
# of always overwriting the same crud.py.
_FILENAME_MAP = [
    (["readme", "documentation"], "README.md"),
    (["requirements", "dependencies"], "requirements.txt"),
    (["gitignore"], ".gitignore"),
    # "Create project structure" → generate .gitignore (useful artifact, always missing).
    # Must come after "requirements" so "Create project structure and requirements.txt"
    # still lands on requirements.txt.
    (["structure", "scaffold", "layout"], ".gitignore"),
    (["schema", "pydantic"], "schemas.py"),
    (["database", "sqlite", "db", "initialization"], "database.py"),
    (["model", "sqlalchemy"], "models.py"),
    (["utility", "utilities", "helper", "helpers", "util"], "utils.py"),
    # main.py before the structural check: "Build FastAPI app with CRUD endpoints"
    # must land in main.py, not crud/. "error"/"exception" tasks also go here.
    (["main", "fastapi", "endpoint", "application", "error", "exception"], "main.py"),
    (["data access"], "crud.py"),   # multi-word fallback kept here
    (["test", "testing", "validation"], "TESTING.md"),
]

# Structural keywords → subdirectory name.
# When a title word matches a key, the remaining non-stop words become the
# filename: "Create expenses CRUD operations" → crud/expenses.py
_SUBDIR_MAP: dict[str, str] = {
    "crud":         "crud",
    "repository":   "crud",
    "repositories": "crud",
    "router":       "routers",
    "routers":      "routers",
    "route":        "routers",
    "routes":       "routers",
}

# Words discarded when extracting the domain component from a task title
_TITLE_STOP_WORDS: frozenset[str] = frozenset({
    "create", "add", "implement", "build", "define", "generate", "write", "set", "setup",
    "and", "the", "a", "an", "for", "with", "of", "to", "in", "on",
    "crud", "repository", "repositories", "router", "routers", "route", "routes",
    "operations", "operation", "functions", "function", "module",
    "handler", "handlers", "endpoints", "endpoint",
    "configuration", "config", "class", "classes", "layer", "service", "services",
})

# Files worth injecting as context so Claude understands the project shape
_CONTEXT_FILES = ["requirements.txt", "schemas.py", "database.py", "models.py", "utils.py", "crud.py", "main.py"]

# Matches the first line that looks like valid Python — used to drop leading prose in .py output.
_FIRST_PY_LINE_RE = re.compile(
    r"^(from |import |#|class |def |\"\"\"|\'\'\'"
    r"|__[a-z_]"        # __all__, __future__, etc.
    r"|[A-Z_]{2,} *=)", # module-level constants, e.g. BASE_URL =
    re.MULTILINE,
)


class DeveloperAgent:
    def __init__(self, session: Session):
        self.session = session
        self.logger = Logger(session.id)

    def run_task(self, task: Task) -> Task:
        task.status = TaskStatus.RUNNING
        task.started_at = utc_now()
        self.logger.info(event="task_started", detail=task.title,
                         extra={"assigned_agent": task.assigned_agent})

        project_dir = ensure_dir(self.session.brief.project_dir)
        filename = self._resolve_filename(task)

        if filename is None:
            task.result_summary = f"No filename mapping for task: {task.title}"
            task.status = TaskStatus.DONE
            task.completed_at = utc_now()
            task.duration_seconds = (task.completed_at - task.started_at).total_seconds()
            self.logger.warning(event="task_skipped", detail=task.title)
            return task

        last_exc: Exception | None = None
        last_tb: str = ""

        for attempt in range(task.max_retries + 1):
            task.attempts_made = attempt + 1
            try:
                prompt = self._build_prompt(task, filename, project_dir)
                raw, usage = ask_claude(prompt=prompt, system=SYSTEM_PROMPT)
                code = self._extract_code(raw, filename)
                self._write(project_dir, filename, code, task)

                task.tokens_used["input_tokens"]  = (task.tokens_used.get("input_tokens",  0) + usage.input_tokens)
                task.tokens_used["output_tokens"] = (task.tokens_used.get("output_tokens", 0) + usage.output_tokens)
                self.session.total_cost_usd += compute_cost(usage)

                self.logger.info(
                    event="task_completed",
                    detail=task.title,
                    extra={
                        "file": filename,
                        "bytes": len(code),
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "attempt": attempt + 1,
                    },
                )
                last_exc = None
                break  # success

            except Exception as exc:
                last_exc = exc
                last_tb = traceback.format_exc()
                if attempt < task.max_retries:
                    delay = task.retry_delay_s * (2 ** attempt)
                    self.logger.warning(
                        event="task_retry",
                        detail=task.title,
                        extra={"attempt": attempt + 1, "of": task.max_retries + 1, "delay_s": delay},
                    )
                    time.sleep(delay)
                else:
                    self.logger.error(
                        event="task_failed",
                        detail=str(exc),
                        extra={"task": task.title, "attempts": task.attempts_made},
                    )

        if last_exc is not None:
            task.status = TaskStatus.FAILED
            task.error = last_tb
            task.completed_at = utc_now()
            task.duration_seconds = (task.completed_at - task.started_at).total_seconds()
            return task

        task.status = TaskStatus.DONE
        task.completed_at = utc_now()
        task.duration_seconds = (task.completed_at - task.started_at).total_seconds()
        return task

    # ------------------------------------------------------------------ #

    def _resolve_filename(self, task: Task) -> str | None:
        title = task.title.lower()

        # 0) Explicit .py path in the raw title (raw preserves casing for the path).
        #    Allows letters (any case), digits, underscores, hyphens, and forward
        #    slashes so paths like "crud/products.py" and "api-routes/items.py" work.
        #    Safety: if ".." appears anywhere in the text before the regex match, the
        #    match is a suffix of a traversal expression (e.g. "../evil.py") and must
        #    be rejected.  Backslashes and ".." inside the captured path are also
        #    rejected.  Absolute paths cannot match because "/" is only allowed as an
        #    interior separator between two non-empty word components.
        m = re.search(r'([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*)\.py\b', task.title)
        if m:
            prefix = task.title[: m.start()]
            path = m.group(1) + ".py"
            if ".." not in prefix and ".." not in path and "\\" not in path:
                return path

        # 1) Static map — flat files always take priority.
        #    Uses whole-word matching so plurals like "endpoints" don't trigger "endpoint".
        for keywords, filename in _FILENAME_MAP:
            if any(re.search(r"\b" + re.escape(kw) + r"\b", title) for kw in keywords):
                return filename

        # 2) Structural keyword detection for subdirectory layout.
        #    Last match wins so "router" beats "crud" when both appear in the title
        #    (e.g. "Implement product CRUD and stock endpoints router" → routers/).
        #    Domain words are extracted from before the *first* subdir keyword to avoid
        #    collecting unrelated nouns that appear after it.
        words = re.sub(r"[^a-z0-9\s]", " ", title).split()
        subdir: str | None = None
        first_subdir_idx = -1
        for i, word in enumerate(words):
            candidate = _SUBDIR_MAP.get(word)
            if candidate is not None:
                if subdir is None:
                    first_subdir_idx = i
                subdir = candidate  # last match wins
        if subdir is not None:
            domain_words = [w for w in words[:first_subdir_idx] if w not in _TITLE_STOP_WORDS]
            if domain_words:
                return f"{subdir}/{'_'.join(domain_words)}.py"
            return f"{subdir}.py"  # no domain → flat canonical name

        return None

    def _build_prompt(self, task: Task, filename: str, project_dir: Path) -> str:
        brief = self.session.brief
        context = self._collect_context(project_dir, filename)
        file_tree = self._build_file_tree(project_dir)

        parts = [
            f"Project: {brief.title}",
            f"Description: {brief.description}",
            "",
            f"Task: {task.title}",
            f"Details: {task.description}",
            "",
        ]

        try:
            spec = agent_registry.get(task.assigned_agent)
            parts += [
                f"You are acting as: {spec.role}",
                f"Your focus: {spec.description}",
                f"Your capabilities: {', '.join(spec.capabilities)}",
                "",
            ]
        except KeyError:
            pass  # unknown agent — no extra context injected

        parts += [
            f"Generate the file: {filename}",
            "",
            "IMPORT RULES — you MUST follow these exactly:",
            "  - This project uses a flat layout. The project root IS the Python path.",
            "  - There is NO 'app/' package. Never write 'from app.X' or 'import app.X'.",
            "  - Derive every import from the actual file path shown in the tree below:",
            "      database.py            →  from database import ...",
            "      models.py              →  from models import ...",
            "      schemas.py             →  from schemas import ...",
            "      crud/categories.py     →  from crud.categories import ...",
            "      crud/expenses.py       →  from crud.expenses import ...",
            "      routers/categories.py  →  from routers.categories import ...",
            "      routers/expenses.py    →  from routers.expenses import ...",
            "  - Subdirectories are Python packages (empty __init__.py already present).",
            "  - If the task description mentions 'app/X.py', ignore the 'app/' prefix;",
            "    the actual file is X.py at the project root.",
            "",
        ]

        if file_tree:
            parts += [
                "Current project file tree (derive all imports from this):",
                file_tree,
                "",
            ]

        if context:
            parts.append("Existing project files for context:\n")
            for fname, content in context.items():
                parts.append(f"--- {fname} ---\n{content}\n")

        parts.append("Return ONLY the raw file content. No markdown fences, no explanation.")
        return "\n".join(parts)

    def _collect_context(self, project_dir: Path, current_file: str) -> dict[str, str]:
        """Read already-generated sibling files so Claude has full project context."""
        context: dict[str, str] = {}

        for fname in _CONTEXT_FILES:
            if fname == current_file:
                continue
            path = project_dir / fname
            if path.exists():
                try:
                    context[fname] = read_file(str(path))
                except Exception:
                    pass

        for subdir in ("crud", "routers"):
            subpath = project_dir / subdir
            if not subpath.is_dir():
                continue
            for p in sorted(subpath.glob("*.py")):
                if p.name == "__init__.py":
                    continue
                fname = f"{subdir}/{p.name}"
                if fname == current_file:
                    continue
                try:
                    context[fname] = read_file(str(p))
                except Exception:
                    pass

        return context

    def _build_file_tree(self, project_dir: Path) -> str:
        """Return a compact listing of project files, skipping noise dirs."""
        _SKIP = {"__pycache__", ".git", ".venv"}
        _EXTS = {".py", ".txt", ".md", ".env", ".cfg", ".toml", ".ini"}
        lines: list[str] = []
        for p in sorted(project_dir.rglob("*")):
            if any(part in _SKIP for part in p.relative_to(project_dir).parts):
                continue
            if p.is_file() and p.suffix in _EXTS:
                lines.append(f"  {p.relative_to(project_dir)}")
        return "\n".join(lines)

    def _extract_code(self, raw: str, filename: str = "") -> str:
        """Strip markdown fences; for .py files also remove any leading prose text."""
        text = raw.strip()
        for fence in ("```python", "```txt", "```markdown", "```bash", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
                break
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        if filename.endswith(".py"):
            m = _FIRST_PY_LINE_RE.search(text)
            if m and m.start() > 0:
                text = text[m.start():]

        return text + "\n"

    def _write(self, project_dir: Path, filename: str, content: str, task: Task) -> None:
        path = project_dir / filename
        if path.parent != project_dir:
            path.parent.mkdir(parents=True, exist_ok=True)
            init = path.parent / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
        write_file(str(path), content)
        task.files_created.append(str(path))
        task.result_summary = f"{filename} generated via LLM."
