# Phase 7 – Step 4: experiment config and per-run results (shared by runner/metrics/report).

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

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
    case_ids: list[str] | None = None  # None = every case in the dataset
    workers: int = Field(default=4, ge=1)

    # Phase 7 – Step 4: short id of the settings that define a cassette set
    @property
    def config_id(self) -> str:
        raw = f"{self.model}__{self.prompt_version}__t{self.temperature:g}"
        if not self.include_llm_evals:
            raw += "__nojudge"
        return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)

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
