from __future__ import annotations

import json
from pathlib import Path

from core.models import Session


MEMORY_DIR = Path("memory/sessions")
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def session_file(session_id: str) -> Path:
    return MEMORY_DIR / f"{session_id}.json"


def save_session(session: Session) -> Path:
    path = session_file(session.id)

    with path.open("w", encoding="utf-8") as f:
        json.dump(session.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

    return path


def load_session(session_id: str) -> Session:
    path = session_file(session_id)

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return Session.model_validate(data)
