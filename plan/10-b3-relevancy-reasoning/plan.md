# Phase 10 – B3 Relevancy & reasoning verification

> Status: **IMPLEMENTED (2026-11-15)** – Q1–Q9 answered with the recommendations below; see "Implementation notes" at the end
> Branch: `feature/phase-10-b3-relevancy-reasoning`
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md) (v4, Phase 10)
> Depends on: Phase 7 B0 (harness, cassettes) ✅, Phase 8 B1 (run-level graders, judge calibration) ✅,
> Phase 9 B2 (GradingContext, failure taxonomy, `--update-expected`) ✅

## Purpose

**Question (goal.md B3):** *is the plan relevant to these travelers, and is its step-by-step
reasoning faithful to the output?*

| Part | Meaning |
|---|---|
| **Answer relevancy** | Does the plan fit *these* travelers – their interests, as well as the available activities and the weather allow? B1 asked "is it real?", B2 "is it allowed?"; B3 asks "is it *good for them*?" |
| **Reasoning verification** | Did the agent follow the procedure its prompt prescribes (weather for every day, total from the calculator, evals before the final answer)? Did it submit what it verified? Do its THOUGHTs match its ACTIONs? |
| **Efficiency** | How much of the trajectory is wasted: repeated identical lookups, error steps. |

B2 found that 7 of 10 failed runs are cost loops caused by **bookkeeping** (the calculator gets the
wrong price list). B3's reasoning checks measure that at its source – on every run, including the
ones that complete – instead of only seeing it when a run fails.

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Answer relevancy** | How well the output serves the request. Here: per traveler, how well the activities match their interests *relative to what was possible* (data + weather), not in absolute terms. |
| **Rubric scoring (1–5)** | The judge scores against fixed, written anchors ("5 = …, 1 = …") instead of a free opinion. Anchors make scores comparable across runs and judge versions. |
| **Ordinal agreement** | For 1–5 scores, "judge said 4, human said 5" is closer than "1 vs 5". We use **within-1 agreement** and **quadratic weighted kappa** (penalizes big disagreements more) to calibrate the relevancy judge. |
| **Trajectory (procedural) validation** | Grading *how* the agent got the answer, step by step, not just the answer. Deterministic checks over the stored `AgentRun.steps`. |
| **Faithfulness** | The output follows from the reasoning that produced it: the plan's total comes from a calculator call on *the plan's own prices*; the plan sent to `final_answer_tool` is the one that passed `run_evals_tool`. An unfaithful run can still produce a correct-looking plan by luck. |
| **Thought↔action consistency** | Each ACTION does what its THOUGHT says (and the THOUGHT doesn't misreport the last observation). Needs judgement → an LLM judge over the trajectory, calibrated on labeled steps. |
| **Redundant-call rate** | Identical lookup calls repeated (same tool, same arguments – weather and activity data never change mid-run). A cost and latency signal. |
| **Per-judge cassettes** | Each LLM judge records to its own grading cassette, so recording a new judge never re-calls (or changes) an existing one. See Design §1. |

---

## Design

### 1. Per-judge grading cassettes (infrastructure, needed first)
**Problem:** `CassetteLLM` in `record` mode empties the cassette before recording
(`recording.py`). Today `<case>/r<n>.grading.jsonl` holds the B1 reasons judge. Recording a new B3
judge there would re-call the B1 judge: extra cost, and the approved B1 numbers could shift
(LLM replies aren't perfectly repeatable).

**Change:** every `kind="llm"` grader gets its own cassette:

| Grader | Cassette |
|---|---|
| `reasons_grounded` (B1) | `r<n>.grading.jsonl` – **unchanged name**, so committed B1 cassettes stay valid |
| any new judge `<name>` | `r<n>.grading.<name>.jsonl` |

`grade_with_cassette` builds one `CassetteLLM` per LLM grader. New option
`--record-graders a,b` (on `run_experiment.py` and `grade_runs.py`): those judges record, every other
judge replays. So B3 can record only its two judges, and B1 stays byte-identical.

### 2. Relevancy graders (`agentsville/graders/relevancy.py`)

| Grader | Kind | Unit | Fails when… |
|---|---|---|---|
| `interest_coverage_labeled` | code (labels) | each **coverable** traveler (not in `uncoverable_travelers`) | no planned activity matches any of their interests |
| `interest_match` | code | each planned activity | it matches none of the travelers' interests (informational: weather can justify it) |
| `traveler_relevancy` | **LLM judge** (`gpt-4.1`, JSON) | each traveler | judge score ≤ 2 on the 1–5 rubric; every score kept in `counts` (`score_1` … `score_5`) |

**Relevancy judge input** (one call per run, all travelers at once):
the travelers (name, age, interests), the plan by day with that day's forecast, and – so the score
is *relative to what was possible* – **all activities available that day** (from `data_api`), with
their interests. It must not penalize a plan for interests no activity offers.

**Rubric** (prompt `prompts/judges/traveler_relevancy/v1.md`):

| Score | Anchor |
|---|---|
| 5 | Gets activities matching their interests whenever a suitable one existed |
| 4 | Well served; missed at most one clearly better available option |
| 3 | Partly served: some matching options available but not chosen |
| 2 | Mostly ignored although matching, suitable options existed |
| 1 | Completely ignored although matching, suitable options existed |

Fails closed like the B1 judge: unparseable reply or LLM error → every traveler scored 1.

### 3. Trajectory graders (`agentsville/graders/trajectory.py`) – code, $0

| Grader | Unit | Fails when… (counts) |
|---|---|---|
| `weather_lookup_coverage` | each trip day | no non-error `get_weather_for_date_tool` call for that day before the final answer |
| `activity_lookup_coverage` | each trip day | no non-error `get_activities_by_date_tool` / `filter_activities_by_interest_tool` call for that day |
| `calculator_total` | the run (plans with ≥ 1 activity) | the plan's `total_cost` isn't the result of a calculator call whose numbers are exactly the plan's prices (`no_calculator` / `total_not_from_calculator` / `wrong_price_list`) |
| `verified_before_final` | the run (accepted final answers) | the accepted plan wasn't checked by `run_evals_tool` with `EVALS PASSED` (`never_ran_evals` / `last_evals_failed` / `plan_changed_after_evals`) |
| `tool_efficiency` | each lookup call | it repeats an earlier identical (tool, arguments) lookup (`redundant`); `counts` also records `error_steps` |

Notes:
- "Before the final answer" = before the step that was **accepted** (guardrail rejections don't count).
- `calculator_total` compares the calculator expression's numbers as a multiset with the plan's
  prices – that catches B2's bookkeeping error (6 prices summed for a 7-activity plan) even when the
  run later passes by luck. Empty plans (g07) are not applicable.
- `verified_before_final` compares plans as canonical JSON (sorted keys).
- Runs without a plan fail the plan-dependent checks (B0 rule); `tool_efficiency` judges every run
  (`needs_plan=False`).

### 4. Thought↔action judge (`thought_action_consistency`, `prompts/judges/thought_action/v1.md`)
- **One call per run** with the condensed trajectory: for each step its THOUGHT, ACTION (tool +
  arguments, long plans abbreviated) and the previous OBSERVATION (truncated).
- Per step verdict: `consistent` / `inconsistent` + a short reason. Inconsistent = the action doesn't
  do what the thought says, **or** the thought misstates the previous observation (e.g. "evals
  passed" after `EVALS FAILED`).
- Unit = step with a parsed action. Fails closed. `gpt-4.1`, JSON mode.

### 5. Judge calibration (both judges, like B1)
Two small, immutable, versioned human-label sets under `evals/datasets/calibration/`:

| Set | Items | Built from | Agreement metrics (trust bar) |
|---|---|---|---|
| `relevancy/v1.0.0` | ~20 (plan, traveler) pairs, human score 1–5 | stored live runs, chosen to cover all score levels | within-1 agreement, quadratic weighted kappa |
| `thought_action/v1.0.0` | ~30 steps, consistent / inconsistent | stored live runs + a few **synthetic** inconsistent steps (thought and action deliberately mismatched) | precision, recall, kappa (inconsistent = positive class) |

Labels: I draft them with a written justification per item, **you review and correct** (you are the
human of record). `scripts/build_*_calibration.py` provenance scripts, as in B1.

### 6. B3 metrics (`RelevancyMetrics` + `ReasoningMetrics` in `metrics.py`, `summary.b3`)

| Metric | Denominator |
|---|---|
| Mean traveler relevancy score, and **relevant rate** (score ≥ 4) | travelers in produced plans |
| Interest coverage (labeled) | coverable travelers |
| Interest match rate | planned activities |
| Weather / activity lookup coverage | trip days |
| **Calculator-total faithfulness** | plans with activities |
| **Verified-before-final rate** | accepted final answers |
| **Faithfulness rate** (both of the above hold) | accepted final answers with activities |
| Thought↔action inconsistency rate | judged steps |
| **Redundant-call rate**; error-step rate | lookup calls; steps |

Report: "B3 – Relevancy & reasoning" section with the worst examples; `compare` gets B3 rows.

### 7. Thresholds `[b3]` – values set after measurement (as in B1/B2)
Candidates: `min_relevant_rate`, `min_interest_coverage`, `min_weather_lookup_coverage`,
`min_calculator_total_faithfulness`, `min_verified_before_final_rate`,
`max_thought_action_inconsistency_rate`, `max_redundant_call_rate`, plus judge trust bars
(`min_relevancy_judge_weighted_kappa`, `min_thought_action_judge_recall`).

### 8. Production-signal contract (`RelevancySignal`, `schema_version "b3.v1"`)
Code graders on every run ($0): coverage, match, lookup coverage, calculator-total and
verified-before-final flags, redundant / error step counts. Both judges on the **10% sample**
(like B1), fields null when not sampled. Spec appended to `production-signal.md`.

### Cost estimate (approval needed, Q6)
| Item | Calls | Est. |
|---|---|---|
| Relevancy judge – 36 live + 12 B0 runs (plans only: 28 + 8) | 36 | ~$0.40 |
| Thought↔action judge – 48 runs (~8k tokens each) | 48 | ~$1.20 |
| Calibration – both judges | ~2 runs | ~$0.15 |
| **Total** | | **~$1.75** (cap $3) |

Only the two new judges are recorded (Design §1); B1/B2 replay for free.

---

## Steps

### Step 1 – Per-judge grading cassettes
**Purpose:** record new judges without touching existing ones.
**Output:** one cassette per LLM grader in `harness/runner.py`; `--record-graders` on
`run_experiment.py` and `grade_runs.py`; tests proving B1 replays byte-identically.
**Depends on:** Phase 8 grading framework.

### Step 2 – Relevancy code graders
**Purpose:** label-aware interest coverage and interest match.
**Output:** `agentsville/graders/relevancy.py` (`interest_coverage_labeled`, `interest_match`).
**Depends on:** Phase 9 `GradingContext`.

### Step 3 – Trajectory code graders
**Purpose:** procedure adherence, faithfulness and efficiency, $0.
**Output:** `agentsville/graders/trajectory.py` (five graders, §3).
**Depends on:** none beyond the grading framework.

### Step 4 – Relevancy judge + calibration
**Purpose:** a trustworthy per-traveler relevancy score.
**Output:** `prompts/judges/traveler_relevancy/v1.md`; `traveler_relevancy` grader; calibration set
`relevancy/v1.0.0` (labels you review); ordinal agreement in `harness/calibration.py`; recorded
calibration report.
**Depends on:** Step 1.

### Step 5 – Thought↔action judge + calibration
**Purpose:** catch thoughts and actions that disagree.
**Output:** `prompts/judges/thought_action/v1.md`; `thought_action_consistency` grader; calibration
set `thought_action/v1.0.0` (labels you review); recorded calibration report.
**Depends on:** Step 1.

### Step 6 – B3 metrics and report
**Purpose:** the B3 numbers with confidence intervals.
**Output:** `RelevancyMetrics` / `ReasoningMetrics` (`summary.b3`); report section; compare rows.
**Depends on:** Steps 2–5.

### Step 7 – First B3 measurement (~$1.75)
**Purpose:** real numbers.
**Output:** code graders on the 36 live runs and the B0 recording ($0); record only the two new
judges (`--record-graders`); refresh B0 expected results and commit the new B0 grading cassettes;
`plan/10-b3-relevancy-reasoning/b3-findings.md`.
**Depends on:** Step 6.

### Step 8 – Thresholds
**Purpose:** pass/fail for B3.
**Output:** `[b3]` in `evals/thresholds.toml` (values from Step 7, which you confirm); getters in
`harness/thresholds.py`.
**Depends on:** Step 7.

### Step 9 – Production-signal contract
**Purpose:** C2 can chart relevancy and reasoning quality.
**Output:** `RelevancySignal` + `relevancy_signal()` in `graders/signals.py`; `production-signal.md`.
**Depends on:** Steps 2–5.

### Step 10 – Tests (Layer A)
**Purpose:** graders, judges (with fakes), metrics and cassettes are trustworthy.
**Output:** `tests/test_relevancy.py`, `tests/test_trajectory.py`; fake-judge replies in
`tests/harness_fakes.py`. Written alongside each step, completed here.
**Depends on:** Steps 1–9.

| Area | Cases |
|---|---|
| per-judge cassettes | new judge records to its own file; B1 cassette untouched; `--record-graders` records only the named judges |
| interest_coverage_labeled | uncoverable traveler excluded; coverable uncovered → fail; no case → not applicable |
| interest_match | outside-interest activity counted |
| weather / activity lookup coverage | missing day; error observation doesn't count; lookup after the final answer doesn't count |
| calculator_total | correct; 6 prices for 7 activities → `wrong_price_list`; no calculator; empty plan → not applicable |
| verified_before_final | passed then submitted; plan changed after evals; last evals failed; never ran evals |
| tool_efficiency | identical repeat → redundant; same tool, different args → not redundant |
| judges | score parsing, fail closed, abbreviated trajectory input, one call per run |
| calibration | within-1, weighted kappa known values |
| metrics / signal | rates use the right denominators; judge fields null when not sampled |

### Step 11 – Documentation
**Purpose:** keep `CLAUDE.md` and README accurate.
**Output:** `CLAUDE.md` (per-judge cassettes, `--record-graders`, B3 graders and judges, `summary.b3`),
README (B3 report section).
**Depends on:** Steps 1–10.

---

## Verification (definition of done)

```bash
ruff check . && pytest
python scripts/run_experiment.py --check-expected --check-thresholds          # CI path, $0
python scripts/grade_runs.py experiments/live-v1-r3 --mode replay --check-thresholds
python scripts/calibrate_judge.py --check-expected                            # all three judges
```
Plus green CI, B1/B2 numbers unchanged, and `b3-findings.md` reviewed together.

---

## Questions for you

| # | Question | My recommendation |
|---|---|---|
| Q1 | Keep golden **v1.0.0** (`uncoverable_travelers` labels already cover B3)? | **Yes** – comparability with B0–B2 |
| Q2 | Per-judge grading cassettes + `--record-graders` (Design §1), rather than a "record only missing" cassette mode? | **Yes** – each judge versioned and re-recorded independently; B1 stays byte-identical |
| Q3 | Relevancy judge sees **all available activities per day**, so it scores relative to what was possible? | **Yes** – otherwise it punishes the agent for gaps in the data (Tess's theatre) |
| Q4 | Thought↔action judge: **one call per run** (all steps) rather than one per step? | **Yes** – ~13× fewer calls; per-step verdicts still come back |
| Q5 | Calibration labels: I draft with justifications, you review and correct? Sizes ~20 relevancy pairs, ~30 steps? | Yes |
| Q6 | Approve the LLM spend: ~$1.75, hard cap $3? | Yes |
| Q7 | B3 stays **measure-only**; fixes (e.g. auto-computed `total_cost`) go to B4? | **Yes** – same reasoning as B2 Q4 |
| Q8 | Set `[b3]` threshold values after the measurement? | Yes |
| Q9 | One commit for the phase; may I create branch `feature/phase-10-b3-relevancy-reasoning` from `main`? | Yes |

---

## Implementation notes (changes from this plan, all reviewed during the phase)

| Planned | Done | Why |
|---|---|---|
| `calculator_total`: calculator numbers = the plan's prices (multiset) | a calculator call returned exactly `total_cost` **and** it equals the real price sum; the detail lists missing/extra prices | a multiset rule wrongly fails correct expressions like `2*20 + …` |
| judges registered in Steps 4–5 | defined and calibrated in Steps 4–5, **registered in Step 7** together with their cassettes | registering earlier makes every replay (CI) miss a cassette |
| relevancy judge returns a 1–5 score (prompt v1) | **v2: the LLM returns per-day `possible` facts, code verifies them and scores** with the approved rule; the judge sees every trip day | v1 calibrated at weighted κ 0.51 (scale compression, over-counting, weather errors); v2 25/25 |
| labeling rule "2 = served on a minority of days" | "2 = served on fewer than a third of possible days" | the only threshold reproducing all 25 approved labels |
| – | a served day always counts as possible (`score_from_days`) | bug found on fresh live data (g09 r1 Ben 1 → 4); calibration unchanged |
| thought↔action judge to the B1 recall bar (0.90) | accepted at recall 0.83 / precision 0.94 (owner decision); its rate is a lower bound | – |
| observations truncated for the judge | tool data rendered compactly but completely (`compact_observation`) | truncation hid the evidence for "misreads the observation" |
| one `summary.b3` | `summary.b3_relevancy` + `summary.b3_reasoning` | the two halves can be missing independently |
| judge trust bars via the existing `calibration` argument | `check_thresholds(..., judge_reports=committed_judge_reports())` | B1 getters stay unchanged |

Spend: ~$0.93 of the $3 cap.
