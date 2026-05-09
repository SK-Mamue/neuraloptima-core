from __future__ import annotations

import os
from dataclasses import dataclass

from anthropic import Anthropic
from dotenv import load_dotenv


load_dotenv()


client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
)

# Sonnet 4.6 pricing (USD per token)
_INPUT_COST_PER_TOKEN  = 3.0  / 1_000_000
_OUTPUT_COST_PER_TOKEN = 15.0 / 1_000_000


@dataclass
class LLMUsage:
    input_tokens: int
    output_tokens: int


def compute_cost(usage: LLMUsage) -> float:
    return (usage.input_tokens  * _INPUT_COST_PER_TOKEN +
            usage.output_tokens * _OUTPUT_COST_PER_TOKEN)


def ask_claude(
    prompt: str,
    system: str = "You are a senior software engineer.",
) -> tuple[str, LLMUsage]:
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )

    usage = LLMUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return response.content[0].text, usage
