# Master Plan – AgentsVille Trip Planner (ReAct)

> Status: **v4 – awaiting review** (v3 approved; Phases 0–6 done)
> Branch: `docs/master-plan-v4`
> Source of requirements: [`goal.md`](../../goal.md)

This document is the map for the whole project. It defines the phases, their order, what each one
delivers, and how they depend on each other. It does **not** contain code. Each phase gets its own
detailed plan in its own `plan/NN-<topic>/` folder, written and reviewed before any code for that phase.

**Change history**
- v2: CI and CD split into two separate phases, both independent of the UI phase.
- v3:
  - **Evals come before tools**, so `run_evals_tool` can be built with the other tools.
  - **CI moves right after Foundations.**
  - **AI QA is split by layer:**
    - Layer A (deterministic tests) is written in every phase and run by CI.
    - Layer B (offline evals) becomes its own phase right after the agent.
    - Layer C (drift) starts collecting traces when the agent is built, and becomes a monitoring phase after CD.
- v3 approved with decisions Q1–Q5 (see section 7).
- v4: `goal.md` §8 now defines the **AI Quality Assurance Platform** as Layer B **scenario slices B0–B5**
  and Layer C pieces **C1–C3**. Old phases 7–11 are replaced by phases **7–18**:
  - Layer B runs **offline first**: B0 → B1 → B2 → B3 → B4 (decision Q6).
  - Then UI → CD → C1 → C2 → C3 → B5.
  - Phases 0–6 are done and unchanged.

---

## 1. What we are building (in one paragraph)

A traveler describes a trip: who's going, their interests, dates, and budget. An **ItineraryAgent**
then builds a day-by-day plan for the fictional city of AgentsVille. It doesn't answer in one shot.
It works in a **ReAct loop**: it *thinks*, calls a *tool* (for example "what's the weather on
06-12?"), reads the *observation*, and repeats until it's confident. Then it calls
`final_answer_tool` with a structured `TravelPlan`. The plan is checked by **evals**: some are
deterministic Python checks, and one uses an LLM as a judge. A **Streamlit UI** wraps it all. The
app is tested in CI, deployed through CD to the existing GCP project, and monitored for quality and
cost over time. Quality is owned by an **AI QA platform**: deterministic tests (Layer A), offline
probabilistic evals on a versioned golden dataset (Layer B), and production metrics, drift alerts and
a feedback loop back into the dataset (Layer C).

---

## 2. Key concepts (short primer)

| Concept | What it means here |
|---|---|
| **Pydantic model** | A Python class that validates data on creation. Bad input (for example departure before arrival) raises a clear error instead of flowing silently into the agent. |
| **Mock API** | `data/data.py` stands in for real weather and activity services. We wrap it in functions that *look* like API calls, so later swapping in a real API changes nothing else. |
| **Eval** | A function that scores an itinerary against one criterion (right city? within budget? no invented activities?). |
| **LLM-as-judge** | An eval where a second LLM call makes a judgment Python can't easily make, such as "is this outdoor tennis event a bad idea in a thunderstorm?" |
| **Tool** | A plain Python function the LLM is allowed to request by name with arguments. The LLM never runs code itself. It *asks*, and our code runs the function. |
| **ReAct** | Reason + Act. Each turn the LLM writes a `THOUGHT` (reasoning) and an `ACTION` (one tool call). Our code runs the tool and replies with an `OBSERVATION`. This repeats until `final_answer_tool`. |
| **CI (Continuous Integration)** | Every push or PR is automatically linted and tested, so broken code is caught before merge. |
| **CD (Continuous Delivery/Deployment)** | Every merge to `main` automatically builds an image and deploys it, so releases are repeatable. |
| **Golden dataset** | A fixed, versioned set of trip requests with labels (what a good plan must or must not do). Experiments are only comparable when they use the same dataset version. |
| **Grader** | A function that scores one aspect of an agent run: code graders (pure Python) or model graders (LLM judge). Our Phase 4 evals are the first graders. |
| **Harness** | The machinery that runs the agent over a dataset N times, applies graders, and aggregates the numbers into a comparable report. |
| **Record/replay** | Recording every LLM request/response once ("cassettes") and replaying them later: deterministic, free and secret-free. That's how CI can run the harness. |
| **Regression gate** | An automatic check that fails when quality drops below thresholds or falls versus a committed baseline. It blocks merges and deploys. |
| **Drift** | Quality or cost slowly changing over time (new model version, prompt edits). We detect it by tracking eval pass rates and metrics across runs, compared to a baseline. |

---

## 3. Current state (after Phase 6)

| Item | Status |
|---|---|
| Phase 0–1: package layout, config, `LLMClient`, pytest/ruff, CI (`lint`, `test`) with branch protection | ✅ done |
| Phase 2–3: validated `VacationInfo`, samples, `data_api` mock API, data review (D1–D10) | ✅ done |
| Phase 4: 9 graders in `evals.py` (8 deterministic + `gpt-4.1` weather judge), `EvalReport` | ✅ done |
| Phase 5: 7 tools + `ToolRegistry` (never raises, JSON observations) | ✅ done |
| Phase 6: ReAct agent (JSON-mode replies, guardrail, prompt v1), `AgentRun` trace, `logs/agent_runs.jsonl` | ✅ done |
| AI QA platform (Layer B harness/slices, Layer C production), UI, CD | ❌ phases 7–17 |

---

## 4. Phase overview

```
DONE    0 Foundations ─► 1 CI ═══════════ (Layer A: checks every later phase)
        2 Vacation details ─┐
        3 Data access ──────┴─► 4 Evals ─► 5 Tools ─► 6 ReAct agent (+ run log)
                                                              │
LAYER B (offline first)                                       ▼
        7 B0 Foundation: harness · golden v1.0.0 · record/replay
        8 B1 Hallucination & grounding
        9 B2 Constraint compliance & goal completion
       10 B3 Relevancy & reasoning verification
       11 B4 Consistency · regression gating · eval-driven improvement (prompt v2)
                                                              │
PRODUCT & LAYER C                                             ▼
       12 Streamlit UI (+ feedback capture) ─► 13 CD → Cloud Run (gated by B4)
       14 C1 Structured logging + BigQuery sink
       15 C2 Log-based metrics + dashboard
       16 C3 Alert policies
       17 B5 Production feedback loop & dataset lifecycle (golden v1.1.0)
       18 Traveler feedback agent (next stage)
```

| # | Phase | Plan folder | Depends on | Question it answers / main deliverable |
|---|---|---|---|---|
| 0–6 | *(done, see §5)* | `plan/00-…` to `plan/06-…` | – | – |
| 7 | **B0 – Foundation** | `plan/07-b0-foundation/` | 6 | Can we run a repeatable experiment and get comparable numbers? Golden v1.0.0, harness, record/replay, report, CI replay smoke |
| 8 | **B1 – Hallucination & grounding** | `plan/08-b1-grounding/` | 7 | Is everything in the plan real? |
| 9 | **B2 – Constraint compliance & goal completion** | `plan/09-b2-constraints/` | 7 | Does the plan satisfy the traveler's hard constraints? |
| 10 | **B3 – Relevancy & reasoning verification** | `plan/10-b3-relevancy-reasoning/` | 7 | Is the plan relevant, and is its reasoning faithful to the output? |
| 11 | **B4 – Consistency, regression gating & eval-driven improvement** | `plan/11-b4-regression-gating/` | 8–10 | Is quality stable, and does a change actually improve it? |
| 12 | **Streamlit UI** | `plan/12-streamlit-ui/` | 6 | `app.py` + feedback capture |
| 13 | **CD → Cloud Run** | `plan/13-cd/` | 1, 11, 12 | Repeatable, gated deploys |
| 14 | **C1 – Structured logging + BigQuery** | `plan/14-c1-logging-bigquery/` | 13 | Can we query production? (needed by B5) |
| 15 | **C2 – Log-based metrics + dashboard** | `plan/15-c2-metrics-dashboard/` | 9, 14 | How is production doing? (goal: after B2) |
| 16 | **C3 – Alert policies** | `plan/16-c3-alerts/` | 11, 15 | Are we told when it degrades? (goal: after B4) |
| 17 | **B5 – Production feedback loop & dataset lifecycle** | `plan/17-b5-feedback-loop/` | 12, 14 | How does production traffic make the evals better? |
| 18 | Traveler feedback agent | `plan/18-feedback-agent/` | 11 | Next stage per `goal.md` |

**Where each AI QA layer lives**

| Layer | Where |
|---|---|
| A – Deterministic testing (minimal) | Tests in **every** phase, run by **CI (Phase 1)**. Harness code gets unit tests with fakes. |
| B – Probabilistic evals (**main**) | Graders from Phase 4 → harness **B0 (7)** → slices **B1–B4 (8–11)** → feedback loop **B5 (17)** |
| C – System metrics & drift (**main**) | Run log from Phase 6 → **C1 (14)** logging/BigQuery → **C2 (15)** dashboard → **C3 (16)** alerts |

**Competencies (`goal.md` §8)**

| Competency | Delivered in |
|---|---|
| Evaluation harnesses: hallucination rate, answer relevancy | 7 (harness), 8 (hallucination rate), 10 (relevancy) |
| Agentic / reasoning validation | 9 (goal completion), 10 (trajectory and faithfulness) |
| Versioned golden datasets | 7 (v1.0.0), 17 (v1.1.0 lifecycle) |
| Observability & feedback loops | 6 (run log), 12 (feedback capture), 14–16 (C1–C3), 17 (B5) |

---

## 5. Phase details

> Phases 0–6 below keep their **original v3 descriptions**. What was actually built is recorded in each phase plan (`plan/00-foundations/` … `plan/06-itinerary-agent/`) and in `CLAUDE.md`. Notable differences:
> - Phase 6 uses **JSON-mode replies** `{thought, action}` instead of free-text `THOUGHT:/ACTION:`.
> - `AgentRun`/`AgentStep` replaced `PromptTrace`.
> - `gpt-4.1-nano` was dropped (the proxy doesn't serve it).
> - Old references to "Phase 7/10/11" mean today's Phases 7–11 (Layer B), 14–16 (Layer C) and 18 (feedback agent).

### Phase 0 – Foundations
**Purpose:** shared plumbing so later phases don't each reinvent setup.
- `config.py`: read `.env` once (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `MODEL`, `PROMPT_VERSION`, GCP values) and fail early with a clear message if a key is missing.
- `llm.py`: a thin wrapper around the OpenAI client (respects `OPENAI_BASE_URL`). It returns the reply plus latency and token counts, which feed `PromptTrace`.
- One **smoke call** to the LLM, to confirm the key and endpoint work.
- `requirements-dev.txt` with `pytest` and `ruff`; a first smoke test that imports `models` and `data`.
- **Decide the project layout (Q5):** flat files vs an `agentsville/` package, with a pros/cons comparison. A flat-file starting point:
  ```
  models.py   config.py   llm.py
  data_api.py  evals.py   tools.py   agent.py
  prompts/    app.py      tests/
  ```

**Learning focus:** environment-based configuration, why the LLM call is wrapped behind one function.

### Phase 1 – CI (Continuous Integration)
**Purpose:** every change from here on is checked automatically before merge.
- GitHub Actions workflow on pull requests and pushes to `main`: set up Python → install deps (cached) → `ruff check` → `pytest`.
- Tests that call the LLM are marked `@pytest.mark.llm` and **excluded** from PR runs (they're slow, cost money, and need secrets). They run on demand or nightly later.
- Branch protection on `main`: CI must pass before merge.
- You set up all GitHub-side settings (workflow enablement, branch protection) yourself. I provide the exact steps.

**Learning focus:** what CI guarantees, test markers, why PR checks must be fast and free of side effects.

### Phase 2 – Vacation details
**Purpose:** a validated trip request is the agent's only input, so it must be trustworthy.
- **Step 1, clean up `models.py` comments (Q1):** remove all existing comments (the leftover "Phase 3 – Step 0" / "Phase 5 – B0 …" labels and old-project notes such as "moved out of planner.py"), then add new comments in this plan's `# Phase N – Step M: <purpose>` format.
- Walk through the existing `VacationInfo` / `Traveler` / `Interest` models and their validators.
- Add the extra checks (Q3): dates must fall inside the 2025-06-10 → 06-15 data window, and the destination must be AgentsVille.
- Create sample `VacationInfo` objects (normal, tight budget, rainy days) used by tests, evals, the agent and the Phase 7 eval suite.
- Tests: valid and invalid inputs (Layer A).

**Learning focus:** Pydantic field constraints vs `model_validator`, why we validate at the boundary.

### Phase 3 – Data access & review
**Purpose:** simulate the external APIs and *look* at the data before asking an LLM to reason over it.
- `get_weather(date)` and `get_activities(date)` in mock-API style, plus bulk variants for a date range.
- Convert raw dicts into `Weather` / `Activity` models (this catches data issues early).
- A short review (script or notebook) answering: which days are inclement (06-12 thunderstorm, 06-13 and 06-14 rainy)? Which activities are outdoor? Which interests does each day cover? Price ranges?
- Tests: lookups by date, unknown dates, model conversion (Layer A).

**Learning focus:** separating data access from logic, manual data review as a step before prompting.

### Phase 4 – Evals
**Purpose:** define what "a good itinerary" means **before** building the agent that produces it. Evals are tested now against `sample_plan.json` and deliberately broken plans (wrong city, over budget, invented activity, outdoor event in a thunderstorm).

Required by `goal.md`:
| Eval | Type | Check |
|---|---|---|
| City and dates match | deterministic | `plan.city`, `start_date`, `end_date`, and each day's date match the request |
| Cost accuracy | deterministic | `total_cost == sum(activity.price)`, the plain sum per group, not × travelers (Q4) |
| Within budget | deterministic | `total_cost ≤ budget` |
| No hallucinated activities | deterministic | every `activity_id` exists in `ACTIVITY_CALENDAR` with identical fields |
| Weather suitability | **LLM judge** | for each activity on an inclement day, the judge reads the description and weather and returns OK/NOT OK with a reason |

Suggested extra evals:
| Eval | Type | Why |
|---|---|---|
| Weather in plan matches forecast | deterministic | the agent might copy the wrong day's weather |
| No overlapping activities per day | deterministic | two events at the same time can't both be attended |
| Interest coverage | deterministic | each traveler gets at least one activity matching their interests |
| Minimum activities per day | deterministic | sets up Phase 11 (≥ 2/day) |
| Recommendation reasons are grounded | LLM judge | the reasons mention real interests or weather, not invented facts |

- `run_all_evals(vacation_info, plan)` returns a structured result (passed, failures, per-eval details), so the agent, the eval suite, the UI and monitoring all reuse it.
- Tests: deterministic evals in CI. The LLM-judge eval is marked `llm`.

**Learning focus:** deterministic vs probabilistic checks, designing a judge prompt that returns structured output, test-first thinking for AI.

### Phase 5 – Tools
**Purpose:** give the agent safe, precise capabilities instead of letting it guess.

| Tool | From goal | Purpose |
|---|---|---|
| `calculator_tool` | ✅ | evaluate arithmetic safely (no raw `eval`), so cost totals are exact |
| `get_weather_for_date_tool` | ✅ | weather for one date |
| `get_activities_by_date_tool` | ✅ | activities for one date |
| `run_evals_tool` | ✅ | let the agent self-check a draft plan (wraps Phase 4 `run_all_evals`) |
| `final_answer_tool` | ✅ | submit the `TravelPlan` JSON; signals the loop to stop |
| `get_activity_by_id_tool` | suggested | fetch exact details, so it copies data instead of retyping it |
| `filter_activities_by_interest_tool` | suggested | narrow choices per traveler |

- A **tool registry**: name → function + a text description and argument schema. The agent's tool catalog is generated from it.
- Every tool returns a **string** (the observation) and never raises into the loop. Errors become observations the LLM can react to.
- Tests: each tool's happy path and error path (Layer A).

**Learning focus:** the tool contract (name, args, string result), defensive tool design.

### Phase 6 – ReAct ItineraryAgent
**Purpose:** the core of the project.
- **System prompt** (versioned in `prompts/itinerary/<PROMPT_VERSION>.md`): role, the trip request, the tool catalog (from the registry), the cost rule (`total_cost` = plain sum of activity prices, not × travelers), the turn format, and the instruction to call `run_evals_tool` before `final_answer_tool`.
- **Turn format:** `THOUGHT: …` then `ACTION: {"tool_name": …, "arguments": {…}}`.
- **Parser:** extract and validate the ACTION. If it's malformed, reply with an OBSERVATION explaining the error, so the model can retry.
- **Loop:** call LLM → parse → run tool → append OBSERVATION → repeat. Stop on `final_answer_tool` or when a **max-steps** limit is reached.
- **Final answer:** validate into `TravelPlan` (Pydantic). On failure, return the error as an observation and continue.
- **Tracing:** record every step and a `PromptTrace` (latency, tokens, cost, prompt version, step count, eval result) and **append it to a JSONL log from the first run**. This is the raw material for Phases 7 and 10.
- Tests: the parser and the loop with a **fake LLM** that returns scripted replies (Layer A, no API cost).

**Learning focus:** how an agent loop really works under the hood, prompt versioning, guarding against runaway loops, testing LLM code with fakes.

### Slice anatomy (Layer B slices B1–B4)
Each slice delivers the same six parts (`goal.md`: *golden data → graders → harness run → thresholds → CI → production signal*):
1. **Golden data:** cases + labels for that quality question, added to the versioned dataset.
2. **Graders:** code and/or LLM judge. Every LLM judge is **calibrated** against human labels (agreement measured).
3. **Harness run:** an experiment on the golden dataset, N repeats, producing a report.
4. **Thresholds:** minimum acceptable rates in `evals/thresholds.toml`.
5. **CI:** the slice's checks run in **replay mode** (recorded cassettes): free, deterministic, no secret.
6. **Production-signal contract:** the exact log field/metric Layer C will emit. With the offline-first order (Q6) this is a written spec in B1–B4, made live in C1–C3 and used in B5.

### Phase 7 – B0 Foundation: harness, golden dataset v1.0.0, record/replay
**Question:** can we run a repeatable experiment and get comparable numbers?
- **Golden dataset v1.0.0** (`evals/datasets/golden/v1.0.0/`): about 12–15 cases (normal, tight budget, rainy days, theatre-only, one-day, large group, infeasible budget) with labels (must-avoid activity IDs, achievable interest coverage, expected behavior). It includes `manifest.json` (version, content hash) and `CHANGELOG.md`. A released version is immutable.
- **Harness** (`agentsville/harness/`): `dataset.py` (load/validate/hash), `runner.py` (experiment = dataset version × model × prompt version × N repeats → runs + grader scores), `metrics.py` (pass rate per grader with confidence intervals, cost, steps, latency, stop-reason mix), `report.py` (markdown report; compare two experiments).
- **Record/replay** (`recording.py`): `RecordingLLM` / `ReplayLLM` wrap `LLMClient`. Cassettes are keyed by a hash of (messages, model, params), and a replay miss is an error. Cassettes are committed under `evals/cassettes/`.
- **CI:** `eval-gate.yml` runs a replay smoke experiment on PRs (no secret, no cost).
- Scripts: `run_experiment.py`, `compare_experiments.py`. Outputs go to the git-ignored `experiments/`.

### Phase 8 – B1 Hallucination & grounding
**Question:** is everything in the plan real?
- Graders: activity existence and field fidelity (existing E4), weather fidelity (X1), a **reasons-grounded LLM judge** (each recommendation reason is supported by the activity, the traveler interests or the weather), and **trajectory grounding** (every planned activity appeared in a tool observation during the run).
- Judge calibration vs hand-labeled reasons (precision/recall, agreement).
- Metrics: **hallucination rate** (activity- and plan-level), grounded-reason rate. Production signal: per-run hallucination flags.

### Phase 9 – B2 Constraint compliance & goal completion
**Question:** does the plan satisfy the traveler's hard constraints?
- Graders: city/dates, budget, cost accuracy, overlaps, weather suitability (judge), minimum activities; **goal completion** (finished with `final_answer` and passed evals); expected behavior on **infeasible** cases (budget too small).
- Metrics: per-constraint violation rate, all-constraints-pass rate, goal-completion rate, guardrail-rejection rate. Production signal: per-run constraint results (feeds C2).

### Phase 10 – B3 Relevancy & reasoning verification
**Question:** is the plan relevant to these travelers, and is its step-by-step reasoning faithful to the output?
- **Answer relevancy:** an LLM judge with a 1–5 rubric per traveler, plus interest coverage.
- **Reasoning/trajectory validation:** weather fetched for every day, total computed with the calculator, evals run before the final answer, a thought↔action consistency judge, tool-use efficiency (redundant calls, steps to completion).
- Metrics: relevancy score, faithfulness rate, redundant-call rate.

### Phase 11 – B4 Consistency, regression gating & eval-driven improvement
**Question:** is quality stable across runs, and does a change actually improve it?
- Consistency: variance across repeats, **pass@k / pass^k**.
- **Baselines** committed per dataset version and config; **regression gate** (`gate.py`): thresholds + baseline delta → exit code.
- `eval-gate.yml` becomes a **required check**: replay on every PR; live runs nightly or on demand with the `OPENAI_API_KEY` GitHub secret (you set it up).
- **Eval-driven improvement:** prompt **v2** built from observed failures (e.g. the rainy-day empty slot), with hypothesis → experiment → significance check → promote baseline.

### Phase 12 – Streamlit UI
**Purpose:** make the agent usable by a non-developer (`goal.md` §6).
- Form: travelers (name, age, interests), dates (limited to the data window), budget, model choice (`OpenAIModel`). Validate into `VacationInfo` with inline Pydantic errors.
- **Explain the cost rule (Q4)** near the budget and the total; hint when an interest has no activities (theatre).
- "Generate itinerary" → live THOUGHT/ACTION/OBSERVATION progress → `TravelPlan` day cards, total vs budget, eval report, trace inspector.
- **Feedback capture** (thumbs up/down + comment per plan), needed by B5.

**Learning focus:** Streamlit's rerun model and `st.session_state`.

### Phase 13 – CD → Cloud Run
**Purpose:** every merge to `main` produces a running, up-to-date app on GCP (`goal.md` §7).
- `Dockerfile` (slim base, non-root, `$PORT`); image in **Artifact Registry** (existing project/region).
- `OPENAI_API_KEY` in **Secret Manager**, injected at runtime, never baked into the image.
- Deploy workflow runs only after **CI and the B4 eval gate** pass on `main`; GitHub → GCP via **Workload Identity Federation** (no JSON keys).
- Rollback via Cloud Run revisions. You run the GCP/GitHub setup commands; I provide them.

### Phase 14 – C1 Structured logging + BigQuery sink
**Question:** can we query production?
- `observability.py`: structured JSON logs for Cloud Logging (run summary, grader scores, feedback events, trace IDs), following the B1–B3 production-signal contracts.
- **Online graders:** deterministic graders on every production run; LLM judges sampled to control cost.
- Log sink → **BigQuery** dataset (needed by B5).

### Phase 15 – C2 Log-based metrics + dashboard
**Question:** how is production doing right now?
- Log-based metrics (online hallucination / constraint / completion rates, cost per run, latency, errors) and a Cloud Monitoring dashboard.

### Phase 16 – C3 Alert policies
**Question:** are we told when it degrades?
- Alerts on drift vs the B4 baseline, cost per run, error rate and latency.

### Phase 17 – B5 Production feedback loop & dataset lifecycle
**Question:** how does production traffic make the evals better?
- BigQuery queries → sample and triage (low grader scores, thumbs-down) → label → **golden v1.1.0** (manifest + changelog) → re-baseline.
- Compare offline vs online rates to detect dataset blind spots.

### Phase 18 – Traveler feedback agent (next stage, not in current scope)
Incorporate traveler feedback on the initial itinerary (at least 2 activities per day), add a stronger-model eval that checks the feedback was honored, and re-run the ReAct loop to revise. The B4 gate measures the improvement.

### Target layout for phases 7+ (finalized in each phase plan)
```
agentsville/harness/   dataset.py  recording.py  runner.py  metrics.py  report.py  gate.py
agentsville/graders/   grounding.py (B1)  constraints.py (B2)  relevancy.py, trajectory.py (B3)
evals/                 datasets/golden/v1.0.0/  cassettes/  thresholds.toml  baselines/
experiments/           (git-ignored)
scripts/               run_experiment.py  compare_experiments.py  eval_gate.py
.github/workflows/     eval-gate.yml
app.py  Dockerfile  agentsville/observability.py
```
Reused, not rebuilt: `run_all_evals`/`EvalResult` (graders), `AgentRun`/`log_run` (run record), `samples.py` and data-review findings (golden seeds and labels), `LLMClient` (wrapped for record/replay), `tests/test_evals_live.py` cases (first human labels).

---

## 6. Working agreement per phase

For every phase:
1. Write `plan/NN-<topic>/plan.md` → **you review**.
2. Create branch `feature/…` (or `docs/`, `chore/`) from an up-to-date `main`.
3. Implement **step by step**, asking permission before each code change. Each new file and function gets a `# Phase N – Step M: …` comment.
4. Add Layer A tests for that phase's code, so CI covers it.
5. Explain new concepts as they come up.
6. Ask before each commit. You push and open/merge the PR (I provide the commands).

---

## 7. Decisions

| # | Decision | Applies in |
|---|---|---|
| Q1 | **Remove all existing comments** in `models.py` (leftover "Phase 3 – Step 0" / "Phase 5 – B0 …" labels and old-project notes such as "moved out of planner.py") and **write new comments** in this plan's `# Phase N – Step M: <purpose>` format | Phase 2 (Step 1) |
| Q2 | **Text-based** THOUGHT/ACTION parsing (not the API's native function calling) | Phases 5–6 |
| Q3 | `VacationInfo` restricts dates to 2025-06-10 → 06-15 and the destination to AgentsVille | Phase 2 |
| Q4 | `total_cost` = **plain sum of activity prices** (matches `sample_plan.json`: 108 = 108), **not** multiplied by the number of travelers. The UI states this rule clearly to the user | Phase 4 (cost eval), Phase 6 (prompt), Phase 8 (UI) |
| Q5 | **Open: revisit.** Flat files vs an `agentsville/` package will be compared and decided in the Phase 0 plan | Phase 0 |
| Q6 | **v4 ordering: Layer B offline first** (B0–B4), then UI → CD → C1–C3 → B5. In B1–B4 the "production signal" is a written contract implemented in C1–C3 | Phases 7–17 |
