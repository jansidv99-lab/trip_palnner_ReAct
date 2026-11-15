# Master Plan – AgentsVille Trip Planner (ReAct)

> Status: **APPROVED v3**
> Branch: `docs/master-plan`
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

---

## 1. What we are building (in one paragraph)

A traveler describes a trip: who's going, their interests, dates, and budget. An **ItineraryAgent**
then builds a day-by-day plan for the fictional city of AgentsVille. It doesn't answer in one shot.
It works in a **ReAct loop**: it *thinks*, calls a *tool* (for example "what's the weather on
06-12?"), reads the *observation*, and repeats until it's confident. Then it calls
`final_answer_tool` with a structured `TravelPlan`. The plan is checked by **evals**: some are
deterministic Python checks, and one uses an LLM as a judge. A **Streamlit UI** wraps it all. The
app is tested in CI, deployed through CD to the existing GCP project, and monitored for quality and
cost over time.

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
| **Drift** | Quality or cost slowly changing over time (new model version, prompt edits). We detect it by tracking eval pass rates and metrics across runs, compared to a baseline. |

---

## 3. Current state (baseline)

| Item | Status |
|---|---|
| `models.py`: `VacationInfo`, `Traveler`, `Interest`, `TravelPlan`, `ItineraryDay`, `Activity`, `Weather`, `PromptTrace`, `OpenAIModel` | ✅ exists |
| `data/data.py`: 24 activities (4/day), weather for 2025-06-10 → 06-15, `INCLIMATE_WEATHER_CONDITIONS` | ✅ exists |
| `sample_plan.json`: reference `TravelPlan` | ✅ exists |
| `requirements.txt`, `.env`, `.gitignore`, `CLAUDE.md` | ✅ exists |
| Config loading, LLM client, evals, tools, agent, UI, tests, CI, CD | ❌ not started |

---

## 4. Phase overview

```
0 Foundations ─► 1 CI ═══════════════════════════════════════════ (checks every later phase)
      │
      ├─► 2 Vacation details ─┐
      └─► 3 Data access ──────┴─► 4 Evals ─► 5 Tools ─► 6 ReAct agent (+ traces)
                                                                 │
                                       7 Offline eval suite (B) ◄┘
                                                                 │
                                       8 Streamlit UI ─► 9 CD ─► 10 Monitoring & drift (C)
                                                                 │
                                                       11 Feedback agent (later)
```

| # | Phase | Plan folder | Depends on | Main deliverable | Why this position |
|---|---|---|---|---|---|
| 0 | Foundations | `plan/00-foundations/` | – | Config loader, LLM client + smoke call, pytest, ruff | The smoke call checks the `OPENAI_BASE_URL` and key on day one |
| 1 | CI | `plan/01-ci/` | 0 | GitHub Actions: lint + tests on every PR | Cheap now; every later phase gets automatic checks (Layer A starts) |
| 2 | Vacation details | `plan/02-vacation-info/` | 0 | Reviewed `VacationInfo`, sample trip requests | Defines the agent's input |
| 3 | Data access & review | `plan/03-data-access/` | 0 | Mock weather/activity API functions, data review | Defines what the agent can know |
| 4 | Evals | `plan/04-evals/` | 2, 3 | Deterministic + LLM-judge evals, `run_all_evals` | Defines "good" before building the thing that produces it. Testable on `sample_plan.json` and hand-made bad plans |
| 5 | Tools | `plan/05-tools/` | 3, 4 | All tools **including `run_evals_tool`**, tool registry | Evals already exist, so the full tool set ships together |
| 6 | ReAct ItineraryAgent | `plan/06-itinerary-agent/` | 5 | Prompt, parser, loop, self-check, trace logging | Built with self-checking from the start. Every run is recorded, which seeds Layer C |
| 7 | Offline eval suite (Layer B) | `plan/07-offline-evals/` | 6 | Set of test trips, N runs/case, pass rates, prompt/model comparison | Gets agent quality right *before* anyone sees it |
| 8 | Streamlit UI | `plan/08-streamlit-ui/` | 6 | `app.py`: form → agent → `TravelPlan` + evals + traces | Wraps a measured, tuned agent |
| 9 | CD | `plan/09-cd/` | 1, 8 | Docker, Artifact Registry, Secret Manager, Workload Identity, Cloud Run | Deploys the finished app |
| 10 | Monitoring & drift (Layer C) | `plan/10-monitoring/` | 6, 7, 9 | Production metrics, drift against the baseline, alerts | Needs production traffic plus a historical baseline |
| 11 | Feedback agent (later) | `plan/11-feedback-agent/` | 6, 7 | Revision loop from traveler feedback (≥ 2 activities/day) | Next stage per `goal.md` |

**Where each AI QA layer lives**

| Layer | Where |
|---|---|
| A – Deterministic testing (minimal) | Tests written in **every** phase, run by **CI (Phase 1)** |
| B – Probabilistic evals (**main**) | Eval functions in **Phase 4** → used by the agent in **Phase 6** → measured statistically in **Phase 7** |
| C – System metrics & drift (**main**) | Traces recorded from **Phase 6** → baseline from **Phase 7** → production monitoring in **Phase 10** |

---

## 5. Phase details

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

### Phase 7 – Offline eval suite (Layer B)
**Purpose:** measure agent quality statistically and tune it before it's put in front of users.
- An **eval dataset**: a fixed set of trip requests covering normal trips, tight budgets, rainy-day trips, many travelers, and narrow interests.
- Run the agent **N times per case** (LLM output varies) and score each run with `run_all_evals`.
- Report **pass rate per eval and per case**, average cost, steps and latency.
- Compare **prompt versions** and **models** (`gpt-4.1` / `-mini` / `-nano`) side by side, and compare runs with and without self-checking.
- Save the result as the **baseline** for drift detection in Phase 10.
- Runs on demand (it costs money), not on every PR.

**Learning focus:** why one run proves nothing for an LLM, pass rates and variance, evidence-based prompt iteration.

### Phase 8 – Streamlit UI
**Purpose:** make the agent usable by a non-developer. (UI only, no deployment concerns.)
- Form: travelers (name, age, interests), dates (limited to the data window), budget, model choice (`OpenAIModel`).
- Validate into `VacationInfo` and show Pydantic errors inline.
- **Explain the cost rule to the user (Q4):** a note near the budget input and next to the total, for example *"Total cost = sum of activity prices (per group, not per traveler)"*.
- "Generate itinerary" button → run the agent with a progress view of THOUGHT/ACTION/OBSERVATION steps.
- Show the `TravelPlan` (day cards with weather and activities), the total vs budget, eval results, and a prompt-trace inspector.
- Run locally with `streamlit run app.py`.

**Learning focus:** Streamlit's rerun model and `st.session_state`.

### Phase 9 – CD (Continuous Delivery/Deployment)
**Purpose:** every merge to `main` produces a running, up-to-date app on GCP without manual steps.
- `Dockerfile` for the Streamlit app (slim Python base, non-root user, listens on `$PORT`).
- Build the image and push it to **Artifact Registry** in the existing project/region.
- Store `OPENAI_API_KEY` in **Secret Manager** and inject it at runtime. It's never baked into the image.
- Deploy to **Cloud Run** from a GitHub Actions workflow that runs only after CI passes on `main`.
- Authenticate GitHub → GCP with **Workload Identity Federation** (no long-lived JSON keys).
- Rollback through Cloud Run revisions: shift traffic back to the previous revision.
- You run the GCP/GitHub setup commands yourself. I provide them.

**Learning focus:** containers, secret handling, keyless auth, revision-based rollback.

### Phase 10 – Monitoring & drift (Layer C)
**Purpose:** know whether the app stays good and affordable in production.
- Send production traces (the same `PromptTrace` + eval result format as Phase 6) to Cloud Logging, then BigQuery for analysis.
- Metrics: latency, tokens, cost per run, steps per run, eval pass rate, error and timeout rate.
- **Drift detection:** compare rolling production metrics to the Phase 7 baseline, and alert when pass rate drops or cost rises past a threshold.
- A small dashboard (Looker Studio or a Streamlit admin page, decided in that phase's plan).

**Learning focus:** what to measure for an AI system in production, baselines and thresholds, structured logging.

### Phase 11 – Traveler feedback agent (next stage, not in current scope)
Incorporate traveler feedback on the initial itinerary (for example "at least 2 activities per day"), add a stronger-model eval that checks the feedback was honored, and re-run the ReAct loop to revise. The Phase 7 suite measures the improvement.

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
