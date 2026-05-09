from __future__ import annotations

from pathlib import Path


def ensure_dir(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_file(path: str, content: str) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    with p.open("w", encoding="utf-8") as f:
        f.write(content)


def read_file(path: str) -> str:
    p = Path(path).expanduser().resolve()

    with p.open("r", encoding="utf-8") as f:
        return f.read()


def append_file(path: str, content: str) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    with p.open("a", encoding="utf-8") as f:
        f.write(content)
