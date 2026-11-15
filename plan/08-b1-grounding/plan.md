# Phase 8 – B1 Hallucination & grounding

> Status: **APPROVED** – all recommendations accepted (Q1 per-activity judge, Q2 separate grading cassettes, Q3 ~30 reviewed calibration reasons, Q4 thresholds after first measurement + judge bar R≥0.90/P≥0.80, Q5 in-loop message in B4, Q6 versioned judge prompt, Q7 one commit)
> Branch: `feature/phase-8-b1-grounding`
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md) (v4, Phase 8)
> Depends on: Phase 7 B0 (golden v1.0.0, harness, record/replay) ✅

## Purpose

**Question (goal.md B1):** *is everything in the plan real?*

A plan can be wrong in two different ways:
- **Fabricated data:** an activity that doesn't exist, a changed price or description, the wrong day's weather.
- **Ungrounded claims:** a reason like *"Matches Hiro's interest in movies"* when Hiro doesn't list movies, or *"indoor venue avoids the storm"* for an outdoor event.

Phase 4 catches some fabricated data, but only as one pass/fail per plan. It doesn't check the reasons at all, and it doesn't check whether the agent actually *saw* the data it used.

B1 is the first **full slice** (master plan *slice anatomy*):
1. **Golden data:** a labeled **judge-calibration set** (`reasons-v1.0.0`).
2. **Graders:** activity grounding, trajectory grounding, reason references (code) and **reasons grounded** (LLM judge).
3. **Harness run:** grade stored and recorded runs, and produce the **hallucination rate**.
4. **Thresholds** in `evals/thresholds.toml`.
5. **CI:** replayed grading, judge calibration and threshold report.
6. **Production-signal contract:** the exact fields Layer C will log.

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Grounding** | Every fact in the output can be traced to a source: tool observations (activities, weather) or the user's request (travelers, interests). |
| **Hallucination rate** | Share of output units that aren't grounded. **Activity-level** = hallucinated activities ÷ planned activities. **Plan-level** = plans with ≥ 1 hallucination ÷ plans. Both are reported with Wilson intervals. |
| **Micro vs macro rate** | Micro pools all units (102 activities), macro averages per run. We report micro, because small plans shouldn't count as much as large ones. |
| **Trajectory grounding** | Checking the *process*, not just the result: did the planned activity (and its weather) actually appear in a tool observation during the run? A correct-looking activity the agent never retrieved was guessed. |
| **Run-level (offline) grader** | A grader that takes the whole `AgentRun` (steps + plan + request) after the run, instead of only the plan inside the agent loop. It can be added later and applied to old runs. |
| **Decoupling generation from evaluation** | Agent responses and grader (judge) responses get **separate cassettes**. Changing a judge prompt means re-grading stored runs, never re-running the agent. |
| **Judge calibration** | Before trusting an LLM judge, measure it against human labels. **Precision** (when it says "ungrounded", is it right?), **recall** (does it catch the ungrounded ones?), **Cohen's kappa** (agreement beyond chance). |
| **Threshold** | The minimum acceptable value for a metric (for example activity hallucination rate ≤ 5%). B1 reports pass/fail per threshold; B4 makes failures block merges. |
| **Production-signal contract** | A fixed schema of what a production run will log for this quality question, so Layer C (C1/C2) can build metrics without redesign. |

---

## Design

### 1. Run-level grader framework (`agentsville/harness/grading.py`)

```python
class GraderOutcome(BaseModel):
    name: str                      # "activity_grounding"
    kind: Literal["deterministic", "llm"]
    passed: bool
    units: int = 0                 # e.g. planned activities / reasons examined
    failed_units: int = 0          # e.g. hallucinated activities / ungrounded reasons
    details: list[str] = []

class RunGrader(Protocol):         # (run, case, llm) -> GraderOutcome
    name: str
    def __call__(self, run: AgentRun, case: GoldenCase, llm) -> GraderOutcome: ...

def grade_run(run, case, graders, llm) -> dict[str, GraderOutcome]
```

- `CaseResult` gains `grader_outcomes: dict[str, GraderOutcome]`. The Phase 4 evals stay as they are, in `eval_results`.
- A run **without a plan** gets `passed=False, units=0` for plan graders (conservative, as in B0).
- **Grading cassettes:** judge calls made while grading go through `CassetteLLM` with their own file, `<case>/r<n>.grading.jsonl`, separate from the agent's `r<n>.jsonl`.

### 2. B1 graders (`agentsville/graders/grounding.py`)

| Grader | Kind | Unit | Fails a unit when… |
|---|---|---|---|
| `activity_grounding` | code | planned activity | its `activity_id` doesn't exist (**fabricated**), or any field differs from `data_api` (**altered**: details name the fields **and show the first differing text** for descriptions) |
| `weather_grounding` | code | itinerary day | the day's weather differs from the forecast (the X1 logic, reported per day) |
| `trajectory_grounding` | code | planned activity + day | the activity ID never appeared in any tool observation during the run (weather tool for days, activity tools for activities) |
| `reason_references` | code | reason | it names a traveler who isn't in the request, or says *"<Name>'s interest in X"* where X isn't one of that traveler's interests (cheap pattern check) |
| `reasons_grounded` | **LLM judge** | reason | the judge finds a claim not supported by the activity (description, interests, location, time), the travelers' interests, or that day's forecast |

**Reasons judge:**
- `gpt-4.1`, JSON mode, **one call per recommended activity**, judging all of its reasons at once (about 3 calls per plan).
- Input: the activity, the day's forecast (with description), the travelers and their interests, the reasons.
- Output: `{"reasons": [{"reason": "...", "grounded": true|false, "unsupported_claim": "..."}]}`.
- **Fails closed:** an unparseable reply or LLM error marks every reason in that call ungrounded.
- **Prompt as a versioned file:** `prompts/judges/reasons_grounded/v1.md` (reusing `render_prompt`). Calibration compares judge prompt versions, so the prompt deserves a diffable file.

### 3. Judge-calibration dataset (`evals/datasets/calibration/reasons/v1.0.0/`)
About **30 hand-labeled items** (you review them before release), with the same immutability rules as golden (sha256 + data fingerprint, manifest, changelog):

| Group | Count | Example | Label |
|---|---|---|---|
| Grounded (from `sample_plan.json` and real runs) | ~12 | "Matches Yuri's interest in technology" on the FutureTech meet-up | grounded |
| Wrong interest | ~4 | "Matches Hiro's interest in movies" (Hiro: reading/art/music) | ungrounded |
| Wrong traveler | ~3 | "Perfect for Maria" (no Maria) | ungrounded |
| Wrong weather/venue claim | ~5 | "Indoor venue avoids the storm" on the outdoor 06-12-2 hike; "sunny weather" on 06-13 | ungrounded |
| Invented feature | ~4 | "Free lunch included" when the description says nothing about it | ungrounded |
| Tricky but grounded | ~2 | "Rain fallback keeps it on track" for 06-12-1 (true, D4) | grounded |

`scripts/calibrate_judge.py` runs the judge over the set, with record/replay, and reports a confusion matrix, precision/recall/F1 for *ungrounded*, accuracy and Cohen's kappa. **Trust bar:** recall ≥ 0.90 and precision ≥ 0.80 on *ungrounded* (Q4). The judge is only used in thresholds if it meets the bar.

### 4. Metrics, report, thresholds
- `metrics.py`: for each run-level grader, a **unit rate** (failed ÷ units, micro, with a Wilson CI) and a **run rate** (runs passed ÷ runs).
- **Headline B1 numbers:**
  - activity hallucination rate (`activity_grounding`)
  - plan hallucination rate (runs with any fabricated or altered activity or weather)
  - trajectory-ungrounded rate
  - ungrounded-reason rate (judge)
  - reason-reference error rate (code)
- **Report:** a new "B1 – Grounding" section with these numbers and the 5 worst examples.
- **`evals/thresholds.toml`** (Python 3.11 `tomllib`, no new dependency), for example:
  ```toml
  [b1]
  max_activity_hallucination_rate = 0.05
  max_plan_hallucination_rate     = 0.10
  max_trajectory_ungrounded_rate  = 0.05
  max_ungrounded_reason_rate      = 0.10
  min_judge_recall                = 0.90
  min_judge_precision             = 0.80
  ```
  The exact numbers are set **after** the first measurement (Q4).
- `harness/thresholds.py`: `check_thresholds(summary, calibration) -> list[ThresholdResult]`, shown in the report. The CLI flag `--check-thresholds` exits 4 on failure. It stays informational in CI until B4.

### 5. Grading stored runs (no agent re-run)
- `scripts/grade_runs.py experiments/<exp>`: loads `runs.jsonl` plus the golden cases, applies the run-level graders, writes `grading.jsonl` and an updated report.
- The first B1 measurement grades the **36 stored B0 live runs** (102 activities, 114 reasons) for only the judge cost (about $0.20), instead of about $0.70 to re-run the agent.

### 6. Re-recording expected results for CI
- `CaseResult` gains `grader_outcomes`, so `expected_results.jsonl` changes.
- Run `run_experiment.py --mode replay --grade-mode record`: the **agent replays** from its cassettes and only the grading judge is recorded, into new `*.grading.jsonl` files. That costs about $0.05 and regenerates `expected_results.jsonl`.
- The agent cassettes stay untouched, which proves the decoupling.

### 7. CI (`eval-gate.yml`, still informational)
- Replay agent and grading, with the repeatability check (as in B0, now including `grader_outcomes`).
- Replay the judge calibration from its cassette, which recomputes precision, recall and kappa deterministically.
- Threshold report (`--check-thresholds`), uploaded with the report artifact. Failures are visible but not yet blocking (B4).

### 8. Production-signal contract (`agentsville/graders/signals.py` + `plan/08-b1-grounding/production-signal.md`)
```python
class GroundingSignal(BaseModel):     # logged per production run in C1 (Phase 14)
    planned_activities: int
    fabricated_activities: int
    altered_activities: int
    trajectory_ungrounded: int
    reasons_total: int
    reason_reference_errors: int
    ungrounded_reasons: int | None    # None when the judge wasn't sampled for this run
    judge_sampled: bool
def grounding_signal(outcomes, judge_sampled) -> GroundingSignal
```
- **Online policy (spec for C1):** the code graders run on **every** production run; the judge runs on a **10% sample** to control cost.
- C2 metrics: `b1/activity_hallucination_rate`, `b1/ungrounded_reason_rate` (judged runs only).

---

## Steps

### Step 1 – Run-level grader framework
**Purpose:** graders that look at the whole run and can be applied after the fact.
**Output:** `agentsville/harness/grading.py`; `CaseResult.grader_outcomes`; `agentsville/graders/__init__.py`.
**Depends on:** Phase 7 harness.

### Step 2 – Code graders
**Purpose:** cheap, exact grounding checks.
**Output:** `activity_grounding`, `weather_grounding`, `trajectory_grounding`, `reason_references` in `agentsville/graders/grounding.py`.
**Depends on:** Step 1, `data_api`.

### Step 3 – Calibration dataset (you review the labels)
**Purpose:** human ground truth for the judge.
**Output:** `scripts/build_calibration_dataset.py`; `evals/datasets/calibration/reasons/v1.0.0/` (items, manifest, changelog); loader `load_calibration()` in `harness/dataset.py` (same hash and fingerprint checks).
**Depends on:** Phase 7 dataset tooling.
**Review gate:** the about 30 items and labels are shown to you before release.

### Step 4 – Reasons-grounded judge
**Purpose:** catch ungrounded claims that code can't see.
**Output:** `prompts/judges/reasons_grounded/v1.md`; `reasons_grounded` grader in `grounding.py`.
**Depends on:** Steps 1, 3; `render_prompt` (Phase 6).

### Step 5 – Judge calibration
**Purpose:** measure whether the judge can be trusted.
**Output:** `agentsville/harness/calibration.py` (confusion matrix, precision/recall/F1, kappa); `scripts/calibrate_judge.py [--mode record|replay]`; calibration cassette under `evals/cassettes/calibration/`.
**Depends on:** Steps 3–4.

### Step 6 – Harness integration
**Purpose:** B1 numbers in every experiment.
**Output:** `runner.py` (graders + grading cassettes, `--grade-mode`), `metrics.py` (unit and run rates), `report.py` ("B1 – Grounding" section), `scripts/grade_runs.py`.
**Depends on:** Steps 1–2, 4.

### Step 7 – Thresholds
**Purpose:** turn numbers into pass/fail.
**Output:** `evals/thresholds.toml`, `agentsville/harness/thresholds.py`, `--check-thresholds` flag.
**Depends on:** Steps 5–6.

### Step 8 – First B1 measurement
**Purpose:** real hallucination numbers.
**Output:**
- calibration recorded (~$0.03)
- the 36 stored live runs graded (~$0.20)
- the B0 recording re-graded with agent replay and grading record (~$0.05), giving the new `expected_results.jsonl` and grading cassettes
- thresholds set from the evidence (you confirm)
- `plan/08-b1-grounding/b1-findings.md`

**Depends on:** Steps 1–7.

### Step 9 – CI
**Purpose:** grading, calibration and thresholds on every relevant PR, for free.
**Output:** `.github/workflows/eval-gate.yml` updated.
**Depends on:** Step 8.

### Step 10 – Production-signal contract
**Purpose:** Layer C can implement B1 monitoring without redesign.
**Output:** `agentsville/graders/signals.py`, `plan/08-b1-grounding/production-signal.md`.
**Depends on:** Step 2, 4.

### Step 11 – Tests (Layer A)
**Purpose:** the graders and the calibration math are trustworthy.
**Output:** `tests/test_grounding.py`, `tests/test_calibration.py`, updates to `tests/test_runner.py`.
**Depends on:** Steps 1–10.

| Area | Cases |
|---|---|
| activity_grounding | golden plan → 0/6; fabricated ID → fabricated; changed price → altered with the field named; changed description → altered with the first differing snippet |
| weather / trajectory | wrong weather → that day fails; an activity never seen in an observation → ungrounded; seen via `get_activity_by_id` or the filter tool → grounded |
| reason_references | "Matches Hiro's interest in movies" → error; unknown name → error; "Matches Yuri's interest in technology" → ok; no names → ok |
| reasons judge (fake LLM) | grounded / ungrounded verdicts aggregate correctly; unparseable reply → all reasons ungrounded; one call per activity |
| grading | no plan → conservative outcomes; grading cassette separate from agent cassette; re-grading never touches agent cassettes |
| calibration math | confusion matrix, precision/recall/F1, kappa on known examples (perfect, chance-level, all-one-class) |
| thresholds | pass/fail per rule; missing metric → reported, not crashed |
| signal | `grounding_signal` counts match the outcomes; judge not sampled → `ungrounded_reasons=None` |

### Step 12 – Documentation
**Purpose:** keep `CLAUDE.md` and README accurate.
**Output:** `CLAUDE.md` (graders package, run-level grading, grading cassettes, calibration, thresholds); README section on B1 metrics.
**Depends on:** Steps 1–11.

---

## Verification (definition of done)

```bash
ruff check . && pytest
python scripts/calibrate_judge.py --mode replay              # judge meets the trust bar
python scripts/grade_runs.py experiments/live-v1-r3          # B1 numbers on 36 stored runs
python scripts/run_experiment.py --check-expected --check-thresholds   # replay + repeatability + thresholds
```
Plus green CI (`lint`, `test`, `eval-replay`) and `b1-findings.md` reviewed together.

---

## Decisions (all recommendations accepted)

| # | Question | My recommendation |
|---|---|---|
| Q1 | Reasons judge granularity: one call per **activity** (all its reasons), or one per plan? | **Per activity.** More accurate, about 3 calls/plan, about 1–2 cents |
| Q2 | Separate grading cassettes from agent cassettes? | **Yes.** Judge changes re-grade only; agent recordings stay valid |
| Q3 | Calibration set of about 30 hand-labeled reasons, reviewed by you before release? | Yes |
| Q4 | Set the threshold numbers **after** the first measurement (the defaults above are placeholders); judge trust bar recall ≥ 0.90, precision ≥ 0.80? | Yes |
| Q5 | The agent's loop in g05 comes from the Phase 4 eval message not saying *where* a description differs. Improve the **in-loop** message now, or in B4? | **B4.** Changing it changes agent behavior and invalidates the B0 recording. B1's new grader shows the snippet offline only |
| Q6 | Judge prompt as a versioned file `prompts/judges/reasons_grounded/v1.md`? | **Yes.** Calibration compares judge prompt versions |
| Q7 | One commit for the phase? | Yes |
| Q8 | May I create branch `feature/phase-8-b1-grounding` from `main`? | Yes |
