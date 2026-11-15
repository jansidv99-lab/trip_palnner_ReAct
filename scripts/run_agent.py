# Phase 6 – Step 8: run the ReAct agent on a sample request and watch every step live.
"""Run from the repo root:

    python scripts/run_agent.py                     # sample request, model from .env
    python scripts/run_agent.py --sample rainy      # default | tight | rainy
    python scripts/run_agent.py --model gpt-4.1-mini --max-steps 15 --no-log
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville import samples  # noqa: E402
from agentsville.agent import AgentStep, ItineraryAgent  # noqa: E402
from agentsville.config import ConfigError, get_settings  # noqa: E402
from agentsville.llm import LLMClient  # noqa: E402

SAMPLES = {
    "default": samples.sample_vacation_info,
    "tight": samples.tight_budget_vacation_info,
    "rainy": samples.rainy_days_vacation_info,
}


def short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + f"… (+{len(text) - limit} chars)"


# Phase 6 – Step 8: print one step as it happens
def print_step(step: AgentStep) -> None:
    print(f"\n── step {step.step} " + "─" * 70)
    if step.thought:
        print(f"THOUGHT: {short(step.thought, 400)}")
    if step.tool_name:
        print(f"ACTION:  {step.tool_name}({short(json.dumps(step.arguments), 120)})")
    tag = "OBSERVATION (error)" if step.is_error else "OBSERVATION"
    if "\n" in step.observation:  # eval summaries are multi-line: show them in full
        print(f"{tag}:\n{step.observation}")
    else:
        print(f"{tag}: {short(step.observation, 400)}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the AgentsVille itinerary agent.")
    parser.add_argument("--sample", choices=SAMPLES, default="default")
    parser.add_argument("--model", help="override MODEL from .env")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--no-log", action="store_true", help="don't append to logs/")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except ConfigError as exc:
        print(f"config error: {exc}")
        return 1

    agent_kwargs = {"log_path": None} if args.no_log else {}
    agent = ItineraryAgent(
        LLMClient(settings),
        model=args.model,
        prompt_version=settings.prompt_version,
        max_steps=args.max_steps,
        on_step=print_step,
        **agent_kwargs,
    )
    request = SAMPLES[args.sample]()
    print(f"model={agent.model} prompt={agent.prompt_version} sample={args.sample}")
    run = agent.run(request)

    print("\n" + "═" * 80)
    print(f"stop_reason: {run.stop_reason}" + (f"  error: {run.error}" if run.error else ""))
    if run.travel_plan:
        plan = run.travel_plan
        print(f"plan: {plan.city} {plan.start_date} → {plan.end_date}, "
              f"total_cost={plan.total_cost} (budget {request.budget})")
        for day in plan.itinerary_days:
            names = ", ".join(r.activity.name for r in day.activity_recommendations) or "—"
            print(f"  {day.date} [{day.weather.condition}]: {names}")
    if run.final_eval_report:
        print("\n" + run.final_eval_report.summary())
    print(
        f"\nsteps={run.step_count} rejections={run.final_rejections} "
        f"tokens={run.total_prompt_tokens}+{run.total_completion_tokens} "
        f"judge_calls={run.judge_calls} cost=${run.total_cost_usd:.4f} "
        f"time={run.total_latency_ms / 1000:.1f}s"
    )
    if not args.no_log:
        print(f"run logged: logs/agent_runs.jsonl (run_id={run.run_id})")
    return 0 if run.stop_reason == "final_answer" else 1


if __name__ == "__main__":
    sys.exit(main())
