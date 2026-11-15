# Phase 5 – Step 7: run example ACTIONs through the tool registry, exactly as the agent will.
"""Run from the repo root:

    python scripts/try_tools.py            # sample actions (no LLM calls)
    python scripts/try_tools.py --catalog  # print the tool catalog the agent will see
    python scripts/try_tools.py --llm      # also let run_evals_tool use the real weather judge
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentsville.config import get_settings  # noqa: E402
from agentsville.llm import LLMClient  # noqa: E402
from agentsville.samples import sample_vacation_info  # noqa: E402
from agentsville.tools import ToolContext, build_default_registry  # noqa: E402

GOLDEN_PLAN = json.loads((ROOT / "sample_plan.json").read_text(encoding="utf-8"))

# Each entry is what the LLM would write after "ACTION:".
SAMPLE_ACTIONS = [
    {"tool_name": "get_weather_for_date_tool", "arguments": {"date": "2025-06-12"}},
    {
        "tool_name": "filter_activities_by_interest_tool",
        "arguments": {"date": "2025-06-12", "interests": ["technology", "music"]},
    },
    {"tool_name": "calculator_tool", "arguments": {"expression": "20 + 20 + 15 + 20 + 18 + 15"}},
    {"tool_name": "calculator_tool", "arguments": {"expression": "__import__('os')"}},
    {"tool_name": "get_weather_for_date_tool", "arguments": {"date": "2025-07-01"}},
    {"tool_name": "book_hotel_tool", "arguments": {}},
    {"tool_name": "run_evals_tool", "arguments": {"travel_plan": GOLDEN_PLAN}},
    {"tool_name": "final_answer_tool", "arguments": {"travel_plan": GOLDEN_PLAN}},
]


def short(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit] + f"… (+{len(text) - limit} chars)"


# Phase 5 – Step 7: print each ACTION and the OBSERVATION the agent would receive
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", action="store_true", help="print the tool catalog and exit")
    parser.add_argument("--llm", action="store_true", help="use the real weather judge in evals")
    args = parser.parse_args()

    registry = build_default_registry()
    if args.catalog:
        print(registry.catalog())
        return

    context = ToolContext(
        vacation_info=sample_vacation_info(),
        llm=LLMClient(get_settings()) if args.llm else None,
        include_llm_evals=args.llm,
    )
    for action in SAMPLE_ACTIONS:
        arguments = short(json.dumps(action["arguments"], ensure_ascii=False), 80)
        print(f'ACTION: {{"tool_name": "{action["tool_name"]}", "arguments": {arguments}}}')
        result = registry.execute(action["tool_name"], action["arguments"], context)
        flags = " [error]" if result.is_error else (" [final]" if result.is_final else "")
        print(f"OBSERVATION{flags}: {short(result.observation)}\n")


if __name__ == "__main__":
    main()
