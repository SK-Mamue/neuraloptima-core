from __future__ import annotations

import typer
from rich import print
from rich.table import Table
from rich import get_console
from core.models import TaskStatus

from core.manifest import save_manifest
from core.orchestrator import Orchestrator
from memory.report import save_report
from memory.store import load_all_sessions, save_session


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

    table = Table(title="Past Sessions", show_lines=False, expand=False)
    table.add_column("ID",     style="cyan",  min_width=12, no_wrap=True)
    table.add_column("Title",  style="white", min_width=20, max_width=30, no_wrap=True, overflow="ellipsis")
    table.add_column("Date",   style="dim",   min_width=11, no_wrap=True)
    table.add_column("Tasks",  justify="center", min_width=5, no_wrap=True)
    table.add_column("Cost",   justify="right",  style="green", min_width=7, no_wrap=True)
    table.add_column("",       justify="center", min_width=2, no_wrap=True)

    for s in sessions:
        done  = sum(1 for t in s.tasks if t.status == TaskStatus.DONE)
        total = len(s.tasks)
        date  = s.started_at.strftime("%m-%d %H:%M") if s.started_at else "—"
        cost  = f"${s.total_cost_usd:.4f}" if s.total_cost_usd else "—"
        status_icon = {"completed": "✅", "failed": "❌", "running": "⏳"}.get(
            s.status.value if hasattr(s.status, "value") else str(s.status), "?"
        )
        short_id = s.id.replace("session_", "")
        table.add_row(
            short_id,
            s.brief.title,
            date,
            f"{done}/{total}",
            cost,
            status_icon,
        )

    get_console().print(table)


if __name__ == "__main__":
    app()
