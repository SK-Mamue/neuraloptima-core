from __future__ import annotations

from pathlib import Path

import typer
from rich import print
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import get_console
from core.models import TaskStatus

from core.agent_registry import registry as agent_registry
from core.manifest import save_manifest
from core.orchestrator import Orchestrator
from memory.report import report_path, save_report
from memory.store import find_session, load_all_sessions, save_session


app = typer.Typer()


@app.command()
def run(brief: str) -> None:
    orchestrator = Orchestrator.from_brief_file(brief)

    result = orchestrator.run()

    path          = save_session(result)
    report_path   = save_report(result)
    manifest_path = save_manifest(result)

    print(f"[green]Session: [/green] {path}")
    print(f"[green]Report:  [/green] {report_path}")
    print(f"[green]Manifest:[/green] {manifest_path}")


@app.command(name="list")
def list_sessions(n: int = typer.Option(20, "--limit", "-n", help="Max sessions to show")) -> None:
    """Show past sessions."""
    sessions = load_all_sessions()[:n]

    if not sessions:
        print("[yellow]No sessions found.[/yellow]")
        return

    table = Table(title="Past Sessions", show_lines=True, expand=False)
    table.add_column("ID",        style="cyan",  min_width=12, no_wrap=True)
    table.add_column("Title",     style="white", min_width=20, max_width=36, no_wrap=False)
    table.add_column("Date",      style="dim",   min_width=11, no_wrap=True)
    table.add_column("Tasks",     justify="center", min_width=5, no_wrap=True)
    table.add_column("Cost",      justify="right",  style="green", min_width=7, no_wrap=True)
    table.add_column("",          justify="center", min_width=2, no_wrap=True)

    for s in sessions:
        done  = sum(1 for t in s.tasks if t.status == TaskStatus.DONE)
        total = len(s.tasks)
        date  = s.started_at.strftime("%m-%d %H:%M") if s.started_at else "—"
        cost  = f"${s.total_cost_usd:.4f}" if s.total_cost_usd else "—"
        status_icon = {"completed": "✅", "failed": "❌", "running": "⏳"}.get(
            s.status.value if hasattr(s.status, "value") else str(s.status), "?"
        )
        short_id = s.id.replace("session_", "")
        workspace = Path(s.brief.project_dir).name
        title_cell = Text(s.brief.title, no_wrap=True, overflow="ellipsis")
        title_cell.append(f"\n{workspace}", style="dim")
        table.add_row(
            short_id,
            title_cell,
            date,
            f"{done}/{total}",
            cost,
            status_icon,
        )

    get_console().print(table)


@app.command()
def agents() -> None:
    """List available agents and their capabilities."""
    table = Table(title="Agent Registry", show_lines=True, expand=False)
    table.add_column("Name",         style="cyan",  min_width=9,  no_wrap=True)
    table.add_column("Role",         style="white", min_width=14, no_wrap=True)
    table.add_column("Description",  style="dim",   max_width=22, no_wrap=True, overflow="ellipsis")
    table.add_column("Capabilities", style="green", min_width=20)

    for spec in agent_registry.list():
        table.add_row(
            spec.name,
            spec.role,
            spec.description,
            ", ".join(spec.capabilities),
        )

    get_console().print(table)


_STATUS_ICON = {"completed": "✅", "failed": "❌", "running": "⏳", "pending": "⏳", "done": "✅", "skipped": "⏭️"}


@app.command()
def show(session_id: str) -> None:
    """Show details for a single session."""
    console = get_console()

    session = find_session(session_id)
    if session is None:
        print(f"[red]No session found matching '[bold]{session_id}[/bold]'.[/red]")
        raise typer.Exit(1)

    brief    = session.brief
    tasks    = session.tasks
    task_dur = sum(t.duration_seconds or 0.0 for t in tasks)
    val_dur  = session.validation_duration_seconds or 0.0
    duration = task_dur + val_dur
    status_val = session.status.value if hasattr(session.status, "value") else str(session.status)
    status_icon = _STATUS_ICON.get(status_val, "?")
    short_id = session.id.replace("session_", "")

    # ── Header panel ────────────────────────────────────────────────────
    meta = Text()
    meta.append("Workspace  ", style="dim")
    meta.append(f"{brief.project_dir}\n")
    meta.append("Session    ", style="dim")
    meta.append(f"{short_id}\n")
    meta.append("Status     ", style="dim")
    meta.append(f"{status_icon} {status_val}\n")
    meta.append("Cost       ", style="dim")
    meta.append(f"${session.total_cost_usd:.4f}\n", style="green")
    meta.append("Duration   ", style="dim")
    meta.append(f"{duration:.1f}s")
    console.print(Panel(meta, title=f"[bold]{brief.title}[/bold]", expand=False))

    # ── Task table ───────────────────────────────────────────────────────
    table = Table(show_lines=False, expand=False, box=None, padding=(0, 1))
    table.add_column("#",        justify="right",  style="dim",  min_width=2,  no_wrap=True)
    table.add_column("Title",    style="white",                  min_width=22, no_wrap=True, overflow="ellipsis")
    table.add_column("Agent",    style="cyan",                   min_width=9,  no_wrap=True)
    table.add_column("St",       justify="center",               min_width=2,  no_wrap=True)
    table.add_column("Dur",      justify="right",  style="cyan", min_width=5,  no_wrap=True)
    table.add_column("Tries",    justify="center", style="dim",  min_width=5,  no_wrap=True)
    table.add_column("Files",    style="dim",                    min_width=8,  no_wrap=True, overflow="ellipsis")

    for i, t in enumerate(tasks, 1):
        t_status = t.status.value if hasattr(t.status, "value") else str(t.status)
        icon     = _STATUS_ICON.get(t_status, "?")
        dur      = f"{t.duration_seconds:.1f}s" if t.duration_seconds is not None else "—"
        tries    = str(t.attempts_made) if t.attempts_made else "1"
        files    = ", ".join(Path(f).name for f in t.files_created) if t.files_created else "—"
        table.add_row(str(i), t.title, t.assigned_agent, icon, dur, tries, files)

    console.print(table)

    # ── Report path ─────────────────────────────────────────────────────
    rp = report_path(session.id)
    if rp.exists():
        console.print(f"\n[dim]Report:[/dim] {rp}")


if __name__ == "__main__":
    app()
