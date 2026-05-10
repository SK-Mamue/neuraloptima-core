from __future__ import annotations

import json

from core.llm import ask_claude
from core.models import Task


SYSTEM_PROMPT = """
You are a senior software architect.

Return ONLY valid JSON — no markdown, no commentary.

Format:
[
  {
    "title": "...",
    "description": "...",
    "depends_on": []
  }
]

Rules:
- "depends_on" is a list of task titles that must complete before this task starts.
- Use exact title strings from earlier entries in the same array.
- The first task always has an empty depends_on list.
- Every file that imports from another generated file must depend on the task that creates it.

FLAT LAYOUT — you MUST follow these rules in every task description:
- The project uses a flat layout. The project root IS the Python path.
- There is NO "app/" package and NO "app/" directory.
- Never write "app/" in any file path: write "database.py", not "app/database.py".
- Never write "app." in any import: write "from database import ...", not "from app.database import ...".
- Subdirectories are routers/ and crud/ only (e.g. "routers/expenses.py", "crud/categories.py").
- When referencing a file another task creates, use its bare path: "database.py", "schemas.py", "routers/expenses.py".
"""


def generate_tasks_from_brief(brief_text: str) -> list[Task]:
    prompt = f"""
Project Brief:

{brief_text}

Generate implementation tasks as JSON array.
"""

    response, _ = ask_claude(
        prompt=prompt,
        system=SYSTEM_PROMPT,
    )

    print("\n=== RAW LLM RESPONSE ===\n")
    print(response)
    print("\n========================\n")

    cleaned = response.strip()

    if cleaned.startswith("```json"):
        cleaned = cleaned.replace("```json", "", 1)

    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```", "", 1)

    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    cleaned = cleaned.strip()

    data = json.loads(cleaned)

    tasks = []

    for item in data:
        tasks.append(
            Task(
                title=item["title"],
                description=item["description"],
                depends_on=item.get("depends_on", []),
            )
        )

    return tasks
