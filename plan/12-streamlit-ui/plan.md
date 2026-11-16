# Phase 12 – Streamlit UI

> Status: **IN PROGRESS** – approved 2026-11-16 (Q1–Q7 = recommendations below); Steps 1–6 done, Step 7 (real-model check) postponed
> Proposed branch: `feature/phase-12-streamlit-ui` (created only after your permission, from a
> `main` that includes Phase 10)
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md) (v5: UI first, then CD, then B4)
> Depends on: Phase 6 (agent) ✅, Phases 8–10 (code graders for the quality panel) ✅

## Purpose

**goal.md §6:** *a Streamlit page where a user enters trip preferences and clicks a button to
generate an AgentsVille itinerary. The UI collects input, validates it into the existing Pydantic
models, calls the itinerary agent, and displays the resulting `TravelPlan`.*

| Part | What the user gets |
|---|---|
| **Trip form** | Travelers (name, age, interests), dates limited to the data window, budget, model choice – validated into `VacationInfo` with readable errors |
| **Live agent progress** | Each THOUGHT → ACTION → OBSERVATION appears as the agent works (runs take 1–2 minutes) |
| **The plan** | Day cards (weather, activities, times, prices, reasons), total vs budget with the cost rule explained |
| **Why it's trustworthy** | The final eval report, a **quality panel** (free B1–B3 code graders), and – when a run doesn't finish – *why* (B2 failure taxonomy) |
| **Feedback** | Thumbs up/down + comment per plan, stored as a versioned record for B5 |

Out of scope here: deployment, authentication and Cloud Logging (Phase 13–14).

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Streamlit's rerun model** | Every widget interaction re-runs the whole script top to bottom. Nothing survives a rerun unless it's in `st.session_state`. |
| **`st.session_state`** | A per-browser-session dictionary. We keep the finished `AgentRun` there, so clicking a feedback button doesn't re-run a 2-minute, paid agent run. |
| **Thin UI, testable core** | Streamlit code is hard to unit-test; pure functions aren't. All logic (form → `VacationInfo`, plan → display rows, feedback records) lives in `agentsville/ui/`; `app.py` only draws. |
| **Callbacks for live progress** | `ItineraryAgent(on_step=…)` already exists. The UI passes a callback that writes each step into an `st.status` container while the run is in progress. |
| **`AppTest`** | Streamlit's headless test runner (`streamlit.testing.v1`): it runs `app.py`, clicks buttons and reads the output – in CI, with a fake LLM, no browser and no network. |
| **Sink interface** | Feedback and run records are written through a small interface: a JSONL file locally, structured logs on Cloud Run later – the UI doesn't change when the destination does. |

---

## Design

### 1. Layout
```
app.py                       thin: page config, layout, wiring
agentsville/ui/__init__.py
agentsville/ui/form.py       form state ↔ VacationInfo, field errors, interest availability hints
agentsville/ui/run.py        build the LLM + agent, run with a progress callback, error handling
agentsville/ui/views.py      plan → day-card rows, cost summary, quality-panel rows (pure data)
agentsville/ui/feedback.py   FeedbackRecord (schema "feedback.v1") + sinks
```
Run locally: `streamlit run app.py`. Streamlit 1.45.1 is already in `requirements.txt`.

### 2. The form (`form.py`)
- **Travelers:** a dynamic list in `st.session_state` (add/remove rows): name, age (0–120), interests
  (multiselect over `Interest`). At least one traveler, at least one interest each (the model
  enforces it; the form shows the error inline).
- **Dates:** `st.date_input` with `min_value`/`max_value` = `TRIP_WINDOW_START`/`TRIP_WINDOW_END`
  from `models.py`, so impossible dates can't be picked.
- **Budget:** integer > 0, with the **cost rule (Q4)** next to it: "Prices are added once for the whole
  group, not per person".
- **Interest hints:** for the chosen dates, interests that **no activity offers** are marked (e.g.
  theatre → "no theatre activity on these dates"). Computed from `data_api`, never from the LLM.
- **Advanced (collapsed):** model (`OpenAIModel`, default `gpt-4o-mini`), weather judge on/off
  (default on), max steps (default 20).
- `to_vacation_info(form) -> VacationInfo | list[FieldError]`: Pydantic `ValidationError` → one
  readable message per field ("Traveler 2 – age: must be ≤ 120").

### 3. Running the agent (`run.py`)
- `get_settings()` once; a missing `OPENAI_API_KEY` shows a clear setup message instead of a crash.
- `run_agent(info, options, on_step) -> AgentRun`: builds `LLMClient` + `ItineraryAgent(on_step=…)`;
  the callback writes `THOUGHT / ACTION / OBSERVATION (abbreviated)` into an `st.status` box.
- The finished `AgentRun` goes into `st.session_state["run"]`; reruns only redraw it.
- The **button is disabled while a run is in progress** (no double-spend on double click).
- `llm_error` / `max_steps` runs are shown, not hidden: the stop reason plus the B2 failure mode in
  plain words (e.g. `eval_loop:total_cost_accurate` → "the agent kept getting the total cost wrong").
- Run log: kept at `logs/agent_runs.jsonl` locally; the path comes from an env var so Phase 13 can
  switch it off (Cloud Run's disk is temporary).

### 4. Results (`views.py` + `app.py`)
- **Summary bar:** total vs budget (with the cost rule), days, activities, steps, cost (USD), time.
- **Day cards:** date + weather (condition, temperature, an inclement-weather badge), then each
  activity: time, name, location, price, interests, and its reasons.
- **Eval report:** the final `run_all_evals` report (✓ / ✗ / warning per eval, with details).
- **Quality panel (free):** the B1–B3 **code** graders run on this plan in-process
  (`grade_run` with the deterministic graders and no golden case): grounding (no invented or altered
  activities, weather matches), budget respected, interest match, calculator total, verified before
  final, redundant lookups. Label-based graders show "needs a golden case"; LLM judges aren't run
  (cost) – a note says so.
- **Trace inspector (collapsed):** every step's thought, action and full observation.

### 5. Feedback (`feedback.py`)
```python
class FeedbackRecord(BaseModel):          # schema_version "feedback.v1" – B5's input
    schema_version: str = "feedback.v1"
    run_id: str                           # joins with AgentRun / production signals
    rating: Literal["up", "down"]
    comment: str = ""                     # optional, length-limited
    model: str
    prompt_version: str
    created_at: datetime
```
- `FeedbackSink` protocol with `JsonlFeedbackSink(path)` now (`logs/feedback.jsonl`, git-ignored).
  Phase 13/14 add a stdout/Cloud Logging sink – the UI code doesn't change.
- One feedback per run (the buttons are replaced by "Thanks" once submitted).
- Spec appended to `plan/08-b1-grounding/production-signal.md` (feedback section).

### 6. Testing (Layer A, no network, no cost)
- Pure-function tests for `form.py`, `views.py`, `feedback.py`, `run.py` (with `ScriptedLLM` /
  `ConversationFake`).
- `AppTest` smoke tests: fill the form → click Generate (fake LLM) → day cards, eval report and
  quality panel appear; invalid input → inline errors and no agent call; feedback writes one record;
  a second click doesn't re-run the agent.

### Cost
**$0 in development and CI** (fakes). Manual testing with the real model: ~1–3 cents per run
(`gpt-4o-mini` + weather judge), ~5–10 runs while building → **≈ $0.30**.

---

## Steps

### Step 1 – App skeleton and UI package
**Purpose:** a page that starts, with the structure the rest builds on.
**Output:** `app.py` (page config, title, sections), `agentsville/ui/__init__.py`; `streamlit run
app.py` works; first `AppTest` smoke test.
**Depends on:** none.

### Step 2 – Trip form → `VacationInfo`
**Purpose:** collect and validate input with readable errors.
**Output:** `agentsville/ui/form.py` (form state, `to_vacation_info`, field errors, interest hints);
the form in `app.py`; tests.
**Depends on:** Step 1.

### Step 3 – Run the agent with live progress
**Purpose:** generate an itinerary without blocking the user's understanding of what's happening.
**Output:** `agentsville/ui/run.py` (settings, agent factory, progress callback, error and
stop-reason handling, session-state caching, disabled button while running); tests with a fake LLM.
**Depends on:** Step 2.

### Step 4 – Plan view, eval report, trace inspector
**Purpose:** show the `TravelPlan` clearly, with the cost rule and the eval results.
**Output:** `agentsville/ui/views.py` (day-card rows, summary, failure explanation); results in
`app.py`; tests.
**Depends on:** Step 3.

### Step 5 – Quality panel
**Purpose:** make the B1–B3 checks visible to the user, free.
**Output:** quality-panel rows in `views.py` (deterministic graders via `grade_run`, no case);
tests.
**Depends on:** Step 4.

### Step 6 – Feedback capture
**Purpose:** collect traveler feedback for B5.
**Output:** `agentsville/ui/feedback.py` (`FeedbackRecord`, `FeedbackSink`, `JsonlFeedbackSink`);
buttons + comment in `app.py`; `logs/feedback.jsonl` git-ignored; spec section; tests.
**Depends on:** Step 4.

### Step 7 – Manual check with the real model (~$0.30)
**Purpose:** see it work end to end, as a user would.
**Output:** a few real runs (default sample, tight budget, rainy days, an invalid input) via the
`run` skill / browser; screenshots in the PR description; issues found are fixed in their step.
**Depends on:** Steps 1–6.

### Step 8 – Tests and docs
**Purpose:** CI covers the UI; future sessions know how it's built.
**Output:** `AppTest` coverage completed; `CLAUDE.md` (UI architecture, how to run and test it),
README (run the app, screenshot).
**Depends on:** Steps 1–7.

| Area | Cases |
|---|---|
| form | valid input → `VacationInfo`; departure before arrival, age 130, no interests, budget 0 → one readable error each; dates outside the window can't be chosen; theatre hint |
| run | progress callback receives every step; missing API key → setup message; `LLMError` → message; `max_steps` → failure mode in plain words; result cached across reruns |
| views | day rows from `sample_plan.json`; total vs budget; inclement badge; empty plan (infeasible) shown sensibly |
| quality panel | golden plan all ✓; altered activity → ✗ with detail; label-based graders "needs a golden case" |
| feedback | record fields; one per run; JSONL append; comment length limit |
| AppTest | form → generate (fake) → results; invalid input → no agent call; feedback writes once |

---

## Verification (definition of done)

```bash
ruff check . && pytest                       # AppTest + unit tests, no network
streamlit run app.py                         # manual: real runs (Step 7)
python scripts/run_experiment.py --check-expected --check-thresholds   # unchanged eval path
```
Plus green CI and a reviewed walkthrough (screenshots).

---

## Questions for you

| # | Question | My recommendation |
|---|---|---|
| Q1 | Thin `app.py` + logic in `agentsville/ui/` (pure, unit-tested) + `AppTest` smoke tests in CI? | **Yes** |
| Q2 | Defaults: `gpt-4o-mini`, weather judge **on**, max 20 steps – changeable under "Advanced"? | Yes (~1–3 cents per run) |
| Q3 | Show a **quality panel** with the free B1–B3 code graders (no LLM judges in the UI)? | **Yes** – the QA platform made visible, at no cost |
| Q4 | Feedback = thumbs up/down + optional comment, one per run, `feedback.v1` record via a sink (JSONL now, Cloud Logging later)? | Yes |
| Q5 | No login in Phase 12 (local app). Access control for the public URL is decided in Phase 13 (each run spends OpenAI credit)? | Yes – flagged in master plan v5 |
| Q6 | Manual check with the real model in Step 7, ≈ $0.30, cap $1? | Yes |
| Q7 | One commit for the phase; branch `feature/phase-12-streamlit-ui` once Phase 10 is merged? | Yes |
