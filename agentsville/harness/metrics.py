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
    )
