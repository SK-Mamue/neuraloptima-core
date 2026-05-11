# NeuralOptima — Vision

## What it is

NeuralOptima is a deterministic AI Developer Worker: give it a plain-text project brief and it produces a complete, runnable FastAPI backend — models, schemas, CRUD, routes, requirements — validated and review-approved before it hands the result back.

**One input. One output. No manual scaffolding.**

## Long-term goal

A worker that can be trusted to generate production-grade backend code with no human review of every file. The generated project should be syntactically correct, semantically consistent, and free from the classes of bugs that LLMs reliably produce (enum divergence, missing field constraints, audit-trail bypasses, unsafe patterns). Achieving that requires systematically migrating quality control from probabilistic prompt rules to deterministic validation.

## Current phase

**Core Pipeline Hardening.**

The end-to-end pipeline exists and runs. The focus now is converting unreliable probabilistic rules into reliable deterministic checks — one class of bug at a time.

## Philosophy

**Deterministic validation over prompt rules.**  
A prompt rule fails silently. A validator fails loudly, stops the pipeline, and triggers targeted repair. Every rule that can be expressed as an AST check should be.

**Repair loops, not rejection.**  
When validation fails, the system queues the exact violating file for LLM repair with full context, then re-validates from scratch. The user never sees a broken project; they see either a passing one or a clear error.

**Controlled autonomy.**  
The agent can write any file and install any dependency. It cannot do anything outside its project directory. Shell commands pass through a safety blocklist. The repair loop has a finite iteration limit. Autonomous does not mean unbounded.

**Reliability over flashy demos.**  
A system that generates 5 correct projects is more valuable than one that generates 50 where 30 have subtle bugs. Benchmark runs measure both what passes and what the reviewer flags — trending toward zero reviewer findings is the target.

## Current focus

- AST-based deterministic validators (enum consistency, numeric constraints, audit-trail bypasses)
- Repair loop precision: return the exact violating file, not a heuristic guess
- Validator coverage: migrate medium-reliability probabilistic rules into deterministic steps
- Benchmark signal: use the reviewer finding count as the leading quality metric

## Non-goals (for now)

- Web dashboard or UI
- Multi-agent orchestration (planner + executor + critic as separate services)
- Vector database / embedding-based memory
- Deployment automation (Dockerfile generation, cloud push)
- OpenTelemetry / distributed tracing
- Redis, queues, or any networked infrastructure
