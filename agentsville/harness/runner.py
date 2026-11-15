# Phase 7 – Step 4: run the agent over a golden dataset × config × repeats, grade and store it all.

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agentsville.agent import AgentRun, ItineraryAgent
from agentsville.graders import ALL_GRADERS
from agentsville.graders.completion import classify_failure
from agentsville.graders.grounding import REASONS_JUDGE_MODEL
from agentsville.harness.dataset import DATASETS_DIR, GoldenCase, GoldenDataset, load_golden
from agentsville.harness.grading import GraderOutcome, RunGrader, grade_run
from agentsville.harness.metrics import ExperimentSummary, summarize
from agentsville.harness.recording import CassetteLLM, Mode
from agentsville.harness.schema import CASSETTES_DIR, CaseResult, ExperimentConfig
from agentsville.llm import LLMClient

EXPECTED_RESULTS_FILE = "expected_results.jsonl"


# Phase 7 – Step 4: the graded, deterministic outcome of one agent run
def result_from_run(
    case_id: str, repeat: int, run: AgentRun,
    grader_outcomes: dict[str, GraderOutcome] | None = None,
) -> CaseResult:
    report = run.final_eval_report
    failures = []
    if report is not None:
        failures = [
            f"{r.name}: {r.details[0] if r.details else 'failed'}"
            for r in report.results
            if not r.passed and r.severity == "error"
        ]
    return CaseResult(
        case_id=case_id,
        repeat=repeat,
        stop_reason=run.stop_reason,
        eval_results={r.name: r.passed for r in report.results} if report else None,
        eval_passed=bool(report and report.passed),
        failures=failures,
        total_cost=run.travel_plan.total_cost if run.travel_plan else None,
        steps=run.step_count,
        cost_usd=round(run.total_cost_usd, 8),
        latency_ms=round(run.total_latency_ms, 3),
        judge_calls=run.judge_calls,
        error=run.error,
        grader_outcomes=grader_outcomes or {},
        failure_mode=classify_failure(run),  # Phase 9 – Step 3
        final_rejections=run.final_rejections,
    )


# Phase 8 – Step 6: run-level graders with their OWN cassette (judges change without agent re-runs)
# Phase 9 – Step 1: pass the golden case so label-based graders can read it
def grade_with_cassette(
    run: AgentRun,
    mode: Mode,
    cassette: Path,
    base_llm: LLMClient | None,
    include_llm: bool,
    graders: list[RunGrader] = ALL_GRADERS,
    case: GoldenCase | None = None,
) -> dict[str, GraderOutcome]:
    selected = [g for g in graders if include_llm or g.kind == "deterministic"]
    llm = None
    if any(g.kind == "llm" for g in selected):
        llm = CassetteLLM(mode, cassette, llm=base_llm, default_model=REASONS_JUDGE_MODEL)
    return grade_run(run, selected, llm, case=case)


# Phase 7 – Step 4: one (case, repeat) through a cassette-backed agent
def run_case(
    case: GoldenCase,
    repeat: int,
    config: ExperimentConfig,
    base_llm: LLMClient | None,
    cassette_root: Path,
) -> tuple[CaseResult, AgentRun]:
    cassette = config.cassette_dir(cassette_root) / case.case_id / f"r{repeat}.jsonl"
    llm = CassetteLLM(config.mode, cassette, llm=base_llm, default_model=config.model)
    agent = ItineraryAgent(
        llm,
        model=config.model,
        prompt_version=config.prompt_version,
        max_steps=config.max_steps,
        include_llm_evals=config.include_llm_evals,
        log_path=None,
    )
    run = agent.run(case.vacation_info)
    grading_cassette = cassette.with_name(f"r{repeat}.grading.jsonl")
    outcomes = grade_with_cassette(run, config.effective_grade_mode, grading_cassette, base_llm,
                                   config.include_llm_evals, case=case)
    return result_from_run(case.case_id, repeat, run, outcomes), run


# Phase 7 – Step 4: dataset × config × repeats → results, summary and stored artifacts
def run_experiment(
    config: ExperimentConfig,
    base_llm: LLMClient | None = None,
    out_dir: Path | None = None,
    cassette_root: Path = CASSETTES_DIR,
    dataset_root: Path = DATASETS_DIR,
    dataset: GoldenDataset | None = None,
    on_result: Callable[[CaseResult, int, int], None] | None = None,  # (result, done, total)
) -> tuple[ExperimentSummary, list[CaseResult]]:
    dataset = dataset or load_golden(config.dataset_version, dataset_root)
    cases = dataset.cases
    if config.case_ids is not None:
        unknown = set(config.case_ids) - {c.case_id for c in cases}
        if unknown:
            raise ValueError(f"unknown case ids: {', '.join(sorted(unknown))}")
        cases = [c for c in cases if c.case_id in config.case_ids]

    tasks = [(case, repeat) for case in cases for repeat in range(1, config.repeats + 1)]
    # Phase 7 – Step 6: report each run as it finishes (completion order), keep task order
    outputs: list[tuple[CaseResult, AgentRun] | None] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=config.workers) as pool:
        futures = {
            pool.submit(run_case, case, repeat, config, base_llm, cassette_root): index
            for index, (case, repeat) in enumerate(tasks)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            outputs[futures[future]] = future.result()
            if on_result is not None:
                on_result(outputs[futures[future]][0], done, len(tasks))
    results = [result for result, _ in outputs]
    summary = summarize(config, dataset.manifest, results)

    if "record" in (config.mode, config.effective_grade_mode):
        write_results(config.cassette_dir(cassette_root) / EXPECTED_RESULTS_FILE, results)
    if out_dir is not None:
        _write_artifacts(out_dir, config, summary, results, [run for _, run in outputs])
    return summary, results


# Phase 7 – Step 4: results as JSON Lines (sorted, so files diff cleanly)
def write_results(path: Path, results: list[CaseResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(results, key=lambda r: (r.case_id, r.repeat))
    path.write_text("".join(r.model_dump_json() + "\n" for r in ordered),
                    encoding="utf-8", newline="\n")


# Phase 9 – Step 4: refresh expected results after a grading-only change – $0, cassettes untouched.
# Only a full replay is allowed: then the agent and judge calls are the recorded ones, so the only
# differences are the new grader code – exactly what the diff of the expected file shows.
def update_expected(
    config: ExperimentConfig, results: list[CaseResult], cassette_root: Path = CASSETTES_DIR,
) -> Path:
    if config.mode != "replay" or config.effective_grade_mode != "replay":
        raise ValueError("--update-expected needs a full replay (mode and grade mode 'replay'); "
                         "record mode already rewrites the expected results")
    if config.case_ids is not None:
        raise ValueError("--update-expected must cover every case (don't pass --cases)")
    path = config.cassette_dir(cassette_root) / EXPECTED_RESULTS_FILE
    write_results(path, results)
    return path


def read_results(path: Path) -> list[CaseResult]:
    return [CaseResult.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# Phase 7 – Step 4: B0's repeatability check – replayed results must equal the recorded ones
def compare_with_expected(results: list[CaseResult], expected: list[CaseResult]) -> list[str]:
    actual = {(r.case_id, r.repeat): r for r in results}
    wanted = {(r.case_id, r.repeat): r for r in expected}
    differences = [f"{k[0]} r{k[1]}: missing from this run" for k in wanted if k not in actual]
    differences += [f"{k[0]} r{k[1]}: not in expected results" for k in actual if k not in wanted]
    for key in sorted(actual.keys() & wanted.keys()):
        a, w = actual[key].model_dump(), wanted[key].model_dump()
        changed = [field for field in w if a[field] != w[field]]
        if changed:
            differences.append(f"{key[0]} r{key[1]}: differs in {', '.join(changed)}")
    return differences


def _write_artifacts(out_dir, config, summary, results, runs) -> None:
    from agentsville.harness.report import render_report  # local import avoids a cycle

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    write_results(out_dir / "results.jsonl", results)
    with (out_dir / "runs.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        # Phase 8 – Step 6: each run carries its case id and repeat, so it can be re-graded later
        for result, run in zip(results, runs, strict=True):
            record = {"case_id": result.case_id, "repeat": result.repeat,
                      "run": json.loads(run.model_dump_json())}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    (out_dir / "report.md").write_text(render_report(summary, results), encoding="utf-8")
