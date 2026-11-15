# Phase 8 – Step 6: apply run-level graders to a stored experiment – no agent re-run needed.
"""Run from the repo root:

    python scripts/grade_runs.py experiments/<exp>                 # record judge calls (costs)
    python scripts/grade_runs.py experiments/<exp> --mode replay   # re-grade from its cassettes
    python scripts/grade_runs.py experiments/<exp> --no-judge      # code graders only (free)
    python scripts/grade_runs.py experiments/<exp> --record-graders thought_action_consistency
                                                   # record ONE judge, replay all the others

Grading cassettes go to experiments/<exp>/grading/; results.jsonl, summary.json and report.md
are rewritten with the grader outcomes.
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.agent import AgentRun  # noqa: E402
from agentsville.config import ConfigError, get_settings  # noqa: E402
from agentsville.graders.completion import classify_failure  # noqa: E402
from agentsville.harness.calibration import load_committed_calibration  # noqa: E402
from agentsville.harness.dataset import load_golden  # noqa: E402
from agentsville.harness.metrics import summarize  # noqa: E402
from agentsville.harness.report import render_report  # noqa: E402
from agentsville.harness.runner import (  # noqa: E402
    grade_with_cassette,
    read_results,
    validate_record_graders,
    write_results,
)
from agentsville.harness.schema import ExperimentConfig  # noqa: E402
from agentsville.harness.thresholds import (  # noqa: E402
    check_thresholds,
    committed_judge_reports,
    thresholds_passed,
)
from agentsville.llm import LLMClient  # noqa: E402


# Phase 8 – Step 6: pair stored runs with their results (new wrapper format or B0 plain lines)
def load_runs(folder: Path, results, dataset) -> dict[tuple[str, int], AgentRun]:
    lines = [json.loads(line) for line in
             (folder / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if lines and "run" in lines[0]:
        return {(x["case_id"], x["repeat"]): AgentRun.model_validate(x["run"]) for x in lines}
    ordered = sorted(results, key=lambda r: (r.case_id, r.repeat))  # B0 wrote runs in this order
    runs = {}
    for result, raw in zip(ordered, lines, strict=True):
        run = AgentRun.model_validate(raw)
        if run.vacation_info != dataset.case(result.case_id).vacation_info:
            raise SystemExit(f"runs.jsonl order doesn't match results at {result.case_id}")
        runs[(result.case_id, result.repeat)] = run
    return runs


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Grade a stored experiment's runs.")
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--mode", choices=["live", "record", "replay"], default="record")
    parser.add_argument("--no-judge", action="store_true", help="code graders only")
    # Phase 10 – Step 1: record only the named LLM judges (own cassettes); others replay
    parser.add_argument("--record-graders",
                        help="comma-separated LLM judges to record; every other judge replays")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--check-thresholds", action="store_true")
    args = parser.parse_args()

    record_graders = args.record_graders.split(",") if args.record_graders else None
    try:
        validate_record_graders(record_graders)
    except ValueError as exc:
        print(exc)
        return 1
    folder = args.experiment
    config = ExperimentConfig.model_validate_json((folder / "config.json").read_text("utf-8"))
    dataset = load_golden(config.dataset_version)
    results = read_results(folder / "results.jsonl")
    runs = load_runs(folder, results, dataset)

    base_llm = None
    if (args.mode != "replay" or record_graders) and not args.no_judge:
        try:
            base_llm = LLMClient(get_settings())
        except ConfigError as exc:
            print(f"config error: {exc}")
            return 1

    def grade(result):
        cassette = folder / "grading" / result.case_id / f"r{result.repeat}.grading.jsonl"
        run = runs[(result.case_id, result.repeat)]
        # Phase 9 – Step 1: pass the golden case so label-based graders can read it
        outcomes = grade_with_cassette(run, args.mode, cassette,
                                       base_llm, include_llm=not args.no_judge,
                                       case=dataset.case(result.case_id),
                                       record_graders=record_graders)
        print(f"graded {result.case_id} r{result.repeat}: "
              + ", ".join(f"{n} {o.failed_units}/{o.units}" for n, o in outcomes.items()),
              flush=True)
        # Phase 9 – Step 3: stored B0/B1 results predate the failure taxonomy – derive it here
        return result.model_copy(update={
            "grader_outcomes": outcomes,
            "failure_mode": classify_failure(run),
            "final_rejections": run.final_rejections,
        })

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        graded = list(pool.map(grade, results))

    summary = summarize(config, dataset.manifest, graded)
    thresholds = check_thresholds(summary, load_committed_calibration(),
                                  judge_reports=committed_judge_reports())
    write_results(folder / "results.jsonl", graded)
    (folder / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    (folder / "report.md").write_text(render_report(summary, graded, thresholds), encoding="utf-8")

    b1 = summary.b1
    print(f"\nB1 on {len(graded)} runs: activity hallucination {b1.activity_hallucination.rate:.1%}"
          f" · plan hallucination {b1.plan_hallucination.rate:.1%} · trajectory ungrounded "
          f"{b1.trajectory_ungrounded.rate:.1%} · reason reference errors "
          f"{b1.reason_reference_errors.rate:.1%}"
          + (f" · ungrounded reasons {b1.ungrounded_reasons.rate:.1%}"
             if b1.ungrounded_reasons else ""))
    print(f"report: {folder / 'report.md'}")
    if args.check_thresholds and not thresholds_passed(thresholds):
        print("THRESHOLDS FAILED – see the report")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
