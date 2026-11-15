# Phase 7 – Step 4: experiment config and per-run results (shared by runner/metrics/report).

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentsville.harness.grading import GraderOutcome
from agentsville.harness.recording import Mode

ROOT = Path(__file__).resolve().parent.parent.parent
CASSETTES_DIR = ROOT / "evals" / "cassettes"
EXPERIMENTS_DIR = ROOT / "experiments"


# Phase 7 – Step 4: everything that can change an experiment's results
class ExperimentConfig(BaseModel):
    dataset_version: str = "v1.0.0"
    model: str = "gpt-4o-mini"
    prompt_version: str = "v1"
    temperature: float = 0.0
    repeats: int = Field(default=1, ge=1)
    max_steps: int = Field(default=20, ge=1)
    include_llm_evals: bool = True
    mode: Mode = "replay"
    grade_mode: Mode | None = None  # Phase 8: grading cassettes; None = same as mode
    case_ids: list[str] | None = None  # None = every case in the dataset
    workers: int = Field(default=4, ge=1)
    # Phase 10 – Step 1: record ONLY these LLM judges; every other judge replays its own cassette
    record_graders: list[str] | None = None

    # Phase 10 – Step 1: --record-graders decides per judge, so it can't be mixed with a grade mode
    @model_validator(mode="after")
    def _record_graders_need_replay(self) -> "ExperimentConfig":
        if self.record_graders and self.grade_mode not in (None, "replay"):
            raise ValueError("record_graders already sets each judge's mode; drop grade_mode")
        if self.record_graders and self.mode == "live":
            raise ValueError("record_graders can't be combined with live agent runs")
        return self

    # Phase 10 – Step 1: does this experiment call (and record with) a real LLM anywhere?
    @property
    def needs_llm(self) -> bool:
        return (self.mode != "replay" or self.effective_grade_mode != "replay"
                or bool(self.record_graders))

    # Phase 7 – Step 4: short id of the settings that define a cassette set
    @property
    def config_id(self) -> str:
        raw = f"{self.model}__{self.prompt_version}__t{self.temperature:g}"
        if not self.include_llm_evals:
            raw += "__nojudge"
        return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)

    # Phase 8 – Step 6: agent and grader recordings are independent (re-grade without re-running)
    @property
    def effective_grade_mode(self) -> Mode:
        return self.grade_mode or self.mode

    def cassette_dir(self, root: Path = CASSETTES_DIR) -> Path:
        return root / f"golden-{self.dataset_version}" / self.config_id


# Phase 7 – Step 4: the graded outcome of one (case, repeat) – deterministic under replay
class CaseResult(BaseModel):
    case_id: str
    repeat: int
    stop_reason: Literal["final_answer", "max_steps", "llm_error"] | None
    eval_results: dict[str, bool] | None = None  # grader → passed; None when there's no plan
    eval_passed: bool = False  # conservative: False without a plan
    failures: list[str] = []  # "grader: first detail" for every failed grader
    total_cost: int | None = None  # the plan's total_cost
    steps: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    judge_calls: int = 0
    error: str | None = None
    grader_outcomes: dict[str, GraderOutcome] = {}  # Phase 8: run-level graders (B1+)
    # Phase 9 – Step 3: why the run didn't complete (None = completed) and guardrail rejections
    failure_mode: str | None = None
    final_rejections: int = 0
