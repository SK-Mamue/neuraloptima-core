# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-11  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `c151bff` Validate API contract consistency  
**Test suite:** 264 tests, all passing

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
| `cbff6d5` | **Deterministic referential integrity validator** — `ProjectValidator.run()` gains an 8th check: `_check_referential_integrity()` scans all generated `.py` files using the `ast` module and detects four FK/referential integrity patterns. (1) ORM class fields ending in `_id` with `Column(Integer)` but no `ForeignKey(...)`. (2) ORM class fields whose names match an existing model class (e.g. `Expense.category = Column(String)` when `Category` exists) — semantically a reference but without a FK constraint. (3) `relationship("Target")` where the expected `target_id` FK column exists in the same class but has no `ForeignKey`, or is absent entirely. (4) Module-level association `Table(...)` with column names ending in `_id` but no `ForeignKey`. Initially returned `(error_msg, Path)` 2-tuples; caused SEVERE regression in expense_tracker when Pattern 2 repair only fixed models.py while CRUD/schemas still referenced the old field name. |
| `c792b54` | **FK repair scope expansion** — `_check_referential_integrity()` return type changed to `(error_msg, primary_file, extra_files)` 3-tuples. Pattern 2 (field name matches a model class — the rename case) now calls new `_files_referencing_field()` helper to scan all project `.py` files for `ast.Attribute`, `ast.Name`, and `ast.Constant` matches on the old field name, then returns all dependent files (schemas.py, crud/*.py) as `extra_files`. Step 8 wiring in `run()` adds both `src_file` and every file in `extra_files` to the `failed` set so LLM repair receives the full rename scope. Error message updated to explicitly describe the three-part rename: (1) models.py rename + FK + relationship, (2) schemas field type change, (3) CRUD/route `.field` → `.field_id` replacement. Patterns 1, 3, 4 continue to return `extra_files=[]` (local fixes, no rename). Adds `_files_referencing_field()` helper and 11 new tests (6 `TestFilesReferencingField`, 5 `TestFKRepairScope`). **Benchmark results restored:** inventory_api — WARNING (no change); expense_tracker — WARNING (restored from SEVERE; repair now correctly queues models.py + schemas.py + crud/expenses.py together). |
| `c151bff` | **Deterministic API contract consistency validator** — `ProjectValidator.run()` gains a 9th check: `_check_api_contract_consistency()` scans all generated `.py` files using the `ast` module and detects seven API contract violation patterns. (A) DELETE route with `status_code=204` and `response_model` declared — HTTP 204 means no body, the `response_model` is silently ignored. (B) POST route with `status_code=204` — POST creation must return 200 or 201 with a response body. (C) CRUD-style GET/POST routes (`get_*`, `list_*`, `read_*`, `create_*`) with no `response_model` — FastAPI cannot serialize, filter, or document the response without it. (D) Route whose name implies multiple items (`list_*`, `get_all_*`, `*_all`) but whose body returns a `dict` literal. (E) Route whose name implies a single item (`get_*` without plural suffix) but whose body returns a `list` literal. (F) Route handler that catches `IntegrityError`/`UniqueViolation` but raises `HTTPException(status_code=400)` — integrity violations must return 409 Conflict. (G) Pydantic Create/Update schema has `field: str` where ORM model stores `field_id` as a FK integer column — clients submit a string but the database expects an ID. Patterns D/E introduce three new module-level helpers: `_is_list_response_model`, `_route_body_returns_dict`, `_route_body_returns_list`. Pattern G uses `_CONTRACT_SKIP_SCHEMA_KEYWORDS` to skip response/summary/aggregate schemas (e.g. `SummaryItem`) that legitimately carry human-readable string labels. Returns `(error_msg, Path)` 2-tuples for precise per-file repair targeting. Adds 22 new tests (9 `TestApiContractHelpers`, 12 `TestCheckApiContractConsistency` including SummaryItem false-positive regression test). **Benchmark results:** inventory_api — WARNING, 0 API contract violations. expense_tracker — WARNING, 0 API contract violations (SummaryItem false positive correctly suppressed by `_CONTRACT_SKIP_SCHEMA_KEYWORDS`). |

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

## Validation Pipeline (9 steps)

```
1. python_compile           — syntax check via compileall
2. pip_install              — install requirements.txt so import check resolves deps
3. app_import_check         — import all generated modules; catch missing deps / circular imports
4. duplicate_enum           — ast scan for enum class names defined in more than one file (deterministic)
5. dead_enum_variant        — ast scan for enum members with no external references (deterministic)
6. numeric_constraints      — ast scan for missing or weak Field bounds and unguarded int parameters (deterministic)
7. audit_trail_bypass       — ast scan for audited fields in Update schemas or generic update funcs (deterministic)
8. referential_integrity    — ast scan for FK/referential integrity violations:
                              _id fields without ForeignKey, plain String fields referencing a model,
                              relationship() with no FK column, association Table columns without FK
                              returns (error_msg, primary_file, extra_files) 3-tuples; Pattern 2
                              (field-rename) includes all referencing files in extra_files so the
                              full rename scope is queued for repair together
9. api_contract_consistency — ast scan for cross-layer API contract violations (deterministic):
                              (A) DELETE 204 + response_model (body on No Content)
                              (B) POST 204 (creation should return 200 or 201)
                              (C) CRUD-style route (get_*, list_*, create_*) missing response_model
                              (D) list-semantics route (list_*, get_all_*) body returns dict literal
                              (E) single-item route (get_* singular) body returns list literal
                              (F) IntegrityError/UniqueViolation caught → HTTPException(400) raised
                                  (must be 409 Conflict)
                              (G) Pydantic Create/Update schema has field: str where ORM has
                                  field_id FK integer column (schema/ORM naming mismatch)
                              response/summary/aggregate schemas skipped via _CONTRACT_SKIP_SCHEMA_KEYWORDS
   → any failure → LLM repair → re-run all 9 steps
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

**Step 9** detects cross-layer API contract violations. It returns `(error_msg, Path)` 2-tuples. The check runs in two passes: (1) collect ORM `_id` FK fields to build `orm_fk_base_names` for Pattern G, then (2) scan each file for route decorator mismatches (Patterns A–F) and schema field naming mismatches (Pattern G). Route-level checks (A–F) operate on the decorator keywords (`response_model`, `status_code`) and the function body AST. Schema-level check (G) skips classes whose names contain any of `_CONTRACT_SKIP_SCHEMA_KEYWORDS` (`"read"`, `"response"`, `"out"`, `"summary"`, `"report"`, `"detail"`, `"info"`, `"stat"`) to avoid false-positives on aggregate/read schemas like `SummaryItem`.

New helpers introduced by step 9:
- `_is_list_response_model(node)` — returns True if the AST node is `List[X]` or `list[X]`.
- `_route_body_returns_dict(func_node)` — walks the function body for a `return {}` dict literal.
- `_route_body_returns_list(func_node)` — walks the function body for a `return []` list literal or list comprehension.

---

## Current System Status

- **Tests:** 264 passing, 0 failing
- **`inventory_api` severity:** WARNING — no FK violations fired; dead enum occasionally caught by step 5 and repaired; no API contract violations. Remaining warnings: concurrency race on stock mutations, SQLAlchemy deprecation import, datetime handling.
- **`expense_tracker` severity:** WARNING — step 8 catches `Expense.category` FK mismatch and repairs consistently across models + schemas + CRUD; step 9 found 0 API contract violations (SummaryItem false positive suppressed correctly).
- **Structural pipeline failures:** None.
- **Framework API issues:** Eliminated (Pydantic v2 enforced; deprecated datetime patterns removed).
- **Enum consistency:** Deterministic. Steps 4–5 catch duplicate definitions and dead variants.
- **Numeric constraints:** Deterministic. Step 6 enforces `Field(gt=0)` / `Field(ge=0)` per field category and guards on internal helper parameters.
- **Referential integrity:** Deterministic. Step 8 catches FK violations at model, association table, and relationship levels. Pattern 2 repairs are dependency-aware.
- **API contract consistency:** Deterministic. Step 9 catches DELETE/POST status code mismatches, missing response_model on CRUD routes, list/dict return shape mismatches, IntegrityError→400 errors, and schema/ORM FK naming mismatches.
- **Reviewer noise:** Eliminated for both inventory and expense domains.

---

## Remaining Known Limitations

### TOCTOU race on stock mutations
The sell and restock endpoints read stock quantity, check sufficiency, then write — without a row-level lock. Concurrent requests can both pass the check before either commits, producing negative stock. This requires an atomic `UPDATE ... WHERE stock_quantity >= :qty` pattern or a version counter; SQLite does not support `SELECT FOR UPDATE`.

### Internal helpers without quantity guards
Module-level CRUD helpers that accept raw `quantity: int` without a `if quantity <= 0: raise` guard can silently corrupt stock if called by internal paths that bypass the public API validation. Step 6 now flags these deterministically.

### Authentication absence
All generated APIs expose all endpoints publicly. Authentication is a brief-level gap, not a generation failure.

---

## Recommended Next Steps

### 1. FK existence-check validator
Add an AST check that verifies `ForeignKey("tablename.id")` references use real table names from the same project. Currently the validator ensures `ForeignKey(...)` is present — not that the target table exists. A mismatch causes a runtime `OperationalError` on first connect. Detection: parse the string argument of each `ForeignKey(...)` call and confirm the table prefix matches a `__tablename__` attribute in any ORM model.

### 2. Atomic stock mutation / concurrency validator
Add an AST detector for read-modify-write patterns on numeric fields (`stock_quantity`, `balance`, `count`) without an atomic SQL UPDATE with a WHERE guard. The tell: a CRUD function reads a field, branches on its value, then updates it in separate statements. Flag the CRUD file for repair to replace with `UPDATE ... SET field = field + :delta WHERE id = :id`.

### 3. Response_model completeness expansion
Extend step 9 Pattern C: when a route has `response_model=SchemaWithRelationships`, check whether the CRUD function uses `joinedload`/`selectinload` for the nested fields the schema declares. Flag routes where the ORM query is missing the required eager load and queue the CRUD file for repair.

### 4. Semantic dependency graph repair expansion
Generalise `_files_referencing_field()` into a full symbol-rename dependency graph. Given any renamed field, function, or class, walk all project files and return the complete transitive repair set. Apply to FK field renames, schema class renames, and CRUD function signature changes.

### 5. Auth/security validator layer
Add a lightweight AST check that flags publicly exposed endpoints (no `Depends(get_current_user)` or similar) and destructive operations (DELETE, PUT without auth guard). Severity: WARNING rather than blocking repair — auth gaps are brief-level gaps, but surfacing them deterministically would move them out of the reviewer's probabilistic findings.

### 6. README/documentation sync validator (optional)
After repair runs, detect cases where the generated README documents endpoints or status codes that no longer exist in the route files. Flag README for re-generation so documentation stays in sync with the actual API surface.

---

## Current Trajectory

The pipeline has progressed through three distinct maturity phases: **syntax validation → structural repair → semantic cross-layer consistency enforcement**. The earliest deterministic steps (4–5) caught intra-file enum problems. Steps 6–7 extended that to schema-level numeric and domain constraints. Steps 8–9 now enforce correctness *across* file boundaries: referential integrity ensures ORM relationships are wired correctly; API contract consistency ensures the route layer, schema layer, and ORM layer agree on field names, status codes, and return shapes.

The downstream repair flow handles all new steps automatically — each new check only needs a detection rule and a structured error message with the violating file path. No new repair infrastructure has been required since step 6.

The quality control layers now stack as follows:

| Layer | Mechanism | Reliability |
|-------|-----------|-------------|
| Structural correctness | `_resolve_filename`, planner FLAT LAYOUT rules | Deterministic |
| Syntax + import validity | `compileall` + `app_import_check` | Deterministic |
| Duplicate enum definitions | `_check_duplicate_enums()` AST scan | Deterministic |
| Dead enum variants | `_check_dead_enum_variants()` AST scan | Deterministic |
| Numeric field constraints | `_check_numeric_constraints()` AST scan | Deterministic |
| Audit-trail bypasses | `_check_audit_trail_bypasses()` AST scan | Deterministic |
| Referential integrity | `_check_referential_integrity()` AST scan | Deterministic |
| API contract consistency | `_check_api_contract_consistency()` AST scan | Deterministic |
| Framework API correctness | Pydantic v2 prompt rules + reviewer enforcement | Probabilistic (high) |
| Domain validation | Semantic prompt rules (cascade, datetime) | Probabilistic (medium) |
| Semantic/concurrency | Reviewer LLM findings | Probabilistic (lower) |

The validator now has 6 deterministic AST steps (4–9). The project is evolving from syntax-level checking toward full cross-layer semantic consistency: step 9 is the first validator step that reasons about contracts *between* the route layer, schema layer, and ORM layer simultaneously. The natural next steps are FK existence validation (confirming FK target tables exist) and response_model completeness (confirming CRUD queries eager-load nested schema fields), which require the same cross-file reference scanning pattern already established by `_files_referencing_field()` and `orm_fk_base_names`.

---

## Key Files

```
agents/developer.py           — SYSTEM_PROMPT (13 API + 5 semantic + 5 Pydantic v2 + 4 DB enum + 4 single-source rules), filename mapper
agents/reviewer.py            — LLM review, truncation + Pydantic + DB enum + single-source reviewer instructions
core/validator.py             — 9-step validator: compileall, pip install, import check, duplicate enum, dead enum, numeric constraints, audit-trail bypass, referential integrity, API contract consistency + LLM repair
core/task_generator.py        — planner system prompt (FLAT LAYOUT rules)
tests/test_developer.py       — 100 tests (filename mapper, prompt rules, all 31 system prompt rules)
tests/test_reviewer.py        — 23 tests (truncation + Pydantic + DB enum + single-source reviewer prompt tests)
tests/test_task_generator.py  — 7 tests (planner prompt coverage)
tests/test_validator_strip.py — 140 tests (fence stripping + enum helpers + numeric constraint helpers + audit helpers + referential integrity helpers + FK repair scope helpers + API contract helpers)
briefs/                       — expense_tracker, url_shortener, todo_api, blog_api, inventory_api
memory/sessions/              — JSON session records for all past runs
memory/reports/               — markdown review reports
```

## Documentation Layer (restructured 2026-05-11)

The project documentation was reorganised. The new authoritative human-readable references are:

| File | Role |
|---|---|
| `docs/VISION.md` | What NeuralOptima is, long-term goal, philosophy, non-goals |
| `docs/ARCHITECTURE.md` | Pipeline flow, agent roles, all 9 validation steps, quality layer table, project structure |
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
