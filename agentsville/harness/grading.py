# Phase 8 – Step 1: run-level (offline) graders – applied to a finished AgentRun, any time later.
"""A run-level grader looks at the whole AgentRun – request, every step, final plan – after the
run. Unlike the in-loop evals (Phase 4) it can be added later and applied to old runs, and its LLM
calls go to a separate grading cassette, so judges can change without re-running the agent.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from agentsville.agent import AgentRun


# Phase 8 – Step 1: the outcome of one grader on one run, counted in units (activities, reasons…)
class GraderOutcome(BaseModel):
    name: str
    kind: Literal["deterministic", "llm"]
    passed: bool
    units: int = 0  # how many things were examined
    failed_units: int = 0  # how many of them failed
    counts: dict[str, int] = {}  # failure breakdown, e.g. {"fabricated": 1, "altered": 2}
    details: list[str] = []


# Phase 8 – Step 1: a named grader; fn(run, llm) -> GraderOutcome (llm is None for code graders)
@dataclass(frozen=True)
class RunGrader:
    name: str
    kind: Literal["deterministic", "llm"]
    fn: Callable[[AgentRun, Any], GraderOutcome]


# Phase 8 – Step 1: build an outcome from examined/failed units
def outcome(
    name: str,
    kind: Literal["deterministic", "llm"],
    units: int,
    problems: list[str],
    counts: dict[str, int] | None = None,
    failed_units: int | None = None,
) -> GraderOutcome:
    failed = len(problems) if failed_units is None else failed_units
    return GraderOutcome(
        name=name, kind=kind, passed=failed == 0, units=units, failed_units=failed,
        counts=counts or {}, details=problems,
    )


# Phase 8 – Step 1: apply graders to one run; a run without a plan fails every grader (B0 rule)
def grade_run(run: AgentRun, graders: list[RunGrader], llm: Any = None) -> dict[str, GraderOutcome]:
    results = {}
    for grader in graders:
        if run.travel_plan is None:
            results[grader.name] = GraderOutcome(
                name=grader.name, kind=grader.kind, passed=False, details=["no plan produced"]
            )
        else:
            results[grader.name] = grader.fn(run, llm if grader.kind == "llm" else None)
    return results
