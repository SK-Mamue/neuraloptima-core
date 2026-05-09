# NeuralOptima Core — Handoff Summary

**Date:** 2026-05-09  
**Branch:** `master` — clean, in sync with `origin/master`  
**Last commit:** `38fc0c2` Map 'Create project structure' tasks to .gitignore  
**Test suite:** 81 tests, all passing

---

## Current Project Status

The pipeline is end-to-end functional:

```
Brief (txt) → Task planner (LLM) → DeveloperAgent (generates files)
           → ProjectValidator (compileall + import check + auto-repair)
           → ReviewAgent (LLM JSON review, severe = exit 1)
```

Five briefs exercised successfully: `test_brief`, `url_shortener`, `expense_tracker`, `todo_api`, `blog_api`.  
`inventory_api` runs but the LLM-generated code triggered a legitimate severe review (wrong route parameter type — real bug in generated code, not a pipeline problem).

---

## Fixes Completed This Session (in order)

| Commit | Fix |
|--------|-----|
| `c69a9bc` | Reviewer now scans `crud/` and `routers/` subdirs; per-file 3k char cap to avoid rate limits |
| `614257d` | Reviewer false-positive: inject file tree into prompt as ground truth; add `utils.py` to reviewed files |
| `33ae39e` | Added `todo_api.txt` and `blog_api.txt` briefs |
| `fd51570` | Filename mapper: detect explicit `.py` literal in title (e.g. "Implement crud.py") before structural detection strips the dot and produces `crud/py.py` |
| `38fc0c2` | Map `structure`/`scaffold`/`layout` keywords → `.gitignore` so "Create project structure" tasks generate a useful file instead of silently skipping at 0.0s |

---

## Current Known Issue

**Inventory API generates broken routes** — the LLM uses integer `product_id` path parameters instead of string `sku` as specified in the brief. This is a generation quality problem, not a pipeline bug. The reviewer correctly catches it as severe.

Root cause: task descriptions say "Create app/models/models.py importing Base from app/db/database.py" — the LLM follows the `app/` prefix pattern in descriptions and generates imports like `from app.models.models import ...`, which then fail validation and trigger a repair cycle. The IMPORT RULES in the prompt are being ignored when the descriptions themselves contain `app/` paths.

---

## Exact Next Step

Fix the planner prompt to strip `app/` prefixes from task descriptions before they reach the developer agent.

The task planner (LLM) is generating descriptions like:
> "Create app/routers/products.py. Import models from app/models/models.py..."

These `app/` paths in the *description* override the IMPORT RULES in the developer prompt. Fix options:

1. **Post-process task descriptions** after LLM planning: strip `app/X.py` → `X.py` and `from app.X import` → `from X import` with a regex pass in `core/planner.py` before tasks are handed to the developer.
2. **Strengthen the planner prompt** in `core/planner.py` to instruct the LLM not to use `app/` prefixes in task descriptions.

Option 2 is lower risk. Look at `core/planner.py` — add an explicit instruction:  
> "Do not use 'app/' path prefixes in task descriptions. The project uses a flat layout — all files are at the root or in named subdirectories (routers/, crud/)."

---

## Verify State

```bash
cd /opt/agent-lab/projects/neuraloptima-core

# Tests
PYTHONPATH=. .venv/bin/pytest -q

# Quick smoke run (expense tracker — most stable brief)
.venv/bin/python cli.py run briefs/expense_tracker.txt

# Git
git log --oneline -6
git status
```

---

## File Map (key files only)

```
agents/developer.py     — file generation, filename mapper, prompt builder
agents/reviewer.py      — LLM review, file collection, file tree injection
core/planner.py         — task planning prompt (next fix target)
core/validator.py       — compileall + import check + LLM repair
core/tool_registry.py   — subprocess tools using sys.executable
tests/test_developer.py — 49 tests (filename mapper, prompt, fence/prose stripping)
tests/test_reviewer.py  — 19 tests (parse, collect_files, build_prompt, review)
tests/test_validator_strip.py — 11 tests (_strip_fences repair path)
briefs/                 — expense_tracker, url_shortener, todo_api, blog_api, inventory_api
```
