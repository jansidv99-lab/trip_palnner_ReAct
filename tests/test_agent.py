# Phase 6 – Step 7: the ReAct loop, parser, prompt and run log – driven by a scripted fake LLM.

import json
from pathlib import Path

import pytest

from agentsville.agent import (
    AgentRun,
    ItineraryAgent,
    ReplyParseError,
    parse_agent_reply,
)
from agentsville.evals import WEATHER_JUDGE_PROMPT
from agentsville.llm import LLMError, LLMResponse
from agentsville.prompts import PromptError, available_versions, load_itinerary_prompt
from agentsville.samples import sample_vacation_info
from agentsville.tools import build_default_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN = json.loads((REPO_ROOT / "sample_plan.json").read_text(encoding="utf-8"))


def action(tool_name: str, thought: str = "thinking", **arguments) -> str:
    reply = {"thought": thought, "action": {"tool_name": tool_name, "arguments": arguments}}
    return json.dumps(reply)


def bad_total_plan() -> dict:
    return {**GOLDEN, "total_cost": 120}


# Phase 6 – Step 7: replays scripted agent replies; answers weather-judge calls separately
class ScriptedLLM:
    default_model = "fake-model"

    def __init__(self, *replies: str, error: Exception | None = None, cost: float = 0.001):
        self.replies = list(replies)
        self.error = error
        self.cost = cost
        self.agent_calls: list[dict] = []
        self.judge_calls = 0

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        if messages[0]["content"] == WEATHER_JUDGE_PROMPT:
            self.judge_calls += 1
            return LLMResponse(
                text='{"suitable": true, "reason": "indoor"}', model="judge", latency_ms=1,
                prompt_tokens=50, completion_tokens=10, cost_usd=0.01,
            )
        self.agent_calls.append({"messages": [dict(m) for m in messages], "json_mode": json_mode})
        if self.error:
            raise self.error
        text = self.replies.pop(0) if self.replies else action("calculator_tool", expression="1+1")
        return LLMResponse(
            text=text, model=model or self.default_model, latency_ms=10.0,
            prompt_tokens=100, completion_tokens=20, cost_usd=self.cost,
        )


def make_agent(llm, tmp_path, **kwargs) -> ItineraryAgent:
    kwargs.setdefault("include_llm_evals", False)
    kwargs.setdefault("log_path", tmp_path / "runs.jsonl")
    return ItineraryAgent(llm, **kwargs)


HAPPY_SCRIPT = [
    action("get_weather_for_date_tool", date="2025-06-10"),
    action("get_activities_by_date_tool", date="2025-06-10"),
    action("run_evals_tool", travel_plan=GOLDEN),
    action("final_answer_tool", thought="Evals passed.", travel_plan=GOLDEN),
]

# --- prompt ---------------------------------------------------------------------------------


def test_prompt_v1_is_complete():
    prompt = load_itinerary_prompt("V1", build_default_registry().catalog())
    for name in build_default_registry().names:
        assert name in prompt
    assert '"itinerary_days"' in prompt  # TravelPlan schema inserted
    assert "PLAIN SUM" in prompt and "Do NOT multiply" in prompt  # cost rule
    assert "{{" not in prompt and "<!--" not in prompt


def test_unknown_prompt_version():
    with pytest.raises(PromptError, match="Available: v1"):
        load_itinerary_prompt("v99", "catalog")


def test_available_versions():
    assert "v1" in available_versions()


# --- parser ---------------------------------------------------------------------------------


def test_parse_valid_reply():
    parsed = parse_agent_reply(action("calculator_tool", thought="add up", expression="1+2"))
    assert (parsed.thought, parsed.tool_name, parsed.arguments) == (
        "add up", "calculator_tool", {"expression": "1+2"}
    )


def test_parse_tolerates_fences_and_surrounding_text():
    text = "Sure!\n```json\n" + action("calculator_tool", expression="2") + "\n```\nDone."
    assert parse_agent_reply(text).tool_name == "calculator_tool"


def test_parse_missing_arguments_defaults_to_empty():
    assert parse_agent_reply('{"thought": "t", "action": {"tool_name": "x"}}').arguments == {}


@pytest.mark.parametrize(
    "text, message",
    [
        ("I will check the weather.", "No JSON object found"),
        ('{"thought": "t", "action": {"tool_name": "x", ', "not valid JSON"),
        ('{"thought": "t"}', 'missing an "action" object'),
        ('{"thought": "t", "action": {"arguments": {}}}', 'missing a "tool_name"'),
        ('{"thought": "t", "action": {"tool_name": "x", "arguments": [1]}}', "must be a JSON"),
    ],
)
def test_parse_errors_guide_the_llm(text, message):
    with pytest.raises(ReplyParseError, match=message) as exc:
        parse_agent_reply(text)
    assert '"thought"' in str(exc.value)  # every error repeats the expected format


# --- happy path -----------------------------------------------------------------------------


def test_happy_path(tmp_path):
    llm = ScriptedLLM(*HAPPY_SCRIPT)
    run = make_agent(llm, tmp_path).run(sample_vacation_info())

    assert run.stop_reason == "final_answer"
    assert run.step_count == 4
    assert [s.tool_name for s in run.steps] == [
        "get_weather_for_date_tool", "get_activities_by_date_tool",
        "run_evals_tool", "final_answer_tool",
    ]
    assert run.travel_plan.total_cost == 108
    assert run.final_eval_report.passed
    assert run.steps[2].observation.startswith("EVALS PASSED")
    assert run.model == "fake-model" and run.prompt_version == "v1"


def test_conversation_shape(tmp_path):
    llm = ScriptedLLM(*HAPPY_SCRIPT)
    make_agent(llm, tmp_path).run(sample_vacation_info())

    assert all(call["json_mode"] for call in llm.agent_calls)
    first, second = llm.agent_calls[0]["messages"], llm.agent_calls[1]["messages"]
    assert [m["role"] for m in first] == ["system", "user"]
    assert "Plan this trip" in first[1]["content"] and '"Yuri"' in first[1]["content"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[2]["content"] == HAPPY_SCRIPT[0]
    assert second[3]["content"].startswith('OBSERVATION: {"temperature": 31.0')


# --- recovery and errors ----------------------------------------------------------------------


def test_recovers_from_unparseable_reply(tmp_path):
    llm = ScriptedLLM("I think I'll look at the weather", HAPPY_SCRIPT[-1])
    run = make_agent(llm, tmp_path).run(sample_vacation_info())
    assert run.steps[0].is_error and run.steps[0].tool_name is None
    assert run.steps[0].observation.startswith("ERROR: No JSON object found")
    assert run.stop_reason == "final_answer"


def test_unknown_tool_is_observation_and_loop_continues(tmp_path):
    llm = ScriptedLLM(action("book_hotel_tool"), HAPPY_SCRIPT[-1])
    run = make_agent(llm, tmp_path).run(sample_vacation_info())
    assert "unknown tool 'book_hotel_tool'" in run.steps[0].observation
    assert run.stop_reason == "final_answer"


def test_max_steps(tmp_path):
    run = make_agent(ScriptedLLM(), tmp_path, max_steps=3).run(sample_vacation_info())
    assert run.stop_reason == "max_steps"
    assert run.step_count == 3 and run.travel_plan is None and run.final_eval_report is None


def test_llm_error_stops_run(tmp_path):
    run = make_agent(ScriptedLLM(error=LLMError("timeout")), tmp_path).run(sample_vacation_info())
    assert run.stop_reason == "llm_error" and "timeout" in run.error
    assert run.step_count == 0


# --- guardrail ----------------------------------------------------------------------------------


def test_guardrail_rejects_then_accepts_fixed_plan(tmp_path):
    llm = ScriptedLLM(
        action("final_answer_tool", travel_plan=bad_total_plan()),
        action("final_answer_tool", travel_plan=GOLDEN),
    )
    run = make_agent(llm, tmp_path).run(sample_vacation_info())
    assert run.steps[0].is_error
    assert run.steps[0].observation.startswith("Final answer REJECTED")
    assert "✗ total_cost_accurate" in run.steps[0].observation
    assert run.final_rejections == 1
    assert run.stop_reason == "final_answer" and run.travel_plan.total_cost == 108


def test_guardrail_gives_up_after_max_rejections(tmp_path):
    llm = ScriptedLLM(*[action("final_answer_tool", travel_plan=bad_total_plan())] * 3)
    run = make_agent(llm, tmp_path).run(sample_vacation_info())
    assert run.final_rejections == 2 and run.step_count == 3
    assert run.stop_reason == "final_answer"
    assert not run.final_eval_report.passed  # accepted, but the report shows the failure


# --- metrics, judge metering, callback, log ----------------------------------------


def test_metrics_include_judge_calls(tmp_path):
    llm = ScriptedLLM(*HAPPY_SCRIPT, cost=0.001)
    run = make_agent(llm, tmp_path, include_llm_evals=True).run(sample_vacation_info())
    # golden plan has one inclement-day activity: judged in run_evals_tool and in the final evals
    assert run.judge_calls == 2 and llm.judge_calls == 2
    assert run.total_prompt_tokens == 400 and run.total_completion_tokens == 80
    assert run.total_cost_usd == pytest.approx(4 * 0.001 + 2 * 0.01)
    assert run.total_latency_ms == pytest.approx(40.0)


def test_on_step_callback(tmp_path):
    seen = []
    make_agent(ScriptedLLM(*HAPPY_SCRIPT), tmp_path, on_step=seen.append).run(
        sample_vacation_info()
    )
    assert [s.step for s in seen] == [1, 2, 3, 4]


def test_run_logged_as_one_json_line(tmp_path):
    log = tmp_path / "logs" / "runs.jsonl"
    agent = make_agent(ScriptedLLM(*HAPPY_SCRIPT, *HAPPY_SCRIPT), tmp_path, log_path=log)
    first, second = agent.run(sample_vacation_info()), agent.run(sample_vacation_info())
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    restored = AgentRun.model_validate_json(lines[0])
    assert restored.run_id == first.run_id != second.run_id
    assert restored.travel_plan == first.travel_plan and restored.step_count == 4


def test_no_log_when_path_is_none(tmp_path):
    make_agent(ScriptedLLM(*HAPPY_SCRIPT), tmp_path, log_path=None).run(sample_vacation_info())
    assert not list(tmp_path.iterdir())
