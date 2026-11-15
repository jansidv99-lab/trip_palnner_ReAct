# Phase 7 – B0 Foundation: harness, golden dataset v1.0.0, record/replay

> Status: **APPROVED** – all recommendations accepted (Q1 12 cases, Q2 commit cassettes, Q3 conservative scoring, Q4 4 workers, Q5 CI informational until B4, Q6 repeats 1/3/5, Q7 branch renamed, Q8 one commit)
> Branch: `feature/phase-7-b0-foundation` (renamed from `docs/master-plan-v4`; also carries the master plan v4 commit)
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md) (v4, Phase 7)
> Depends on: Phase 4 (graders), Phase 6 (`ItineraryAgent`, `AgentRun`) ✅

## Purpose

**Question (goal.md B0):** *can we run a repeatable experiment and get comparable numbers?*

So far we've judged the agent from single runs ("this one passed 9/9"). One LLM run proves very
little: the next run may differ. B0 builds the **measurement instrument** every later slice uses:

1. A **golden dataset** (v1.0.0): a fixed, versioned, labeled set of trip requests.
2. An **experiment harness**: run the agent over the dataset N times with a fixed configuration, grade every run, store everything.
3. **Record/replay**: capture every LLM response once, then re-run the whole experiment **without calling the LLM**. It's deterministic, free and needs no secret, so CI can do it.
4. **Metrics and reports**: pass rates with confidence intervals, cost, steps, latency; plus a comparison of two experiments that refuses to compare apples with oranges.
5. A **CI replay job** that proves repeatability on every PR.

B0 adds **no new graders**. It uses the 9 from Phase 4 and stores golden labels for B1–B3 to use.

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Golden dataset** | Curated inputs + labels that define "the exam". Every experiment on the same version answers the same questions, so results are comparable. |
| **Versioning & immutability** | `v1.0.0` never changes after release. A fix or new case becomes `v1.1.0` (new cases) or `v2.0.0` (changed meaning). A **content hash** in `manifest.json` detects accidental edits. |
| **Labels** | Human judgments attached to a case (for example "outdoor-only activity X is unsuitable on 06-13"). Graders compare agent output against them. Labels must be **unambiguous**: unclear cases are marked as such, not guessed. |
| **Data fingerprint** | A hash of `data/data.py` stored in the manifest. Labels are only valid for the exact data they were written against. |
| **Experiment config** | Everything that can change results: dataset version, model, prompt version, temperature, repeats, max steps. Results are only comparable when the configs say so. |
| **Record/replay (VCR pattern)** | In *record* mode every LLM request/response is saved to a **cassette**. In *replay* mode the same requests are answered from the cassette. A request that isn't in the cassette is an error, which tells you the code or prompt changed and you need to re-record. |
| **Cassette key** | `sha256` of the canonical request (model, messages, temperature, json_mode). Identical requests get the same key, and repeats are kept apart by storing each (case, repeat) in its own cassette. |
| **Repeats** | Running the same case several times exposes randomness. B4 turns this into pass@k / pass^k. |
| **Wilson score interval** | A 95% confidence interval for a pass rate that behaves well with small samples (for example 11/12 → 0.65–0.99). Two experiments whose intervals overlap heavily are *not* clearly different. |
| **Conservative scoring** | A run that never produced a plan (step limit, LLM error) counts as **failed** for every error-severity grader, so a crashing agent can't look good. |

---

## Design

### 1. Golden dataset v1.0.0

```
evals/datasets/golden/v1.0.0/
  cases.jsonl     one GoldenCase per line
  manifest.json   name, version, created, case_count, cases_sha256, data_fingerprint
  CHANGELOG.md    what this version contains and why
```

```python
class GoldenLabels(BaseModel):
    must_avoid_activity_ids: list[str] = []   # clearly unsuitable for the weather (outdoor-only on inclement days)
    ambiguous_activity_ids: list[str] = []    # excluded from weather labels (e.g. morning event before an afternoon storm, D2)
    uncoverable_travelers: list[str] = []     # no weather-suitable activity matches their interests (e.g. theatre, D6/D9)
    max_affordable_activities: int | None = None   # for budget-pressure cases
    expected_behavior: str                    # one sentence, e.g. "empty or near-empty plan, no overspend"

class GoldenCase(BaseModel):
    case_id: str                  # "g01-sample-yuri-hiro"
    tags: list[str]               # ["baseline"], ["budget"], ["weather"], …
    description: str
    vacation_info: VacationInfo
    labels: GoldenLabels
```

**Proposed cases (Q1):** labels are drafted from data review D1–D10, and **you review them before release**.

| ID | Case | Dates | Tests |
|---|---|---|---|
| g01 | Yuri + Hiro (= `sample_plan.json`) | 06-10 → 12, budget 130 | baseline, storm day |
| g02 | Same, tight budget 40 | 06-10 → 12 | budget pressure (≤ 2 activities) |
| g03 | Mika: hiking/photography/sports | 06-12 → 14, 150 | all matches outdoor in rain (D9) |
| g04 | Tess: theatre only + a tech fan | 06-10 → 12, 130 | uncoverable interest (D6) |
| g05 | One-day sunny trip | 06-15 → 15, 60 | shortest trip, outdoor allowed |
| g06 | Family of 4, mixed interests | 06-10 → 15, 300 | full window, coverage across many travelers |
| g07 | Infeasible budget 10 | 06-10 → 11 | nothing affordable: expect an empty plan, no overspend |
| g08 | Solo tech enthusiast | 06-10 → 12, 100 | narrow interest, easy coverage |
| g09 | Group of 6, diverse interests | 06-11 → 12, 200 | many travelers, coverage tradeoffs |
| g10 | Outdoor lover on fair-weather days | 06-10 → 11, 100 | outdoor activities *should* be chosen |
| g11 | Storm day only | 06-12 → 12, 50 | single inclement day, indoor/fallback choice |
| g12 | Generous budget 1000 | 06-11 → 13, 1000 | no budget pressure: overlaps / over-planning |

`must_avoid` draft (outdoor-only on inclement days): `06-12-2`, `06-13-1`, `06-13-2`, `06-13-3`, `06-14-0`, `06-14-1`, `06-14-2`.
`ambiguous`: `06-12-0` (08:00–10:00, before the afternoon storm, D2).
*Not* must-avoid: `06-12-1` (rain fallback, D4) and `06-14-3` (indoors, D5).

- `agentsville/harness/dataset.py`: `load_golden(version)` validates every line, recomputes `cases_sha256` and the current data fingerprint, and **refuses to load** on a mismatch (immutability is enforced in code, not only by convention).
- `scripts/build_golden_dataset.py`: writes v1.0.0 from Python definitions and computes the manifest. It's kept for provenance and never re-run for an existing version.

### 2. Record/replay (`agentsville/harness/recording.py`)

```python
class CassetteLLM:                        # has the same chat() as LLMClient, so the agent can't tell the difference
    def __init__(self, mode: Literal["live", "record", "replay"], cassette: Path, llm: LLMClient | None)
    def chat(self, messages, model=None, temperature=0.0, json_mode=False) -> LLMResponse
```

| Mode | Behavior |
|---|---|
| `live` | call the real LLM, store nothing (exploration) |
| `record` | call the real LLM and append `{key, occurrence, response, request_summary}` to the cassette |
| `replay` | answer from the cassette, **never** touch the network; a missing key raises `CassetteMissError` naming the request |

- **Key:** `sha256(json.dumps({model, messages, temperature, json_mode}, sort_keys=True))`.
- **Occurrence counter:** the same request can legitimately happen twice in one run (the judge asked about the same activity in `run_evals_tool` and again in the final evals). Responses are stored per key in order and replayed in order.
- **One cassette per (case, repeat):** `evals/cassettes/golden-v1.0.0/<config_id>/<case_id>/r<n>.jsonl`, where `config_id` is, for example, `gpt-4o-mini__v1__t0`. Repeats don't collide, and record mode with parallel workers never writes to the same file.
- **Everything goes through it:** the agent's calls *and* the judge calls (the agent passes its `llm` to the evals), so a replayed run is complete.
- Recorded latency, tokens and cost are replayed too, so replayed metrics equal the recorded ones.

### 3. Experiment runner (`agentsville/harness/runner.py`)

```python
class ExperimentConfig(BaseModel):
    dataset_version: str = "v1.0.0"
    model: str = "gpt-4o-mini"
    prompt_version: str = "v1"
    temperature: float = 0.0
    repeats: int = 1
    max_steps: int = 20
    include_llm_evals: bool = True
    mode: Literal["live", "record", "replay"] = "replay"
    case_ids: list[str] | None = None      # subset; None = all
    workers: int = 4                        # parallel case runs (threads)

class CaseResult(BaseModel):              # one (case, repeat)
    case_id: str; repeat: int; stop_reason: str
    eval_results: dict[str, bool] | None  # grader name → passed (None = no plan)
    eval_passed: bool                     # conservative: False when there's no plan
    steps: int; cost_usd: float; latency_ms: float; judge_calls: int

def run_experiment(config, out_dir) -> ExperimentSummary
```

- For each (case, repeat): build a `CassetteLLM` for that cassette, then `ItineraryAgent(llm=…, model, prompt_version, max_steps, include_llm_evals, log_path=None)`, run it, and turn the `AgentRun` into a `CaseResult`.
- Runs execute in a thread pool (`workers`): a live experiment of 12 cases takes roughly 4 minutes instead of 15.
- Outputs go to `experiments/<timestamp>__<config_id>/` (git-ignored): `config.json`, `runs.jsonl` (full `AgentRun`s), `results.jsonl`, `summary.json`, `report.md`.

### 4. Metrics (`agentsville/harness/metrics.py`)

| Metric | Definition |
|---|---|
| **Goal completion rate** | runs with `stop_reason == "final_answer"` **and** all error graders passing ÷ runs |
| **Pass rate per grader** | runs where that grader passed ÷ **all** runs (no plan = fail), with a **Wilson 95% CI** |
| Plan rate | runs that produced a plan ÷ runs |
| Stop-reason mix | counts of `final_answer` / `max_steps` / `llm_error` |
| Cost / steps / latency | mean, p50, p95 per run; total cost |
| Per-case table | pass rate per case across repeats (shows *which* cases are hard) |

### 5. Reports (`agentsville/harness/report.py`)
- `report.md`: config + dataset (version and hash), headline metrics, a per-grader table with CIs, a per-case table, and a list of failing runs with their eval-summary lines.
- **Compare** (`compare_experiments.py A B`): a delta per metric, marking a difference as *likely real* only when the Wilson intervals don't overlap. It **refuses** (unless `--force`) when the dataset version or hash differs, because those numbers aren't comparable.

### 6. CI replay job (`.github/workflows/eval-gate.yml`)
- Triggers: PRs and pushes to `main` that touch `agentsville/`, `prompts/`, `evals/` or the workflow.
- Job `eval-replay`: install deps → `run_experiment.py --mode replay` on the committed cassettes → **check that the replayed results equal `expected_results.jsonl`** saved next to the cassettes at record time. That check *is* B0's question: same inputs → same numbers. The report is uploaded as an artifact.
- No secret, no LLM cost. **Not a required check yet**: B4 adds thresholds and makes it required.
- If a PR changes the prompt or agent code, the requests change and the replay fails with `CassetteMissError`. The fix is to **re-record** (about $0.20) and commit the new cassettes. This is the intended VCR behavior: an outdated recording can't silently pass.

---

## Steps

### Step 1 – Golden dataset schema and loader
**Purpose:** a versioned, tamper-evident dataset format.
**Output:** `agentsville/harness/__init__.py`, `agentsville/harness/dataset.py` (`GoldenLabels`, `GoldenCase`, `DatasetManifest`, `load_golden`, `data_fingerprint`).
**Depends on:** Phase 2 models.

### Step 2 – Golden dataset v1.0.0 (you review the labels)
**Purpose:** the "exam" every experiment takes.
**Output:** `scripts/build_golden_dataset.py`; `evals/datasets/golden/v1.0.0/{cases.jsonl, manifest.json, CHANGELOG.md}`.
**Depends on:** Step 1, data review D1–D10.
**Review gate:** I'll show you the 12 cases and their labels; the dataset is released only after your OK.

### Step 3 – Record/replay
**Purpose:** deterministic, free, secret-free re-runs.
**Output:** `agentsville/harness/recording.py` (`CassetteLLM`, `CassetteMissError`, `request_key`).
**Depends on:** Phase 0 `LLMClient`.

### Step 4 – Experiment runner
**Purpose:** dataset × config × repeats → graded, stored results.
**Output:** `agentsville/harness/runner.py` (`ExperimentConfig`, `CaseResult`, `run_experiment`).
**Depends on:** Steps 1–3, Phase 6 agent.

### Step 5 – Metrics
**Purpose:** turn results into comparable numbers with uncertainty.
**Output:** `agentsville/harness/metrics.py` (`wilson_interval`, `summarize` → `ExperimentSummary`).
**Depends on:** Step 4.

### Step 6 – Reports and comparison
**Purpose:** a readable report, and safe comparisons.
**Output:** `agentsville/harness/report.py`; `scripts/run_experiment.py`, `scripts/compare_experiments.py`; `experiments/` in `.gitignore`.
**Depends on:** Steps 4–5.

### Step 7 – First recorded experiment
**Purpose:** real baseline numbers, and the cassettes CI will replay.
**Output:** `evals/cassettes/golden-v1.0.0/gpt-4o-mini__v1__t0/…` (12 cases × 1 repeat, ~0.5 MB) + `expected_results.jsonl`; the first `report.md` shown to you.
**Depends on:** Steps 2–6. **Cost:** about $0.20 and ~4 minutes. A local 3-repeat run (about $0.60) shows the variance, but isn't committed.

### Step 8 – CI replay job
**Purpose:** prove repeatability on every relevant PR.
**Output:** `.github/workflows/eval-gate.yml`.
**Depends on:** Step 7.

### Step 9 – Tests (Layer A)
**Purpose:** the harness itself must be trustworthy.
**Output:** `tests/test_harness_dataset.py`, `tests/test_recording.py`, `tests/test_runner.py`, `tests/test_metrics.py`.
**Depends on:** Steps 1–6.

| Area | Cases |
|---|---|
| Dataset | v1.0.0 loads (12 cases, all valid `VacationInfo`); a tampered line → hash error; a changed data fingerprint → error; duplicate `case_id` → error; every labeled activity ID exists in `data_api` |
| Recording | record then replay returns identical responses; a replay miss raises with the request summary; the same request twice → second response replayed second; different cassettes don't mix; `live` mode writes nothing |
| Runner | with a scripted fake LLM in record mode, then replay: identical `CaseResult`s; a run without a plan → `eval_passed=False`; repeats create separate cassettes; `case_ids` subset respected |
| Metrics | Wilson interval known values (0/10, 5/10, 10/10, 11/12); goal-completion and per-grader rates; p50/p95; stop-reason mix |
| Report/compare | report contains config, dataset hash and grader table; compare refuses different dataset hashes; overlapping intervals → "not clearly different" |

### Step 10 – Documentation
**Purpose:** keep `CLAUDE.md` and README accurate.
**Output:** `CLAUDE.md` (harness architecture, record/replay rules, how to re-record, dataset immutability); README "Experiments" section.
**Depends on:** Steps 1–9.

---

## Verification (definition of done)

```bash
ruff check .
pytest                                                     # incl. harness tests (fakes, no network)
python scripts/run_experiment.py --mode record             # Step 7: ~$0.20, writes cassettes + report
python scripts/run_experiment.py --mode replay             # zero LLM calls, identical results
python scripts/compare_experiments.py <exp-A> <exp-B>      # replay vs record: no differences
```
Plus the green `CI / eval-replay` job on the PR, and the first experiment report reviewed together.

---

## Decisions (all recommendations accepted)

| # | Question | My recommendation |
|---|---|---|
| Q1 | The 12 golden cases above: OK as a start (you review the final labels in Step 2)? | Yes |
| Q2 | Commit cassettes to git (12 cases × 1 repeat, ~0.5 MB) so CI replays for free? | **Yes.** Re-recorded only when the prompt or agent changes |
| Q3 | Conservative scoring: a run without a plan fails every error grader? | **Yes.** A crash must never look good |
| Q4 | Parallel workers default 4 (threads)? | **4.** About 4× faster, still gentle on the proxy |
| Q5 | CI replay job informational now, **required** in B4? | Yes |
| Q6 | Repeats: 1 committed (CI), 3 for local variance checks; 5 for B4 baselines? | Yes |
| Q7 | You asked for this phase on `docs/master-plan-v4`. Since it now contains code, rename it to `feature/phase-7-b0-foundation` (`git branch -m`, local only, before you push)? | **Rename.** The branch name then describes the PR; it's optional |
| Q8 | One commit for the phase (on top of the master-plan commit)? | Yes |
