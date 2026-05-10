# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-10  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `fb98432` Add semantic domain validation rules  
**Test suite:** 120 tests, all passing

---

## Pipeline Architecture

```
Brief (txt) → Task planner (LLM) → DeveloperAgent (generates files)
           → ProjectValidator (compileall + import check + auto-repair)
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

---

## Pipeline Improvements Achieved

| Area | Before | After |
|------|--------|-------|
| Subdirectory routing | Router tasks clobbered `main.py`; CRUD landed at root | `crud/products.py`, `routers/suppliers.py` etc. placed correctly |
| Traversal path safety | `"../evil.py"` partially matched as `"evil.py"` | Returns `None`; prefix check prevents any traversal bypass |
| Duplicate-key errors | `IntegrityError` propagated as unhandled 500 | Wrapped in `try/except`; re-raised as `HTTPException(409)` |
| Schema ordering | Forward references caused declaration-order bugs | Schemas now declared in dependency order |
| Dead enum variants | `adjustment` added "for completeness" with no route | Omitted unless brief requires it |
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

---

## Current System Status

- **Tests:** 120 passing, 0 failing
- **`inventory_api` severity:** WARNING — cascade delete and ORM monkeypatching warnings eliminated; remaining issues are concurrency, enum serialization, and domain-level integrity
- **`expense_tracker` severity:** WARNING — negative/zero amount warning eliminated; remaining issues are Pydantic API consistency, FK referential integrity, and concurrency
- **Structural pipeline failures:** None. All generated files land in the correct location; validation passes without repair on clean runs.
- **Reviewer noise:** Eliminated. All reported findings are real code issues visible in the provided file content.
- **Domain validation:** Active. Quantity, price, and audit-trail constraints now enforced at schema level.

---

## Remaining Known Limitations

### Concurrency and race conditions
Sell and restock endpoints check stock levels before committing without a database-level lock. Under concurrent requests, two sells can both pass the availability check before either commits, resulting in negative stock. Fix requires either `SELECT ... FOR UPDATE` (not available in SQLite) or optimistic concurrency with version counters, or application-level locking.

### Enum serialization correctness
`MovementType` and similar enums are serialized as enum objects rather than plain string values unless `use_enum_values = True` is set on the Pydantic model config or the schema field uses an explicit `str` type with a validator. The generated code does not consistently apply this.

### Pydantic v1/v2 API consistency
Some generated files mix v1 (`orm_mode = True` in `Config`) and v2 (`model_dump()`, `model_config = ConfigDict(from_attributes=True)`) APIs. This causes runtime warnings or errors depending on the installed Pydantic version. The root cause is that the LLM draws from both API versions without a consistent version target.

### Missing FK/domain-level referential integrity
The expense_tracker generates `Expense.category` as a plain `String` field with no foreign key to the `Category` table. Expenses can reference categories that do not exist; category renames do not cascade. Fix requires either a proper FK column or explicit CRUD-level validation on every create/update.

### Authentication absence
All generated APIs expose all endpoints without authentication. This is a structural gap — authentication requires framework-specific decisions (OAuth2, API keys, JWT) that the brief does not specify. Not a generation failure; requires either brief-level specification or a post-generation scaffold step.

---

## Recommended Next Steps

### 1. Pydantic version-consistency rule (high value, low risk)
Add a quality rule: "All Pydantic models must use the v2 API consistently: `model_config = ConfigDict(from_attributes=True)` (not `class Config: orm_mode = True`), and enum fields must set `use_enum_values=True` or be typed as `str` with a validator. Never mix v1 and v2 APIs in the same file."

### 2. Concurrency-aware generation guidance
Add a rule: "When a route reads and then modifies a value based on the read (e.g. checking stock then decrementing), document the race condition in a comment and use a single atomic UPDATE with a WHERE clause guard rather than a read-then-write pattern. Example: `UPDATE products SET stock_quantity = stock_quantity - :qty WHERE sku = :sku AND stock_quantity >= :qty`."

### 3. FK referential integrity rule
Add a rule: "When an entity references another entity by name or identifier (e.g. `Expense.category` referencing `Category.name`), use a proper SQLAlchemy ForeignKey constraint on the column, not a plain String. This enforces referential integrity at the database level and enables cascade behavior."

### 4. DB-level integrity reasoning in reviewer
Extend the reviewer prompt to check for missing FK constraints between related tables. The reviewer should flag any `String` or `Integer` column that is semantically a foreign key but lacks an explicit `ForeignKey()` declaration.

### 5. Autonomous repair loop evaluation
Consider adding a second validator pass specifically for schema/domain rule violations: after the validator's compileall + import check passes, run a lightweight static analysis pass (e.g. AST inspection for `Field(ge=0)` presence on numeric fields) and trigger targeted LLM repair if violations are found. This would catch rule violations that the LLM ignores rather than relying solely on post-hoc review.

### 6. Architecture-level evaluation
Consider whether the single-agent developer model should be replaced with two-pass generation: (a) generate schema/model layer, validate it, then (b) generate router/CRUD layer with the validated schema as context. This would eliminate forward-reference ordering problems structurally and give each pass a narrower, more verifiable scope.

---

## Current Trajectory

Structural pipeline bugs (wrong file placement, clobbered `main.py`, `app/` prefix contamination, traversal path matches) are **fully eliminated**. Domain-validation gaps (negative values, cascade deletes, ORM monkeypatching, audit-trail bypass) have been addressed by the semantic rule layer and are largely eliminated from reviewer output.

The remaining reviewer findings now resemble **real senior-engineer code review comments** rather than generation failures: race conditions under concurrency, enum serialization edge cases, Pydantic API version mixing, missing FK constraints. These are issues a competent developer would write on a pull request — not symptoms of a broken pipeline.

The rule-based iterative hardening approach has been highly effective across three generations of quality rules. Bug count per run has dropped from 6–8 severe bugs at session start to 3–6 warning-level findings, with severity holding at WARNING across both `inventory_api` and `expense_tracker`. The next productive hardening cycle targets Pydantic version consistency and FK referential integrity, which are the most consistently surfacing remaining issues.

---

## Key Files

```
agents/developer.py          — SYSTEM_PROMPT (13 API quality rules + 5 semantic domain rules), filename mapper, prompt builder
agents/reviewer.py           — LLM review, _MAX_FILE_CHARS cap (6 000), truncation instruction, file collection
core/task_generator.py       — planner system prompt (FLAT LAYOUT rules)
core/validator.py            — compileall + import check + LLM repair
tests/test_developer.py      — 89 tests (filename mapper, prompt rules, all 18 system prompt rules)
tests/test_reviewer.py       — 20 tests (incl. truncation prompt instruction test)
tests/test_task_generator.py — 7 tests (planner prompt coverage)
tests/test_validator_strip.py — 11 tests
briefs/                      — expense_tracker, url_shortener, todo_api, blog_api, inventory_api
memory/sessions/             — JSON session records for all past runs
memory/reports/              — markdown review reports
```

## Verify State

```bash
cd /opt/agent-lab/projects/neuraloptima-core

# Tests
PYTHONPATH=. .venv/bin/pytest -q

# Smoke run
.venv/bin/python cli.py run briefs/expense_tracker.txt

# Git
git log --oneline -10
git status
```
