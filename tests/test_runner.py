# Phase 7 – Step 9: experiment runner, metrics and report – record once, replay identically.

import pytest

from agentsville.harness.dataset import load_golden
from agentsville.harness.metrics import ExperimentSummary, percentile, summarize, wilson_interval
from agentsville.harness.recording import CassetteMissError
from agentsville.harness.report import ComparisonError, compare, render_report
from agentsville.harness.runner import (
    EXPECTED_RESULTS_FILE,
    compare_with_expected,
    read_results,
    run_experiment,
)
from agentsville.harness.schema import CaseResult, ExperimentConfig
from tests.harness_fakes import HAPPY_SCRIPT, ConversationFake, make_dataset


@pytest.fixture
def roots(tmp_path):
    make_dataset(tmp_path / "datasets")
    return {"dataset_root": tmp_path / "datasets", "cassette_root": tmp_path / "cassettes"}


def config(**overrides) -> ExperimentConfig:
    values = {"dataset_version": "v0.0.1", "model": "fake-model", "workers": 2,
              "include_llm_evals": True, "max_steps": 4}
    return ExperimentConfig(**(values | overrides))


# --- record → replay ---------------------------------------------------------------------------


def test_record_then_replay_gives_identical_results(roots, tmp_path):
    fake = ConversationFake(HAPPY_SCRIPT)
    recorded_summary, recorded = run_experiment(config(mode="record"), base_llm=fake, **roots)
    calls_after_record = fake.calls

    replay_summary, replayed = run_experiment(config(mode="replay"), base_llm=None, **roots)
    assert fake.calls == calls_after_record  # replay never touched the LLM
    assert compare_with_expected(replayed, recorded) == []
    # identical numbers; only config.mode differs (record vs replay)
    assert replay_summary.model_dump(exclude={"config"}) == recorded_summary.model_dump(
        exclude={"config"}
    )

    expected = read_results(config().cassette_dir(roots["cassette_root"]) / EXPECTED_RESULTS_FILE)
    assert compare_with_expected(replayed, expected) == []


def test_results_reflect_graders(roots):
    _, results = run_experiment(config(mode="record"), base_llm=ConversationFake(HAPPY_SCRIPT),
                                **roots)
    by_case = {r.case_id: r for r in results}
    good, wrong_dates = by_case["g01-sample"], by_case["g02-rainy"]
    assert good.stop_reason == "final_answer" and good.eval_passed and good.failures == []
    assert good.judge_calls == 1 and good.total_cost == 108
    # same plan submitted for a different request: guardrail rejects twice, then accepts it
    assert wrong_dates.stop_reason == "final_answer" and not wrong_dates.eval_passed
    assert any(f.startswith("city_and_dates") for f in wrong_dates.failures)


def test_run_without_plan_is_conservatively_failed(roots):
    _, results = run_experiment(config(mode="record", max_steps=2),
                                base_llm=ConversationFake(["garbage"]), **roots)
    for r in results:
        assert r.stop_reason == "max_steps" and r.eval_results is None and not r.eval_passed
        assert r.failure_mode == "max_steps:other"  # Phase 9: unparseable replies, no loop rule


# Phase 9 – Step 8: the runner passes the case to graders and fills the B2 fields end to end
def test_runner_produces_b2_outcomes_and_failure_modes(roots):
    summary, results = run_experiment(config(mode="record"),
                                      base_llm=ConversationFake(HAPPY_SCRIPT), **roots)
    by_case = {r.case_id: r for r in results}
    good, wrong_dates = by_case["g01-sample"], by_case["g02-rainy"]
    b2_graders = {"weather_label_compliance", "infeasible_handling", "budget_respected",
                  "weather_judge_agreement"}
    assert b2_graders <= set(good.grader_outcomes)
    # the case reached the label graders: g01 has one labeled storm-day pick (06-12)
    assert good.grader_outcomes["weather_label_compliance"].units == 1
    assert good.grader_outcomes["infeasible_handling"].details == [
        "not applicable: feasible case"]
    assert good.failure_mode is None and good.final_rejections == 0
    # same plan for other dates: rejected twice by the guardrail, then accepted still failing
    assert wrong_dates.failure_mode == "guardrail_exhausted:city_and_dates"
    assert wrong_dates.final_rejections == 2
    b2 = summary.b2
    assert b2 is not None and b2.failure_modes == {"guardrail_exhausted:city_and_dates": 1}
    assert (b2.violations["city_dates"].successes, b2.violations["city_dates"].n) == (1, 2)
    assert (b2.guardrail_rejection.successes, b2.guardrail_rejection.n) == (1, 2)


def test_repeats_use_separate_cassettes(roots):
    run_experiment(config(mode="record", repeats=2), base_llm=ConversationFake(HAPPY_SCRIPT),
                   **roots)
    case_dir = config().cassette_dir(roots["cassette_root"]) / "g01-sample"
    assert sorted(p.name for p in case_dir.iterdir()) == [
        "r1.grading.jsonl", "r1.jsonl", "r2.grading.jsonl", "r2.jsonl"
    ]  # Phase 8: agent and grading cassettes are separate files


def test_case_subset_and_unknown_ids(roots):
    _, results = run_experiment(config(mode="record", case_ids=["g02-rainy"]),
                                base_llm=ConversationFake(HAPPY_SCRIPT), **roots)
    assert [r.case_id for r in results] == ["g02-rainy"]
    with pytest.raises(ValueError, match="unknown case ids: g99"):
        run_experiment(config(mode="record", case_ids=["g99"]),
                       base_llm=ConversationFake(HAPPY_SCRIPT), **roots)


def test_replay_after_prompt_change_fails_loudly(roots):
    run_experiment(config(mode="record"), base_llm=ConversationFake(HAPPY_SCRIPT), **roots)
    # a different max_steps doesn't change requests; a different model does
    with pytest.raises(CassetteMissError):
        run_experiment(config(mode="replay", model="other-model"), **roots)


def test_recorded_judge_failure_replays(roots):
    fake = ConversationFake(HAPPY_SCRIPT, fail_judge=True)
    _, recorded = run_experiment(config(mode="record", case_ids=["g01-sample"]), base_llm=fake,
                                 **roots)
    _, replayed = run_experiment(config(mode="replay", case_ids=["g01-sample"]), **roots)
    assert compare_with_expected(replayed, recorded) == []
    assert any("judge call failed" in f for f in replayed[0].failures)


def test_artifacts_written(roots, tmp_path):
    out = tmp_path / "exp"
    run_experiment(config(mode="record"), base_llm=ConversationFake(HAPPY_SCRIPT), out_dir=out,
                   **roots)
    names = {p.name for p in out.iterdir()}
    assert names == {"config.json", "summary.json", "results.jsonl", "runs.jsonl", "report.md"}
    assert ExperimentSummary.model_validate_json((out / "summary.json").read_text("utf-8"))


def test_compare_with_expected_reports_differences():
    a = CaseResult(case_id="g01", repeat=1, stop_reason="final_answer", eval_passed=True)
    b = a.model_copy(update={"eval_passed": False})
    c = a.model_copy(update={"case_id": "g02"})
    assert compare_with_expected([a], [b]) == ["g01 r1: differs in eval_passed"]
    assert "g02 r1: not in expected results" in compare_with_expected([a, c], [a])


# --- metrics ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "successes, n, low, high",
    [(0, 10, 0.0, 0.2775), (5, 10, 0.2366, 0.7634), (10, 10, 0.7225, 1.0),
     (11, 12, 0.6461, 0.9851)],
)
def test_wilson_interval_known_values(successes, n, low, high):
    lo, hi = wilson_interval(successes, n)
    assert (round(lo, 4), round(hi, 4)) == (low, high)


def test_wilson_empty_and_percentiles():
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([7], 95) == 7 and percentile([], 50) == 0.0


def test_summarize_counts(roots):
    manifest = load_golden("v0.0.1", roots["dataset_root"]).manifest
    results = [
        CaseResult(case_id="g01", repeat=1, stop_reason="final_answer", eval_passed=True,
                   eval_results={"x": True}, steps=4, cost_usd=0.01, latency_ms=1000),
        CaseResult(case_id="g01", repeat=2, stop_reason="final_answer", eval_passed=False,
                   eval_results={"x": False}, steps=6, cost_usd=0.03, latency_ms=3000),
        CaseResult(case_id="g02", repeat=1, stop_reason="max_steps", steps=20, cost_usd=0.02),
    ]
    s = summarize(config(), manifest, results)
    assert (s.goal_completion.successes, s.goal_completion.n) == (1, 3)
    assert s.plan_rate.successes == 2
    assert s.graders["x"].successes == 1 and s.graders["x"].n == 3  # no-plan run counts as fail
    assert s.per_case["g01"].rate == 0.5 and s.per_case["g02"].rate == 0.0
    assert s.stop_reasons == {"final_answer": 2, "max_steps": 1}
    assert s.cost_usd.total == pytest.approx(0.06) and s.steps.p50 == 6


# --- report and comparison ------------------------------------------------------------


def test_report_and_compare(roots):
    summary, results = run_experiment(config(mode="record"),
                                      base_llm=ConversationFake(HAPPY_SCRIPT), **roots)
    report = render_report(summary, results)
    assert "Goal completion" in report and summary.dataset_sha256[:12] in report
    assert "g02-rainy r1" in report  # listed under failing runs

    text = compare(summary, summary)
    assert "not clearly different" in text
    other = summary.model_copy(update={"dataset_sha256": "different"})
    with pytest.raises(ComparisonError, match="not comparable"):
        compare(summary, other)
    assert "Comparison" in compare(summary, other, force=True)


# Phase 7 – Step 6: progress callback fires once per run with a running count
def test_on_result_reports_every_run(roots):
    seen = []
    _, results = run_experiment(
        config(mode="record", repeats=2), base_llm=ConversationFake(HAPPY_SCRIPT),
        on_result=lambda result, done, total: seen.append((result.case_id, done, total)), **roots
    )
    assert [done for _, done, _ in seen] == [1, 2, 3, 4]
    assert {total for _, _, total in seen} == {4}
    assert sorted(case for case, _, _ in seen) == sorted(r.case_id for r in results)
    assert [(r.case_id, r.repeat) for r in results] == [
        ("g01-sample", 1), ("g01-sample", 2), ("g02-rainy", 1), ("g02-rainy", 2)
    ]  # results stay in task order even though callbacks arrive in completion order


# Phase 8 – Step 11: re-grading replays the agent and re-records ONLY the grading cassettes
def test_regrade_leaves_agent_cassettes_untouched(roots):
    fake = ConversationFake(HAPPY_SCRIPT)
    run_experiment(config(mode="record"), base_llm=fake, **roots)
    case_dir = config().cassette_dir(roots["cassette_root"]) / "g01-sample"
    agent_bytes = (case_dir / "r1.jsonl").read_bytes()

    summary, results = run_experiment(config(mode="replay", grade_mode="record"), base_llm=fake,
                                      **roots)
    assert (case_dir / "r1.jsonl").read_bytes() == agent_bytes
    assert (case_dir / "r1.grading.jsonl").stat().st_size > 0
    good = next(r for r in results if r.case_id == "g01-sample")
    assert good.grader_outcomes["activity_grounding"].passed
    assert good.grader_outcomes["reasons_grounded"].units == 11
    assert summary.b1 is not None and summary.b1.activity_hallucination.successes == 0


def test_no_judge_skips_llm_graders(roots):
    _, results = run_experiment(config(mode="record", include_llm_evals=False),
                                base_llm=ConversationFake(HAPPY_SCRIPT), **roots)
    assert "reasons_grounded" not in results[0].grader_outcomes
    assert "activity_grounding" in results[0].grader_outcomes
