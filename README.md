# NeuralOptima Core

An AI Developer Worker that converts plain-text project briefs into complete, validated FastAPI backends.

**Input:** a brief describing what to build.  
**Output:** runnable Python project — models, schemas, CRUD, routes, requirements — validated and LLM-reviewed.

## Current maturity

Production-quality for the target use case (FastAPI + SQLAlchemy + Pydantic v2 + SQLite). The validation pipeline runs 7 deterministic checks before the LLM reviewer sees the output; any failure triggers targeted repair and a full re-validation cycle.

**Test suite:** 206 tests passing.  
**Validation:** 7-step AST pipeline (syntax, imports, duplicate enums, dead enum variants, numeric constraints, audit-trail bypasses) + LLM repair loop.  
**Benchmark briefs:** `inventory_api`, `expense_tracker`, `todo_api`, `blog_api`, `url_shortener`.

## Run a benchmark

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Generate, validate, and review a project
python cli.py run briefs/inventory_api.txt

# Results
cat memory/reports/<session_id>.md   # reviewer findings
cat memory/sessions/<session_id>.json # full session record
```

## Run the test suite

```bash
PYTHONPATH=. .venv/bin/pytest -q
```

## Active operational state

See `docs/HANDOFF.md` for current sprint status, test counts, known limitations, and next steps.

## Architecture

See `docs/ARCHITECTURE.md` for the full pipeline, validation steps, and quality control layer breakdown.
