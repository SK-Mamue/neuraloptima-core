from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Logger:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.log_file = LOG_DIR / f"{session_id}.jsonl"

    def write(self, level: str, event: str, detail: str, extra: dict | None = None) -> None:
        payload = {
            "timestamp": utc_now_iso(),
            "session_id": self.session_id,
            "level": level,
            "event": event,
            "detail": detail,
            "extra": extra or {},
        }

        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def info(self, event: str, detail: str, extra: dict | None = None) -> None:
        self.write("info", event, detail, extra)

    def warning(self, event: str, detail: str, extra: dict | None = None) -> None:
        self.write("warning", event, detail, extra)

    def error(self, event: str, detail: str, extra: dict | None = None) -> None:
        self.write("error", event, detail, extra)
