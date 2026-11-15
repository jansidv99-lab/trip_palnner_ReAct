# Phase 4 – Step 7: evaluate a plan file against the sample request and print the report.
"""Run from the repo root:

    python scripts/run_evals.py                 # sample_plan.json, with the LLM judge (~1 cent)
    python scripts/run_evals.py --no-llm        # deterministic evals only (free)
    python scripts/run_evals.py --plan my.json  # evaluate another TravelPlan JSON file
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentsville.config import ConfigError, get_settings  # noqa: E402
from agentsville.evals import run_all_evals  # noqa: E402
from agentsville.llm import LLMClient  # noqa: E402
from agentsville.models import TravelPlan  # noqa: E402
from agentsville.samples import sample_vacation_info  # noqa: E402


# Phase 4 – Step 7: parse args, load the plan, run evals, print the summary
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description="Run itinerary evals on a TravelPlan JSON file.")
    parser.add_argument("--plan", type=Path, default=ROOT / "sample_plan.json")
    parser.add_argument("--no-llm", action="store_true", help="skip the LLM weather judge")
    args = parser.parse_args()

    plan = TravelPlan.model_validate_json(args.plan.read_text(encoding="utf-8"))
    llm = None
    if not args.no_llm:
        try:
            llm = LLMClient(get_settings())
        except ConfigError as exc:
            print(f"config error: {exc}")
            return 1

    report = run_all_evals(sample_vacation_info(), plan, llm=llm, include_llm=not args.no_llm)
    print(f"plan: {args.plan.name}   request: sample_vacation_info()\n")
    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
