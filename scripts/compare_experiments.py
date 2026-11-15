# Phase 7 – Step 6: compare two experiment folders (A = before, B = after).
"""Run from the repo root:

    python scripts/compare_experiments.py experiments/<A> experiments/<B> [--force]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.harness.metrics import ExperimentSummary  # noqa: E402
from agentsville.harness.report import ComparisonError, compare  # noqa: E402


def load(folder: Path) -> ExperimentSummary:
    return ExperimentSummary.model_validate_json(
        (folder / "summary.json").read_text(encoding="utf-8")
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Compare two experiments.")
    parser.add_argument("a", type=Path, help="experiment folder A (baseline)")
    parser.add_argument("b", type=Path, help="experiment folder B (candidate)")
    parser.add_argument("--force", action="store_true", help="compare different datasets anyway")
    args = parser.parse_args()
    try:
        print(compare(load(args.a), load(args.b), force=args.force))
    except ComparisonError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
