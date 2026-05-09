# External Repo Analysis: open-multi-agent vs NeuralOptima Core

**Reference:** https://github.com/JackChen-me/open-multi-agent  
**Date:** 2026-05-09  
**Purpose:** Extract useful architectural patterns — do NOT copy blindly.

---

## What open-multi-agent is

TypeScript-native multi-agent orchestration framework. Converts goals into dependency-aware task DAGs,
dispatches tasks across a named agent pool, and supports 10+ LLM providers. Three runtime deps:
`@anthropic-ai/sdk`, `openai`, `zod`.

---

## 8-Dimension Analysis

### 1. Task Queue

**Their approach:**  
`TaskQueue` (src/task/queue.ts) — event-driven, dependency-aware. Tasks carry a `dependsOn: string[]`
field. On task completion, the queue scans blocked tasks and promotes any whose dependencies are now
fully satisfied. Emits typed events: `task:ready`, `task:complete`, `task:failed`, `task:skipped`,
`all:complete`. Cascade logic recursively marks downstream tasks as `skipped` when a parent fails.

**NeuralOptima today:**  
Flat list, iterated sequentially in `Orchestrator.run()`. No dependency tracking. Order is whatever
the LLM returns — which means `crud.py` can be generated before `database.py`, forcing Claude to
invent imports it can't verify.

**What to copy:** `depends_on: list[str]` on the Task model + a topological sort before execution.
Not the full event-driven machinery — a simple ordered list is enough for our single-agent case.

---

### 2. Scheduler

**Their approach:**  
`Scheduler` (src/orchestrator/scheduler.ts) — 4 strategies: round-robin, least-busy, capability-match
(keyword scoring against agent configs), dependency-first (critical-path prioritization). Stateless
between calls; mutations happen in TaskQueue.

**NeuralOptima today:**  
No scheduler. One agent type (`DeveloperAgent`), tasks run in sequence.

**What to copy:** Nothing yet. Scheduling is meaningful only when there are multiple agent types
(e.g., a `TestAgent`, `DocAgent`). The capability-match pattern is worth revisiting in Phase 2.

---

### 3. Agent Pool

**Their approach:**  
`AgentPool` (src/agent/pool.ts) — named agent registry, global semaphore (default: 5 concurrent),
per-agent mutex to prevent race conditions. Methods: `run()`, `runParallel()`, `runAny()`,
`runEphemeral()`. Reports per-agent lifecycle status snapshots.

**NeuralOptima today:**  
Single `DeveloperAgent` instantiated inside `Orchestrator.__init__`. Sequential execution, no
concurrency concern.

**What to copy:** The pattern of named, registry-based agents (a `dict[str, Agent]`). Useful
when a second agent type is added. Concurrency control is not needed until parallel file
generation is attempted.

---

### 4. Tool Framework

**Their approach:**  
`defineTool()` in src/tool/framework.ts — wraps a callable with a name, description, Zod input schema,
optional output schema. `ToolRegistry` stores tools, exports them in LLM-API-compatible format.
`ToolExecutor` validates input (Zod), caps parallel executions (semaphore: 4), isolates errors,
truncates oversized outputs. Built-ins: bash, file_read, file_write, grep, glob. MCP integration.

**NeuralOptima today:**  
`tools/filesystem.py` (read/write/append) and `tools/shell.py` (subprocess wrapper) exist but are
called directly — no registry, no schema, no LLM-callable interface. `ask_claude` is the only LLM
interaction and it has no tool-binding.

**What to copy:** A lightweight registry — a Python dataclass + dict — so tools have names,
descriptions, and callables. No Zod needed; Pydantic `BaseModel` for input schemas does the same
job. This makes agents composable and lets future LLM calls use tool-use API natively.

---

### 5. Shared Memory

**Their approach:**  
`SharedMemory` (src/memory/shared.ts) — namespaced KV: keys are `agentName/key`. Supports TTL via
turn-counter (`writeExpiring()`). `getSummary()` renders markdown context grouped by agent, truncates
values at 200 chars. Custom backend interface (Redis, Postgres, etc.) via duck-typing.

**NeuralOptima today:**  
The `Session` object (Pydantic model, persisted to JSON) serves this role. `brief`, `tasks`,
`log`, `total_cost_usd` are all in-session. `memory/store.py` saves/loads sessions to disk.
Generated files on disk serve as implicit shared state between tasks.

**What to copy:** The `agentName/key` namespacing pattern, if a second agent is added. The TTL
mechanism is unnecessary for now — session lifetime is a single CLI run. The existing Session
model is sufficient for Phase 1 and most of Phase 2.

---

### 6. Team Messaging

**Their approach:**  
`Team` + `MessageBus` (src/team/) — point-to-point `sendMessage()` and `broadcast()`. Agents
maintain persistent conversation history across turns. Typed event bus for orchestrator reactions.
Agent status: `idle → running → completed | error`.

**NeuralOptima today:**  
No inter-agent messaging. Single agent, no coordination needed.

**What to copy:** Nothing for now. When a second agent type exists, the typed event approach
(a simple `Enum` of event types + callback list) is worth adopting — lighter than a full message bus.

---

### 7. Trace / Observability

**Their approach:**  
Three layers:
1. **Progress events** (`onProgress` callback): `task_start`, `task_complete`, `task_retry`,
   `agent_start`, `budget_exceeded`, `error` — lightweight, real-time.
2. **Trace spans** (`onTrace` callback): structured telemetry with parent IDs, durations, token
   counts, tool I/O — compatible with OpenTelemetry/Datadog/Langfuse.
3. **Post-run HTML dashboard**: `renderTeamRunDashboard()` — task DAG visualization, timing,
   token usage.

**NeuralOptima today:**  
`core/logger.py` — JSONL per session, events have `timestamp`, `level`, `event`, `detail`, `extra`.
`Session` has a `total_cost_usd` float (never populated) and a `log: list[LogEntry]`. Tasks have
`started_at` / `completed_at` fields (defined in the model but never set). The logger is the only
observability surface.

**What to copy:**
- Populate `task.started_at` and `task.completed_at` in `DeveloperAgent.run_task()` — the fields
  already exist, they just need to be written.
- Capture `input_tokens` and `output_tokens` from every `ask_claude()` call; accumulate in
  `session.total_cost_usd` (Sonnet 4.6 pricing: $3/$15 per MTok in/out).
- No OpenTelemetry, no HTML dashboard — the JSONL log is sufficient for Phase 1.

---

### 8. Retry Logic

**Their approach:**  
Per-task `maxRetries`, `retryDelayMs`, `retryBackoff` (exponential, capped at 30 s).
`executeWithRetry()` accumulates token usage across attempts. `LoopDetector` — sliding window over
tool call signatures and text outputs; triggers alert on `maxRepetitions` (default 3) identical
actions within a window of 4.

**NeuralOptima today:**  
`ProjectValidator.repair()` does one repair attempt (re-validate after patching). No per-task
retry in `DeveloperAgent`. No loop detection. No backoff.

**What to copy:** `max_retries: int = 0` on the Task model + a retry loop in `DeveloperAgent.run_task()`.
Not the LoopDetector — the validator+repair cycle already handles stuck generation. Exponential
backoff is useful for API rate-limit errors specifically; a simple `time.sleep(2 ** attempt)` is
enough.

---

## Summary Table

| Dimension         | open-multi-agent          | NeuralOptima today                  | Action                         |
|-------------------|---------------------------|-------------------------------------|--------------------------------|
| Task queue        | DAG, event-driven         | Flat list, sequential               | Add `depends_on` + topo sort   |
| Scheduler         | 4 strategies              | None (1 agent type)                 | Skip until Phase 2             |
| Agent pool        | Named registry, semaphore | Single hardcoded agent              | Pattern useful in Phase 2      |
| Tool framework    | Zod registry + executor   | Direct function calls               | Add lightweight Pydantic registry |
| Shared memory     | Namespaced KV + TTL       | Session JSON (sufficient)           | No change needed               |
| Team messaging    | MessageBus + typed events | None (1 agent)                      | Skip until Phase 2             |
| Observability     | 3-layer (events/spans/UI) | JSONL + unpopulated Task timestamps | Populate timestamps + tokens   |
| Retry logic       | Backoff + LoopDetector    | One-shot repair in Validator        | Add max_retries to Task model  |

---

## What NeuralOptima Already Has (and They Don't)

- **LLM-generated tasks from a natural-language brief** — open-multi-agent requires explicit task
  graphs; NeuralOptima generates them from text automatically.
- **Auto-repair loop** — `ProjectValidator` generates a diff, patches a broken file, and re-validates.
  open-multi-agent has retry but no self-healing code generation.
- **Python / Pydantic** — leaner type system, no build step, faster iteration.
- **Session persistence as source of truth** — the full run is serializable to JSON and reloadable
  (`memory/store.py`), enabling replay and debugging without external tooling.

---

## What NOT to Copy

| Item                         | Reason                                                       |
|------------------------------|--------------------------------------------------------------|
| TypeScript / Zod             | We are Python. Pydantic is equivalent and already in use.    |
| Full event-driven TaskQueue  | Overkill for sequential single-agent execution.              |
| 4-strategy Scheduler         | Premature with one agent type.                               |
| MessageBus                   | No second agent to message.                                  |
| HTML dashboard               | The JSONL log + session JSON covers debugging needs.         |
| MCP integration              | Adds a dependency and protocol surface not needed in Phase 1.|
| OpenTelemetry / Datadog      | External infra we don't have; JSONL is sufficient.           |
| LoopDetector                 | Validator + repair already handles stuck generation.         |
| Semaphore concurrency        | Sequential file generation has no race conditions.           |

---

## Next 5 Implementation Steps

These are ordered by impact vs. complexity. Each is a self-contained change that does not require
touching existing working code paths.

### Step 1 — Task dependency ordering
**File:** `core/models.py` + `core/orchestrator.py`

Add `depends_on: list[str] = []` to the `Task` model (list of task titles or IDs). In
`Orchestrator.run()`, topologically sort `session.tasks` before iterating. This ensures
`database.py` is always generated before `crud.py`, and `schemas.py` before both — giving Claude
accurate context files to read from disk before generating each file.

The task generator prompt already asks Claude for tasks in dependency order; this makes that
ordering structural and guaranteed rather than incidental.

---

### Step 2 — Token and cost tracking
**File:** `core/llm.py` + `core/models.py`

Change `ask_claude()` to return `(text: str, usage: dict)` where `usage` contains
`input_tokens` and `output_tokens` from `response.usage`. Callers that ignore the second element
continue to work unchanged (Python tuple unpacking is optional).

Accumulate tokens per task in a new `Task.tokens_used: dict = {}` field. After each LLM call,
add to `session.total_cost_usd` using Sonnet 4.6 pricing ($3/$15 per MTok). The field already
exists in `Session`; it just needs to be written.

This surfaces real API cost per run without any external instrumentation.

---

### Step 3 — Populate task timing (zero-cost observability win)
**File:** `agents/developer.py`

`Task` already has `started_at: datetime | None` and `completed_at: datetime | None` — they are
never set. Add two lines to `DeveloperAgent.run_task()`:

```python
task.started_at = utc_now()   # at RUNNING transition
task.completed_at = utc_now() # at DONE/FAILED transition
```

The session JSON then carries full timing for every task. Duration can be computed in any consumer
(`completed_at - started_at`). Zero new dependencies, no schema changes.

---

### Step 4 — Lightweight tool registry
**File:** `tools/registry.py` (new)

A `@register_tool` decorator + `ToolRegistry` dict that maps `name -> (callable, description)`.
Register `generate_file`, `repair_file`, `run_shell` as named tools. `DeveloperAgent` looks up
tools by name rather than calling functions directly.

This does not change behavior — it changes the coupling. The value: a second agent type
(`TestAgent`, `DocAgent`) can discover what tools exist via `registry.list()`, and future LLM
calls can pass tool definitions directly to Claude's tool-use API without hardcoding them.

---

### Step 5 — Per-task retry with backoff
**File:** `core/models.py` + `agents/developer.py`

Add `max_retries: int = 0` and `retry_delay_s: float = 2.0` to the `Task` model.

In `DeveloperAgent.run_task()`, wrap the LLM generation + write block in a retry loop:

```python
for attempt in range(task.max_retries + 1):
    try:
        ...generate and write...
        break
    except Exception:
        if attempt == task.max_retries:
            task.status = TaskStatus.FAILED
        else:
            time.sleep(task.retry_delay_s * (2 ** attempt))
```

The task generator can set `max_retries=1` on tasks that are historically fragile (e.g., `main.py`,
which has the most inter-file dependencies). The validator's repair loop remains separate —
this retry is for LLM API errors and transient failures, not code quality issues.

---

*End of analysis. Do not change source code based on this document without explicit instruction.*
