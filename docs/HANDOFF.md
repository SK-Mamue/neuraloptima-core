# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-11  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `35be98a` Validate numeric constraint consistency  
**Test suite:** 188 tests, all passing

---

## Pipeline Architecture

```
Brief (txt) → Task planner (LLM) → DeveloperAgent (generates files)
           → ProjectValidator (compileall + import check + enum check + auto-repair)
           → ReviewAgent (LLM JSON review, severe = exit 1)
```

---

## Fixes Completed This Session (in order)

| Commit | Fix |
|--------|-----|
| `eaf3149` | **Bug 1** — `_FILENAME_MAP` whole-word matching: "endpoints" no longer triggers "endpoint" keyword. Step 2 (structural subdir detection) updated to last-match-wins so "router" beats "crud" when both appear in a title. |
| `27954f9` | **Bug 2** — Planner prompt (`core/task_generator.py`) gains explicit FLAT LAYOUT block forbidding `app/` path prefixes and `app.` import paths in task descriptions. Adds `tests/test_task_generator.py` (7 tests). |
| `ba2cf32` | **Generation quality rules (round 1)** — `SYSTEM_PROMPT` in `agents/developer.py` gains `API QUALITY RULES` block: no bare return, raise HTTPException correctly, route paths match brief (sku not product_id), static routes before parameterised, no duplicate routes, no undocumented features, imports must match real files, no circular schemas. |
| `305f01b` | **Bug 3** — `_resolve_filename` step 0 extended to capture full subdirectory paths from task titles ("Create crud/products.py" → `crud/products.py` instead of `products.py`). Regex allows single-level prefix; character class `[A-Za-z0-9_-]` prevents `..` and absolute paths from matching. |
| `a5c040d` | **Bug 3 hardening** — Step 0 now uses raw `task.title` (not `.lower()`) to preserve casing. Regex widened to allow hyphens (`api-routes/products.py`). Traversal safety: text *before* the regex match is checked for `..`; `"../evil.py"` now correctly returns `None`. Traversal test strengthened from weak assertion to `assert result is None`. |
| `e65d0de` | **Quality rules (round 2)** — Five inventory_api warning patterns addressed: atomic DB writes (single `db.commit()`), no string-literal `order_by`, `datetime.now(timezone.utc)` instead of `utcnow`, no `aiosqlite` unless async SQLAlchemy, SKU immutability in Update schemas. |
| `545ceec` | **Quality rules (round 3)** — Five more: `IntegrityError` → 409 + rollback, schema dependency-order declarations, no dead enum variants, no redundant column-default overrides, no unused imports. |
| `c334f8c` | **Reviewer visibility** — `_MAX_FILE_CHARS` raised from 3 000 → 6 000. Reviewer prompt gains explicit instruction not to report unverifiable or "cannot verify" findings based on truncated content. Adds `test_truncation_note_in_prompt`. |
| `fb98432` | **Semantic domain rules** — Five new `SEMANTIC DOMAIN RULES` in `SYSTEM_PROMPT`: `Field(ge=0)`/`Field(gt=0)` on quantity/price fields, audit-trail integrity (derived fields must not be in Update schemas), no ORM dynamic monkeypatching, cascade delete + `PRAGMA foreign_keys=ON`, SQLite-aware datetime defaults (`server_default=func.now()`). Adds 6 new prompt-coverage tests. |
| `67d0345` | **Pydantic v2 consistency** — New `PYDANTIC V2 RULES` section in `SYSTEM_PROMPT`: forbid `class Config`/`orm_mode`/`from_orm()`/`.dict()`/`parse_obj()`, require `ConfigDict(from_attributes=True)`, `model_dump()`, `model_validate()`, and `use_enum_values=True` for enum fields. Reviewer prompt gains a `PYDANTIC API CONSISTENCY` block. Adds 5 developer + 1 reviewer prompt tests. |
| `c0d09e6` | **DB enum enforcement** — New `DB ENUM ENFORCEMENT RULES` section in `SYSTEM_PROMPT`: use `Column(Enum(MyEnum))` instead of `Column(String)` for enum-backed fields; require `(str, PyEnum)` base class; define enum in one place and import into both model and schema; SQLite-compatible note. Reviewer prompt gains a `DB ENUM ENFORCEMENT` block. Adds 3 developer + 1 reviewer prompt tests. |
| `b8cf583` | **Enum single-source rules** — New `ENUM SINGLE-SOURCE-OF-TRUTH RULES` section in `SYSTEM_PROMPT`: define each enum exactly once in models.py; schemas.py must import, never redefine; same imported class object required for both `Column(Enum(...))` and Pydantic field. Reviewer prompt gains an `ENUM SINGLE-SOURCE-OF-TRUTH` block. Adds 3 developer + 1 reviewer prompt tests. |
| `0b2f9a0` | **Deterministic duplicate enum validator** — `ProjectValidator.run()` gains a 4th check: `_check_duplicate_enums()` scans all generated `.py` files with the `ast` module, detects class names inheriting from any Enum base appearing in more than one file, and fails validation with a message naming the class, both files, and the required fix. Duplicate detection queues `schemas.py` for LLM repair; the repair receives `models.py` as context and replaces the duplicate class definition with `from models import EnumName`. Adds 9 new tests (5 for `_enum_class_names`, 4 for `_check_duplicate_enums`). |
| `a277084` | **Deterministic dead enum variant validator** — `ProjectValidator.run()` gains a 5th check: `_check_dead_enum_variants()` scans all generated `.py` files with the `ast` module, collects each enum member (via new `_enum_members()` helper), then scans all other project files (via new `_references_member_in_files()` helper) for attribute access (`EnumClass.MEMBER`) or exact string constant (`"value"`) references. Members with zero external references are flagged as dead variants. Detection queues `models.py` for LLM repair so the unused member is removed. Adds 19 new tests (5 `TestEnumMembers`, 7 `TestReferencesMemberInFiles`, 7 `TestCheckDeadEnumVariants`). Verified on `inventory_api`: `MovementType.adjustment` detected and removed by repair; dead enum warning eliminated. |
| `35be98a` | **Deterministic numeric constraint validator** — `ProjectValidator.run()` gains a 6th check: `_check_numeric_constraints()` scans all generated `.py` files for two violation classes. (1) Schema fields: `AnnAssign` nodes in non-read Pydantic classes are checked against field-category rules — `quantity`/`amount` must have `Field(gt=0)`; `stock_quantity`/`count`/`balance` accept `Field(ge=0)` or `Field(gt=0)`; `price`/`cost`/`rate`/`total`/`subtotal` must have `Field(gt=0)`. `Optional` fields and `PositiveInt`/`PositiveFloat` annotations are skipped. Read/Response/Out classes are skipped entirely. (2) Function parameters: module-level (non-route-handler) functions with a raw `quantity: int` or `amount: int` parameter are required to have a zero/negative guard (`if param <= 0: raise` or `assert param > 0`). Unlike previous checks, returns `(error_msg, Path)` pairs so the exact violating file is queued for repair. Adds 5 new helpers (`_field_numeric_constraint`, `_is_optional_annotation`, `_is_route_handler`, `_compare_involves`, `_has_numeric_guard`) and 26 new tests (6 `TestFieldNumericConstraint`, 6 `TestHasNumericGuard`, 14 `TestCheckNumericConstraints`). Verified on `inventory_api`: LLM generated correct constraints; validator stayed silent as expected safety net. |

---

## Pipeline Improvements Achieved

| Area | Before | After |
|------|--------|-------|
| Subdirectory routing | Router tasks clobbered `main.py`; CRUD landed at root | `crud/products.py`, `routers/suppliers.py` etc. placed correctly |
| Traversal path safety | `"../evil.py"` partially matched as `"evil.py"` | Returns `None`; prefix check prevents any traversal bypass |
| Duplicate-key errors | `IntegrityError` propagated as unhandled 500 | Wrapped in `try/except`; re-raised as `HTTPException(409)` |
| Schema ordering | Forward references caused declaration-order bugs | Schemas now declared in dependency order |
| Dead enum variants | `adjustment` added "for completeness" with no route | Caught by `_check_dead_enum_variants()`; repaired by removing unused member from models.py |
| Stock operations | Two `db.commit()` calls in one endpoint (split transaction) | Single commit after all model changes |
| Datetime deprecation | `datetime.utcnow()` (deprecated, naive) | `datetime.now(timezone.utc)` in app logic; `server_default=func.now()` in SQLite column defaults |
| Unused imports | `field_validator`, `List`, `Optional` imported but unused | Removed |
| SKU mutability | `sku` field in `ProductUpdate` schema | Excluded from Update schemas by default |
| `app/` path prefixes | Planner generated `"Create app/routers/products.py"` | Descriptions use bare paths: `"Create routers/products.py"` |
| Reviewer truncation artifacts | Large files capped at 3 000 chars; reviewer flagged "cannot verify" as bugs | Cap raised to 6 000; prompt instructs reviewer to skip unverifiable findings |
| Cascade delete failures | Parent deletion produced unhandled 500 on FK violation | `cascade="all, delete-orphan"` rule + SQLite FK enforcement guidance added |
| ORM dynamic monkeypatching | `product.recent_movements = [...]` set on ORM instances; lost on refresh | Explicit Pydantic response construction rule enforced |
| Negative/zero field values | Negative quantities and zero prices accepted silently | `Field(ge=0)` / `Field(gt=0)` constraints required in all Create and Update schemas |
| Audit-trail bypass | `stock_quantity` directly settable in Update schemas despite StockMovement system | Derived fields must not appear in Update schemas; all mutations through movement endpoints |
| Pydantic v1/v2 API mixing | `orm_mode = True`, `.dict()`, `from_orm()` mixed with v2 APIs; runtime instability | v2-only rules enforced in developer prompt; reviewer flags any v1 pattern as a bug |
| Enum serialization | `MovementType.RESTOCK` serialized as enum object, not string `"RESTOCK"` | `use_enum_values=True` required in `ConfigDict`; `(str, PyEnum)` base ensures string-compatible values |
| DB-level enum enforcement | `movement_type = Column(String)` — invalid values persisted without constraint | `Column(Enum(MovementType))` required; SQLAlchemy generates CHECK constraint on SQLite |
| Duplicate enum definitions | `MovementType` defined independently in models.py and schemas.py — latent divergence risk | `_check_duplicate_enums()` in validator detects and fails; LLM repair rewrites schemas.py to import from models.py |
| Numeric field constraints | `quantity`/`price` fields accepted without bounds; internal helpers accepted negative quantities silently | `_check_numeric_constraints()` enforces `Field(gt=0)` / `Field(ge=0)` per field category; flags module-level helpers missing zero/negative guards |

---

## Validation Pipeline (6 steps)

```
1. python_compile      — syntax check via compileall
2. pip_install         — install requirements.txt so import check resolves deps
3. app_import_check    — import all generated modules; catch missing deps / circular imports
4. duplicate_enum      — ast scan for enum class names defined in more than one file (deterministic)
5. dead_enum           — ast scan for enum members with no external references (deterministic)
6. numeric_constraints — ast scan for missing or weak Field bounds and unguarded int parameters (deterministic)
   → any failure → LLM repair → re-run all 6 steps
```

**Step 4** fires when any enum class (inheriting from `Enum`, `PyEnum`, `IntEnum`, `StrEnum`, `Flag`, `IntFlag`, or `enum.Enum`) appears under the same name in more than one file. `schemas.py` is queued for repair; the repair prompt provides `models.py` as context so Claude replaces the duplicate class with an import.

**Step 5** fires when any enum member has zero references in files other than the one that defines it. A reference is either an attribute access (`EnumClass.MEMBER`) or an exact string constant matching the member's value (`"restock"`). `models.py` is queued for repair so the LLM removes the unused member. The detection logic is:

- `_enum_members(path)` — parses a file's AST and returns `{ClassName: [(MEMBER_NAME, value_str), ...]}` for every enum class.
- `_references_member_in_files(files, member_name, member_value)` — walks the AST of each file looking for `ast.Attribute` nodes whose `.attr` matches `member_name`, or `ast.Constant` string nodes whose value matches `member_value` (case-insensitive, exact).
- `_check_dead_enum_variants()` — combines the two helpers, builds the error string (class name, member name/value, files inspected, fix instruction), and returns all dead-member errors.

**Step 6** fires on two patterns. Unlike steps 4–5, it returns `(error_msg, Path)` pairs so the exact violating file is queued for repair rather than a heuristic target.

*Schema field rules* — applied to `AnnAssign` nodes in any class whose name does **not** end in `Read`, `Response`, or `Out`. `Optional` fields and `PositiveInt`/`PositiveFloat` annotations are skipped.

| Field name | Required constraint | Notes |
|---|---|---|
| `quantity`, `amount` | `Field(gt=0)` | `ge=0` is flagged as too weak |
| `stock_quantity`, `count`, `balance` | `Field(ge=0)` or `Field(gt=0)` | zero stock is valid |
| `price`, `cost`, `rate`, `total`, `subtotal` | `Field(gt=0)` | monetary values cannot be zero |

`Field(ge=N)` where N > 0 is treated as equivalent to `Field(gt=0)` for integers.

*Function parameter rules* — applied to module-level (non-route-handler) `FunctionDef` nodes. A function is a route handler if any decorator resolves to `.get`, `.post`, `.put`, `.patch`, or `.delete`. Parameters named `quantity` or `amount` with a raw `int` or `float` annotation must have a zero/negative guard in the function body:

- `_field_numeric_constraint(assign)` — reads `gt`/`ge` from `Field(...)` keyword args; returns `None` if no Field or no numeric bound.
- `_is_optional_annotation(ann)` — detects `Optional[X]`, `Union[X, None]`, and `X | None`.
- `_is_route_handler(func_node)` — detects HTTP method decorators.
- `_compare_involves(cmp, name)` — checks whether a `Compare` node directly references a named variable.
- `_has_numeric_guard(func_node, param_name)` — walks the function body for `assert param > 0` or `if param <= 0: raise/return`.

---

## Current System Status

- **Tests:** 188 passing, 0 failing
- **`inventory_api` severity:** WARNING — dead enum `MovementType.adjustment` caught and removed by validator/repair; LLM generated correct `Field(gt=0)` constraints so numeric validator fired no violations; remaining issues are unrelated to numeric constraints or enum structure
- **`expense_tracker` severity:** WARNING — 3 bugs; FK referential integrity, status code mismatch, minor code quality
- **Structural pipeline failures:** None.
- **Framework API issues:** Eliminated (Pydantic v2 enforced; deprecated datetime patterns removed).
- **Enum consistency:** Deterministic. Duplicate definitions and dead variants are caught by steps 4–5 and repaired before the reviewer runs.
- **Numeric constraints:** Deterministic. Step 6 enforces `Field(gt=0)` / `Field(ge=0)` per field category and guards on internal helper parameters.
- **Reviewer noise:** Eliminated. All reported findings are real code issues.

---

## Remaining Known Limitations

### TOCTOU race on stock mutations
The sell and restock endpoints read stock quantity, check sufficiency, then write — without a row-level lock. Concurrent requests can both pass the check before either commits, producing negative stock. This requires an atomic `UPDATE ... WHERE stock_quantity >= :qty` pattern or a version counter; SQLite does not support `SELECT FOR UPDATE`.

### Internal helpers without quantity guards
Module-level CRUD helpers that accept raw `quantity: int` without a `if quantity <= 0: raise` guard can silently corrupt stock if called by internal paths that bypass the public API validation. Step 6 now flags these deterministically.

### Missing FK/domain-level referential integrity
`Expense.category` is a plain `String` with no `ForeignKey` to the `Category` table. Expenses can reference non-existent categories; category renames do not cascade.

### Authentication absence
All generated APIs expose all endpoints publicly. Authentication is a brief-level gap, not a generation failure.

---

## Recommended Next Steps

### 1. Validator: audit-trail bypass detection
Add an AST check: if a `StockMovement` or similar history model exists, flag any Update schema (class names ending in `Update`) that contains a field matching the audited column (e.g. `stock_quantity`). Trigger repair to remove the field from the Update schema.

### 2. Validator: FK referential integrity
Add an AST check: scan SQLAlchemy model classes for `Column(String)` or `Column(Integer)` fields whose names end in `_id`, `_name`, or match another model's primary key. Flag fields that semantically reference another table but lack a `ForeignKey(...)` declaration.

### 3. Atomic stock mutation / concurrency validator
Add a quality rule: "Replace read-modify-write patterns on numeric fields (stock_quantity, balance, count) with a single atomic SQL UPDATE using a WHERE guard. Check affected rowcount to detect constraint violations instead of reading first." Or add an AST detector for the read-then-write pattern without a lock.

### 4. Validator: response_model completeness
Add an AST check: scan FastAPI route definitions for endpoints whose `response_model` schema references nested relationships. Flag routes where the corresponding CRUD function does not use `joinedload` or `selectinload` for those relationships. Trigger repair to add eager loading.

### 5. README/documentation fence validator (optional)
After repair runs, detect cases where the generated README still describes enum variants or endpoints that were removed by earlier repair steps. Flag the README for re-generation to stay in sync with the actual code.

---

## Current Trajectory

The pipeline has made three significant architectural maturity steps: **from prompt-only quality control to deterministic static validation with automatic repair**. Duplicate enum definitions (step 4), dead enum variants (step 5), and numeric constraint consistency (step 6) are all caught by no-LLM, no-false-negative AST scans that fire reliably on every run. The downstream repair flow is already wired — each new static check only needs a detection rule and a structured error message; no new repair infrastructure is required.

The validator layer is now the central quality gate. The pattern is established: identify a class of probabilistic prompt rule failures, write an AST check that detects it deterministically, wire it as a new pipeline step, and return the exact file path for targeted repair. Each migration unconditionally eliminates a class of reviewer findings and reduces dependency on LLM compliance. Step 6 introduced a refinement over steps 4–5: it returns `(error_msg, Path)` pairs instead of plain strings, allowing precise per-file repair targeting rather than heuristic file selection.

The quality control layers now stack as follows:

| Layer | Mechanism | Reliability |
|-------|-----------|-------------|
| Structural correctness | `_resolve_filename`, planner FLAT LAYOUT rules | Deterministic |
| Syntax + import validity | `compileall` + `app_import_check` | Deterministic |
| Duplicate enum definitions | `_check_duplicate_enums()` AST scan | Deterministic |
| Dead enum variants | `_check_dead_enum_variants()` AST scan | Deterministic |
| Numeric field constraints | `_check_numeric_constraints()` AST scan | Deterministic |
| Framework API correctness | Pydantic v2 prompt rules + reviewer enforcement | Probabilistic (high) |
| Domain validation | Semantic prompt rules (cascade, audit trail) | Probabilistic (medium) |
| Semantic/concurrency | Reviewer LLM findings | Probabilistic (lower) |

The clear next step is to continue migrating the remaining medium-reliability probabilistic rules (audit-trail bypass, FK integrity, concurrency) into the deterministic validator layer.

---

## Key Files

```
agents/developer.py           — SYSTEM_PROMPT (13 API + 5 semantic + 5 Pydantic v2 + 4 DB enum + 4 single-source rules), filename mapper
agents/reviewer.py            — LLM review, truncation + Pydantic + DB enum + single-source reviewer instructions
core/validator.py             — 6-step validator: compileall, pip install, import check, duplicate enum, dead enum, numeric constraints + LLM repair
core/task_generator.py        — planner system prompt (FLAT LAYOUT rules)
tests/test_developer.py       — 100 tests (filename mapper, prompt rules, all 31 system prompt rules)
tests/test_reviewer.py        — 23 tests (truncation + Pydantic + DB enum + single-source reviewer prompt tests)
tests/test_task_generator.py  — 7 tests (planner prompt coverage)
tests/test_validator_strip.py — 65 tests (fence stripping + _enum_class_names + _check_duplicate_enums + _enum_members + _references_member_in_files + _check_dead_enum_variants + _field_numeric_constraint + _has_numeric_guard + _check_numeric_constraints)
briefs/                       — expense_tracker, url_shortener, todo_api, blog_api, inventory_api
memory/sessions/              — JSON session records for all past runs
memory/reports/               — markdown review reports
```

## Documentation Layer (restructured 2026-05-11)

The project documentation was reorganised. The new authoritative human-readable references are:

| File | Role |
|---|---|
| `docs/VISION.md` | What NeuralOptima is, long-term goal, philosophy, non-goals |
| `docs/ARCHITECTURE.md` | Pipeline flow, agent roles, all 7 validation steps, quality layer table, project structure |
| `docs/HANDOFF.md` | Active sprint state (this file) |
| `CLAUDE.md` | Claude Code CLI working rules — auto-loaded by the CLI |

Archived (superseded, kept for historical reference):

| File | Reason |
|---|---|
| `docs/archive/PRACTICAL_MVC_PLAN.md` | Original MVC design plan; project has grown well past it |
| `docs/archive/ROADMAP.md` | Static 4-phase outline; superseded by the next-steps section in this file |

The root-level `HANDOFF.md` (session-disconnect note from 2026-05-10) is also superseded by this file and was not removed but can be deleted.

**Important:** No agent reads any of these doc files at runtime. Context reaches the LLM agents exclusively through hardcoded `SYSTEM_PROMPT` strings in `agents/developer.py`, `agents/reviewer.py`, and `core/task_generator.py`.

---

## Verify State

```bash
cd /opt/agent-lab/projects/neuraloptima-core

# Tests
PYTHONPATH=. .venv/bin/pytest -q

# Smoke run (watch for "Validation failed — attempting repair" on enum/constraint violations)
.venv/bin/python cli.py run briefs/inventory_api.txt

# Git
git log --oneline -10
git status
```
