# Phase 9 – Step 2: B2 constraint graders (label-based and run-based), no LLM calls.
# Phase 9 – Step 3: failure taxonomy.
# Phase 9 – Step 4: weather judge vs labels, B2 metrics, report, compare, update_expected.
# Phase 9 – Step 6: [b2] thresholds.
# Phase 9 – Step 7: ConstraintSignal (b2.v1).

import copy
from datetime import date

import pytest

from agentsville.agent import AgentRun, AgentStep
from agentsville.data_api import get_activity_by_id
from agentsville.evals import EvalReport, EvalResult
from agentsville.graders import B2_GRADERS
from agentsville.graders.completion import classify_failure
from agentsville.graders.constraints import (
    budget_respected,
    infeasible_handling,
    weather_judge_agreement,
    weather_label_compliance,
)
from agentsville.graders.signals import constraint_signal
from agentsville.harness.dataset import DatasetManifest, GoldenCase, GoldenLabels
from agentsville.harness.grading import GraderOutcome, GradingContext, grade_run
from agentsville.harness.metrics import summarize
from agentsville.harness.report import compare, render_report
from agentsville.harness.runner import read_results, update_expected
from agentsville.harness.schema import CaseResult, ExperimentConfig
from agentsville.harness.thresholds import check_thresholds, thresholds_passed
from agentsville.models import TravelPlan
from agentsville.samples import sample_vacation_info
from tests.harness_fakes import GOLDEN_PLAN

# sample_plan.json: day index 2 (06-12) is a thunderstorm day with one activity, event-2025-06-12-3
STORM_DAY = 2


def run_with(plan: dict | None, stop_reason: str = "final_answer", budget: int | None = None):
    info = sample_vacation_info()
    if budget is not None:
        info = info.model_copy(update={"budget": budget})
    return AgentRun(model="m", prompt_version="v1", vacation_info=info, system_prompt="",
                    user_prompt="", steps=[], stop_reason=stop_reason,
                    travel_plan=TravelPlan.model_validate(plan) if plan else None)


def case(**labels) -> GoldenCase:
    return GoldenCase(case_id="g99-test", tags=["test"], description="test",
                      vacation_info=sample_vacation_info(),
                      labels=GoldenLabels(expected_behavior="test", **labels))


def storm_day_activity(activity_id: str) -> dict:
    """GOLDEN_PLAN with the storm-day activity swapped for a real one from the data."""
    plan = copy.deepcopy(GOLDEN_PLAN)
    source = get_activity_by_id(activity_id).model_dump(mode="json")
    plan["itinerary_days"][STORM_DAY]["activity_recommendations"][0]["activity"] = source
    return plan


def empty_plan() -> dict:
    plan = copy.deepcopy(GOLDEN_PLAN)
    for day in plan["itinerary_days"]:
        day["activity_recommendations"] = []
    plan["total_cost"] = 0
    return plan


# --- weather_label_compliance ---------------------------------------------------------------------


def test_weather_labels_flag_must_avoid_activity():
    ctx = GradingContext(case=case(must_avoid_activity_ids=["event-2025-06-12-2"]))
    o = weather_label_compliance(run_with(storm_day_activity("event-2025-06-12-2")), ctx)
    assert not o.passed and (o.units, o.failed_units) == (1, 1)
    assert o.counts == {"must_avoid": 1} and "event-2025-06-12-2" in o.details[0]


def test_weather_labels_skip_ambiguous_activity():
    ctx = GradingContext(case=case(ambiguous_activity_ids=["event-2025-06-12-0"]))
    o = weather_label_compliance(run_with(storm_day_activity("event-2025-06-12-0")), ctx)
    assert o.passed and o.units == 0


def test_weather_labels_count_only_inclement_days():
    # 06-10 and 06-11 are fair: their 5 activities are not units; the storm-day pick is fine
    ctx = GradingContext(case=case(must_avoid_activity_ids=["event-2025-06-10-0"]))
    o = weather_label_compliance(run_with(GOLDEN_PLAN), ctx)
    assert o.passed and o.units == 1


def test_weather_labels_not_applicable_without_case():
    o = weather_label_compliance(run_with(GOLDEN_PLAN), GradingContext())
    assert o.passed and o.units == 0 and o.details == ["not applicable: no golden case"]


# Phase 9 – Step 8: a plan with only fair-weather days has nothing to check against the labels
def test_weather_labels_fair_weather_plan_has_no_units():
    plan = copy.deepcopy(GOLDEN_PLAN)
    plan["itinerary_days"][STORM_DAY]["activity_recommendations"] = []
    ctx = GradingContext(case=case(must_avoid_activity_ids=["event-2025-06-10-0"]))
    o = weather_label_compliance(run_with(plan), ctx)
    assert o.passed and o.units == 0 and o.details == []


# --- infeasible_handling --------------------------------------------------------------------------

INFEASIBLE = GradingContext(case=case(max_affordable_activities=0))


def test_infeasible_empty_plan_with_final_answer_passes():
    o = infeasible_handling(run_with(empty_plan()), INFEASIBLE)
    assert o.passed and (o.units, o.failed_units) == (1, 0)


def test_infeasible_plan_with_activities_fails():
    o = infeasible_handling(run_with(GOLDEN_PLAN), INFEASIBLE)
    assert not o.passed and (o.units, o.failed_units) == (1, 1)
    assert o.counts == {"activities_planned": 1, "nonzero_total": 1}


def test_infeasible_max_steps_without_plan_is_counted_as_a_unit():
    # needs_plan=False: grade_run lets this grader judge the plan-less run itself
    run = run_with(None, stop_reason="max_steps")
    o = grade_run(run, B2_GRADERS, case=INFEASIBLE.case)["infeasible_handling"]
    assert not o.passed and (o.units, o.failed_units) == (1, 1)
    assert o.counts == {"no_final_answer": 1}


def test_infeasible_not_applicable_to_feasible_case_even_without_plan():
    run = run_with(None, stop_reason="max_steps")
    outcomes = grade_run(run, B2_GRADERS, case=case(max_affordable_activities=2))
    assert outcomes["infeasible_handling"].passed and outcomes["infeasible_handling"].units == 0
    # the B0 rule still holds for graders that need a plan
    assert not outcomes["budget_respected"].passed
    assert not outcomes["weather_label_compliance"].passed


# --- budget_respected -----------------------------------------------------------------------------


def test_budget_respected_within_budget():
    o = budget_respected(run_with(GOLDEN_PLAN))  # 108 of 130
    assert o.passed and o.units == 1


def test_budget_uses_actual_sum_even_if_total_understates():
    plan = copy.deepcopy(GOLDEN_PLAN)
    plan["total_cost"] = 50  # the plan lies; the real sum is 108
    o = budget_respected(run_with(plan, budget=100))
    assert not o.passed and o.counts == {"over_budget": 1}
    assert "cost 108 (plan reports 50), budget is 100 (over by 8)" in o.details[0]


# --- failure taxonomy (Phase 9 – Step 3) ----------------------------------------------------------


def step(observation: str, tool: str = "calculator_tool") -> AgentStep:
    return AgentStep(step=1, raw_reply="{}", tool_name=tool, observation=observation)


def report(*failing: str) -> EvalReport:
    names = ["city_and_dates", "total_cost_accurate", "within_budget", "weather_suitability"]
    return EvalReport(results=[EvalResult(name=n, passed=n not in failing) for n in names])


def taxonomy_run(stop_reason="max_steps", steps=(), final_report=None, rejections=0, error=None):
    run = run_with(GOLDEN_PLAN if stop_reason == "final_answer" else None, stop_reason=stop_reason)
    return run.model_copy(update={"steps": list(steps), "final_eval_report": final_report,
                                  "final_rejections": rejections, "error": error})


EVALS_FAILED = "EVALS FAILED (3/4 ok)\n✓ city_and_dates\n✗ total_cost_accurate\n    - off by 5"
BAD_ARGS = "ERROR: invalid arguments for run_evals_tool: travel_plan: field required"


@pytest.mark.parametrize(
    "run, expected",
    [
        (taxonomy_run("final_answer", final_report=report()), None),
        (taxonomy_run("llm_error", error="Request timed out."), "llm_error:timeout"),
        (taxonomy_run("llm_error", error="502 bad gateway"), "llm_error:other"),
        (taxonomy_run("final_answer", final_report=report("total_cost_accurate", "within_budget"),
                      rejections=2), "guardrail_exhausted:total_cost_accurate"),
        (taxonomy_run("final_answer", final_report=report("weather_suitability")),
         "final_failed:weather_suitability"),
        (taxonomy_run(steps=[step(BAD_ARGS)] * 3), "invalid_args_loop:run_evals_tool"),
        (taxonomy_run(steps=[step(EVALS_FAILED)] * 2), "eval_loop:total_cost_accurate"),
        (taxonomy_run(steps=[step(BAD_ARGS)] * 2 + [step("{}")]), "max_steps:other"),
        (taxonomy_run(steps=[step(EVALS_FAILED)]), "max_steps:other"),
    ],
    ids=["completed", "timeout", "llm-other", "guardrail-exhausted", "final-failed",
         "invalid-args-loop", "eval-loop", "two-bad-args-is-not-a-loop", "one-eval-fail"],
)
def test_classify_failure(run, expected):
    assert classify_failure(run) == expected


def test_invalid_args_loop_wins_over_eval_loop():
    # rule order: an argument loop is the more specific diagnosis
    run = taxonomy_run(steps=[step(EVALS_FAILED)] * 4 + [step(BAD_ARGS)] * 3)
    assert classify_failure(run) == "invalid_args_loop:run_evals_tool"


def test_eval_loop_names_the_most_frequent_failing_eval():
    budget = "EVALS FAILED (3/4 ok)\n✗ within_budget"
    run = taxonomy_run(steps=[step(EVALS_FAILED), step(budget), step(budget)])
    assert classify_failure(run) == "eval_loop:within_budget"


def test_case_result_records_failure_mode_and_rejections():
    from agentsville.harness.runner import result_from_run

    run = taxonomy_run("final_answer", final_report=report("total_cost_accurate"), rejections=2)
    result = result_from_run("g99-test", 1, run)
    assert result.failure_mode == "guardrail_exhausted:total_cost_accurate"
    assert result.final_rejections == 2


# --- weather_judge_agreement (Phase 9 – Step 4) ---------------------------------------------------


def judged_run(plan: dict, flagged: list[str]):
    """A run whose final report holds weather-judge details for the flagged activity ids."""
    details = [f"{a} on 2025-06-12 (thunderstorm): outdoors" for a in flagged]
    final = EvalReport(results=[EvalResult(name="weather_suitability", passed=not flagged,
                                           kind="llm", details=details)])
    return run_with(plan).model_copy(update={"final_eval_report": final})


LABELED = GradingContext(case=case(must_avoid_activity_ids=["event-2025-06-12-2"],
                                   ambiguous_activity_ids=["event-2025-06-12-0"]))


def test_judge_agrees_with_label():
    run = judged_run(storm_day_activity("event-2025-06-12-2"), ["event-2025-06-12-2"])
    o = weather_judge_agreement(run, LABELED)
    assert o.passed and (o.units, o.failed_units) == (1, 0)


def test_judge_missed_a_must_avoid_activity():
    o = weather_judge_agreement(judged_run(storm_day_activity("event-2025-06-12-2"), []), LABELED)
    assert not o.passed and o.counts == {"missed": 1}


def test_judge_false_alarm_on_suitable_activity():
    o = weather_judge_agreement(judged_run(GOLDEN_PLAN, ["event-2025-06-12-3"]), LABELED)
    assert not o.passed and o.counts == {"false_alarm": 1}


def test_judge_agreement_not_applicable_when_judge_off():
    no_judge = EvalReport(results=[EvalResult(name="city_and_dates", passed=True)])
    run = run_with(GOLDEN_PLAN).model_copy(update={"final_eval_report": no_judge})
    o = weather_judge_agreement(run, LABELED)
    assert o.passed and o.details == ["not applicable: weather judge did not run"]


# --- B2 metrics, report, compare (Phase 9 – Step 4) -----------------------------------------------


def outcome_of(name, units=1, failed=0, **counts):
    return GraderOutcome(name=name, kind="deterministic", passed=failed == 0, units=units,
                         failed_units=failed, counts=counts)


def result(case_id, repeat=1, stop="final_answer", evals=None, outcomes=(), mode=None,
           rejections=0, steps=8, plan=True):
    evals = {"city_and_dates": True, "total_cost_accurate": True,
             "no_overlapping_activities": True, "weather_suitability": True} | (evals or {})
    return CaseResult(
        case_id=case_id, repeat=repeat, stop_reason=stop,
        eval_results=evals if plan else None,
        eval_passed=plan and stop == "final_answer" and all(evals.values()),
        grader_outcomes={o.name: o for o in outcomes}, failure_mode=mode,
        final_rejections=rejections, steps=steps,
    )


def b2_results():
    ok = [outcome_of("budget_respected"), outcome_of("weather_label_compliance", units=2),
          outcome_of("weather_judge_agreement", units=2)]
    return [
        result("g01", outcomes=ok, steps=6),
        result("g01", 2, outcomes=ok, steps=10, rejections=1),
        # final answer accepted after 2 rejections, still a wrong total and over budget
        result("g02", evals={"total_cost_accurate": False}, rejections=2, steps=14,
               mode="guardrail_exhausted:total_cost_accurate",
               outcomes=[outcome_of("budget_respected", failed=1, over_budget=1),
                         outcome_of("weather_label_compliance", units=1, failed=1, must_avoid=1),
                         outcome_of("weather_judge_agreement", units=1, failed=1, missed=1)]),
        # no plan: only infeasible_handling has a unit
        result("g07", stop="max_steps", steps=20, plan=False,
               mode="invalid_args_loop:final_answer_tool",
               outcomes=[outcome_of("infeasible_handling", failed=1, no_final_answer=1)]),
    ]


def summary_of(results):
    manifest = DatasetManifest(version="v9.9.9", created=date(2026, 1, 1), case_count=3,
                               cases_sha256="x" * 64, data_fingerprint="y")
    return summarize(ExperimentConfig(dataset_version="v9.9.9", model="m"), manifest, results)


def test_b2_metrics():
    b2 = summary_of(b2_results()).b2
    assert (b2.violations["cost_accuracy"].successes, b2.violations["cost_accuracy"].n) == (1, 3)
    assert b2.violations["city_dates"].successes == 0
    assert (b2.violations["budget"].successes, b2.violations["budget"].n) == (1, 3)
    assert (b2.weather_label_violations.successes, b2.weather_label_violations.n) == (1, 5)
    assert (b2.all_hard_pass.successes, b2.all_hard_pass.n) == (2, 3)
    assert b2.failure_modes == {"guardrail_exhausted:total_cost_accurate": 1,
                                "invalid_args_loop:final_answer_tool": 1}
    assert (b2.guardrail_rejection.successes, b2.guardrail_rejection.n) == (2, 3)
    assert b2.steps_to_completion.p50 == 8  # completed runs: 6 and 10 steps
    assert (b2.infeasible_handled.successes, b2.infeasible_handled.n) == (0, 1)
    assert (b2.weather_judge_agreement.successes, b2.weather_judge_agreement.n) == (4, 5)
    assert b2.judge_missed == 1 and b2.judge_false_alarms == 0


def test_b2_absent_for_results_graded_before_b2():
    assert summary_of([result("g01")]).b2 is None


def test_b2_weather_judge_violation_absent_when_judge_off():
    results = [r.model_copy(update={"eval_results": {k: v for k, v in r.eval_results.items()
                                                     if k != "weather_suitability"}})
               for r in b2_results()[:3]]
    assert "weather_judge" not in summary_of(results).b2.violations


def test_report_has_b2_section_with_failure_examples():
    results = b2_results()
    text = render_report(summary_of(results), results)
    assert "## B2 – Constraints & completion" in text
    assert "| `guardrail_exhausted:total_cost_accurate` | 1 | g02 r1 (14 steps) |" in text
    assert "missed 1, false alarms 0" in text


def test_compare_has_b2_rows():
    results = b2_results()
    text = compare(summary_of(results), summary_of(results[:2]))
    assert "b2.cost_accuracy_violation (lower is better)" in text
    assert "b2.infeasible_handled" in text  # measured only in A: shown as "only in one"


# --- update_expected (Phase 9 – Step 4) -----------------------------------------------------------


def test_update_expected_rewrites_in_full_replay(tmp_path):
    cfg = ExperimentConfig(dataset_version="v9.9.9", model="m", mode="replay")
    path = update_expected(cfg, [result("g02"), result("g01")], cassette_root=tmp_path)
    assert [r.case_id for r in read_results(path)] == ["g01", "g02"]  # sorted, diff-friendly


@pytest.mark.parametrize(
    "overrides",
    [{"mode": "record"}, {"mode": "live"}, {"mode": "replay", "grade_mode": "record"},
     {"mode": "replay", "case_ids": ["g01"]}],
)
def test_update_expected_refuses_anything_but_a_full_replay(tmp_path, overrides):
    cfg = ExperimentConfig(dataset_version="v9.9.9", model="m", **overrides)
    with pytest.raises(ValueError):
        update_expected(cfg, [result("g01")], cassette_root=tmp_path)
    assert not any(tmp_path.iterdir())


# --- [b2] thresholds (Phase 9 – Step 6) -----------------------------------------------------------


def test_b2_thresholds(tmp_path):
    rules = tmp_path / "t.toml"
    rules.write_text(
        "[b2]\nmax_city_dates_violation_rate = 0.05\nmax_cost_accuracy_violation_rate = 0.10\n"
        "max_budget_violation_rate = 0.5\nmax_weather_label_violation_rate = 0.05\n"
        "min_goal_completion_rate = 0.5\nmin_weather_judge_agreement = 0.9\n"
        "max_overlap_violation_rate = 0.05\n",
        encoding="utf-8",
    )
    results = {r.rule: r for r in check_thresholds(summary_of(b2_results()), None, rules)}
    assert results["max_city_dates_violation_rate"].passed is True  # 0/3
    assert results["max_cost_accuracy_violation_rate"].value == pytest.approx(1 / 3)
    assert results["max_cost_accuracy_violation_rate"].passed is False
    assert results["max_budget_violation_rate"].passed is True  # 1/3 ≤ 0.5
    assert results["max_weather_label_violation_rate"].value == pytest.approx(1 / 5)
    assert results["min_goal_completion_rate"].value == pytest.approx(2 / 4)
    assert results["min_goal_completion_rate"].passed is True  # 0.5 ≥ 0.5
    assert results["min_weather_judge_agreement"].value == pytest.approx(4 / 5)
    assert results["min_weather_judge_agreement"].passed is False
    assert all(r.note != "unknown rule" for r in results.values())


def test_b2_thresholds_not_measured_before_b2(tmp_path):
    rules = tmp_path / "t.toml"
    rules.write_text("[b2]\nmax_budget_violation_rate = 0.05\nmin_weather_judge_agreement = 0.9\n",
                     encoding="utf-8")
    results = check_thresholds(summary_of([result("g01")]), None, rules)
    assert all(r.passed is None for r in results) and thresholds_passed(results)


def test_committed_thresholds_know_every_rule():
    # a typo in evals/thresholds.toml would silently become "unknown rule"
    assert all(r.note != "unknown rule"
               for r in check_thresholds(summary_of(b2_results()), None))


# --- production signal b2.v1 (Phase 9 – Step 7) ---------------------------------------------------


def test_constraint_signal_completed_run():
    run = taxonomy_run("final_answer", final_report=report())
    signal = constraint_signal(run)
    assert signal.schema_version == "b2.v1" and signal.goal_completed and signal.plan_produced
    assert signal.failure_mode is None and signal.stop_reason == "final_answer"
    assert signal.constraints == {"city_and_dates": True, "total_cost_accurate": True,
                                  "within_budget": True, "weather_suitability": True}
    assert (signal.budget, signal.total_cost) == (130, 108)


def test_constraint_signal_failed_final_answer():
    run = taxonomy_run("final_answer", final_report=report("total_cost_accurate"), rejections=2)
    signal = constraint_signal(run)
    assert not signal.goal_completed and signal.final_rejections == 2
    assert signal.failure_mode == "guardrail_exhausted:total_cost_accurate"
    assert signal.constraints["total_cost_accurate"] is False


def test_constraint_signal_without_plan():
    run = taxonomy_run(steps=[step(BAD_ARGS)] * 3)
    signal = constraint_signal(run)
    assert not signal.plan_produced and not signal.goal_completed
    assert signal.constraints == {} and signal.total_cost is None
    assert signal.failure_mode == "invalid_args_loop:run_evals_tool" and signal.steps == 3


def test_constraint_signal_ignores_warning_evals():
    final = EvalReport(results=[EvalResult(name="city_and_dates", passed=True),
                                EvalResult(name="interest_coverage", passed=False,
                                           severity="warning")])
    signal = constraint_signal(taxonomy_run("final_answer", final_report=final))
    assert signal.constraints == {"city_and_dates": True} and signal.goal_completed


def test_constraint_signal_completion_matches_harness_definition():
    # goal_completed must equal the harness rule: final answer AND eval_passed
    from agentsville.harness.runner import result_from_run

    for run in (taxonomy_run("final_answer", final_report=report()),
                taxonomy_run("final_answer", final_report=report("within_budget")),
                taxonomy_run("llm_error", error="timeout")):
        result = result_from_run("g99-test", 1, run)
        expected = result.stop_reason == "final_answer" and result.eval_passed
        assert constraint_signal(run).goal_completed == expected
