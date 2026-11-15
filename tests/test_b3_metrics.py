# Phase 10 – Step 6: B3 metrics (relevancy + reasoning), report section and compare rows.
# Phase 10 – Step 8: [b3] thresholds and the B3 judge trust bars.
# Phase 10 – Step 9: RelevancySignal (b3.v1).

import pytest

from agentsville.graders.signals import relevancy_signal
from agentsville.harness.report import compare, render_report
from agentsville.harness.thresholds import check_thresholds, thresholds_passed
from tests.test_constraints import outcome_of, result, summary_of


def b3_results():
    """Three runs: a faithful one, an unfaithful one, and one without a plan."""
    faithful = [
        outcome_of("interest_coverage_labeled", units=2),
        outcome_of("interest_match", units=4),
        outcome_of("traveler_relevancy", units=2, score_5=1, score_4=1),
        outcome_of("weather_lookup_coverage", units=3),
        outcome_of("activity_lookup_coverage", units=3),
        outcome_of("calculator_total"),
        outcome_of("verified_before_final"),
        outcome_of("tool_efficiency", units=6, error_steps=1),
        outcome_of("thought_action_consistency", units=8),
    ]
    unfaithful = [
        outcome_of("interest_coverage_labeled", units=2, failed=1, uncovered=1),
        outcome_of("interest_match", units=2, failed=1, no_matching_interest=1),
        outcome_of("traveler_relevancy", units=2, failed=1, score_1=1, score_3=1),
        outcome_of("weather_lookup_coverage", units=3, failed=1, missing_day=1),
        outcome_of("activity_lookup_coverage", units=3),
        outcome_of("calculator_total", failed=1, no_calculator=1),
        outcome_of("verified_before_final"),
        outcome_of("tool_efficiency", units=4, failed=1, redundant=1, error_steps=2),
        outcome_of("thought_action_consistency", units=10, failed=2, action_mismatch=2),
    ]
    no_plan = [  # B0 rule: plan-dependent graders fail with 0 units; the rest still count
        outcome_of(name, units=0, failed=0) for name in
        ("interest_coverage_labeled", "interest_match", "weather_lookup_coverage",
         "activity_lookup_coverage", "calculator_total", "verified_before_final")
    ] + [outcome_of("tool_efficiency", units=5, failed=2, redundant=2, error_steps=4),
         outcome_of("thought_action_consistency", units=12, failed=6, action_mismatch=6)]
    return [result("g01", outcomes=faithful, steps=10),
            result("g02", outcomes=unfaithful, steps=12),
            result("g03", stop="max_steps", plan=False, outcomes=no_plan, steps=20)]


def test_b3_relevancy_metrics():
    rel = summary_of(b3_results()).b3_relevancy
    assert (rel.interest_coverage.successes, rel.interest_coverage.n) == (3, 4)
    assert (rel.interest_mismatch.successes, rel.interest_mismatch.n) == (1, 6)
    assert (rel.relevant_rate.successes, rel.relevant_rate.n) == (2, 4)  # scores 5, 4 of 5,4,3,1
    assert (rel.low_relevancy.successes, rel.low_relevancy.n) == (1, 4)
    assert rel.mean_relevancy_score == pytest.approx((5 + 4 + 3 + 1) / 4)
    assert rel.score_counts == {"score_1": 1, "score_3": 1, "score_4": 1, "score_5": 1}


def test_b3_reasoning_metrics():
    rea = summary_of(b3_results()).b3_reasoning
    assert (rea.weather_lookup_coverage.successes, rea.weather_lookup_coverage.n) == (5, 6)
    assert (rea.calculator_faithfulness.successes, rea.calculator_faithfulness.n) == (1, 2)
    assert (rea.verified_before_final.successes, rea.verified_before_final.n) == (2, 2)
    assert (rea.faithfulness.successes, rea.faithfulness.n) == (1, 2)  # no-plan run excluded
    # judge and efficiency count every run, including the one without a plan
    assert (rea.thought_action_inconsistency.successes,
            rea.thought_action_inconsistency.n) == (8, 30)
    assert (rea.redundant_call_rate.successes, rea.redundant_call_rate.n) == (3, 15)
    assert (rea.error_step_rate.successes, rea.error_step_rate.n) == (7, 42)
    assert rea.failure_counts["calculator_total"] == {"no_calculator": 1}
    assert "error_steps" not in rea.failure_counts["tool_efficiency"]


def test_b3_judge_metrics_not_measured_without_judges():
    results = [r.model_copy(update={"grader_outcomes": {
        k: v for k, v in r.grader_outcomes.items()
        if k not in ("traveler_relevancy", "thought_action_consistency")}})
        for r in b3_results()]
    summary = summary_of(results)
    assert summary.b3_relevancy.relevant_rate is None
    assert summary.b3_relevancy.mean_relevancy_score is None
    assert summary.b3_reasoning.thought_action_inconsistency is None
    assert summary.b3_reasoning.faithfulness is not None  # code graders still measured


def test_b3_absent_for_results_graded_before_b3():
    summary = summary_of([result("g01")])
    assert summary.b3_relevancy is None and summary.b3_reasoning is None


def test_report_has_b3_section():
    results = b3_results()
    text = render_report(summary_of(results), results)
    assert "## B3 – Relevancy & reasoning" in text
    assert "| **Faithful** (both of the above) |  50.0%" in text
    assert "| Mean relevancy score (1–5) | 3.25 (1: 1, 3: 1, 4: 1, 5: 1) |" in text
    assert "calculator_total: no_calculator 1" in text


def test_report_marks_unmeasured_judge_rows():
    results = [r.model_copy(update={"grader_outcomes": {
        k: v for k, v in r.grader_outcomes.items() if k != "traveler_relevancy"}})
        for r in b3_results()]
    text = render_report(summary_of(results), results)
    assert "| **Relevant travelers** (judge score ≥ 4) | not measured |" in text


def test_compare_has_b3_rows():
    results = b3_results()
    text = compare(summary_of(results), summary_of(results[:1]))
    assert "| b3.faithfulness |" in text
    assert "b3.thought_action_inconsistency (lower is better)" in text


# --- [b3] thresholds (Phase 10 – Step 8) ----------------------------------------------------------


class Report:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def test_b3_thresholds(tmp_path):
    rules = tmp_path / "t.toml"
    rules.write_text(
        "[b3]\nmin_faithfulness = 0.45\nmin_calculator_faithfulness = 0.6\n"
        "max_thought_action_inconsistency = 0.2\nmin_relevant_rate = 0.5\n"
        "max_redundant_call_rate = 0.15\nmin_relevancy_judge_qwk = 0.8\n"
        "min_thought_action_judge_recall = 0.8\nmin_thought_action_judge_precision = 0.85\n",
        encoding="utf-8")
    reports = {"traveler_relevancy": Report(qwk=1.0),
               "thought_action": Report(recall=0.83, precision=0.80)}
    results = {r.rule: r for r in check_thresholds(summary_of(b3_results()), None, rules,
                                                   judge_reports=reports)}
    assert results["min_faithfulness"].value == pytest.approx(0.5)
    assert results["min_faithfulness"].passed is True
    assert results["min_calculator_faithfulness"].passed is False  # 0.5 < 0.6
    assert results["max_thought_action_inconsistency"].value == pytest.approx(8 / 30)
    assert results["max_thought_action_inconsistency"].passed is False
    assert results["min_relevant_rate"].passed is True  # 0.5 ≥ 0.5
    assert results["max_redundant_call_rate"].passed is False  # 3/15 = 0.2
    assert results["min_relevancy_judge_qwk"].passed is True
    assert results["min_thought_action_judge_recall"].passed is True
    assert results["min_thought_action_judge_precision"].passed is False


def test_b3_judge_bars_not_measured_without_reports(tmp_path):
    rules = tmp_path / "t.toml"
    rules.write_text("[b3]\nmin_relevancy_judge_qwk = 0.8\nmin_faithfulness = 0.45\n",
                     encoding="utf-8")
    results = {r.rule: r for r in check_thresholds(summary_of([result("g01")]), None, rules)}
    assert results["min_relevancy_judge_qwk"].passed is None
    assert results["min_faithfulness"].passed is None and thresholds_passed(list(results.values()))


def test_committed_judge_reports_meet_their_bars():
    from agentsville.harness.thresholds import committed_judge_reports

    b3 = [r for r in check_thresholds(summary_of(b3_results()), None,
                                      judge_reports=committed_judge_reports())
          if r.section == "b3" and "judge" in r.rule]
    assert len(b3) == 3 and all(r.passed for r in b3)


# --- production signal b3.v1 (Phase 10 – Step 9) --------------------------------------------------


def test_relevancy_signal_faithful_run():
    outcomes = b3_results()[0].grader_outcomes
    s = relevancy_signal(outcomes, judges_sampled=True)
    assert s.schema_version == "b3.v1" and s.plan_produced
    assert (s.planned_activities, s.activities_matching_nobody, s.trip_days) == (4, 0, 3)
    assert s.total_from_calculator and s.verified_before_final and s.faithful
    assert (s.lookup_calls, s.redundant_lookups, s.error_steps) == (6, 0, 1)
    assert (s.travelers_judged, s.relevant_travelers, s.poorly_served_travelers) == (2, 2, 0)
    assert s.mean_relevancy_score == 4.5 and (s.judged_steps, s.inconsistent_steps) == (8, 0)


def test_relevancy_signal_unfaithful_run():
    s = relevancy_signal(b3_results()[1].grader_outcomes, judges_sampled=True)
    assert s.total_from_calculator is False and s.verified_before_final and s.faithful is False
    assert s.days_without_weather_lookup == 1 and s.activities_matching_nobody == 1
    assert (s.relevant_travelers, s.poorly_served_travelers) == (0, 1)
    assert s.inconsistent_steps == 2


def test_relevancy_signal_unsampled_judges_are_none():
    s = relevancy_signal(b3_results()[0].grader_outcomes, judges_sampled=False)
    assert not s.judges_sampled and s.travelers_judged is None
    assert s.mean_relevancy_score is None and s.inconsistent_steps is None
    assert s.faithful is True  # code graders still reported


def test_relevancy_signal_without_plan():
    outcomes = dict(b3_results()[2].grader_outcomes)
    outcomes["interest_match"] = outcomes["interest_match"].model_copy(
        update={"details": ["no plan produced"]})
    s = relevancy_signal(outcomes, judges_sampled=True)
    assert not s.plan_produced and s.faithful is None and s.total_from_calculator is None
    assert s.travelers_judged is None  # the relevancy judge examined nothing
    assert (s.judged_steps, s.inconsistent_steps) == (12, 6)  # the trajectory still judged
    assert (s.redundant_lookups, s.error_steps) == (2, 4)
