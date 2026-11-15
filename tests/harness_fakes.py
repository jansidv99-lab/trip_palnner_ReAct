# Phase 7 – Step 9: shared fakes for harness tests (no network, deterministic, thread-safe).

import json
from datetime import date
from pathlib import Path

from agentsville.evals import WEATHER_JUDGE_PROMPT
from agentsville.harness.dataset import GoldenCase, GoldenLabels, write_golden
from agentsville.llm import LLMError, LLMResponse
from agentsville.samples import rainy_days_vacation_info, sample_vacation_info

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PLAN = json.loads((REPO_ROOT / "sample_plan.json").read_text(encoding="utf-8"))


def action(tool_name: str, **arguments) -> str:
    return json.dumps({"thought": "t", "action": {"tool_name": tool_name, "arguments": arguments}})


# Phase 7 – Step 9: stands in for LLMClient – the reply depends only on the conversation, so
# concurrent runs are independent: step k gets script[k] (the last reply repeats);
# judge calls get a fixed verdict.
class ConversationFake:
    default_model = "fake-model"

    def __init__(self, script: list[str], fail_judge: bool = False):
        self.script = script
        self.fail_judge = fail_judge
        self.calls = 0

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        self.calls += 1
        if messages[0]["content"] == WEATHER_JUDGE_PROMPT:
            if self.fail_judge:
                raise LLMError("judge unavailable")
            return LLMResponse(text='{"suitable": true, "reason": "ok"}', model="judge",
                               latency_ms=2.0, prompt_tokens=40, completion_tokens=8,
                               cost_usd=0.002)
        step = sum(m["role"] == "assistant" for m in messages)
        text = self.script[min(step, len(self.script) - 1)]  # keep repeating the last reply
        return LLMResponse(text=text, model=model or self.default_model, latency_ms=10.0,
                           prompt_tokens=100, completion_tokens=20, cost_usd=0.001)


HAPPY_SCRIPT = [
    action("get_weather_for_date_tool", date="2025-06-10"),
    action("final_answer_tool", travel_plan=GOLDEN_PLAN),
]


# Phase 7 – Step 9: a tiny 2-case dataset in a temp folder (g01 matches the golden plan)
def make_dataset(root: Path, version: str = "v0.0.1") -> None:
    labels = GoldenLabels(expected_behavior="test")
    write_golden(
        version,
        [
            GoldenCase(case_id="g01-sample", tags=["test"], description="matches sample_plan.json",
                       vacation_info=sample_vacation_info(), labels=labels),
            GoldenCase(case_id="g02-rainy", tags=["test"], description="different dates",
                       vacation_info=rainy_days_vacation_info(), labels=labels),
        ],
        created=date(2026, 1, 1),
        root=root,
    )
