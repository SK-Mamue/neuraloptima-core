from __future__ import annotations

import subprocess


def run_command(command: str, cwd: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
    )

    return (
        result.returncode,
        result.stdout,
        result.stderr,
    )
