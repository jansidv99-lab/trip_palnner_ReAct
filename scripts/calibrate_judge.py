# Phase 8 – Step 5: measure the reasons-grounded judge against the human-labeled calibration set.
# Phase 10 – Step 4: also the traveler-relevancy judge (--judge); ordinal agreement metrics.
# Phase 10 – Step 5: also the thought↔action judge (positive class = inconsistent).
"""Run from the repo root:

    python scripts/calibrate_judge.py                   # replay every judge's cassette (free)
    python scripts/calibrate_judge.py --check-expected  # + verify each equals its committed report
    python scripts/calibrate_judge.py --judge traveler_relevancy --mode record   # call one judge
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.config import ConfigError, get_settings  # noqa: E402
from agentsville.graders.grounding import REASONS_JUDGE_MODEL  # noqa: E402
from agentsville.graders.relevancy import RELEVANCY_JUDGE_MODEL  # noqa: E402
from agentsville.graders.trajectory import THOUGHT_ACTION_JUDGE_MODEL  # noqa: E402
from agentsville.harness.calibration import (  # noqa: E402
    CalibrationReport,
    RelevancyCalibrationReport,
    calibrate_reasons_judge,
    calibrate_relevancy_judge,
    calibrate_thought_action_judge,
    calibration_dir,
    relevancy_calibration_dir,
    thought_action_calibration_dir,
)
from agentsville.harness.dataset import (  # noqa: E402
    CALIBRATION_DIR,
    load_calibration,
    load_relevancy_calibration,
    load_thought_action_calibration,
)
from agentsville.harness.recording import CassetteLLM, CassetteMissError  # noqa: E402
from agentsville.llm import LLMClient  # noqa: E402


def print_reasons(report: CalibrationReport) -> None:
    print(f"confusion (positive = the failure to catch): TP {report.tp}  FP {report.fp}  "
          f"TN {report.tn}  FN {report.fn}")
    print(f"precision {report.precision:.2f}  recall {report.recall:.2f}  F1 {report.f1:.2f}  "
          f"accuracy {report.accuracy:.2f}  kappa {report.kappa:.2f}")


def print_relevancy(report: RelevancyCalibrationReport) -> None:
    print(f"exact {report.exact:.2f}  within-1 {report.within_1:.2f}  MAE {report.mae:.2f}  "
          f"weighted kappa {report.qwk:.2f}")


# Phase 10 – Step 4: everything that differs between the judges
JUDGES = {
    "reasons": dict(dataset="reasons", load=lambda v: load_calibration("reasons", v),
                    folder=calibration_dir, run=calibrate_reasons_judge,
                    model=REASONS_JUDGE_MODEL, report=CalibrationReport, show=print_reasons),
    "traveler_relevancy": dict(dataset="relevancy", load=load_relevancy_calibration,
                               folder=relevancy_calibration_dir, run=calibrate_relevancy_judge,
                               model=RELEVANCY_JUDGE_MODEL, report=RelevancyCalibrationReport,
                               show=print_relevancy),
    "thought_action": dict(dataset="thought_action", load=load_thought_action_calibration,
                           folder=thought_action_calibration_dir,
                           run=calibrate_thought_action_judge, model=THOUGHT_ACTION_JUDGE_MODEL,
                           report=CalibrationReport, show=print_reasons),
}


# Phase 10 – Step 4: calibrate one judge; returns an exit code (0 ok, 2 replay miss, 3 differs)
def calibrate(name: str, version: str, mode: str, check_expected: bool, base_llm) -> int:
    judge = JUDGES[name]
    dataset = judge["load"](version)
    folder = judge["folder"](version)
    llm = CassetteLLM(mode, folder / "cassette.jsonl", llm=base_llm, default_model=judge["model"])
    try:
        report = judge["run"](dataset, llm)
    except CassetteMissError as exc:
        print(f"REPLAY FAILED: {exc}")
        return 2

    print(f"\n[{name}] judge {report.judge_model} prompt {report.judge_prompt_version} on "
          f"{report.dataset} (n = {report.n})")
    judge["show"](report)
    for line in report.disagreements:
        print(f"  disagreement – {line}")

    report_file = folder / "report.json"
    if mode == "record":
        report_file.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8",
                               newline="\n")
        print(f"wrote {report_file}")
    if check_expected:
        expected = judge["report"].model_validate_json(report_file.read_text(encoding="utf-8"))
        if expected != report:
            print("REPEATABILITY CHECK FAILED: report differs from the committed report.json")
            return 3
        print("repeatability check passed: report identical to the committed one")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Calibrate LLM judges against human labels.")
    parser.add_argument("--judge", choices=["all", *JUDGES], default="all")
    parser.add_argument("--version", default="v1.0.0")
    parser.add_argument("--mode", choices=["live", "record", "replay"], default="replay")
    parser.add_argument("--check-expected", action="store_true",
                        help="fail unless each report equals its committed report.json")
    args = parser.parse_args()

    base_llm = None
    if args.mode != "replay":
        try:
            base_llm = LLMClient(get_settings())
        except ConfigError as exc:
            print(f"config error: {exc}")
            return 1

    names = list(JUDGES) if args.judge == "all" else [args.judge]
    worst = 0
    for name in names:
        if not (CALIBRATION_DIR / JUDGES[name]["dataset"] / args.version).is_dir():
            if args.judge == "all":  # a judge without a released calibration set yet
                print(f"\n[{name}] skipped: no calibration set {args.version}")
                continue
            print(f"[{name}] no calibration set {args.version}")
            return 1
        worst = max(worst, calibrate(name, args.version, args.mode, args.check_expected,
                                     base_llm))
    return worst


if __name__ == "__main__":
    sys.exit(main())
