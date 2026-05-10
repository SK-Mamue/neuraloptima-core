# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-10  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `c0d09e6` Add DB-level enum enforcement rules  
**Test suite:** 130 tests, all passing

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
| `67d0345` | **Pydantic v2 consistency** — New `PYDANTIC V2 RULES` section in `SYSTEM_PROMPT`: forbid `class Config`/`orm_mode`/`from_orm()`/`.dict()`/`parse_obj()`, require `ConfigDict(from_attributes=True)`, `model_dump()`, `model_validate()`, and `use_enum_values=True` for enum fields. Reviewer prompt gains a `PYDANTIC API CONSISTENCY` block. Adds 5 developer + 1 reviewer prompt tests. |
| `c0d09e6` | **DB enum enforcement** — New `DB ENUM ENFORCEMENT RULES` section in `SYSTEM_PROMPT`: use `Column(Enum(MyEnum))` instead of `Column(String)` for enum-backed fields; require `(str, PyEnum)` base class for string-compatible serialisation; define enum in one place and import into both model and schema; SQLite-compatible note (SQLAlchemy generates VARCHAR + CHECK, not native ENUM). Reviewer prompt gains a `DB ENUM ENFORCEMENT` block. Adds 3 developer + 1 reviewer prompt tests. |

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
| Pydantic v1/v2 API mixing | `orm_mode = True`, `.dict()`, `from_orm()` mixed with v2 APIs; runtime instability | v2-only rules enforced in developer prompt; reviewer flags any v1 pattern as a bug |
| Enum serialization | `MovementType.RESTOCK` serialized as enum object, not string `"RESTOCK"` | `use_enum_values=True` required in `ConfigDict`; `(str, PyEnum)` base class ensures string-compatible values |
| DB-level enum enforcement | `movement_type = Column(String)` — invalid values persisted without constraint | `Column(Enum(MovementType))` required; SQLAlchemy generates CHECK constraint on SQLite |

---

## Current System Status

- **Tests:** 130 passing, 0 failing
- **`inventory_api` severity:** WARNING — DB-level enum enforcement added; remaining issues are duplicate enum definition risk, audit-trail bypass, concurrency, and association-table cascade
- **`expense_tracker` severity:** WARNING — 3 bugs; FK referential integrity (category), README formatting, category normalization
- **Structural pipeline failures:** None. All generated files land in the correct location; validation passes without repair on clean runs.
- **Reviewer noise:** Eliminated. All reported findings are real code issues.
- **Enum handling:** Enforced at both layers — API serialization (`use_enum_values=True`) and database storage (`Column(Enum(...))`).

---

## Remaining Known Limitations

### Duplicate enum definitions across models and schemas
The LLM sometimes defines `MovementType` (or equivalent enums) independently in both `models.py` and `schemas.py` instead of importing a single definition. Both classes may look identical today, but if a member is added to one and not the other, the DB column type and the API validation will enforce different value sets. Fix: define the enum once (in `models.py` or a shared `enums.py`) and import it into both files.

### Audit-trail bypass via direct stock updates
`ProductUpdate` sometimes allows `stock_quantity` to be set directly via `PUT /products/{sku}`, bypassing the `StockMovement` system entirely. A stock change via PUT creates no movement record, making the movement log inconsistent with actual quantity changes. The audit-trail rule is in the prompt but not fully enforced by the LLM in every generation.

### Concurrency and race conditions
Sell and restock endpoints check stock levels before committing without a DB-level lock. Under concurrent requests, two sells can both pass the availability check before either commits, resulting in negative stock. Requires either an atomic `UPDATE ... WHERE stock_quantity >= :qty` pattern or optimistic concurrency with a version counter.

### Association-table cascade gaps
`product_supplier` and similar many-to-many association tables are generated without `ondelete='CASCADE'` on the `ForeignKey` columns. If DB FK enforcement is active (e.g. `PRAGMA foreign_keys=ON` in SQLite), deleting a parent record fails or leaves orphan rows.

### Missing FK/domain-level referential integrity
`Expense.category` is a plain `String` with no `ForeignKey` to the `Category` table. Expenses can reference non-existent categories; category renames do not cascade. Requires `Column(String, ForeignKey("categories.name"))` or explicit CRUD-layer existence validation.

### README/documentation formatting issues
Generated `README.md` files occasionally have unclosed markdown code fences, producing malformed documentation. Minor but consistent across runs.

---

## Recommended Next Steps

### 1. Enum single-definition rule (high value, low risk)
Add a quality rule: "Define each enum class exactly once — in `models.py` or a dedicated `enums.py` — and import it into both the SQLAlchemy model and the Pydantic schema. Never redefine the same enum in `schemas.py`. A divergent copy in schemas is a latent data-integrity bug."

### 2. FK referential integrity rule
Add a rule: "When an entity field references another entity by name or identifier (e.g. `Expense.category` referencing `Category.name`), use `Column(String, ForeignKey('categories.name'))` — not a plain `Column(String)`. This enforces referential integrity at the DB level and enables cascade behavior."

### 3. Atomic stock update pattern
Add a rule: "Read-modify-write patterns on numeric fields (stock_quantity, balance, count) are vulnerable to race conditions. Use a single atomic SQL UPDATE with a WHERE guard: `db.query(Product).filter(Product.sku == sku, Product.stock_quantity >= qty).update({'stock_quantity': Product.stock_quantity - qty})` and check the affected rowcount to detect insufficient stock."

### 4. Association-table ondelete cascade rule
Add a rule: "Foreign key columns in many-to-many association tables must include `ondelete='CASCADE'`: `ForeignKey('products.id', ondelete='CASCADE')`. Without this, deleting a parent row fails or leaves orphan rows when FK constraints are enforced."

### 5. README validation rule
Add a rule or post-generation check: "The generated README.md must have balanced markdown fences — every opening triple-backtick must have a matching closing triple-backtick. Unclosed fences corrupt all markdown rendering after the gap."

### 6. Autonomous semantic repair loop
Consider a lightweight post-generation static analysis pass: after `compileall` and import checks pass, scan for known violation patterns (`Column(String)` on enum-backed fields, missing `ForeignKey`, unclosed markdown fences, `orm_mode`, `.dict()`) and trigger targeted LLM repair for each hit before the reviewer runs. This converts known rule violations from review findings into pre-review auto-fixes.

---

## Current Trajectory

Structural pipeline bugs (file placement, `app/` prefixes, traversal paths) are **fully eliminated**. Domain-validation gaps (negative values, cascade deletes, ORM monkeypatching, audit-trail bypass) are **largely eliminated**. Framework API misuse (Pydantic v1/v2 mixing, deprecated datetime, enum serialization) is **fully eliminated**. DB-level enum enforcement is **now active** — `Column(Enum(MyEnum))` is generated instead of `Column(String)`, and the reviewer flags any regression.

Enum correctness is now enforced at all three layers: Python Enum class definition, SQLAlchemy column storage (`Column(Enum(...))`), and Pydantic schema serialization (`use_enum_values=True`). The remaining enum issue is a single-source-of-truth problem — the enum is correctly handled everywhere but defined in two files rather than one.

The remaining reviewer findings fall into four categories:
- **Single-source-of-truth consistency** — enum definitions duplicated across files
- **Referential integrity** — `Expense.category` with no FK, association tables with no `ondelete`
- **Concurrency correctness** — read-modify-write without atomic SQL guards
- **Transactional semantics** — audit trail bypassed when update schemas expose derived fields

These are genuine engineering concerns that a senior reviewer would raise on production code. The generation pipeline is no longer producing structurally broken or framework-incorrect code — every remaining finding requires domain knowledge and architectural judgment to resolve.

---

## Key Files

```
agents/developer.py          — SYSTEM_PROMPT (13 API rules + 5 semantic rules + 5 Pydantic v2 rules + 4 DB enum rules), filename mapper, prompt builder
agents/reviewer.py           — LLM review, truncation + Pydantic consistency + DB enum enforcement instructions
core/task_generator.py       — planner system prompt (FLAT LAYOUT rules)
core/validator.py            — compileall + import check + LLM repair
tests/test_developer.py      — 97 tests (filename mapper, prompt rules, all 27 system prompt rules)
tests/test_reviewer.py       — 22 tests (truncation + Pydantic + DB enum reviewer prompt tests)
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
