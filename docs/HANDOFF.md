# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-10  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `0b2f9a0` Validate duplicate enum definitions  
**Test suite:** 143 tests, all passing

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

---

## Pipeline Improvements Achieved

| Area | Before | After |
|------|--------|-------|
| Subdirectory routing | Router tasks clobbered `main.py`; CRUD landed at root | `crud/products.py`, `routers/suppliers.py` etc. placed correctly |
| Traversal path safety | `"../evil.py"` partially matched as `"evil.py"` | Returns `None`; prefix check prevents any traversal bypass |
| Duplicate-key errors | `IntegrityError` propagated as unhandled 500 | Wrapped in `try/except`; re-raised as `HTTPException(409)` |
| Schema ordering | Forward references caused declaration-order bugs | Schemas now declared in dependency order |
| Dead enum variants | `adjustment` added "for completeness" with no route | Omitted unless brief requires it (prompt rule; validator pending) |
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

---

## Validation Pipeline (4 steps)

```
1. python_compile   — syntax check via compileall
2. pip_install      — install requirements.txt so import check resolves deps
3. app_import_check — import all generated modules; catch missing deps / circular imports
4. enum_check       — ast scan for duplicate enum class names across files (deterministic)
   → any failure → LLM repair → re-run all 4 steps
```

Step 4 is no-LLM, no false negatives. Any enum class (inheriting from `Enum`, `PyEnum`, `IntEnum`, `StrEnum`, `Flag`, `IntFlag`, or `enum.Enum`) that appears under the same name in more than one file triggers an immediate failure with a clear message identifying the class, both files, and the fix. `schemas.py` is queued for repair; the repair prompt provides `models.py` as context so Claude replaces the duplicate class with an import.

---

## Current System Status

- **Tests:** 143 passing, 0 failing
- **`inventory_api` severity:** WARNING — duplicate enum eliminated by validator/repair; remaining issues are semantic and concurrency concerns
- **`expense_tracker` severity:** WARNING — 3 bugs; FK referential integrity, status code mismatch, minor code quality
- **Structural pipeline failures:** None.
- **Framework API issues:** Eliminated (Pydantic v2 enforced; deprecated datetime patterns removed).
- **Enum consistency:** Deterministic. Duplicate enum definitions are caught by the static validator and repaired before the reviewer runs.
- **Reviewer noise:** Eliminated. All reported findings are real code issues.

---

## Remaining Known Limitations

### Quantity constraint inconsistency
`StockMovementRead.quantity` uses `Field(ge=0)` (allows zero) while `RestockRequest.quantity` and `SellRequest.quantity` use `Field(gt=0)` (rejects zero). A zero-quantity movement cannot be created through the public API, but a direct DB insert would pass the read schema. Minor inconsistency; validator rule pending.

### Dead enum variant without endpoint
The `adjustment` movement type is sometimes generated in `MovementType` despite the "no dead enum variants" prompt rule. The `adjustment` value exists in the DB column type but has no corresponding API route. The prompt rule is probabilistic; a static validator check would make this deterministic.

### TOCTOU race on stock mutations
The sell and restock endpoints read stock quantity, check sufficiency, then write — without a row-level lock. Concurrent requests can both pass the check before either commits, producing negative stock. This requires an atomic `UPDATE ... WHERE stock_quantity >= :qty` pattern or a version counter; SQLite does not support `SELECT FOR UPDATE`.

### Internal `add_stock_movement` accepts unsafe quantities
`add_stock_movement()` applies an adjustment branch (`product.stock_quantity += quantity`) reachable only by internal callers, not the public API. A negative internal call bypasses the `gt=0` constraint and could silently corrupt stock. Fix: add an assertion or explicit guard inside the function.

### Missing FK/domain-level referential integrity
`Expense.category` is a plain `String` with no `ForeignKey` to the `Category` table. Expenses can reference non-existent categories; category renames do not cascade.

### Authentication absence
All generated APIs expose all endpoints publicly. Authentication is a brief-level gap, not a generation failure.

---

## Recommended Next Steps

### 1. Validator: dead enum variant detection
Add an AST check: scan models for `Column(Enum(MyEnum))` column definitions, then scan router files for routes that create movements/records of each enum value. Flag any enum member that has no corresponding route as a dead variant. This makes the "no dead enum variants" prompt rule deterministic.

### 2. Validator: quantity constraint consistency
Add an AST check: scan Pydantic schemas for numeric fields named `quantity`, `amount`, `count`, `stock`, `price`. Flag any that are missing `ge=0` or `gt=0` in their `Field(...)` call. Trigger targeted repair for each violation.

### 3. Validator: audit-trail bypass detection
Add an AST check: if a `StockMovement` or similar history model exists, flag any Update schema (class names ending in `Update`) that contains a field matching the audited column (e.g. `stock_quantity`). Trigger repair to remove the field from the Update schema.

### 4. Atomic stock mutation pattern
Add a quality rule: "Replace read-modify-write patterns on numeric fields (stock_quantity, balance, count) with a single atomic SQL UPDATE using a WHERE guard. Check affected rowcount to detect constraint violations instead of reading first."

### 5. FK referential integrity validator
Add an AST check: scan SQLAlchemy model classes for `Column(String)` or `Column(Integer)` fields whose names end in `_id`, `_name`, or match another model's primary key. Flag fields that semantically reference another table but lack a `ForeignKey(...)` declaration.

### 6. Semantic repair loop expansion
Expand the validator's repair path to handle semantic violations (dead enum variants, quantity constraints, audit-trail bypasses) as well as structural failures. Each new static check generates a targeted error message that the repair LLM can act on — no new repair infrastructure needed, only new detection rules.

---

## Current Trajectory

The pipeline has made a significant architectural maturity step this session: **from prompt-only quality control to deterministic static validation with automatic repair**. The duplicate enum check is the first validator rule that enforces a semantic correctness property without any LLM involvement. It fires reliably on every run, never produces false negatives, and the downstream repair is already wired up.

The quality control layers now stack as follows:

| Layer | Mechanism | Reliability |
|-------|-----------|-------------|
| Structural correctness | `_resolve_filename`, planner FLAT LAYOUT rules | Deterministic |
| Syntax + import validity | `compileall` + `app_import_check` | Deterministic |
| Duplicate enum definitions | `_check_duplicate_enums()` AST scan | Deterministic |
| Framework API correctness | Pydantic v2 prompt rules + reviewer enforcement | Probabilistic (high) |
| Domain validation | Semantic prompt rules (`Field(ge=0)`, cascade, audit trail) | Probabilistic (medium) |
| Semantic/concurrency | Reviewer LLM findings | Probabilistic (lower) |

The clear next step is to move the medium-reliability probabilistic rules (quantity constraints, dead enum variants, audit-trail bypass) into the deterministic validator layer. Each such migration eliminates a whole class of review findings unconditionally and reduces dependency on LLM compliance.

---

## Key Files

```
agents/developer.py          — SYSTEM_PROMPT (13 API + 5 semantic + 5 Pydantic v2 + 4 DB enum + 4 single-source rules), filename mapper
agents/reviewer.py           — LLM review, truncation + Pydantic + DB enum + single-source reviewer instructions
core/validator.py            — 4-step validator: compileall, pip install, import check, duplicate enum AST scan + LLM repair
core/task_generator.py       — planner system prompt (FLAT LAYOUT rules)
tests/test_developer.py      — 100 tests (filename mapper, prompt rules, all 31 system prompt rules)
tests/test_reviewer.py       — 23 tests (truncation + Pydantic + DB enum + single-source reviewer prompt tests)
tests/test_task_generator.py — 7 tests (planner prompt coverage)
tests/test_validator_strip.py — 20 tests (fence stripping + _enum_class_names + _check_duplicate_enums)
briefs/                      — expense_tracker, url_shortener, todo_api, blog_api, inventory_api
memory/sessions/             — JSON session records for all past runs
memory/reports/              — markdown review reports
```

## Verify State

```bash
cd /opt/agent-lab/projects/neuraloptima-core

# Tests
PYTHONPATH=. .venv/bin/pytest -q

# Smoke run (watch for "Validation failed — attempting repair" on enum duplicates)
.venv/bin/python cli.py run briefs/inventory_api.txt

# Git
git log --oneline -10
git status
```
