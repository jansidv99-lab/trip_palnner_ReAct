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
from agentsville.harness.dataset import CalibrationDataset
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
