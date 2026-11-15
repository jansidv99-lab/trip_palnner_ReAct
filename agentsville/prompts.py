# Phase 6 – Step 1: load versioned prompt files and fill their placeholders.
"""Prompts live in prompts/<name>/<version>.md so changes are reviewable diffs and versions
can be compared (Phase 7). Placeholders use {{NAME}} and are filled with plain string
replacement, because JSON schemas contain braces that str.format would misread."""

import json
import re
from pathlib import Path

from agentsville.models import TravelPlan

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")
_HTML_COMMENT = re.compile(r"<!--.*?-->\s*", re.S)


# Phase 6 – Step 1: one error type for missing versions or unfilled placeholders
class PromptError(RuntimeError):
    """Raised when a prompt file is missing or a placeholder is left unfilled."""


# Phase 6 – Step 1: list the versions available for a prompt (e.g. ["v1"])
def available_versions(name: str = "itinerary") -> list[str]:
    return sorted(p.stem for p in (PROMPTS_DIR / name).glob("*.md"))


# Phase 6 – Step 1: read a prompt file and replace {{NAME}} placeholders
def render_prompt(name: str, version: str, values: dict[str, str]) -> str:
    path = PROMPTS_DIR / name / f"{version.lower()}.md"
    if not path.is_file():
        raise PromptError(
            f"no prompt '{name}/{version}'. Available: {', '.join(available_versions(name))}"
        )
    text = _HTML_COMMENT.sub("", path.read_text(encoding="utf-8"))
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    leftover = _PLACEHOLDER.findall(text)
    if leftover:
        raise PromptError(f"unfilled placeholders in '{name}/{version}': {', '.join(leftover)}")
    return text.strip()


# Phase 6 – Step 1: the itinerary agent's system prompt with the real tools and schema
def load_itinerary_prompt(version: str, tool_catalog: str) -> str:
    return render_prompt(
        "itinerary",
        version,
        {
            "TOOL_CATALOG": tool_catalog,
            "TRAVEL_PLAN_SCHEMA": json.dumps(TravelPlan.model_json_schema(), indent=2),
        },
    )
