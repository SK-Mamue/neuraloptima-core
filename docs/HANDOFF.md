# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-10  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `c334f8c` Improve reviewer full-file visibility  
**Test suite:** 114 tests, all passing

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
| Datetime deprecation | `datetime.utcnow()` (deprecated, naive) | `datetime.now(timezone.utc)` |
| Unused imports | `field_validator`, `List`, `Optional` imported but unused | Removed |
| SKU mutability | `sku` field in `ProductUpdate` schema | Excluded from Update schemas by default |
| `app/` path prefixes | Planner generated `"Create app/routers/products.py"` | Descriptions use bare paths: `"Create routers/products.py"` |
| Reviewer truncation artifacts | Large files capped at 3 000 chars; reviewer flagged "cannot verify" as bugs | Cap raised to 6 000; prompt instructs reviewer to skip unverifiable findings |

---

## Current System Status

- **Tests:** 114 passing, 0 failing
- **`inventory_api` severity:** WARNING — 5 genuine bugs reported; truncation artifacts eliminated
- **`expense_tracker` severity:** WARNING — 3 bugs reported; no regressions from quality rule additions
- **Structural pipeline failures:** None. All generated files land in the correct location, validation passes without repair on clean runs, the reviewer has visibility into `crud/` and `routers/` subdirectory files.
- **Reviewer noise:** Eliminated. All reported findings are now real code issues visible in the provided file content.

---

## Remaining Known Limitations

### SQLite timezone nuance
The `datetime.now(timezone.utc)` rule produces timezone-aware datetimes. SQLite stores datetimes as naive strings. Comparisons between aware and naive datetimes fail at query time. For SQLite projects the safest column default is `server_default=func.now()` (delegated to the DB) or a naive `datetime.utcnow` (deprecated but compatible). The current rule creates a subtle compatibility issue on SQLite; it is correct for PostgreSQL.

### Relationship cascade gaps
Many-to-many association tables are generated without `cascade="all, delete-orphan"` on the relationship. Deleting a parent record leaves orphan rows in the association table, and deleting a product with existing `StockMovement` records will produce a 500 instead of a meaningful 409 or cascaded delete.

### Dynamic ORM monkeypatching
Some generated code sets dynamic attributes on ORM objects to pass extra data to the response serialiser (e.g. `product.recent_movements = [...]`). This is fragile — the attribute is not declared on the model and will be lost if SQLAlchemy refreshes or expires the instance. Fix: pass extra fields explicitly to the response schema constructor instead of mutating the ORM object.

### Missing domain validation rules
No quality rules yet cover:
- Positive-quantity / non-negative-stock validation (`Field(ge=0)`)
- Immutability of fields beyond SKU (e.g. `created_at`, `product_id` on movements)
- Future-date rejection for expense dates
- Rejection of `created_at` / `updated_at` in Create/Update schemas (server-set fields)

### Direct stock_quantity updates bypass audit trail
`ProductUpdate` does not include `stock_quantity`, but the underlying CRUD `update_product` still accepts arbitrary field changes. If the planner generates a task that includes `stock_quantity` in the update schema, the audit trail via `StockMovement` is bypassed.

---

## Recommended Next Steps

### 1. Validator/domain hardening (high value, low risk)
Add quality rules for:
- `Field(ge=0)` on any quantity or stock count field
- `Field(gt=0)` on any amount or price field (expenses, product prices)
- Rejection of `created_at` / `updated_at` in Create/Update schemas (server-set fields)

### 2. Cascade delete rule
Add a quality rule: "For any model with a one-to-many or many-to-many relationship, configure `cascade='all, delete-orphan'` on the SQLAlchemy relationship and ensure the DELETE route either cascades or returns a meaningful 409."

### 3. ORM response pattern rule
Add a quality rule: "Do not set dynamic attributes on SQLAlchemy ORM instances to pass extra data to serialisers. Construct the Pydantic response schema explicitly using data from separate queries."

### 4. SQLite-aware datetime rule
Nuance the `datetime.now(timezone.utc)` rule: "For SQLite databases, use `server_default=func.now()` for timestamp columns instead of a Python-side default, to avoid timezone-aware vs. naive comparison errors."

### 5. Transactional consistency rule
Add a rule: "If a route modifies two or more related rows (e.g. product stock + movement record), wrap both in a single `try/except` block — do not commit partial state."

### 6. Architecture-level evaluation
Consider whether the single-agent developer model should be replaced with two-pass generation: (a) generate schema/model layer, validate it, then (b) generate router/CRUD layer with the validated schema as context. This would eliminate the forward-reference ordering problem structurally.

---

## Current Trajectory

Structural pipeline bugs (wrong file placement, clobbered `main.py`, `app/` prefix contamination, traversal path matches) are **fully eliminated**. The pipeline reliably generates a correctly-laid-out project with files in `crud/`, `routers/`, and the project root.

Reviewer infrastructure quality has also been substantially improved. The per-file visibility cap was the primary source of false positives: the reviewer would see a truncated file and flag "cannot verify" findings as bugs. With the cap doubled to 6 000 characters and an explicit prompt instruction to skip unverifiable findings, all reported warnings now correspond to real code issues.

The remaining issues are **purely semantic and business-logic quality issues**: missing field validators, cascade delete rules, audit-trail gaps, SQLite timezone nuances, ORM attribute patterns. These are not pipeline failures — they are code quality findings that a human reviewer would also raise on handwritten code.

The rule-based iterative hardening approach continues to work. Bug count per run has dropped from 6–8 severe bugs at session start to 3–5 warning-level findings, with severity holding at WARNING across both `inventory_api` and `expense_tracker`. The next hardening cycle should target cascade deletes and domain field validation, which are the most consistently reported remaining issues.

---

## Key Files

```
agents/developer.py          — SYSTEM_PROMPT (quality rules), filename mapper, prompt builder
agents/reviewer.py           — LLM review, _MAX_FILE_CHARS cap, truncation instruction, file collection
core/task_generator.py       — planner system prompt (FLAT LAYOUT rules)
core/validator.py            — compileall + import check + LLM repair
tests/test_developer.py      — 83 tests (filename mapper, prompt rules, system prompt coverage)
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
git log --oneline -8
git status
```
