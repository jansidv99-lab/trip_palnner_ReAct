# Phase 8 – Step 5: measure an LLM judge against human labels before trusting it.
"""Positive class = UNGROUNDED (the thing the judge must catch).

    precision = of the reasons the judge flagged, how many were really ungrounded
    recall    = of the really ungrounded reasons, how many the judge caught
    kappa     = Cohen's kappa: agreement beyond what chance would give (1 perfect, 0 chance)
"""

from pathlib import Path

from pydantic import BaseModel

from agentsville.data_api import get_activity_by_id, get_weather
from agentsville.graders.grounding import (
    REASONS_JUDGE_MODEL,
    REASONS_JUDGE_PROMPT_VERSION,
    judge_reasons,
)
from agentsville.graders.relevancy import (
    RELEVANCY_JUDGE_MODEL,
    RELEVANCY_JUDGE_PROMPT_VERSION,
    judge_relevancy,
)
from agentsville.graders.trajectory import (
    THOUGHT_ACTION_JUDGE_MODEL,
    THOUGHT_ACTION_JUDGE_PROMPT_VERSION,
    judge_thought_action,
)
from agentsville.harness.dataset import (
    CalibrationDataset,
    RelevancyCalibrationDataset,
    ThoughtActionCalibrationDataset,
)
from agentsville.harness.schema import CASSETTES_DIR


# Phase 8 – Step 5: judge vs human on a calibration set
class CalibrationReport(BaseModel):
    dataset: str
    dataset_sha256: str
    judge_model: str
    judge_prompt_version: str
    n: int
    tp: int  # judge: ungrounded, human: ungrounded
    fp: int  # judge: ungrounded, human: grounded
    tn: int
    fn: int  # judge: grounded, human: ungrounded  (missed hallucination)
    precision: float
    recall: float
    f1: float
    accuracy: float
    kappa: float
    disagreements: list[str] = []


# Phase 8 – Step 5: confusion counts with "ungrounded" as the positive class
def confusion(human_ungrounded: list[bool], judge_ungrounded: list[bool]) -> dict[str, int]:
    pairs = list(zip(human_ungrounded, judge_ungrounded, strict=True))
    return {
        "tp": sum(h and j for h, j in pairs),
        "fp": sum(j and not h for h, j in pairs),
        "tn": sum(not h and not j for h, j in pairs),
        "fn": sum(h and not j for h, j in pairs),
    }


# Phase 8 – Step 5: precision/recall/F1/accuracy/kappa from confusion counts
def scores(tp: int, fp: int, tn: int, fn: int) -> dict[str, float]:
    n = tp + fp + tn + fn
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / n if n else 0.0
    expected = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / (n * n) if n else 0.0
    kappa = (accuracy - expected) / (1 - expected) if expected < 1 else 1.0
    return {"precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy,
            "kappa": kappa}


# Phase 8 – Step 5: run the reasons judge on every calibration item and compare with the labels
def calibrate_reasons_judge(dataset: CalibrationDataset, llm) -> CalibrationReport:
    human, judged, disagreements = [], [], []
    for item in dataset.items:
        activity = get_activity_by_id(item.activity_id)
        forecast = get_weather(activity.start_time.date())
        verdicts = judge_reasons(llm, activity, forecast, item.travelers, item.reasons)
        for reason, label, verdict in zip(item.reasons, item.grounded, verdicts, strict=True):
            human.append(not label)
            judged.append(not verdict.grounded)
            if label != verdict.grounded:
                kind = "missed" if label is False else "false alarm"
                disagreements.append(f"{item.item_id} ({kind}): {reason!r} – judge: "
                                     f"{verdict.unsupported_claim or 'grounded'}")
    counts = confusion(human, judged)
    return CalibrationReport(
        dataset=f"{dataset.manifest.name} {dataset.manifest.version}",
        dataset_sha256=dataset.manifest.cases_sha256,
        judge_model=REASONS_JUDGE_MODEL,
        judge_prompt_version=REASONS_JUDGE_PROMPT_VERSION,
        n=len(human),
        **counts,
        **scores(**counts),
        disagreements=disagreements,
    )


# Phase 8 – Step 5: where the calibration cassette and the committed report.json live
def calibration_dir(version: str = "v1.0.0", root: Path = CASSETTES_DIR) -> Path:
    return (root / "calibration" / f"reasons-{version}"
            / f"{REASONS_JUDGE_MODEL}__{REASONS_JUDGE_PROMPT_VERSION}")


# Phase 8 – Step 7: the committed calibration report (used by threshold checks), if any
def load_committed_calibration(version: str = "v1.0.0") -> CalibrationReport | None:
    path = calibration_dir(version) / "report.json"
    if not path.is_file():
        return None
    return CalibrationReport.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Phase 10 – Step 4: ordinal (1–5) agreement for the traveler-relevancy judge
# For scores, "judge 4 vs human 5" is a smaller miss than "1 vs 5", so instead of precision/recall:
#   exact    = share of identical scores
#   within_1 = share of scores at most 1 apart
#   mae      = mean absolute difference
#   qwk      = quadratic weighted kappa: agreement beyond chance, where a disagreement costs the
#              SQUARE of its distance (1 perfect, 0 chance, negative worse than chance)
# ---------------------------------------------------------------------------


# Phase 10 – Step 4: quadratic weighted kappa for integer ratings in [low, high]
def quadratic_weighted_kappa(human: list[int], judge: list[int], low: int = 1,
                             high: int = 5) -> float:
    k, n = high - low + 1, len(human)
    if n == 0:
        return 0.0
    observed = [[0] * k for _ in range(k)]
    for h, j in zip(human, judge, strict=True):
        observed[h - low][j - low] += 1
    hist_h = [sum(row) for row in observed]
    hist_j = [sum(observed[i][c] for i in range(k)) for c in range(k)]
    num = den = 0.0
    for i in range(k):
        for c in range(k):
            weight = (i - c) ** 2 / (k - 1) ** 2
            num += weight * observed[i][c]
            den += weight * hist_h[i] * hist_j[c] / n
    if den == 0:  # every rating identical on both sides: perfect only if they agree
        return 1.0 if num == 0 else 0.0
    return 1 - num / den


# Phase 10 – Step 4: exact / within-1 / MAE / QWK from paired scores
def ordinal_agreement(human: list[int], judge: list[int]) -> dict[str, float]:
    n = len(human)
    diffs = [abs(h - j) for h, j in zip(human, judge, strict=True)]
    return {
        "exact": sum(d == 0 for d in diffs) / n if n else 0.0,
        "within_1": sum(d <= 1 for d in diffs) / n if n else 0.0,
        "mae": sum(diffs) / n if n else 0.0,
        "qwk": quadratic_weighted_kappa(human, judge),
    }


# Phase 10 – Step 4: relevancy judge vs human scores
class RelevancyCalibrationReport(BaseModel):
    dataset: str
    dataset_sha256: str
    judge_model: str
    judge_prompt_version: str
    n: int  # traveler scores compared
    exact: float
    within_1: float
    mae: float
    qwk: float
    disagreements: list[str] = []  # every pair more than 1 apart, plus every off-by-one


# Phase 10 – Step 4: run the relevancy judge on every calibration plan and compare per traveler
def calibrate_relevancy_judge(
    dataset: RelevancyCalibrationDataset, llm,
) -> RelevancyCalibrationReport:
    human, judged, disagreements = [], [], []
    for item in dataset.items:
        info = item.vacation_info
        scores = judge_relevancy(llm, info, item.travel_plan)
        for traveler, label, s in zip(info.travelers, item.scores, scores, strict=True):
            human.append(label)
            judged.append(s.score)
            if label != s.score:
                disagreements.append(f"{item.item_id} {traveler.name}: human {label}, judge "
                                     f"{s.score} – {s.reason}")
    return RelevancyCalibrationReport(
        dataset=f"{dataset.manifest.name} {dataset.manifest.version}",
        dataset_sha256=dataset.manifest.cases_sha256,
        judge_model=RELEVANCY_JUDGE_MODEL,
        judge_prompt_version=RELEVANCY_JUDGE_PROMPT_VERSION,
        n=len(human),
        **ordinal_agreement(human, judged),
        disagreements=disagreements,
    )


# Phase 10 – Step 4: cassette + committed report location for the relevancy judge
def relevancy_calibration_dir(version: str = "v1.0.0", root: Path = CASSETTES_DIR) -> Path:
    return (root / "calibration" / f"relevancy-{version}"
            / f"{RELEVANCY_JUDGE_MODEL}__{RELEVANCY_JUDGE_PROMPT_VERSION}")


# Phase 10 – Step 4: the committed relevancy calibration report (for threshold checks), if any
def load_committed_relevancy_calibration(
    version: str = "v1.0.0",
) -> RelevancyCalibrationReport | None:
    path = relevancy_calibration_dir(version) / "report.json"
    if not path.is_file():
        return None
    return RelevancyCalibrationReport.model_validate_json(path.read_text(encoding="utf-8"))


# Phase 10 – Step 5: thought↔action judge vs human labels; positive class = INCONSISTENT
def calibrate_thought_action_judge(
    dataset: ThoughtActionCalibrationDataset, llm,
) -> CalibrationReport:
    human, judged, disagreements = [], [], []
    for item in dataset.items:
        judgments = judge_thought_action(llm, item.steps, item.budget, item.start_observation)
        for label, j, why in zip(item.consistent, judgments, item.justifications, strict=True):
            human.append(not label)
            judged.append(not j.consistent)
            if label != j.consistent:
                kind = "missed" if not label else "false alarm"
                disagreements.append(f"{item.item_id} step {j.step} ({kind}): human: {why} | "
                                     f"judge: {j.reason or 'consistent'}")
    counts = confusion(human, judged)
    return CalibrationReport(
        dataset=f"{dataset.manifest.name} {dataset.manifest.version}",
        dataset_sha256=dataset.manifest.cases_sha256,
        judge_model=THOUGHT_ACTION_JUDGE_MODEL,
        judge_prompt_version=THOUGHT_ACTION_JUDGE_PROMPT_VERSION,
        n=len(human),
        **counts,
        **scores(**counts),
        disagreements=disagreements,
    )


# Phase 10 – Step 5: cassette + committed report location for the thought↔action judge
def thought_action_calibration_dir(version: str = "v1.0.0", root: Path = CASSETTES_DIR) -> Path:
    return (root / "calibration" / f"thought_action-{version}"
            / f"{THOUGHT_ACTION_JUDGE_MODEL}__{THOUGHT_ACTION_JUDGE_PROMPT_VERSION}")


# Phase 10 – Step 5: the committed thought↔action calibration report, if any
def load_committed_thought_action_calibration(
    version: str = "v1.0.0",
) -> CalibrationReport | None:
    path = thought_action_calibration_dir(version) / "report.json"
    if not path.is_file():
        return None
    return CalibrationReport.model_validate_json(path.read_text(encoding="utf-8"))
