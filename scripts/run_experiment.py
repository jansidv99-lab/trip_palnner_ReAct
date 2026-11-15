# Phase 7 – Step 6: run an experiment on the golden dataset (live / record / replay).
"""Run from the repo root:

    python scripts/run_experiment.py                         # replay committed cassettes (free)
    python scripts/run_experiment.py --check-expected        # + verify replay == recording (CI)
    python scripts/run_experiment.py --mode record           # call the LLM, (re)write cassettes
    python scripts/run_experiment.py --mode live --repeats 3 # explore variance, store nothing
    python scripts/run_experiment.py --cases g01-sample-yuri-hiro,g07-infeasible-budget
    python scripts/run_experiment.py --grade-mode record      # replay agent, re-record grading only
    python scripts/run_experiment.py --check-thresholds       # + evals/thresholds.toml verdicts
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.config import ConfigError, get_settings  # noqa: E402
from agentsville.harness.calibration import load_committed_calibration  # noqa: E402
from agentsville.harness.recording import CassetteMissError  # noqa: E402
from agentsville.harness.report import render_report  # noqa: E402
from agentsville.harness.runner import (  # noqa: E402
    EXPECTED_RESULTS_FILE,
    compare_with_expected,
    read_results,
    run_experiment,
)
from agentsville.harness.schema import (  # noqa: E402
    EXPERIMENTS_DIR,
    CaseResult,
    ExperimentConfig,
)
from agentsville.harness.thresholds import check_thresholds, thresholds_passed  # noqa: E402
from agentsville.llm import LLMClient  # noqa: E402


# Phase 7 – Step 6: one line per finished run, flushed immediately (works under pipes/CI logs)
def print_progress(result: CaseResult, done: int, total: int) -> None:
    ok = result.stop_reason == "final_answer" and result.eval_passed
    mark = "✓" if ok else "✗"
    reason = (result.failures or [result.error or f"no plan ({result.stop_reason})"])[0]
    detail = "" if ok else f"  ← {reason[:70]}"
    print(f"[{done:>{len(str(total))}}/{total}] {mark} {result.case_id:<28} r{result.repeat}  "
          f"{result.stop_reason or '-':<12} {result.steps:>2} steps  ${result.cost_usd:.4f}  "
          f"{result.latency_ms / 1000:5.1f}s{detail}", flush=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the itinerary agent over a golden dataset.")
    parser.add_argument("--dataset", default="v1.0.0")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--prompt", default="v1")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM weather judge")
    parser.add_argument("--mode", choices=["live", "record", "replay"], default="replay")
    parser.add_argument("--grade-mode", choices=["live", "record", "replay"],
                        help="mode for grading (judge) cassettes; default: same as --mode")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cases", help="comma-separated case ids (default: all)")
    parser.add_argument("--out", type=Path, help="output folder (default: experiments/<ts>__<id>)")
    parser.add_argument("--check-expected", action="store_true",
                        help="fail unless results equal the recorded expected_results.jsonl")
    parser.add_argument("--check-thresholds", action="store_true",
                        help="add evals/thresholds.toml verdicts to the report; exit 4 on failure")
    args = parser.parse_args()

    config = ExperimentConfig(
        dataset_version=args.dataset, model=args.model, prompt_version=args.prompt,
        temperature=args.temperature, repeats=args.repeats, max_steps=args.max_steps,
        include_llm_evals=not args.no_judge, mode=args.mode, grade_mode=args.grade_mode,
        workers=args.workers,
        case_ids=args.cases.split(",") if args.cases else None,
    )
    base_llm = None
    if config.mode != "replay" or config.effective_grade_mode != "replay":
        try:
            base_llm = LLMClient(get_settings())
        except ConfigError as exc:
            print(f"config error: {exc}")
            return 1

    out = args.out or EXPERIMENTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}__{config.config_id}"
    print(f"experiment {config.config_id} · dataset {config.dataset_version} · mode {config.mode}"
          f" · repeats {config.repeats} · workers {config.workers}")
    try:
        summary, results = run_experiment(config, base_llm=base_llm, out_dir=out,
                                          on_result=print_progress)
    except CassetteMissError as exc:
        print(f"REPLAY FAILED: {exc}")
        return 2

    gc = summary.goal_completion
    print(f"goal completion {gc.rate:.1%} [{gc.ci_low:.0%}–{gc.ci_high:.0%}] "
          f"({gc.successes}/{gc.n}) · cost total ${summary.cost_usd.total:.4f} · "
          f"steps mean {summary.steps.mean:.1f}")
    print(f"report: {out / 'report.md'}")
    if config.mode == "record":
        print(f"cassettes + {EXPECTED_RESULTS_FILE}: {config.cassette_dir()}")

    if args.check_expected:
        expected = read_results(config.cassette_dir() / EXPECTED_RESULTS_FILE)
        if config.case_ids is not None:
            expected = [r for r in expected if r.case_id in config.case_ids]
        differences = compare_with_expected(results, expected)
        if differences:
            print("REPEATABILITY CHECK FAILED:\n  " + "\n  ".join(differences))
            return 3
        print(f"repeatability check passed: {len(results)} runs identical to the recording")

    if args.check_thresholds:
        thresholds = check_thresholds(summary, load_committed_calibration())
        (out / "report.md").write_text(render_report(summary, results, thresholds),
                                       encoding="utf-8")
        for t in thresholds:
            verdict = {True: "pass", False: "FAIL", None: "not measured"}[t.passed]
            value = "—" if t.value is None else f"{t.value:.3f}"
            print(f"threshold {t.section}.{t.rule} ≤/≥ {t.limit:g}: {value} → {verdict}")
        if not thresholds_passed(thresholds):
            print("THRESHOLDS FAILED – see the report")
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
