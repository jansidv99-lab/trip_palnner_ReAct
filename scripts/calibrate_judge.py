# Phase 8 – Step 5: measure the reasons-grounded judge against the human-labeled calibration set.
"""Run from the repo root:

    python scripts/calibrate_judge.py                   # replay the committed cassette (free)
    python scripts/calibrate_judge.py --check-expected  # + verify it equals the committed report
    python scripts/calibrate_judge.py --mode record     # call the judge; rewrite cassette + report
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.config import ConfigError, get_settings  # noqa: E402
from agentsville.graders.grounding import REASONS_JUDGE_MODEL  # noqa: E402
from agentsville.harness.calibration import (  # noqa: E402
    CalibrationReport,
    calibrate_reasons_judge,
    calibration_dir,
)
from agentsville.harness.dataset import load_calibration  # noqa: E402
from agentsville.harness.recording import CassetteLLM, CassetteMissError  # noqa: E402
from agentsville.llm import LLMClient  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Calibrate the reasons-grounded judge.")
    parser.add_argument("--version", default="v1.0.0")
    parser.add_argument("--mode", choices=["live", "record", "replay"], default="replay")
    parser.add_argument("--check-expected", action="store_true",
                        help="fail unless the report equals the committed report.json")
    args = parser.parse_args()

    dataset = load_calibration("reasons", args.version)
    folder = calibration_dir(args.version)
    base_llm = None
    if args.mode != "replay":
        try:
            base_llm = LLMClient(get_settings())
        except ConfigError as exc:
            print(f"config error: {exc}")
            return 1
    llm = CassetteLLM(args.mode, folder / "cassette.jsonl", llm=base_llm,
                      default_model=REASONS_JUDGE_MODEL)
    try:
        report = calibrate_reasons_judge(dataset, llm)
    except CassetteMissError as exc:
        print(f"REPLAY FAILED: {exc}")
        return 2

    print(f"judge {report.judge_model} prompt {report.judge_prompt_version} on {report.dataset} "
          f"({report.n} reasons)")
    print(f"confusion (positive = ungrounded): TP {report.tp}  FP {report.fp}  "
          f"TN {report.tn}  FN {report.fn}")
    print(f"precision {report.precision:.2f}  recall {report.recall:.2f}  F1 {report.f1:.2f}  "
          f"accuracy {report.accuracy:.2f}  kappa {report.kappa:.2f}")
    for line in report.disagreements:
        print(f"  disagreement – {line}")

    report_file = folder / "report.json"
    if args.mode == "record":
        report_file.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8",
                               newline="\n")
        print(f"wrote {report_file}")
    if args.check_expected:
        expected = CalibrationReport.model_validate_json(report_file.read_text(encoding="utf-8"))
        if expected != report:
            print("REPEATABILITY CHECK FAILED: report differs from the committed report.json")
            return 3
        print("repeatability check passed: report identical to the committed one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
