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
    )
