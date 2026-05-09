# Claude Arbeitsregeln für NeuralOptima Core

Ziel:
Baue einen praktischen AI Developer Worker, kein theoretisches Framework.

Regeln:
- Keine neuen Architektur-Docs ohne explizite Anweisung.
- Keine Redis/Qdrant/Chroma/OpenTelemetry/Multi-Agent-Komplexität in Phase 1.
- Implementiere kleine lauffähige Dateien.
- Nach jeder Änderung: kurz prüfen mit python -m compileall oder pytest, falls vorhanden.
- Bestehende Struktur respektieren.
- Fokus: ProjectBrief -> Tasks -> Execute -> Log -> Session speichern.

Aktueller Ziel-Stack:
- Python
- Pydantic
- Typer
- Rich
- python-dotenv
- anthropic
- JSON-Dateien als Memory/Session Store
