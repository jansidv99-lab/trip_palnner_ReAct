# Phase 8 – Step 7: turn experiment numbers into pass/fail against evals/thresholds.toml.
"""Rules are named `max_<metric>` (value must be ≤ limit) or `min_<metric>` (value must be ≥
limit). A metric that wasn't measured (e.g. judge skipped) is reported as not measured, never as a
crash or a silent pass. B1 reports results; B4 (Phase 11) makes failures block merges.
"""

import tomllib
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agentsville.harness.calibration import (
    CalibrationReport,
    load_committed_relevancy_calibration,
    load_committed_thought_action_calibration,
)
from agentsville.harness.metrics import ExperimentSummary
from agentsville.harness.schema import ROOT

THRESHOLDS_FILE = ROOT / "evals" / "thresholds.toml"

Getter = Callable[[ExperimentSummary, CalibrationReport | None], float | None]


def _b1(attr: str) -> Getter:
    def get(summary: ExperimentSummary, calibration: CalibrationReport | None) -> float | None:
        stat = getattr(summary.b1, attr, None) if summary.b1 else None
        return stat.rate if stat is not None and stat.n else None
    return get


# Phase 9 – Step 6: B2 getters – a violation rate by constraint key, or a ConstraintMetrics field
def _b2_violation(key: str) -> Getter:
    def get(summary: ExperimentSummary, calibration: CalibrationReport | None) -> float | None:
        stat = summary.b2.violations.get(key) if summary.b2 else None
        return stat.rate if stat is not None and stat.n else None
    return get


def _b2(attr: str) -> Getter:
    def get(summary: ExperimentSummary, calibration: CalibrationReport | None) -> float | None:
        stat = getattr(summary.b2, attr, None) if summary.b2 else None
        return stat.rate if stat is not None and stat.n else None
    return get


def _goal_completion(summary: ExperimentSummary, calibration: CalibrationReport | None):
    stat = summary.goal_completion
    return stat.rate if stat.n else None


# Phase 10 – Step 8: B3 getters – a RateStat field of summary.b3_relevancy / b3_reasoning
def _b3(group: str, attr: str) -> Getter:
    def get(summary: ExperimentSummary, calibration: CalibrationReport | None) -> float | None:
        metrics = getattr(summary, group, None)
        stat = getattr(metrics, attr, None) if metrics else None
        return stat.rate if stat is not None and stat.n else None
    return get


def _calibration(attr: str) -> Getter:
    return lambda summary, calibration: getattr(calibration, attr) if calibration else None


# Phase 8 – Step 7: metric name (as used in the TOML) → where to read it
METRICS: dict[str, Getter] = {
    "activity_hallucination_rate": _b1("activity_hallucination"),
    "plan_hallucination_rate": _b1("plan_hallucination"),
    "trajectory_ungrounded_rate": _b1("trajectory_ungrounded"),
    "reason_reference_error_rate": _b1("reason_reference_errors"),
    "ungrounded_reason_rate": _b1("ungrounded_reasons"),
    "judge_recall": _calibration("recall"),
    "judge_precision": _calibration("precision"),
    # Phase 9 – Step 6: B2 constraints & completion
    "city_dates_violation_rate": _b2_violation("city_dates"),
    "budget_violation_rate": _b2_violation("budget"),
    "overlap_violation_rate": _b2_violation("overlap"),
    "cost_accuracy_violation_rate": _b2_violation("cost_accuracy"),
    "weather_label_violation_rate": _b2("weather_label_violations"),
    "weather_judge_agreement": _b2("weather_judge_agreement"),
    "goal_completion_rate": _goal_completion,
    # Phase 10 – Step 8: B3 relevancy & reasoning
    "interest_coverage": _b3("b3_relevancy", "interest_coverage"),
    "relevant_rate": _b3("b3_relevancy", "relevant_rate"),
    "weather_lookup_coverage": _b3("b3_reasoning", "weather_lookup_coverage"),
    "verified_before_final_rate": _b3("b3_reasoning", "verified_before_final"),
    "calculator_faithfulness": _b3("b3_reasoning", "calculator_faithfulness"),
    "faithfulness": _b3("b3_reasoning", "faithfulness"),
    "thought_action_inconsistency": _b3("b3_reasoning", "thought_action_inconsistency"),
    "redundant_call_rate": _b3("b3_reasoning", "redundant_call_rate"),
    "error_step_rate": _b3("b3_reasoning", "error_step_rate"),
}

# Phase 10 – Step 8: trust bars of the B3 judges – metric → (judge, field of its calibration report)
JUDGE_METRICS: dict[str, tuple[str, str]] = {
    "relevancy_judge_qwk": ("traveler_relevancy", "qwk"),
    "thought_action_judge_recall": ("thought_action", "recall"),
    "thought_action_judge_precision": ("thought_action", "precision"),
}


# Phase 10 – Step 8: the committed calibration reports of the B3 judges (missing → not measured)
def committed_judge_reports() -> dict[str, BaseModel | None]:
    return {"traveler_relevancy": load_committed_relevancy_calibration(),
            "thought_action": load_committed_thought_action_calibration()}


# Phase 8 – Step 7: one rule's verdict
class ThresholdResult(BaseModel):
    section: str
    rule: str
    limit: float
    value: float | None
    passed: bool | None  # None = not measured
    note: str = ""


# Phase 8 – Step 7: evaluate every rule in the thresholds file
def check_thresholds(
    summary: ExperimentSummary,
    calibration: CalibrationReport | None = None,
    path: Path = THRESHOLDS_FILE,
    judge_reports: dict[str, BaseModel | None] | None = None,  # Phase 10: B3 judge trust bars
) -> list[ThresholdResult]:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    results = []
    for section, rules in config.items():
        for rule, limit in rules.items():
            direction, _, metric = rule.partition("_")
            getter = METRICS.get(metric)
            if metric in JUDGE_METRICS:  # Phase 10 – Step 8
                judge, attr = JUDGE_METRICS[metric]
                report = (judge_reports or {}).get(judge)
                getter = lambda s, c, r=report, a=attr: getattr(r, a) if r else None  # noqa: E731
            if direction not in ("max", "min") or getter is None:
                results.append(ThresholdResult(section=section, rule=rule, limit=limit, value=None,
                                               passed=None, note="unknown rule"))
                continue
            value = getter(summary, calibration)
            passed = None if value is None else (
                value <= limit if direction == "max" else value >= limit
            )
            results.append(ThresholdResult(section=section, rule=rule, limit=limit, value=value,
                                           passed=passed,
                                           note="not measured" if value is None else ""))
    return results


def thresholds_passed(results: list[ThresholdResult]) -> bool:
    return all(r.passed is not False for r in results)
