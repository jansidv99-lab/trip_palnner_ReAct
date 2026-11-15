# Phase 10 – Step 3: B3 trajectory graders – procedure adherence, faithfulness, efficiency.
# Phase 10 – Step 5: thought↔action consistency judge and its calibration.

import copy
import json
from datetime import date

import pytest

from agentsville.agent import AgentStep
from agentsville.graders.trajectory import (
    activity_lookup_coverage,
    calculator_total,
    compact_observation,
    judge_thought_action,
    steps_before_final,
    thought_action_consistency,
    thought_action_input,
    thought_action_prompt,
    tool_efficiency,
    verified_before_final,
    weather_lookup_coverage,
)
from agentsville.harness.calibration import calibrate_thought_action_judge
from agentsville.harness.dataset import (
    ThoughtActionCalibrationItem,
    load_thought_action_calibration,
    write_calibration,
)
from agentsville.harness.grading import GradingContext
from agentsville.llm import LLMError, LLMResponse
from tests.harness_fakes import GOLDEN_PLAN
from tests.test_constraints import empty_plan, run_with

# sample_vacation_info(): trip 2025-06-10 → 06-12; GOLDEN_PLAN prices sum to 108.
DAYS = ("2025-06-10", "2025-06-11", "2025-06-12")
PASSED = "EVALS PASSED (9/9 ok)\n✓ city_and_dates"
FAILED = "EVALS FAILED (8/9 ok)\n✗ total_cost_accurate\n    - plan says total_cost=90"


def step(tool, observation="ok", is_error=False, **arguments) -> AgentStep:
    return AgentStep(step=0, raw_reply="{}", tool_name=tool, arguments=arguments,
                     observation=observation, is_error=is_error)


def lookups() -> list[AgentStep]:
    return [s for d in DAYS for s in (step("get_weather_for_date_tool", date=d),
                                      step("get_activities_by_date_tool", date=d))]


def run(steps, plan=GOLDEN_PLAN, stop="final_answer"):
    """A run whose steps are numbered and, for final_answer runs, end with the accepted final."""
    steps = list(steps)
    if stop == "final_answer":
        steps.append(step("final_answer_tool", "Final answer accepted.", travel_plan=plan))
    numbered = [s.model_copy(update={"step": n}) for n, s in enumerate(steps, start=1)]
    return run_with(plan if stop == "final_answer" else None, stop_reason=stop).model_copy(
        update={"steps": numbered})


def faithful_steps(plan=GOLDEN_PLAN):
    return [*lookups(), step("calculator_tool", "108", expression="20+20+15+20+18+15"),
            step("run_evals_tool", PASSED, travel_plan=plan)]


# --- lookup coverage ------------------------------------------------------------------------------


def test_lookup_coverage_every_day():
    r = run(faithful_steps())
    assert weather_lookup_coverage(r).passed and weather_lookup_coverage(r).units == 3
    assert activity_lookup_coverage(r).passed


def test_lookup_coverage_missing_day_and_error_lookup_do_not_count():
    steps = [s for s in lookups() if s.arguments["date"] != "2025-06-12"]
    steps.append(step("get_weather_for_date_tool", "ERROR: boom", is_error=True, date="2025-06-12"))
    o = weather_lookup_coverage(run(steps))
    assert not o.passed and (o.units, o.failed_units) == (3, 1)
    assert o.details == ["2025-06-12: never looked up before the final answer"]


def test_filter_tool_counts_as_activity_lookup():
    steps = [step("filter_activities_by_interest_tool", date=d, interests=["art"]) for d in DAYS]
    assert activity_lookup_coverage(run(steps)).passed


def test_lookup_after_the_final_answer_does_not_count():
    # in a max_steps run every step counts; for a final_answer run the last step is the final
    r = run(lookups())
    assert steps_before_final(r) == r.steps[:-1]
    assert run(lookups(), stop="max_steps").steps == steps_before_final(
        run(lookups(), stop="max_steps"))


# --- calculator_total -----------------------------------------------------------------------------


def test_calculator_total_faithful():
    o = calculator_total(run(faithful_steps()))
    assert o.passed and o.units == 1


def test_calculator_total_accepts_any_correct_expression():
    steps = [*lookups(), step("calculator_tool", "108", expression="2*20 + 2*15 + 20 + 18")]
    assert calculator_total(run(steps)).passed


def test_calculator_total_wrong_price_list():
    # B2's bookkeeping error: the calculator sums the wrong prices and the plan copies the result
    plan = copy.deepcopy(GOLDEN_PLAN)
    plan["total_cost"] = 93
    steps = [*lookups(), step("calculator_tool", "93", expression="20+20+20+18+15")]
    o = calculator_total(run(steps, plan=plan))
    assert not o.passed and o.counts == {"wrong_price_list": 1}
    assert "prices sum to 108 (missing [15], extra [])" in o.details[0]


def test_calculator_total_correct_but_not_from_calculator():
    steps = [*lookups(), step("calculator_tool", "70", expression="20+20+15+15")]
    o = calculator_total(run(steps))  # plan says 108 – right, but not what the calculator said
    assert not o.passed and o.counts == {"total_not_from_calculator": 1}


@pytest.mark.parametrize("calc_steps", [[], [step("calculator_tool", "ERROR: bad", is_error=True,
                                                  expression="1/0")]])
def test_calculator_total_no_calculator(calc_steps):
    o = calculator_total(run([*lookups(), *calc_steps]))
    assert not o.passed and o.counts == {"no_calculator": 1}


def test_calculator_total_not_applicable_to_empty_plan():
    o = calculator_total(run(lookups(), plan=empty_plan()))
    assert o.passed and o.units == 0


# --- verified_before_final ------------------------------------------------------------------------


def test_verified_before_final_passes_when_submitted_plan_passed_evals():
    assert verified_before_final(run(faithful_steps())).passed


def test_verified_before_final_plan_changed_after_evals():
    other = copy.deepcopy(GOLDEN_PLAN)
    other["itinerary_days"][0]["activity_recommendations"].pop()
    o = verified_before_final(run([step("run_evals_tool", PASSED, travel_plan=other)]))
    assert not o.passed and o.counts == {"plan_changed_after_evals": 1}


def test_verified_before_final_last_evals_failed():
    o = verified_before_final(run([step("run_evals_tool", FAILED, travel_plan=GOLDEN_PLAN)]))
    assert not o.passed and o.counts == {"last_evals_failed": 1}


def test_verified_before_final_never_ran_evals():
    bad_args = step("run_evals_tool", "ERROR: invalid arguments for run_evals_tool: x",
                    is_error=True, travel_plan={})
    o = verified_before_final(run([*lookups(), bad_args]))
    assert not o.passed and o.counts == {"never_ran_evals": 1}


def test_verified_before_final_ignores_formatting_differences():
    # same plan, keys in a different order – compared through the TravelPlan model
    reordered = dict(reversed(list(GOLDEN_PLAN.items())))
    checked = step("run_evals_tool", PASSED, travel_plan=reordered)
    assert verified_before_final(run([checked])).passed


def test_verified_before_final_not_applicable_without_final_answer():
    assert verified_before_final(run(lookups(), stop="max_steps")).units == 0


# --- tool_efficiency ------------------------------------------------------------------------------


def test_tool_efficiency_identical_repeat_is_redundant():
    repeat = step("get_weather_for_date_tool", date="2025-06-10")
    o = tool_efficiency(run([*lookups(), repeat]))
    assert not o.passed and (o.units, o.failed_units) == (7, 1)
    assert o.counts == {"redundant": 1}


def test_tool_efficiency_retry_after_error_and_different_args_are_not_redundant():
    steps = [step("get_weather_for_date_tool", "ERROR: x", is_error=True, date="2025-06-10"),
             *lookups(),
             step("filter_activities_by_interest_tool", date="2025-06-10", interests=["art"]),
             step("filter_activities_by_interest_tool", date="2025-06-10", interests=["music"])]
    o = tool_efficiency(run(steps))
    assert o.passed and o.counts == {"error_steps": 1}


def test_tool_efficiency_judges_runs_without_a_plan():
    from agentsville.graders import B3_GRADERS
    from agentsville.harness.grading import grade_run

    code_graders = [g for g in B3_GRADERS if g.kind == "deterministic"]  # no LLM here
    outcomes = grade_run(run([*lookups(), lookups()[0]], stop="max_steps"), code_graders)
    assert outcomes["tool_efficiency"].counts == {"redundant": 1}
    assert outcomes["calculator_total"].details == ["no plan produced"]  # B0 rule still applies


# --- thought↔action judge (Phase 10 – Step 5) ---------------------------------------------------


class StepJudge:
    """Fake thought↔action judge: replies with given verdicts (or raises)."""

    def __init__(self, verdicts=None, text=None, error=None):
        self.text = text if text is not None else json.dumps({"steps": verdicts or []})
        self.error, self.calls, self.messages = error, 0, None

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        self.calls, self.messages = self.calls + 1, messages
        if self.error:
            raise self.error
        return LLMResponse(text=self.text, model="judge", latency_ms=1)


def thought(step: AgentStep, text: str) -> AgentStep:
    return step.model_copy(update={"thought": text})


def ok(n):
    return {"step": n, "consistent": True}


def bad(n, quote, kind="action_mismatch"):
    return {"step": n, "consistent": False, "type": kind, "quote": quote, "why": "w"}


def resubmission_run():
    """evals → fails → 'I will remove an activity' but the SAME plan is sent again."""
    steps = [thought(step("run_evals_tool", FAILED, travel_plan=GOLDEN_PLAN), "Checking my plan."),
             thought(step("run_evals_tool", FAILED, travel_plan=GOLDEN_PLAN),
                     "I will remove the most expensive activity.")]
    return run(steps, stop="max_steps")


def test_thought_action_input_gives_code_facts():
    r = resubmission_run()
    text = thought_action_input(r.steps, budget=130)
    assert "FACT: first travel_plan sent in this trajectory" in text
    assert "FACT: IDENTICAL to the travel_plan sent at step 1" in text
    assert "06-10: [10-0, 10-1, 10-3]" in text and "FACT: prices sum to 108, budget 130" in text
    assert text.startswith("STEP 1\nPREVIOUS OBSERVATION: (start of the run")
    assert "PREVIOUS OBSERVATION: EVALS FAILED (8/9 ok) | ✗ total_cost_accurate" in text


def test_compact_observation_keeps_every_activity():
    from agentsville.data_api import get_activities

    raw = json.dumps([a.model_dump(mode="json") for a in get_activities("2025-06-13")])
    text = compact_observation(raw)
    assert text.startswith("4 activities: event-2025-06-13-0 | Laugh & Groove")
    assert text.count("event-2025-06-13-") == 4 and len(text) < len(raw) / 3


def test_unparsed_steps_are_not_judged_but_keep_the_observation_chain():
    steps = [AgentStep(step=1, raw_reply="garbage", observation="ERROR: reply was not JSON"),
             thought(step("calculator_tool", "108", expression="1+1"), "Add up.")]
    text = thought_action_input(run(steps, stop="max_steps").steps, budget=130)
    assert "STEP 1" not in text and "PREVIOUS OBSERVATION: ERROR: reply was not JSON" in text


def test_judge_flags_claimed_fix_with_identical_plan():
    judge = StepJudge([ok(1), bad(2, "I will remove the most expensive activity")])
    o = thought_action_consistency(resubmission_run(), GradingContext(llm=judge))
    assert judge.calls == 1 and judge.messages[0]["content"] == thought_action_prompt()
    assert (o.units, o.failed_units) == (2, 1) and o.counts == {"action_mismatch": 1}
    assert o.details[0].startswith("step 2 (action_mismatch): 'I will remove")


def test_judge_claim_with_invented_quote_is_rejected():
    judge = StepJudge([ok(1), bad(2, "I removed the cheapest activity")])  # not in the thought
    o = thought_action_consistency(resubmission_run(), GradingContext(llm=judge))
    assert o.passed and o.units == 2


def test_quote_matching_ignores_case_spacing_and_quotes():
    judge = StepJudge([ok(1), bad(2, '"i will  remove the MOST expensive activity."')])
    o = thought_action_consistency(resubmission_run(), GradingContext(llm=judge))
    assert o.failed_units == 1


@pytest.mark.parametrize(
    "judge, message",
    [(StepJudge(text="not json"), "unparseable"),
     (StepJudge(error=LLMError("timeout")), "judge call failed"),
     (StepJudge([ok(1)]), "judge returned steps [1], expected [1, 2]")],
)
def test_thought_action_fails_closed(judge, message):
    o = thought_action_consistency(resubmission_run(), GradingContext(llm=judge))
    assert o.failed_units == o.units == 2 and o.counts == {"judge_failure": 2}
    assert message in o.details[0]


def test_thought_action_judges_runs_without_a_plan_and_skips_empty_trajectories():
    judge = StepJudge([ok(1), ok(2)])
    assert thought_action_consistency(resubmission_run(), GradingContext(llm=judge)).units == 2
    assert judge_thought_action(StepJudge(), [], budget=10) == []


def test_calibrate_thought_action_judge(tmp_path):
    r = resubmission_run()
    item = ThoughtActionCalibrationItem(
        item_id="t01-resubmit", source="test", budget=130, start_observation="(start)",
        steps=r.steps, consistent=[True, False], justifications=["fine", "claims a removal"])
    write_calibration("thought_action", "v0.0.1", [item], created=date(2026, 1, 1),
                      root=tmp_path)
    dataset = load_thought_action_calibration("v0.0.1", root=tmp_path)
    caught = calibrate_thought_action_judge(
        dataset, StepJudge([ok(1), bad(2, "I will remove the most expensive activity")]))
    assert (caught.tp, caught.tn, caught.fp, caught.fn) == (1, 1, 0, 0) and caught.kappa == 1.0
    missed = calibrate_thought_action_judge(dataset, StepJudge([ok(1), ok(2)]))
    assert missed.fn == 1 and missed.recall == 0.0
    assert missed.disagreements[0].startswith("t01-resubmit step 2 (missed): human: claims")


def test_thought_action_item_needs_one_label_per_judged_step():
    with pytest.raises(ValueError, match="one label"):
        ThoughtActionCalibrationItem(item_id="t01-x", source="t", budget=1, start_observation="",
                                     steps=resubmission_run().steps, consistent=[True],
                                     justifications=["a"])
