# Phase 4 – Evals

> Status: **APPROVED** – all recommendations accepted (Q1 inclement only, Q2 X1–X4 now, Q3 gpt-4.1, Q4 fail closed, Q5 constant, Q6 one commit)
> Branch: `feature/phase-4-evals`
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md)
> Depends on: Phase 0 (`LLMClient`) ✅, Phase 2 (models, samples) ✅, Phase 3 (`data_api`, data review) ✅

## Purpose

Define **what a good itinerary is** before building the agent that produces one (`goal.md` §4).
Each eval checks one criterion and returns a structured result. `run_all_evals()` runs them all,
and it's reused by:
- **Phase 5:** `run_evals_tool`, so the agent self-checks its draft,
- **Phase 7:** the offline eval suite (pass rates over many runs),
- **Phase 8:** the UI (shows results to the user),
- **Phase 10:** production monitoring.

Since no agent exists yet, evals are proven against **`sample_plan.json`** (known good) and
**deliberately broken copies** of it (known bad).

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Eval** | A function `(request, plan) → result` that scores one quality criterion. A unit test checks *our code*; an eval checks *the AI's output*. |
| **Deterministic eval** | Plain Python with a guaranteed answer (is the total correct?). Free, fast, repeatable. |
| **LLM-as-judge** | A second LLM call judges something code can't, such as "is this event OK in a thunderstorm?" Costs money, can vary, and needs calibration. |
| **Severity: error vs warning** | *Error* evals decide pass/fail (wrong city, invented activity). *Warning* evals are informational (interest coverage), because sometimes a perfect score is impossible (data review D6, D9). |
| **JSON mode** | Asking the API to return only valid JSON (`response_format={"type": "json_object"}`), so the judge's verdict can be parsed reliably into a Pydantic model. |
| **Calibration cases** | Hand-labeled examples with a known right answer (from the data review). If the judge gets them wrong, we fix the judge prompt before trusting it. |
| **Golden + mutated fixtures** | Start from one known-good plan and break exactly one thing per test. A failing eval then points at exactly one cause. |

---

## Design

### Result objects (Pydantic, in `agentsville/evals.py`)

```python
class EvalResult(BaseModel):
    name: str                   # "city_and_dates"
    passed: bool
    severity: Literal["error", "warning"]
    kind: Literal["deterministic", "llm"]
    score: float | None = None  # 0–1 where meaningful (e.g. interest coverage)
    details: list[str] = []     # one human-readable line per problem found

class EvalReport(BaseModel):
    results: list[EvalResult]
    passed: bool                # True if every *error*-severity eval passed
    def summary(self) -> str    # compact text: one line per eval + problem lines
```
`summary()` is what the agent will read as its OBSERVATION in Phase 5, so it has to be short and specific (for example `✗ total_cost_accurate: plan says 120, activities sum to 108`).

### Evals

**Required by `goal.md`** (all severity *error*):

| # | Name | Kind | Check |
|---|---|---|---|
| E1 | `city_and_dates` | deterministic | `plan.city == request.destination`; `start_date`/`end_date` equal arrival/departure; `itinerary_days` contains **every** trip date exactly once, in order |
| E2 | `total_cost_accurate` | deterministic | `plan.total_cost == sum(activity.price)` (the plain per-group sum, master-plan Q4) |
| E3 | `within_budget` | deterministic | the **actual** sum of prices ≤ `request.budget`. Uses the real sum, not the reported total, so a wrong total can't hide overspending. |
| E4 | `no_hallucinated_activities` | deterministic | every activity exists (`data_api.get_activity_by_id`), **all its fields match** the source exactly (price, times, name…), and it sits on the itinerary day matching its `start_time` date |
| E5 | `weather_suitability` | **LLM judge** | for each activity on an **inclement** day, the judge reads the activity description and the forecast description and returns `{"suitable": bool, "reason": str}`. Non-inclement days pass without an LLM call (saves cost). |

**Extra evals** (the "suggest the evals" part of `goal.md` §4):

| # | Name | Kind | Severity | Check | Why |
|---|---|---|---|---|---|
| X1 | `weather_matches_forecast` | deterministic | error | each day's `weather` (temperature, unit, condition) equals `data_api.get_weather(day)` | the agent may copy the wrong day's weather |
| X2 | `no_overlapping_activities` | deterministic | error | within a day, no two activities overlap in time, and no activity appears twice in the plan | a group can't be in two places at once |
| X3 | `interest_coverage` | deterministic | **warning** | share of travelers with ≥ 1 activity matching their interests; `score` = that share | perfect coverage is sometimes impossible (D6 theatre, D9 rainy sample) |
| X4 | `activities_per_day` | deterministic | **warning** | every day has ≥ 1 activity (threshold is a parameter; Phase 11 will use 2) | flags empty days |

*Deferred:* "recommendation reasons are grounded" (a second LLM judge) moves to Phase 7, when we have real agent output to judge (Q2).

### Weather judge (E5) details
- **Model:** `gpt-4.1` (strongest available; ~1 cent per plan). Configurable.
- **Prompt** (constant in `evals.py`): role ("strict travel-safety reviewer"), the rule *"judge whether a reasonable traveler could enjoy this activity in this weather; indoor venues and stated rain fallbacks are suitable; outdoor-only activities during rain or thunderstorms are not; consider timing if the forecast says when bad weather arrives"*, and then the activity (name, time, description) and forecast (condition, temperature, description).
- **Output:** JSON mode → parsed into `WeatherVerdict(suitable: bool, reason: str)`. If the reply can't be parsed, the activity counts as **not suitable** with detail *"judge reply unparseable"* (fail closed, never silently pass).
- **One call per activity** on inclement days: simple and easy to debug. A typical 3-day plan has 1–4 such activities.
- `run_all_evals(..., include_llm=False)` skips E5 entirely, for cheap runs and unit tests.

### Small change to `llm.py`
Add an optional `json_mode: bool = False` to `LLMClient.chat()`. When true, it passes `response_format={"type": "json_object"}`. The existing behavior is unchanged.

---

## Steps

### Step 1 – Result models and runner skeleton
**Purpose:** a common shape for every eval, so the agent, the eval suite and the UI handle results uniformly.
**Output:** `agentsville/evals.py` (`EvalResult`, `EvalReport`, `summary()`, `run_all_evals()` running a list of evals).
**Depends on:** Phase 2 models.

### Step 2 – Required deterministic evals (E1–E4)
**Purpose:** the `goal.md` checks that need no LLM.
**Output:** four functions in `evals.py`.
**Depends on:** Step 1, `data_api` (Phase 3).

### Step 3 – Extra deterministic evals (X1–X4)
**Purpose:** catch further failure modes cheaply.
**Output:** four functions in `evals.py`.
**Depends on:** Step 1, `data_api`.

### Step 4 – JSON mode in `LLMClient`
**Purpose:** reliable structured output from the judge.
**Output:** `agentsville/llm.py` (`json_mode` parameter) + a unit test with the fake client.
**Depends on:** Phase 0 `llm.py`.

### Step 5 – Weather-suitability LLM judge (E5)
**Purpose:** the one check plain Python can't do (data review D4, D5).
**Output:** `WeatherVerdict` model, judge prompt, `weather_suitability()` in `evals.py`.
**Depends on:** Steps 1 and 4, `data_api.get_weather` / `is_inclement`.

### Step 6 – Tests
**Purpose:** prove each eval catches its failure and passes the golden plan.
**Output:** `tests/test_evals.py` (unit, no network) and `tests/test_evals_live.py` (`@pytest.mark.llm`).
**Depends on:** Steps 1–5.

Unit tests, using a `golden_plan` fixture (`sample_plan.json`) with `sample_vacation_info()`:

| Mutation of the golden plan | Expected failing eval |
|---|---|
| none | all pass |
| city = "Paris" / end_date shifted / a day removed / days out of order | E1 |
| total_cost = 120 | E2 (E3 still passes: real sum is 108) |
| same plan with `tight_budget_vacation_info()` (budget 40) | E3 |
| unknown `activity_id` / price changed to 5 / activity moved to another day | E4 |
| 06-10 weather condition changed to "rainy" | X1 |
| same activity added twice | X2 |
| request where a traveler's only interest is theatre | X3 warning (`score` < 1), report still `passed` |
| a day with no activities | X4 warning |
| E5 with **fake LLM**: verdicts suitable / unsuitable / garbage | pass / fail with reason / fail "unparseable"; no call for non-inclement days |
| `include_llm=False` | E5 absent; no LLM calls |

Live calibration tests (`pytest -m llm`, real `gpt-4.1`; cases from data review §3):

| Activity on its own (inclement) day | Expected |
|---|---|
| `event-2025-06-13-1` outdoor hike, rainy | **not suitable** |
| `event-2025-06-12-1` picnic with indoor fallback, thunderstorm | **suitable** |
| `event-2025-06-14-3` indoor writing/dance evening, rainy | **suitable** |
| `event-2025-06-12-3` indoor tech & film night, thunderstorm | **suitable** |

Plus: the golden `sample_plan.json` gets `passed=True` end-to-end with the real judge.

### Step 7 – Demo script
**Purpose:** see an eval report with your own eyes (learning).
**Output:** `scripts/run_evals.py`: evaluates `sample_plan.json` against `sample_vacation_info()` and prints `report.summary()`. `--no-llm` skips the judge; `--plan PATH` evaluates another plan file.
**Depends on:** Steps 1–5.

### Step 8 – Documentation
**Purpose:** keep `CLAUDE.md` accurate.
**Output:** `CLAUDE.md` architecture section: `evals.py`, the severity rule, `include_llm`, the `json_mode` flag.
**Depends on:** Steps 1–7.

---

## Verification (definition of done)

```bash
ruff check .
pytest                              # unit tests incl. tests/test_evals.py (no network)
pytest -m llm                       # judge calibration cases + golden plan (costs ~2–3 cents)
python scripts/run_evals.py         # golden plan → all ✓
```
Plus green `CI / lint` + `CI / test` on the PR.

---

## Decisions (all recommendations accepted)

| # | Question | My recommendation |
|---|---|---|
| Q1 | LLM judge only for activities on **inclement** days, or every activity? | **Inclement days only.** That's where the risk is (D3), and it costs about a third as much. Heat (D10) stays out of scope. |
| Q2 | Which extra evals now? | **X1–X4 now**; defer the "reasons grounded" LLM judge to Phase 7 |
| Q3 | Judge model: `gpt-4.1` (strongest) or `gpt-4o-mini` (cheapest)? | **`gpt-4.1`.** A judge should be at least as strong as the agent it grades. |
| Q4 | Unparseable judge reply: fail closed (count as unsuitable) or skip? | **Fail closed.** Never silently pass. |
| Q5 | Judge prompt as a constant in `evals.py`, or a file under `prompts/evals/`? | **Constant for now.** Prompt files and versioning arrive with the agent prompt in Phase 6. |
| Q6 | One commit for the phase? | Yes |
| Q7 | May I create branch `feature/phase-4-evals` from `main`? | Yes |
