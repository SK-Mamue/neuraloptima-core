# NeuralOptima — Architecture

## Pipeline overview

```
brief.txt
    │
    ▼
[TaskGenerator]          core/task_generator.py
  LLM: brief text → ordered list of Tasks
    │
    ▼
[DeveloperAgent]         agents/developer.py
  LLM: task title + description + current file tree → writes files
  Repeats for each Task in sequence
    │
    ▼
[ProjectValidator]       core/validator.py
  7-step deterministic + repair loop (see below)
    │
    ▼
[ReviewAgent]            agents/reviewer.py
  LLM: reads generated files → JSON review result
  severity: ok | warning | severe
  severe → exit 1
    │
    ▼
Session saved to memory/sessions/<id>.json
```

## Agent roles

| Agent | Model | Input | Output |
|---|---|---|---|
| TaskGenerator | claude-sonnet-4-6 | Brief text | Ordered `Task[]` list |
| DeveloperAgent | claude-sonnet-4-6 | Task + file tree | Writes files to project dir |
| ProjectValidator | None (AST) / claude-sonnet-4-6 (repair) | Project dir | Pass/fail + error list |
| ReviewAgent | claude-sonnet-4-6 | Generated files (capped 6 000 chars each) | JSON review result |

## Validation pipeline (7 steps)

All steps run in sequence. Any failure queues the responsible file for LLM repair, then all 7 steps re-run from step 1.

```
1. python_compile         — compileall syntax check on all generated .py files
2. pip_install            — install requirements.txt so imports resolve
3. app_import_check       — import every generated module; catches circular imports and missing deps
4. duplicate_enum         — AST scan: same enum class name in more than one file
5. dead_enum_variant      — AST scan: enum member with zero references outside its defining file
6. numeric_constraints    — AST scan: missing Field(gt=0)/Field(ge=0) on numeric schema fields;
                            unguarded int/float parameters in module-level CRUD helpers
7. audit_trail_bypass     — AST scan: audited field (stock_quantity, balance, …) appearing in an
                            Update/Patch schema or directly assigned in a generic update function,
                            when a history model (StockMovement, AuditLog, …) exists
8. referential_integrity  — AST scan: ORM _id fields without ForeignKey; plain String/Integer
                            fields whose names match an existing model class; relationship()
                            without a matching FK column; association Table columns without FK
```

Steps 1–3 target structure and syntax. Steps 4–8 target semantic correctness. Steps 6–8 return `(error_msg, Path)` pairs so the exact violating file is queued for repair rather than a heuristic guess.

## Repair loop

```
validate() returns errors
    │
    ├─ errors empty → done
    │
    └─ errors present
           │
           ▼
       collect failed files
       for each file:
           ask_claude(repair_prompt, context_files) → patched content
           write patched content back to project dir
           │
           ▼
       re-run all 7 validation steps from scratch
       (max iterations: 3)
```

Repair prompts include the full content of related context files (e.g. `models.py` is passed as context when repairing `schemas.py` for a duplicate enum).

## Quality control layers

| Layer | Mechanism | Reliability |
|---|---|---|
| Structural file placement | `_resolve_filename()` + planner FLAT LAYOUT rules | Deterministic |
| Syntax + import validity | `compileall` + `app_import_check` | Deterministic |
| Duplicate enum definitions | `_check_duplicate_enums()` AST scan | Deterministic |
| Dead enum variants | `_check_dead_enum_variants()` AST scan | Deterministic |
| Numeric field constraints | `_check_numeric_constraints()` AST scan | Deterministic |
| Audit-trail bypass | `_check_audit_trail_bypasses()` AST scan | Deterministic |
| Referential integrity | `_check_referential_integrity()` AST scan | Deterministic |
| Framework API correctness | Pydantic v2 prompt rules + reviewer enforcement | Probabilistic (high) |
| Domain validation | Semantic prompt rules (cascade, datetime) | Probabilistic (medium) |
| Semantic / concurrency | Reviewer LLM JSON findings | Probabilistic (lower) |

The architectural direction is to migrate items from the bottom of this table upward.

## Benchmark flow

```bash
.venv/bin/python cli.py run briefs/inventory_api.txt
# → generates project, validates, reviews, saves session + report

# Reports land in:
memory/reports/<session_id>.md        # reviewer JSON formatted as markdown
memory/sessions/<session_id>.json     # full session record
```

Quality trend signal: count `bugs_found` items in reviewer output across successive runs on the same brief. Target is zero `severe` findings and a declining `warning` count.

## Project structure

```
neuraloptima-core/
├── cli.py                        — entry point: python cli.py run <brief>
├── CLAUDE.md                     — Claude Code CLI working rules (auto-loaded)
├── pyproject.toml
│
├── core/
│   ├── models.py                 — ProjectBrief, Task, Session, ReviewResult, LogEntry
│   ├── orchestrator.py           — Brief → Tasks → execute → validate → review → save
│   ├── validator.py              — 7-step AST validator + LLM repair loop
│   ├── task_generator.py         — LLM task planner
│   ├── llm.py                    — bare ask_claude() wrapper
│   └── logger.py                 — structured JSONL + Rich console logging
│
├── agents/
│   ├── developer.py              — DeveloperAgent: writes project files task by task
│   └── reviewer.py               — ReviewAgent: LLM JSON review of generated project
│
├── tools/
│   ├── filesystem.py             — read_file, write_file, list_files (path-sandboxed)
│   └── shell.py                  — run_command (BLOCKED_COMMANDS safety list)
│
├── tests/
│   ├── test_developer.py         — 100 tests: filename mapper + all SYSTEM_PROMPT rules
│   ├── test_reviewer.py          — 23 tests: reviewer prompt coverage
│   ├── test_task_generator.py    — 7 tests: planner FLAT LAYOUT rules
│   └── test_validator_strip.py   — 76 tests: fence stripping + all AST validator helpers
│
├── briefs/                       — plain-text project briefs for benchmark runs
├── memory/sessions/              — JSON session records
├── memory/reports/               — markdown review reports
├── logs/                         — JSONL session logs
│
└── docs/
    ├── VISION.md                 — what NeuralOptima is and where it is going
    ├── ARCHITECTURE.md           — this file
    ├── HANDOFF.md                — active sprint state, test counts, next steps
    └── archive/                  — superseded planning documents
```

## Architectural maturity

The pipeline is feature-complete for a Phase 1 worker. The quality layer is past its initial probabilistic-only phase: 4 of the 7 validator steps are deterministic AST checks. The next maturity step is continuing to migrate medium-reliability probabilistic rules (FK integrity, concurrency, response_model completeness) into deterministic validator steps using the same `(error_msg, Path)` return pattern established in steps 6 and 7.

Context injection into LLM agents is exclusively through hardcoded `SYSTEM_PROMPT` strings in `agents/developer.py`, `agents/reviewer.py`, and `core/task_generator.py`. No doc files are read at runtime by any agent — new rules must be added directly to those strings.
