# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-10  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `545ceec` Add rules for remaining inventory API warnings  
**Test suite:** 113 tests, all passing

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

---

## Current System Status

- **Tests:** 113 passing, 0 failing
- **`inventory_api` severity:** WARNING (was SEVERE at session start)
- **`expense_tracker` severity:** WARNING (was SEVERE at previous session start; regression check confirms no regressions from quality rule additions)
- **Structural pipeline failures:** None. All generated files land in the correct location, validation passes without repair on clean runs, the reviewer has visibility into `crud/` and `routers/` subdirectory files.

---

## Remaining Known Limitations

### Reviewer truncation artifacts
The reviewer caps file content at ~3 000 characters per file. For large generated files (complex router or CRUD modules) the reviewer sees a truncated view and flags "cannot verify" as a bug. This is a reviewer infrastructure issue, not a generation problem. Fix: increase the per-file cap or split large files.

### Dynamic ORM monkeypatching
Some generated code sets dynamic attributes on ORM objects to pass extra data to the response serialiser (e.g. `product.recent_movements = [...]`). This is fragile — the attribute is not declared on the model and will be lost if SQLAlchemy refreshes or expires the instance. Fix: pass extra fields explicitly to the response schema constructor instead of mutating the ORM object.

### SQLite timezone nuance
The `datetime.now(timezone.utc)` rule produces timezone-aware datetimes. SQLite stores datetimes as naive strings. Comparisons between aware and naive datetimes fail at query time. For SQLite projects the safest column default is `server_default=func.now()` (delegated to the DB) or a naive `datetime.utcnow` (deprecated but compatible). The current rule creates a subtle compatibility issue on SQLite; it is correct for PostgreSQL.

### Missing domain validation rules
No quality rules yet cover:
- Positive-quantity / non-negative-stock validation (`Field(ge=0)`)
- Immutability of fields beyond SKU (e.g. `created_at`, `product_id` on movements)
- Future-date rejection for expense dates

### Relationship cascade gaps
Many-to-many association tables are generated without `cascade="all, delete-orphan"` on the relationship. Deleting a parent record leaves orphan rows in the association table.

### Direct stock_quantity updates bypass audit trail
`ProductUpdate` does not include `stock_quantity`, but the underlying CRUD `update_product` still accepts arbitrary field changes. If the planner generates a task that includes `stock_quantity` in the update schema, the audit trail via `StockMovement` is bypassed.

---

## Recommended Next Steps

### 1. Validator/domain hardening (high value, low risk)
Add quality rules for:
- `Field(ge=0)` on any quantity or stock count field
- `Field(gt=0)` on any amount or price field (expenses, product prices)
- Rejection of `created_at` / `updated_at` in Create/Update schemas (server-set fields)

### 2. Reviewer truncation handling (infrastructure)
Increase the per-file char cap in `agents/reviewer.py` from 3 000 to ~6 000, or split review into two passes (schema + model layer first, router layer second) to reduce false "cannot verify" findings.

### 3. ORM response pattern rule
Add a quality rule: "Do not set dynamic attributes on SQLAlchemy ORM instances to pass extra data to serialisers. Construct the Pydantic response schema explicitly using data from separate queries."

### 4. Transactional consistency rule
Add a rule: "If a route modifies two or more related rows (e.g. product stock + movement record), wrap both in a single `try/except` block — do not commit partial state."

### 5. SQLite-aware datetime rule
Nuance the `datetime.now(timezone.utc)` rule: "For SQLite databases, use `server_default=func.now()` for timestamp columns instead of a Python-side default, to avoid timezone-aware vs. naive comparison errors."

### 6. Architecture-level evaluation
Consider whether the single-agent developer model should be replaced with two-pass generation: (a) generate schema/model layer, validate it, then (b) generate router/CRUD layer with the validated schema as context. This would eliminate the forward-reference ordering problem structurally.

---

## Current Trajectory

Structural pipeline bugs (wrong file placement, clobbered `main.py`, `app/` prefix contamination, traversal path matches) are **fully eliminated**. The pipeline reliably generates a correctly-laid-out project with files in `crud/`, `routers/`, and the project root.

The remaining issues are **increasingly semantic and business-logic quality issues**: missing field validators, audit-trail gaps, SQLite timezone nuances, cascade delete rules. These are not pipeline failures — they are code quality findings that a human reviewer would also raise on handwritten code.

The rule-based iterative hardening approach is working. Each round of rules eliminates the bugs visible in that review cycle, and the next cycle surfaces the next layer of issues. Bug count per run has dropped from 6–8 severe bugs to 5–7 warning-level findings, with severity holding at WARNING across both `inventory_api` and `expense_tracker`.

---

## Key Files

```
agents/developer.py          — SYSTEM_PROMPT (quality rules), filename mapper, prompt builder
agents/reviewer.py           — LLM review, file collection, file tree injection
core/task_generator.py       — planner system prompt (FLAT LAYOUT rules)
core/validator.py            — compileall + import check + LLM repair
tests/test_developer.py      — 83 tests (filename mapper, prompt rules, system prompt coverage)
tests/test_reviewer.py       — 19 tests
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
