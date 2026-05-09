from __future__ import annotations

import json
from pathlib import Path

from core.models import Session


def save_manifest(session: Session) -> Path:
    """Write manifest.json into the session's workspace directory."""
    brief    = session.brief
    tasks    = session.tasks
    task_dur = sum(t.duration_seconds or 0.0 for t in tasks)
    val_dur  = session.validation_duration_seconds or 0.0

    manifest = {
        "session_id":    session.id,
        "title":         brief.title,
        "brief_summary": brief.description,
        "workspace":     brief.project_dir,
        "generated_at":  (session.completed_at or session.started_at).isoformat(),
        "files":         [f for t in tasks for f in t.files_created],
        "tasks": [
            {
                "title":            t.title,
                "status":           t.status.value,
                "files_created":    t.files_created,
                "duration_seconds": round(t.duration_seconds, 2) if t.duration_seconds is not None else None,
                "attempts_made":    t.attempts_made,
            }
            for t in tasks
        ],
        "total_duration_seconds": round(task_dur + val_dur, 2),
        "total_cost_usd":         round(session.total_cost_usd, 6),
        "validation":             _validation_outcome(session),
    }

    workspace = Path(brief.project_dir).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _validation_outcome(session: Session) -> str:
    for entry in reversed(session.log):
        if entry.event == "repair":
            return "repaired" if entry.detail == "succeeded" else "failed"
        if entry.event == "validation" and entry.detail == "passed":
            return "passed"
    return "unknown"
