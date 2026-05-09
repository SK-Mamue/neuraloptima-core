from __future__ import annotations

import typer
from rich import print

from core.orchestrator import Orchestrator
from memory.store import save_session


app = typer.Typer()


@app.command()
def run(brief: str) -> None:
    orchestrator = Orchestrator.from_brief_file(brief)

    result = orchestrator.run()

    path = save_session(result)

    print(f"[green]Session gespeichert:[/green] {path}")


if __name__ == "__main__":
    app()
