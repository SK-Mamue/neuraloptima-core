from __future__ import annotations

import json

from core.llm import ask_claude
from core.models import Task


SYSTEM_PROMPT = """
You are a senior software architect.

Return ONLY valid JSON.

Format:
[
  {
    "title": "...",
    "description": "..."
  }
]
"""


def generate_tasks_from_brief(brief_text: str) -> list[Task]:
    prompt = f"""
Project Brief:

{brief_text}

Generate implementation tasks as JSON array.
"""

    response = ask_claude(
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
            )
        )

    return tasks
