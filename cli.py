from __future__ import annotations

import typer
from rich import print

from core.manifest import save_manifest
from core.orchestrator import Orchestrator
from memory.report import save_report
from memory.store import save_session


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


if __name__ == "__main__":
    app()
