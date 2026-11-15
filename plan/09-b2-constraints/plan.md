# Phase 9 – B2 Constraint compliance & goal completion

> Status: **APPROVED (2026-11-15)** – Q1–Q7 answered with the recommendations below
> Branch: `feature/phase-9-b2-constraints`
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md) (v4, Phase 9)
> Depends on: Phase 7 B0 (harness) ✅, Phase 8 B1 (run-level graders, thresholds, signals) ✅

## Purpose

**Question (goal.md B2):** *does the plan satisfy the traveler's hard constraints?* Plus the
agentic half: *does the agent actually finish the job, and if not, why not?*

| Part | Meaning |
|---|---|
| **Constraint compliance** | For every plan produced: right city/dates, within budget, correct total, no overlaps, weather-appropriate. Measured as a **violation rate per constraint**, not one pass/fail. |
| **Goal completion** | The run ends with a final answer **and** all hard constraints hold. When it doesn't, **why**: a cost loop, invalid-argument loop, guardrail exhausted, timeout? |
| **Infeasible requests** | When no valid plan with activities exists (g07, budget 10), the correct outcome is an empty plan delivered properly, not a loop. |

**B2 adds no LLM cost.** Its graders are code, and they reuse the Phase 4 in-loop eval results
already stored with every run. The first measurement re-grades the stored 36 live runs and the B0
recording for free.

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Hard vs soft constraints** | Hard: must hold for the plan to be acceptable (city/dates, budget, total, overlaps, weather). Soft: nice to have (interest coverage, 2 activities/day). B2 is about hard ones; soft ones go to B3. |
| **Violation rate per constraint** | Of the plans produced, how many break *this* constraint. That shows *which* rule the agent struggles with, which one pass/fail number hides. |
| **Conditional vs unconditional rates** | Compliance is measured **over produced plans** (conditional: "when it answers, is the answer valid?"). Goal completion is over **all runs** (unconditional: "does the job get done?"). Both are needed. |
| **Failure taxonomy** | A fixed set of categories for *why* a run didn't complete, assigned by deterministic rules from the trajectory. It turns "28% failed" into "17% cost loops, 6% argument loops…": something you can fix. |
| **Label-based grading** | Comparing the plan with **human labels** from the golden dataset (`must_avoid_activity_ids`), instead of another LLM. It's cheap and exact, and it also lets us check the weather **judge** against humans on real runs. |
| **Judge–label agreement on live data** | B1 calibrated a judge on a curated set. Here we check the *weather* judge on the activities agents actually picked: does "unsuitable" match the human `must_avoid` label? |
| **Case-aware graders** | Graders that need the golden case (its labels) as well as the run. The grader context grows from `llm` to `GradingContext(llm, case)`. |

---

## Design

### 1. Case-aware grading (`harness/grading.py`)
```python
@dataclass
class GradingContext:
    llm: Any = None                 # judge client (None for code graders)
    case: GoldenCase | None = None  # labels; None when grading runs outside a dataset

RunGrader.fn: (run: AgentRun, ctx: GradingContext) -> GraderOutcome
```
- B1 graders are migrated mechanically (`llm` → `ctx.llm`). Their outcomes are unchanged, which the existing tests prove.
- The runner and `grade_runs.py` pass the case. Graders that need labels return a *not applicable* outcome (`units=0`, passed) when the case is missing.

### 2. B2 graders (`agentsville/graders/constraints.py`)

| Grader | Kind | Unit | Fails when… |
|---|---|---|---|
| `weather_label_compliance` | code (labels) | planned activity on an inclement day | the activity is in the case's `must_avoid_activity_ids` (ambiguous ones are skipped) |
| `infeasible_handling` | code (labels) | the run, only for cases with `max_affordable_activities == 0` | the run doesn't end with `final_answer` **and** an empty plan with `total_cost == 0` |
| `budget_respected` | code | the run | the actual price sum > budget (computed from the run itself, not the report) |

The other hard constraints (city/dates, cost accuracy, overlaps, weather judge) are **already graded in-loop** (Phase 4) and stored in `CaseResult.eval_results`. B2 aggregates them instead of grading twice.

### 3. Failure taxonomy (`agentsville/graders/completion.py`)
`classify_failure(run, eval_results, max_rejections=2) -> str | None` (None = completed). Rules are applied in order:

| Category | Rule | Seen in stored runs |
|---|---|---|
| `llm_error:timeout` / `llm_error:other` | `stop_reason == "llm_error"` (timeout if the error mentions it) | B0 g06 |
| `guardrail_exhausted:<grader>` | final accepted after `max_rejections` rejections, still failing (`<grader>` = first failing hard eval) | g05 r3, g06 r1 |
| `final_failed:<grader>` | final accepted with fewer rejections but failing (e.g. the judge-only weather check) | – |
| `invalid_args_loop:<tool>` | ≥ 3 `invalid arguments` errors on the same tool | g07 r3, g09 r3 |
| `eval_loop:<grader>` | ≥ 2 `EVALS FAILED` observations; `<grader>` = the most frequent ✗ line | g02 ×3, g01 r3, g06 r2 |
| `max_steps:other` | anything else that hit `max_steps` | g03 r2 |

`CaseResult` gains `failure_mode: str | None` and `final_rejections: int`.

### 4. B2 metrics (`ConstraintMetrics` in `metrics.py`)

| Metric | Denominator | Source |
|---|---|---|
| Violation rate: city/dates, cost accuracy, overlaps, budget, weather (judge), weather (labels) | produced plans (or labeled units) | `eval_results` + B2 graders |
| **All hard constraints pass** | produced plans | `eval_passed` |
| **Goal completion** | all runs | existing |
| Failure-mode distribution | non-completed runs | taxonomy |
| Guardrail rejection rate | runs reaching a final answer | `final_rejections > 0` |
| Steps to completion | completed runs | p50 / p95 |
| Infeasible handling | infeasible cases | `infeasible_handling` |
| **Weather judge vs labels** | labeled inclement-day activities that were planned | judge verdicts (parsed from the stored `weather_suitability` details) vs `must_avoid` → agreement, plus missed / false alarm counts |

Report: a new "B2 – Constraints & completion" section (violation table, failure-mode table with an example run each). `compare` gets B2 rows.

### 5. Thresholds `[b2]` in `evals/thresholds.toml` (values set after measurement, Q5)
```toml
[b2]
max_city_dates_violation_rate = …
max_budget_violation_rate = …
max_cost_accuracy_violation_rate = …
max_overlap_violation_rate = …
max_weather_label_violation_rate = …
min_goal_completion_rate = …
```

### 6. Refreshing expected results without LLM calls
B2 changes `CaseResult` (new fields, new grader outcomes), so `expected_results.jsonl` must be regenerated. The agent and grading cassettes are **unchanged** (B2 graders make no LLM calls), so a new flag `run_experiment.py --update-expected` (replay only) rewrites the file. It costs $0, and the diff is reviewable.

### 7. Production-signal contract (`graders/signals.py`, `production-signal.md` updated)
```python
class ConstraintSignal(BaseModel):    # schema_version "b2.v1", logged per production run (C1)
    stop_reason: str
    goal_completed: bool
    failure_mode: str | None
    steps: int
    final_rejections: int
    constraints: dict[str, bool]      # city_and_dates, within_budget, total_cost_accurate, …
    budget: int
    total_cost: int | None
```
These feed the **C2 dashboard** (`goal.md`: "C2 … after B2"): online completion rate, failure-mode mix and per-constraint violation rates.

---

## Steps

### Step 1 – Case-aware grading context
**Purpose:** graders can read the golden labels.
**Output:** `GradingContext` in `harness/grading.py`; B1 graders migrated; the runner and `grade_runs.py` pass the case.
**Depends on:** Phase 8 framework.

### Step 2 – B2 constraint graders
**Purpose:** label-based and run-based constraint checks.
**Output:** `agentsville/graders/constraints.py` (`weather_label_compliance`, `infeasible_handling`, `budget_respected`), registered in `ALL_GRADERS`.
**Depends on:** Step 1.

### Step 3 – Failure taxonomy
**Purpose:** explain every non-completed run.
**Output:** `agentsville/graders/completion.py` (`classify_failure`); `CaseResult.failure_mode` and `final_rejections`.
**Depends on:** Step 1.

### Step 4 – B2 metrics and report
**Purpose:** per-constraint violation rates, the completion picture, and weather judge vs labels.
**Output:** `ConstraintMetrics` in `metrics.py`; "B2" section and compare rows in `report.py`; `--update-expected` in `run_experiment.py`.
**Depends on:** Steps 2–3.

### Step 5 – First B2 measurement ($0)
**Purpose:** real numbers.
**Output:** re-grade the 36 stored live runs (`grade_runs.py --mode replay`, which reuses the B1 grading cassettes); refresh the B0 expected results (`--update-expected`); `plan/09-b2-constraints/b2-findings.md`.
**Depends on:** Step 4.

### Step 6 – Thresholds
**Purpose:** pass/fail for B2.
**Output:** `[b2]` in `evals/thresholds.toml` (values from Step 5, which you confirm); metric getters in `harness/thresholds.py`.
**Depends on:** Step 5.

### Step 7 – Production-signal contract
**Purpose:** C2 can chart completion and constraint violations without redesign.
**Output:** `ConstraintSignal` + `constraint_signal()` in `graders/signals.py`; `production-signal.md` (B2 section).
**Depends on:** Steps 2–3.

### Step 8 – Tests (Layer A)
**Purpose:** graders, taxonomy and metrics are trustworthy.
**Output:** `tests/test_constraints.py`; updates to `tests/test_grounding.py` / `test_runner.py` for the context change.
**Depends on:** Steps 1–7.

| Area | Cases |
|---|---|
| weather_label_compliance | must-avoid activity planned → violation; ambiguous activity → skipped; fair-weather case → no units; no case → not applicable |
| infeasible_handling | g07-like case: empty plan + final → pass; plan with activities, or max_steps → fail; feasible case → not applicable |
| budget_respected | over budget by actual sum (even if `total_cost` understates) → fail |
| taxonomy | one synthetic run per category (timeout, guardrail exhausted, final failed, invalid-args loop, eval loop with the dominant grader, max_steps other); completed run → None |
| metrics | violation rates over produced plans only; failure-mode counts; steps to completion over completed runs; judge-vs-label agreement counts |
| update-expected | rewrites the expected file in replay mode; refuses in record/live |
| signal | `constraint_signal` fields match the run |

### Step 9 – Documentation
**Purpose:** keep `CLAUDE.md` and README accurate.
**Output:** `CLAUDE.md` (GradingContext, B2 graders, taxonomy, `--update-expected`); README (B2 metrics).
**Depends on:** Steps 1–8.

---

## Verification (definition of done)

```bash
ruff check . && pytest
python scripts/grade_runs.py experiments/live-v1-r3 --mode replay --check-thresholds   # $0
python scripts/run_experiment.py --check-expected --check-thresholds                  # CI path
```
Plus green CI and `b2-findings.md` reviewed together. **No LLM spend in this phase.**

---

## Questions for you

| # | Question | My recommendation |
|---|---|---|
| Q1 | Keep golden **v1.0.0** (its labels already cover B2: `must_avoid`, `max_affordable_activities`); grow the dataset later in B5? | **Yes.** A new version means re-recording everything and breaks comparability with B0/B1 |
| Q2 | Make graders case-aware via `GradingContext(llm, case)` (small, mechanical B1 refactor)? | Yes |
| Q3 | The failure taxonomy categories above? | Yes. Rules are deterministic, applied in that order |
| Q4 | B2 stays **measure-only**: fixes for the cost loop, invalid-argument loop and timeout go to B4 (eval-driven improvement)? | **Yes.** Keeps B0–B2 numbers comparable; B4 fixes with evidence and measures the lift |
| Q5 | Set the `[b2]` threshold values after the measurement (as in B1), you choosing target vs regression guard where they fail? | Yes |
| Q6 | One commit for the phase? | Yes |
| Q7 | May I create branch `feature/phase-9-b2-constraints` from `main`? | Yes |
