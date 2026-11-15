# Phase 8 – Step 7: turn experiment numbers into pass/fail against evals/thresholds.toml.
"""Rules are named `max_<metric>` (value must be ≤ limit) or `min_<metric>` (value must be ≥
limit). A metric that wasn't measured (e.g. judge skipped) is reported as not measured, never as a
crash or a silent pass. B1 reports results; B4 (Phase 11) makes failures block merges.
"""

import tomllib
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agentsville.harness.calibration import CalibrationReport
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
}


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
) -> list[ThresholdResult]:
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    results = []
    for section, rules in config.items():
        for rule, limit in rules.items():
            direction, _, metric = rule.partition("_")
            getter = METRICS.get(metric)
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
