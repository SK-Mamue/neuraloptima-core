from __future__ import annotations

import os

from anthropic import Anthropic
from dotenv import load_dotenv


load_dotenv()


client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
)


def ask_claude(prompt: str, system: str = "You are a senior software engineer.") -> str:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    return response.content[0].text
