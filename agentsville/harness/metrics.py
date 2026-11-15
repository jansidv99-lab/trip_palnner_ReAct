# Phase 7 – Step 5: turn per-run results into comparable numbers with uncertainty.

import math
from collections import Counter

from pydantic import BaseModel

from agentsville.harness.dataset import DatasetManifest
from agentsville.harness.schema import CaseResult, ExperimentConfig


# Phase 7 – Step 5: Wilson score interval – a 95% CI for a pass rate that behaves well for small n
def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


# Phase 7 – Step 5: linear-interpolated percentile (q in 0–100)
def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


# Phase 7 – Step 5: a rate with its confidence interval
class RateStat(BaseModel):
    successes: int
    n: int
    rate: float
    ci_low: float
    ci_high: float

    @classmethod
    def of(cls, successes: int, n: int) -> "RateStat":
        low, high = wilson_interval(successes, n)
        return cls(successes=successes, n=n, rate=successes / n if n else 0.0,
                   ci_low=low, ci_high=high)


# Phase 7 – Step 5: distribution summary for cost / steps / latency
class DistStat(BaseModel):
    mean: float
    p50: float
    p95: float
    total: float

    @classmethod
    def of(cls, values: list[float]) -> "DistStat":
        return cls(
            mean=sum(values) / len(values) if values else 0.0,
            p50=percentile(values, 50),
            p95=percentile(values, 95),
            total=sum(values),
        )


# Phase 8 – Step 6: a run-level grader across an experiment – runs passed and unit failure rate
class UnitStat(BaseModel):
    runs_passed: RateStat  # runs where the grader passed ÷ all runs (no plan = fail)
    unit_failure: RateStat  # failed units ÷ examined units (micro, pooled over runs)
    counts: dict[str, int] = {}  # summed failure breakdown


# Phase 8 – Step 6: the B1 headline numbers ("is everything in the plan real?")
class GroundingMetrics(BaseModel):
    activity_hallucination: RateStat  # fabricated/altered/wrong-day activities ÷ planned activities
    plan_hallucination: RateStat  # plans with any activity or weather hallucination ÷ plans
    trajectory_ungrounded: RateStat  # used-but-never-retrieved activities/days ÷ units
    reason_reference_errors: RateStat  # reasons naming unknown travelers / wrong interests
    ungrounded_reasons: RateStat | None = None  # LLM judge; None when the judge didn't run


# Phase 9 – Step 4: in-loop hard evals (Phase 4) that B2 aggregates, plus its own run-level graders
IN_LOOP_CONSTRAINTS = {
    "city_dates": "city_and_dates",
    "cost_accuracy": "total_cost_accurate",
    "overlap": "no_overlapping_activities",
    "weather_judge": "weather_suitability",
}


# Phase 9 – Step 4: the B2 numbers ("does the plan satisfy the hard constraints?")
class ConstraintMetrics(BaseModel):
    # violation rates (lower is better) over PRODUCED plans – conditional on answering
    violations: dict[str, RateStat]  # city_dates, cost_accuracy, overlap, budget, weather_judge
    weather_label_violations: RateStat  # must-avoid picks ÷ labeled inclement-day picks (units)
    all_hard_pass: RateStat  # plans passing every error eval ÷ plans (higher is better)
    # completion picture over ALL runs – unconditional
    failure_modes: dict[str, int]  # "<category>:<detail>" → runs, for non-completed runs
    guardrail_rejection: RateStat  # final-answer runs with ≥ 1 rejection ÷ final-answer runs
    steps_to_completion: DistStat  # completed runs only
    infeasible_handled: RateStat | None = None  # passed ÷ infeasible-case runs (None: no such case)
    weather_judge_agreement: RateStat | None = None  # judge = label ÷ labeled units judged
    judge_missed: int = 0  # label must-avoid, judge said suitable
    judge_false_alarms: int = 0  # judge flagged, label says suitable


# Phase 10 – Step 6: B3 relevancy numbers ("is the plan relevant to THESE travelers?")
class RelevancyMetrics(BaseModel):
    interest_coverage: RateStat | None = None  # coverable travelers matched ÷ coverable travelers
    interest_mismatch: RateStat | None = None  # activities matching nobody ÷ activities (lower)
    relevant_rate: RateStat | None = None  # travelers scored ≥ 4 ÷ judged travelers (judge)
    low_relevancy: RateStat | None = None  # travelers scored ≤ 2 ÷ judged travelers (lower)
    mean_relevancy_score: float | None = None  # mean 1–5 judge score
    score_counts: dict[str, int] = {}  # score_1 … score_5


# Phase 10 – Step 6: B3 reasoning numbers ("is the step-by-step reasoning faithful?")
class ReasoningMetrics(BaseModel):
    weather_lookup_coverage: RateStat | None = None  # trip days looked up ÷ trip days
    activity_lookup_coverage: RateStat | None = None
    calculator_faithfulness: RateStat | None = None  # plans whose total came from the calculator
    verified_before_final: RateStat | None = None  # accepted plans that passed run_evals_tool
    faithfulness: RateStat | None = None  # accepted plans with activities passing BOTH checks
    thought_action_inconsistency: RateStat | None = None  # judged steps (lower; judge – a
    # lower bound: calibration recall 0.83)
    redundant_call_rate: RateStat | None = None  # repeated identical lookups ÷ lookups (lower)
    error_step_rate: RateStat | None = None  # error steps ÷ all steps (lower)
    failure_counts: dict[str, dict[str, int]] = {}  # grader → failure kind → count


# Phase 7 – Step 5: everything an experiment report and a comparison need
class ExperimentSummary(BaseModel):
    config: ExperimentConfig
    dataset_version: str
    dataset_sha256: str
    case_count: int
    run_count: int
    goal_completion: RateStat  # final answer AND all error graders passed
    plan_rate: RateStat  # runs that produced a plan
    graders: dict[str, RateStat]  # per grader; a run without a plan counts as a failure
    per_case: dict[str, RateStat]  # goal completion per case across repeats
    stop_reasons: dict[str, int]
    cost_usd: DistStat
    steps: DistStat
    latency_s: DistStat
    run_graders: dict[str, UnitStat] = {}  # Phase 8
    b1: GroundingMetrics | None = None  # Phase 8
    b2: ConstraintMetrics | None = None  # Phase 9
    b3_relevancy: RelevancyMetrics | None = None  # Phase 10
    b3_reasoning: ReasoningMetrics | None = None  # Phase 10


# Phase 8 – Step 6: pool one run-level grader over all results
def _unit_stat(results: list[CaseResult], name: str) -> UnitStat:
    outcomes = [r.grader_outcomes.get(name) for r in results]
    counts: Counter = Counter()
    for o in outcomes:
        if o:
            counts.update(o.counts)
    return UnitStat(
        runs_passed=RateStat.of(sum(bool(o and o.passed) for o in outcomes), len(results)),
        unit_failure=RateStat.of(sum(o.failed_units for o in outcomes if o),
                                 sum(o.units for o in outcomes if o)),
        counts=dict(counts),
    )


# Phase 8 – Step 6: B1 metrics; plan-level rate counts only runs that produced a plan
def _grounding(results: list[CaseResult], stats: dict[str, UnitStat]) -> GroundingMetrics | None:
    if "activity_grounding" not in stats:
        return None
    planned = [r for r in results if r.eval_results is not None and r.grader_outcomes]
    hallucinated = sum(
        any(not o.passed for name, o in r.grader_outcomes.items()
            if name in ("activity_grounding", "weather_grounding"))
        for r in planned
    )
    judge = stats.get("reasons_grounded")
    return GroundingMetrics(
        activity_hallucination=stats["activity_grounding"].unit_failure,
        plan_hallucination=RateStat.of(hallucinated, len(planned)),
        trajectory_ungrounded=stats["trajectory_grounding"].unit_failure,
        reason_reference_errors=stats["reason_references"].unit_failure,
        ungrounded_reasons=judge.unit_failure if judge else None,
    )


# Phase 9 – Step 4: passed units ÷ units (the flip of unit_failure); None when nothing was examined
def _passed_units(stat: UnitStat | None) -> RateStat | None:
    if stat is None or stat.unit_failure.n == 0:
        return None
    return RateStat.of(stat.unit_failure.n - stat.unit_failure.successes, stat.unit_failure.n)


# Phase 9 – Step 4: B2 metrics; None for results graded before B2 (no budget_respected outcome)
def _constraints(results: list[CaseResult], stats: dict[str, UnitStat]) -> ConstraintMetrics | None:
    if "budget_respected" not in stats:
        return None
    plans = [r for r in results if r.eval_results is not None]
    violations = {}
    for key, eval_name in IN_LOOP_CONSTRAINTS.items():
        judged = [r for r in plans if eval_name in r.eval_results]
        if judged:  # weather_judge is absent when the judge was off
            violations[key] = RateStat.of(sum(not r.eval_results[eval_name] for r in judged),
                                          len(judged))
    over = [r for r in plans if "budget_respected" in r.grader_outcomes]
    violations["budget"] = RateStat.of(
        sum(not r.grader_outcomes["budget_respected"].passed for r in over), len(over))

    finals = [r for r in results if r.stop_reason == "final_answer"]
    completed = [r for r in results if r.stop_reason == "final_answer" and r.eval_passed]
    agreement = stats.get("weather_judge_agreement")
    return ConstraintMetrics(
        violations=dict(sorted(violations.items())),
        weather_label_violations=stats["weather_label_compliance"].unit_failure,
        all_hard_pass=RateStat.of(sum(r.eval_passed for r in plans), len(plans)),
        failure_modes=dict(Counter(r.failure_mode for r in results if r.failure_mode)
                           .most_common()),
        guardrail_rejection=RateStat.of(sum(r.final_rejections > 0 for r in finals), len(finals)),
        steps_to_completion=DistStat.of([float(r.steps) for r in completed]),
        infeasible_handled=_passed_units(stats.get("infeasible_handling")),
        weather_judge_agreement=_passed_units(agreement),
        judge_missed=agreement.counts.get("missed", 0) if agreement else 0,
        judge_false_alarms=agreement.counts.get("false_alarm", 0) if agreement else 0,
    )


# Phase 10 – Step 6: B3 relevancy from the run-level grader outcomes
def _relevancy(stats: dict[str, UnitStat]) -> RelevancyMetrics | None:
    if "interest_match" not in stats:
        return None
    judge = stats.get("traveler_relevancy")
    metrics = RelevancyMetrics(
        interest_coverage=_passed_units(stats.get("interest_coverage_labeled")),
        interest_mismatch=stats["interest_match"].unit_failure,
    )
    if judge and judge.unit_failure.n:
        counts = {k: v for k, v in sorted(judge.counts.items()) if k.startswith("score_")}
        judged = sum(counts.values())
        good = counts.get("score_4", 0) + counts.get("score_5", 0)
        metrics.relevant_rate = RateStat.of(good, judged)
        metrics.low_relevancy = judge.unit_failure
        metrics.mean_relevancy_score = (
            sum(int(k[-1]) * v for k, v in counts.items()) / judged if judged else None)
        metrics.score_counts = counts
    return metrics


B3_REASONING_GRADERS = ("weather_lookup_coverage", "activity_lookup_coverage", "calculator_total",
                        "verified_before_final", "tool_efficiency", "thought_action_consistency")


# Phase 10 – Step 6: B3 reasoning; plan-dependent checks count only runs that produced a plan
def _reasoning(results: list[CaseResult], stats: dict[str, UnitStat]) -> ReasoningMetrics | None:
    if "calculator_total" not in stats:
        return None
    both = [r for r in results
            if r.grader_outcomes.get("calculator_total")
            and r.grader_outcomes["calculator_total"].units
            and r.grader_outcomes.get("verified_before_final")
            and r.grader_outcomes["verified_before_final"].units]
    faithful = sum(r.grader_outcomes["calculator_total"].passed
                   and r.grader_outcomes["verified_before_final"].passed for r in both)
    errors = sum(r.grader_outcomes["tool_efficiency"].counts.get("error_steps", 0)
                 for r in results if "tool_efficiency" in r.grader_outcomes)
    judge = stats.get("thought_action_consistency")
    efficiency = stats.get("tool_efficiency")
    return ReasoningMetrics(
        weather_lookup_coverage=_passed_units(stats.get("weather_lookup_coverage")),
        activity_lookup_coverage=_passed_units(stats.get("activity_lookup_coverage")),
        calculator_faithfulness=_passed_units(stats.get("calculator_total")),
        verified_before_final=_passed_units(stats.get("verified_before_final")),
        faithfulness=RateStat.of(faithful, len(both)) if both else None,
        thought_action_inconsistency=judge.unit_failure if judge and judge.unit_failure.n
        else None,
        redundant_call_rate=efficiency.unit_failure if efficiency else None,
        error_step_rate=RateStat.of(errors, sum(r.steps for r in results)) if results else None,
        failure_counts={name: {k: v for k, v in stats[name].counts.items() if k != "error_steps"}
                        for name in B3_REASONING_GRADERS if name in stats},
    )


# Phase 7 – Step 5: aggregate the results of one experiment
def summarize(
    config: ExperimentConfig, manifest: DatasetManifest, results: list[CaseResult]
) -> ExperimentSummary:
    n = len(results)
    grader_names = sorted({g for r in results if r.eval_results for g in r.eval_results})
    graders = {
        g: RateStat.of(sum(bool(r.eval_results and r.eval_results.get(g)) for r in results), n)
        for g in grader_names
    }
    completed = [r.stop_reason == "final_answer" and r.eval_passed for r in results]
    per_case = {
        case_id: RateStat.of(
            sum(c for r, c in zip(results, completed, strict=True) if r.case_id == case_id),
            sum(r.case_id == case_id for r in results),
        )
        for case_id in sorted({r.case_id for r in results})
    }
    run_graders = {
        name: _unit_stat(results, name)
        for name in sorted({g for r in results for g in r.grader_outcomes})
    }
    return ExperimentSummary(
        config=config,
        dataset_version=manifest.version,
        dataset_sha256=manifest.cases_sha256,
        case_count=len(per_case),
        run_count=n,
        goal_completion=RateStat.of(sum(completed), n),
        plan_rate=RateStat.of(sum(r.eval_results is not None for r in results), n),
        graders=graders,
        per_case=per_case,
        stop_reasons=dict(Counter(str(r.stop_reason) for r in results)),
        cost_usd=DistStat.of([r.cost_usd for r in results]),
        steps=DistStat.of([float(r.steps) for r in results]),
        latency_s=DistStat.of([r.latency_ms / 1000 for r in results]),
        run_graders=run_graders,
        b1=_grounding(results, run_graders),
        b2=_constraints(results, run_graders),
        b3_relevancy=_relevancy(run_graders),
        b3_reasoning=_reasoning(results, run_graders),
    )
