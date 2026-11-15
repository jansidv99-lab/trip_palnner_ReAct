# Phase 8 – Step 11: B1 grounding graders, run-level grading, thresholds and the production signal.

import json

import pytest

from agentsville.agent import AgentRun, AgentStep
from agentsville.graders import B1_GRADERS
from agentsville.graders.grounding import (
    activity_grounding,
    check_reason_references,
    first_difference,
    reason_references,
    reasons_grounded,
    trajectory_grounding,
    weather_grounding,
)
from agentsville.graders.signals import grounding_signal
from agentsville.harness.grading import grade_run
from agentsville.llm import LLMError
from agentsville.models import TravelPlan
from agentsville.samples import sample_vacation_info
from agentsville.tools import ToolContext, build_default_registry
from tests.harness_fakes import GOLDEN_PLAN, ConversationFake

REGISTRY = build_default_registry()


def tool_step(n: int, tool: str, **arguments) -> AgentStep:
    """A step with a REAL observation produced by the actual tool."""
    result = REGISTRY.execute(tool, arguments, ToolContext(sample_vacation_info()))
    return AgentStep(step=n, raw_reply="", tool_name=tool, arguments=arguments,
                     observation=result.observation, is_error=result.is_error)


def golden_run(plan: dict | None = None, steps: list[AgentStep] | None = None) -> AgentRun:
    if steps is None:  # an agent that looked everything up properly
        steps = []
        for day in ("2025-06-10", "2025-06-11", "2025-06-12"):
            steps.append(tool_step(len(steps) + 1, "get_weather_for_date_tool", date=day))
            steps.append(tool_step(len(steps) + 1, "get_activities_by_date_tool", date=day))
    plan = GOLDEN_PLAN if plan is None else plan
    return AgentRun(model="m", prompt_version="v1", vacation_info=sample_vacation_info(),
                    system_prompt="", user_prompt="", steps=steps, stop_reason="final_answer",
                    travel_plan=TravelPlan.model_validate(plan) if plan else None)


def mutated(**changes) -> dict:
    plan = json.loads(json.dumps(GOLDEN_PLAN))
    activity = plan["itinerary_days"][0]["activity_recommendations"][0]
    for key, value in changes.items():
        if key == "reasons":
            activity["reasons_for_recommendation"] = value
        else:
            activity["activity"][key] = value
    return plan


# --- activity / weather grounding ----------------------------------------------------------


def test_golden_plan_is_fully_grounded():
    outcomes = grade_run(golden_run(), [g for g in B1_GRADERS if g.kind == "deterministic"])
    assert all(o.passed for o in outcomes.values()), outcomes
    assert outcomes["activity_grounding"].units == 6
    assert outcomes["reason_references"].units == 11


def test_fabricated_activity():
    o = activity_grounding(golden_run(mutated(activity_id="event-2025-06-10-9")))
    assert o.counts["fabricated"] == 1 and o.failed_units == 1 and "not in data" in o.details[0]


def test_altered_price_names_the_field():
    o = activity_grounding(golden_run(mutated(price=5)))
    assert o.counts["altered"] == 1 and "fields price" in o.details[0]


def test_altered_description_shows_first_difference():
    source = GOLDEN_PLAN["itinerary_days"][0]["activity_recommendations"][0]["activity"]
    o = activity_grounding(golden_run(mutated(description=source["description"][:120])))
    assert "description at char 120" in o.details[0]


def test_first_difference_snippet():
    assert first_difference("abcdef", "abcXef").startswith("at char 3")
    assert first_difference("abc", "abcdef").startswith("at char 3")  # truncated text


def test_wrong_weather_fails_that_day():
    plan = json.loads(json.dumps(GOLDEN_PLAN))
    plan["itinerary_days"][1]["weather"]["condition"] = "sunny"
    o = weather_grounding(golden_run(plan))
    assert o.units == 3 and o.failed_units == 1 and "2025-06-11" in o.details[0]


# --- trajectory grounding --------------------------------------------------------------------


def test_activity_never_retrieved():
    steps = [tool_step(1, "get_weather_for_date_tool", date=d)
             for d in ("2025-06-10", "2025-06-11", "2025-06-12")]
    o = trajectory_grounding(golden_run(steps=steps))
    assert o.counts == {"activity_not_retrieved": 6, "weather_not_retrieved": 0}


def test_retrieval_via_id_and_filter_tools_counts():
    ids = [rec["activity"]["activity_id"] for day in GOLDEN_PLAN["itinerary_days"]
           for rec in day["activity_recommendations"]]
    steps = [tool_step(1, "get_weather_for_date_tool", date=d)
             for d in ("2025-06-10", "2025-06-11", "2025-06-12")]
    steps += [tool_step(10 + i, "get_activity_by_id_tool", activity_id=a)
              for i, a in enumerate(ids)]
    assert trajectory_grounding(golden_run(steps=steps)).passed
    steps[-1] = tool_step(99, "filter_activities_by_interest_tool", date="2025-06-12",
                          interests=["technology"])
    assert trajectory_grounding(golden_run(steps=steps)).passed


def test_weather_never_retrieved_and_error_observations_ignored():
    steps = [tool_step(1, "get_activities_by_date_tool", date=d)
             for d in ("2025-06-10", "2025-06-11", "2025-06-12")]
    steps.append(tool_step(9, "get_weather_for_date_tool", date="bad-date"))  # an error step
    o = trajectory_grounding(golden_run(steps=steps))
    assert o.counts["weather_not_retrieved"] == 3


# --- reason references --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason, problem",
    [
        ("Matches Yuri's interest in technology", None),
        ("Matches Yuri's technology and Hiro's music interests", None),
        ("Indoor venue avoids the storm", None),
        ("Matches Hiro's interest in movies", "Hiro has no interest in movies"),
        ("Matches Maria's interest in art", "'Maria' is not a traveler"),
        ("Matches Yuri's technology and Hiro's tennis interests", "Hiro has no interest in tennis"),
    ],
)
def test_check_reason_references(reason, problem):
    problems = check_reason_references(reason, sample_vacation_info().travelers)
    assert problems == ([] if problem is None else [problem])


def test_reason_references_counts_reasons():
    o = reason_references(golden_run(mutated(reasons=["Matches Hiro's interest in movies", "ok"])))
    assert o.units == 11 and o.failed_units == 1  # first activity: 2 reasons replaced by 2


# --- reasons judge ----------------------------------------------------------------------------


def test_reasons_judge_one_call_per_activity():
    fake = ConversationFake([])
    o = reasons_grounded(golden_run(), fake)
    assert o.passed and o.units == 11 and fake.calls == 6


def test_reasons_judge_flags_ungrounded():
    o = reasons_grounded(golden_run(mutated(reasons=["ok", "UNGROUNDED free lunch"])),
                         ConversationFake([]))
    assert o.failed_units == 1 and "UNGROUNDED free lunch" in o.details[0]


class BrokenJudge:
    def __init__(self, text=None, error=None):
        self.text, self.error = text, error

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        from agentsville.llm import LLMResponse
        if self.error:
            raise self.error
        return LLMResponse(text=self.text, model="judge", latency_ms=1)


@pytest.mark.parametrize(
    "judge, message",
    [
        (BrokenJudge(text="not json"), "unparseable"),
        (BrokenJudge(error=LLMError("timeout")), "judge call failed"),
        (BrokenJudge(text='{"reasons": []}'), "returned 0 verdicts"),
    ],
)
def test_reasons_judge_fails_closed(judge, message):
    o = reasons_grounded(golden_run(), judge)
    assert o.failed_units == o.units == 11 and message in o.details[0]


# --- run-level grading --------------------------------------------------------------------------


def test_run_without_plan_fails_every_grader():
    run = golden_run().model_copy(update={"travel_plan": None, "stop_reason": "max_steps"})
    outcomes = grade_run(run, B1_GRADERS, ConversationFake([]))
    assert all(not o.passed and o.units == 0 for o in outcomes.values())


def test_code_graders_never_receive_the_llm():
    outcomes = grade_run(golden_run(), B1_GRADERS, llm=ConversationFake([]))
    assert set(outcomes) == {g.name for g in B1_GRADERS}


# --- production signal ----------------------------------------------------------------------------


def test_grounding_signal_counts():
    run = golden_run(mutated(activity_id="event-x", reasons=["Matches Hiro's interest in movies"]))
    outcomes = grade_run(run, B1_GRADERS, ConversationFake([]))
    signal = grounding_signal(outcomes, judge_sampled=True)
    assert signal.plan_produced and signal.planned_activities == 6
    assert signal.fabricated_activities == 1 and signal.reason_reference_errors == 1
    assert signal.judge_sampled and signal.ungrounded_reasons == 0
    unsampled = grounding_signal(outcomes, judge_sampled=False)
    assert unsampled.ungrounded_reasons is None and not unsampled.judge_sampled


def test_grounding_signal_without_plan():
    run = golden_run().model_copy(update={"travel_plan": None})
    signal = grounding_signal(grade_run(run, B1_GRADERS), judge_sampled=False)
    assert not signal.plan_produced and signal.planned_activities == 0
