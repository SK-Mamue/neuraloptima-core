from __future__ import annotations

from pathlib import Path

from core.models import Session, TaskStatus

REPORTS_DIR = Path("memory/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def report_path(session_id: str) -> Path:
    return REPORTS_DIR / f"{session_id}.md"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

_STATUS_ICON = {
    TaskStatus.DONE:    "✅",
    TaskStatus.FAILED:  "❌",
    TaskStatus.SKIPPED: "⏭️",
    TaskStatus.RUNNING: "🔄",
    TaskStatus.PENDING: "⏳",
}


def save_report(session: Session) -> Path:
    path = REPORTS_DIR / f"{session.id}.md"
    path.write_text(_render(session), encoding="utf-8")
    return path


# ------------------------------------------------------------------ #

def _render(session: Session) -> str:
    brief  = session.brief
    tasks  = session.tasks

    n_done    = sum(1 for t in tasks if t.status == TaskStatus.DONE)
    n_failed  = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
    task_dur  = sum(t.duration_seconds or 0.0 for t in tasks)
    val_dur   = session.validation_duration_seconds or 0.0
    total_dur = task_dur + val_dur
    total_in  = sum(t.tokens_used.get("input_tokens",  0) for t in tasks)
    total_out = sum(t.tokens_used.get("output_tokens", 0) for t in tasks)
    ts        = (session.completed_at or session.started_at).strftime("%Y-%m-%d %H:%M UTC")

    all_files    = [f for t in tasks for f in t.files_created]
    failed_tasks = [t for t in tasks if t.status == TaskStatus.FAILED]

    L: list[str] = []

    # ── Header ──────────────────────────────────────────────────────
    L += [
        f"# Run Report: {brief.title}",
        "",
        f"**Session:** `{session.id}`  ",
        f"**Date:** {ts}  ",
        f"**Workspace:** `{brief.project_dir}`",
        "",
        "---",
        "",
    ]

    # ── Summary ─────────────────────────────────────────────────────
    L += [
        "## Summary",
        "",
        "| | |",
        "|---|---|",
        f"| Tasks total | {len(tasks)} |",
        f"| Completed | {n_done} |",
        f"| Failed | {n_failed} |",
        f"| Total duration | {total_dur:.1f}s |",
        f"| Total cost | ${session.total_cost_usd:.4f} |",
        "",
        "---",
        "",
    ]

    # ── Task table ──────────────────────────────────────────────────
    L += [
        "## Tasks",
        "",
        "| # | Title | Status | File | Duration | Attempts |",
        "|---|-------|--------|------|----------|----------|",
    ]
    for i, task in enumerate(tasks, 1):
        icon     = _STATUS_ICON.get(task.status, "?")
        file_col = f"`{Path(task.files_created[0]).name}`" if task.files_created else "—"
        dur      = f"{task.duration_seconds:.1f}s" if task.duration_seconds is not None else "—"
        attempts = str(task.attempts_made) if task.attempts_made else "—"
        retry    = f" ⟳{task.attempts_made - 1}" if task.attempts_made > 1 else ""
        L.append(
            f"| {i} | {task.title} | {icon} {task.status.value.title()} "
            f"| {file_col} | {dur} | {attempts}{retry} |"
        )
    L += ["", "---", ""]

    # ── Files created ────────────────────────────────────────────────
    L += ["## Files Created", ""]
    if all_files:
        for f in all_files:
            L.append(f"- `{f}`")
    else:
        L.append("*(none)*")
    L += ["", "---", ""]

    # ── Validation ──────────────────────────────────────────────────
    L += ["## Validation", "", _validation_outcome(session), "", "---", ""]

    # ── Cost ────────────────────────────────────────────────────────
    L += [
        "## Cost",
        "",
        "| | |",
        "|---|---|",
        f"| Input tokens | {total_in:,} |",
        f"| Output tokens | {total_out:,} |",
        f"| Total | ${session.total_cost_usd:.4f} |",
        "",
        "---",
        "",
    ]

    # ── Errors ──────────────────────────────────────────────────────
    L += ["## Errors", ""]
    if failed_tasks:
        for task in failed_tasks:
            L += [
                f"### {task.title}",
                "",
                "```",
                task.error.strip() if task.error else "(no traceback captured)",
                "```",
                "",
            ]
    else:
        L.append("*(none)*")
    L.append("")

    return "\n".join(L)


def _validation_outcome(session: Session) -> str:
    dur = session.validation_duration_seconds
    dur_str = f" in {dur:.1f}s" if dur is not None else ""

    # Scan log in reverse — repair events appear after validation events
    for entry in reversed(session.log):
        if entry.event == "repair":
            if entry.detail == "succeeded":
                return f"⚠️ Failed — repaired successfully{dur_str}"
            if entry.detail == "failed":
                return f"❌ Failed — repair unsuccessful{dur_str}"
        if entry.event == "validation" and entry.detail == "passed":
            return f"✅ Passed{dur_str}"

    return f"⚠️ Unknown{dur_str}"
