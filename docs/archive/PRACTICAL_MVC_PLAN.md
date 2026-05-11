# PRACTICAL MVC PLAN
## NeuralOptima — Ein AI Developer Agent der echte Software baut

> Replaces: MASTER_SYSTEM_BLUEPRINT.md für den aktuellen Entwicklungsstand
> Fokus: Ein einzelner, funktionstüchtiger AI Developer Worker
> Datum: 2026-05-09

---

## Was dieser Agent tun soll

Ein Nutzer gibt einen Auftrag:
> "Baue mir einen FastAPI-Backend für ein CRM mit Kontakten und Deals"

Der Agent:
1. Liest den Auftrag und erstellt einen konkreten Task-Plan
2. Arbeitet die Tasks Schritt für Schritt ab
3. Schreibt Dateien, führt Befehle aus, prüft Ergebnisse
4. Loggt jede Aktion in einer Session-Datei
5. Merkt sich abgeschlossene Projekte in einer Memory-Datei
6. Bereitet einen Git-Commit vor

**Kein Microservice-System. Kein verteiltes Framework. Nur: Brief rein → Projekt raus.**

---

## Zielverwendungen

| Auftrag | Erwarteter Output |
|---|---|
| "Baue eine FastAPI REST API mit SQLite" | `main.py`, `models.py`, `routes/`, `requirements.txt` |
| "Erstelle ein Web-Scraper-Skript für HN" | `scraper.py`, `requirements.txt`, Beispiel-Output |
| "Mache ein Dashboard mit Streamlit" | `app.py`, `data/`, `requirements.txt` |
| "Automatisiere E-Mail-Reports per Cron" | `reporter.py`, `config.yaml`, Cronjob-Anleitung |
| "Deploye die App auf Fly.io" | `Dockerfile`, `fly.toml`, Deployment-Steps |

---

## Architektur (MVC — kein Overkill)

```
neuraloptima-core/
├── cli.py                  # Entry Point: python cli.py run "brief"
├── pyproject.toml          # Dependencies
│
├── core/
│   ├── models.py           # ProjectBrief, Task, Session, LogEntry
│   ├── orchestrator.py     # Koordiniert: Brief → Plan → Execute → Log
│   └── logger.py           # Strukturiertes Logging in Datei + Konsole
│
├── agents/
│   └── developer.py        # Der AI-Worker (Claude + Tools, ReAct-Loop)
│
├── tools/
│   ├── filesystem.py       # read_file, write_file, list_files, create_dir
│   └── shell.py            # run_command (mit Safety-Check)
│
└── memory/
    ├── store.py             # SessionStore: lesen/schreiben als JSON
    └── sessions/            # sessions/session_<id>.json (auto-erstellt)
```

**Gesamt: ~8 Dateien, ~600-800 Zeilen Code.**

---

## 1. Datenmodelle (`core/models.py`)

```python
class OutputType(str, Enum):
    API         = "api"
    WEBSITE     = "website"
    DASHBOARD   = "dashboard"
    SCRAPER     = "scraper"
    AUTOMATION  = "automation"
    CRM         = "crm"
    DEPLOYMENT  = "deployment"
    OTHER       = "other"

class ProjectBrief(BaseModel):
    """Was der Nutzer bauen will."""
    id: str                         # UUID
    title: str                      # Kurztitel, vom Agent inferiert
    description: str                # Originaler Nutzertext
    output_type: OutputType
    tech_stack: list[str]           # ["Python", "FastAPI", "SQLite"] — inferiert
    requirements: list[str]         # Konkrete Anforderungen — vom Agent extrahiert
    project_dir: str                # Zielverzeichnis für Ausgabe-Dateien
    created_at: datetime

class TaskStatus(str, Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    DONE     = "done"
    FAILED   = "failed"
    SKIPPED  = "skipped"

class Task(BaseModel):
    """Ein atomarer Arbeitsschritt des Agents."""
    id: str
    title: str
    description: str                # Was soll hier konkret passieren?
    status: TaskStatus = TaskStatus.PENDING
    result_summary: str = ""        # Was hat der Agent gemacht?
    files_created: list[str] = []   # Relative Pfade
    files_modified: list[str] = []
    commands_run: list[str] = []
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

class LogEntry(BaseModel):
    """Ein einzelner Log-Eintrag während einer Session."""
    timestamp: datetime
    level: str                      # info | warning | error
    task_id: str | None
    event: str                      # z.B. "tool.write_file"
    detail: str

class Session(BaseModel):
    """Vollständige Aufzeichnung eines Agent-Runs."""
    id: str
    brief: ProjectBrief
    tasks: list[Task] = []
    log: list[LogEntry] = []
    git_commit_message: str = ""
    status: str = "running"         # running | completed | failed
    started_at: datetime
    completed_at: datetime | None = None
    total_cost_usd: float = 0.0
```

---

## 2. Agent-Rolle (`agents/developer.py`)

Der Agent hat eine feste Identität: **AI Software Developer**.

```python
DEVELOPER_SYSTEM_PROMPT = """
Du bist ein erfahrener Software-Entwickler.
Du erhältst einen Task und erledigst ihn vollständig.

Deine Fähigkeiten:
- Dateien lesen und schreiben
- Shell-Befehle ausführen (pip install, pytest, etc.)
- Verzeichnisse auflisten
- Code schreiben: Python, HTML, SQL, YAML, Dockerfile, etc.

Arbeitsweise:
1. Analysiere den Task
2. Plane 2-3 konkrete Schritte
3. Führe sie aus (nutze deine Tools)
4. Prüfe das Ergebnis
5. Melde: was du getan hast, welche Dateien erstellt wurden

Qualitätsregeln:
- Schreibe lauffähigen, echten Code — keine Platzhalter
- Füge requirements.txt hinzu wenn nötig
- Halte Dateien übersichtlich (< 200 Zeilen wenn möglich)
- Kommentiere nur was nicht offensichtlich ist
"""

# Tools die Claude nutzen kann:
DEVELOPER_TOOLS = [
    "read_file",     # Datei lesen
    "write_file",    # Datei schreiben (erstellt Verzeichnis wenn nötig)
    "list_files",    # Verzeichnis auflisten
    "run_command",   # Shell-Befehl ausführen
]
```

**Modell:** `claude-sonnet-4-6` (Balance: Qualität + Kosten)
**Tool-Call-Limit:** 30 pro Task
**Timeout:** 5 Minuten pro Task

---

## 3. Tools (`tools/`)

### filesystem.py
```python
def read_file(path: str, project_dir: str) -> str
    # Liest Datei, prüft dass path innerhalb project_dir liegt
    # Returns: Dateiinhalt als String

def write_file(path: str, content: str, project_dir: str) -> str
    # Schreibt Datei, erstellt Verzeichnisse wenn nötig
    # Returns: "OK: wrote N bytes to path"

def list_files(path: str, project_dir: str) -> str
    # Listet Verzeichnis auf (max 2 Ebenen tief)
    # Returns: Tree-String

def create_dir(path: str, project_dir: str) -> str
    # Erstellt Verzeichnis
```

### shell.py
```python
BLOCKED_COMMANDS = [
    "rm -rf /", "sudo rm", "mkfs", "dd if=",
    "chmod 777 /", "> /etc", "curl | bash", "wget | sh"
]

def run_command(command: str, project_dir: str, timeout: int = 30) -> str
    # Prüft gegen BLOCKED_COMMANDS
    # Führt in project_dir aus
    # Returns: stdout + stderr (max 5000 Zeichen)
    # Raises: CommandBlockedError, TimeoutError
```

---

## 4. Orchestrator (`core/orchestrator.py`)

```python
class Orchestrator:

    async def run(self, description: str, project_dir: str) -> Session:

        # Schritt 1: Brief erstellen
        brief = await self._parse_brief(description, project_dir)
        session = Session(brief=brief, ...)
        self.store.save(session)

        # Schritt 2: Task-Plan erstellen (Claude)
        tasks = await self._plan_tasks(brief)
        session.tasks = tasks

        # Schritt 3: Tasks ausführen
        for task in session.tasks:
            result = await self.developer.execute_task(task, brief)
            task.status = TaskStatus.DONE if result.ok else TaskStatus.FAILED
            session.log += result.log_entries
            self.store.save(session)

        # Schritt 4: Git-Commit vorbereiten
        session.git_commit_message = await self._generate_commit_msg(session)

        # Schritt 5: Session abschließen
        session.status = "completed"
        self.store.save(session)
        return session
```

**Kein Event Bus. Keine Queues. Direkter, sequenzieller Aufruf.**

---

## 5. Logging (`core/logger.py`)

Einfaches strukturiertes Logging:
- **Konsole:** farbige, lesbare Ausgabe mit Rich
- **Datei:** `logs/session_<id>.jsonl` (eine JSON-Zeile pro Eintrag)

```
[14:23:01] INFO   | Brief erstellt: "FastAPI CRM Backend" (api)
[14:23:02] INFO   | Planer: 5 Tasks erstellt
[14:23:03] INFO   | Task 1/5: Projektstruktur erstellen
[14:23:05] INFO   |   → write_file: src/main.py (142 Bytes)
[14:23:07] INFO   |   → write_file: src/models.py (89 Bytes)
[14:23:08] INFO   |   ✓ Task abgeschlossen
[14:23:09] INFO   | Task 2/5: Datenbank-Modelle
...
[14:28:41] INFO   | ✓ Session abgeschlossen. 5/5 Tasks erfolgreich.
[14:28:41] INFO   | Git-Commit: "feat: FastAPI CRM Backend mit Kontakten und Deals"
```

---

## 6. Memory (`memory/store.py`)

Einfaches JSON-basiertes Memory. Kein Vektor-Store, kein Embedding.

```
memory/
└── sessions/
    ├── session_abc123.json    # Vollständige Session-Daten
    ├── session_def456.json
    └── index.json             # Leichtgewichtiger Index aller Sessions
```

**index.json:**
```json
[
  {
    "id": "abc123",
    "title": "FastAPI CRM Backend",
    "output_type": "api",
    "status": "completed",
    "date": "2026-05-09",
    "files_created": 8
  }
]
```

**Spätere Erweiterung:** SQLite wenn Index > 100 Einträge. Kein Umbau der Interfaces nötig.

---

## 7. CLI (`cli.py`)

```bash
# Projekt bauen
python cli.py run "Baue einen FastAPI CRM mit Kontakten, Deals und SQLite"

# Mit Zielverzeichnis
python cli.py run "Baue einen Scraper für HN" --dir ./my-scraper

# Letzte Session anzeigen
python cli.py status

# Alle Sessions auflisten
python cli.py list

# Session-Log anzeigen
python cli.py log <session-id>
```

---

## Datenfluss (End-to-End)

```
User: python cli.py run "Baue einen FastAPI CRM..."
            │
            ▼
      [Orchestrator]
      Brief parsen (Claude) → ProjectBrief
            │
            ▼
      Task-Plan erstellen (Claude)
      → ["Projektstruktur", "Modelle", "Routes", "Tests", "README"]
            │
            ▼ für jeden Task:
      [Developer Agent] — ReAct Loop
      Reason → Tool Call → Observe → Repeat
            │
      ┌─────┴─────────────────┐
      │  filesystem.write_file │
      │  filesystem.read_file  │
      │  shell.run_command     │
      └───────────────────────┘
            │
      TaskResult + LogEntries
            │
            ▼
      [Memory Store]
      session_<id>.json aktualisieren
            │
            ▼
      Git-Commit-Message generieren
            │
            ▼
User: "✓ Fertig. 6 Dateien erstellt. Commit-Message bereit."
```

---

## Dependencies (minimal)

```toml
[project]
name = "neuraloptima-core"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "anthropic>=0.40.0",      # Claude API
    "pydantic>=2.0",          # Datenmodelle
    "typer>=0.12",            # CLI
    "rich>=13.0",             # Terminal-Ausgabe
    "python-dotenv>=1.0",     # .env Konfiguration
]
```

**Keine Redis, Qdrant, ChromaDB, OpenTelemetry, NATS, Docker SDK.**

---

## Was NICHT im MVC ist (bewusst weggelassen)

| Feature | Warum nicht jetzt |
|---|---|
| Redis Event Bus | Braucht man nicht für 1 Agent |
| Vektor-Datenbank | JSON-Index reicht für <100 Sessions |
| Multi-Worker | 1 Agent, sequenziell — ausreichend |
| Docker Sandbox | Safety-Checks in shell.py reichen |
| Critic Agent | Selbst-Review durch Executor-Prompt |
| Skill-System | Kommt wenn Patterns sich wiederholen |
| Dashboard | Terminal-Output reicht im MVC |
| OpenTelemetry | JSONL-Logs reichen für Debugging |

---

## Implementierungsreihenfolge

```
Tag 1 — Fundament
  [1] pyproject.toml + .env.example
  [2] core/models.py (alle Datenmodelle)
  [3] core/logger.py (Rich-Konsole + JSONL)
  [4] memory/store.py (JSON read/write)

Tag 2 — Tools + Agent
  [5] tools/filesystem.py (read, write, list, create_dir)
  [6] tools/shell.py (run_command + safety)
  [7] agents/developer.py (ReAct-Loop mit Claude)

Tag 3 — Orchestrator + CLI
  [8] core/orchestrator.py (Brief → Plan → Execute → Log)
  [9] cli.py (typer: run, status, list, log)

Tag 4 — Integration + Test
  [10] End-to-End-Test: "Baue mir eine FastAPI TODO-API"
  [11] Fehlerbehandlung, Edge Cases
  [12] README mit Schnellstart
```

---

## Erfolgskriterien

Das MVC ist fertig wenn:

```
□ python cli.py run "Baue eine FastAPI Todo API" läuft durch
□ Mindestens 3 Dateien werden im Zielverzeichnis erstellt
□ Session wird in memory/sessions/ gespeichert
□ Logs sind in logs/ geschrieben
□ python cli.py list zeigt abgeschlossene Session
□ Git-Commit-Message wird ausgegeben
□ Kein Crash bei: ungültigem Pfad, fehlschlagendem Befehl, API-Fehler
```

---

## Verhältnis zu den bisherigen Architekturdokumenten

| Dokument | Status |
|---|---|
| PROJECT_OVERVIEW.md | Vision gültig, Tech-Stack zu komplex → PRACTICAL_MVC_PLAN hat Vorrang |
| SYSTEM_ARCHITECTURE.md | Referenz für spätere Phasen |
| AGENT_ROLES.md | Agent-Rollen-Konzept gültig, Umfang reduziert |
| TASK_FLOW.md | Task-Lifecycle übernommen (vereinfacht) |
| MEMORY_SYSTEM.md | Typ-Modell gültig, Backend vereinfacht |
| MASTER_SYSTEM_BLUEPRINT.md | Langfristige Roadmap — gilt ab Phase 3 |

**Jetzt bauen wir das hier. Der Rest kommt wenn dieses läuft.**
