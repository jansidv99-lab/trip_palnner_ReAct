# Phase 2 – Vacation details

> Status: **APPROVED** (decisions in the last section; unique traveler names were dropped)
> Branch: `feature/phase-2-vacation-info`
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md)
> Depends on: Phase 0 (package, config, tests) ✅, Phase 1 (CI) ✅

## Purpose

`VacationInfo` is the **only input** to the agent. If it's wrong (impossible dates, unknown city,
an empty traveler list), everything downstream wastes LLM calls producing a plan that can't be
correct. This phase makes the input trustworthy:

- clean up `models.py` (decision Q1 from the master plan),
- align the model list with what the LLM proxy actually accepts,
- add the business rules decided in the master plan (Q3: data-window dates, AgentsVille only),
- create reusable **sample trip requests** for tests, evals, the agent and the eval suite,
- cover all of it with Layer A tests, so CI guards it.

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Field constraints** | Rules attached to one field, for example `Field(ge=0, le=120)` for age. Pydantic checks them while building the object. |
| **`field_validator`** | Custom Python code for **one** field. It can reject the value or *normalize* it (for example turn `" agentsville "` into `"AgentsVille"`). |
| **`model_validator(mode="after")`** | Custom code that runs after all fields are parsed. Use it for rules involving **several** fields (departure ≥ arrival). |
| **Normalize vs reject** | Fix harmless input (casing, spaces) silently; reject meaningful errors (wrong city) with a clear message. |
| **`ValidationError`** | Pydantic collects **all** problems at once. Each error has a `loc` (which field) and a `msg`, which the UI (Phase 8) will show next to the right input. |
| **`str` + `Enum`** | `class Interest(str, Enum)` members behave like strings (`Interest.ART == "art"`), so they serialize cleanly to JSON and LLM prompts. |
| **Factory functions for samples** | `sample_vacation_info()` returns a **new** object on every call, so one test can't accidentally modify data another test uses. |
| **Consistency test** | A test that fails if two sources of truth drift apart (our date-window constants vs the dates in `data/data.py`). |

---

## Current state of `agentsville/models.py`

| Item | Today | Problem |
|---|---|---|
| Comments | "Phase 3 – Step 0", "Phase 5 – B0 Step 3", "moved out of planner.py", … | from an older project; misleading (Q1) |
| Typing style | `List[...]`, `Optional[...]` | outdated for Python 3.11. A temporary ignore in `ruff.toml` hides 15 lint findings. |
| `OpenAIModel` | `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano` | the proxy returns **404 for `gpt-4.1-nano`**; `gpt-4o-mini` (our default in `.env`/config) is missing |
| `VacationInfo` | checks travelers ≥ 1, budget > 0, departure ≥ arrival | no data-window check, any destination accepted (Q3) |
| `Traveler` | name non-empty, age 0–120, interests ≥ 1 | OK |
| Output models (`TravelPlan` …) | unchanged structure | OK; only comments and typing change |

---

## Steps

### Step 1 – Clean up `models.py` comments and typing
**Purpose:** remove misleading history and bring the file up to the project's lint standard.
**Output:** `agentsville/models.py` (comments + typing only, **no behavior change**); `ruff.toml` loses its temporary `models.py` ignore.
**Depends on:** nothing.
- Delete **all** existing comments and the module docstring.
- Add a header `# Phase 2 – Step 1: Pydantic data models shared by the agent, tools, evals and UI.` and one `# Phase 2 – Step 1: <purpose>` comment per class. Keep a few short section dividers (*Input*, *Output*, *Observability*) because they help orientation.
- `List[X]` → `list[X]`, `Optional[X]` → `X | None`, imports sorted.
- `PromptTrace.prompt_version` comment becomes `# which prompts/itinerary/<version>.md was used (Phase 6)`.
- Remove the `"agentsville/models.py" = [...]` line from `ruff.toml`.
- Check: `ruff check .` passes **without** the ignore, and all existing tests still pass (proving no behavior changed).

### Step 2 – Align `OpenAIModel` with the proxy
**Purpose:** the UI should only offer models that actually work.
**Output:** `agentsville/models.py` (`OpenAIModel`), `agentsville/llm.py` (price table).
**Depends on:** Step 1.

| Member | Value | Status from the Phase 0 smoke test |
|---|---|---|
| `GPT_4O_MINI` | `gpt-4o-mini` | ✅ works, **default** (matches `.env` and `config.DEFAULT_MODEL`) |
| `GPT_41_MINI` | `gpt-4.1-mini` | ✅ works |
| `GPT_41` | `gpt-4.1` | ✅ works, strongest (good for the LLM-judge eval later) |
| ~~`GPT_41_NANO`~~ | ~~`gpt-4.1-nano`~~ | ❌ 404, **removed** |

- Remove `gpt-4.1-nano` from `PRICES_PER_1M_TOKENS` in `llm.py`, so the two lists match.
- `config.MODEL` **stays free-form** (Q-A from Phase 0): developers can still try other models from the command line; the UI restricts choices to `OpenAIModel`.
- A test asserts every `OpenAIModel` value has a price in `PRICES_PER_1M_TOKENS`, so cost tracking can't silently break when a model is added.

### Step 3 – Business rules on `VacationInfo` (Q3)
**Purpose:** reject impossible requests before they reach the agent.
**Output:** `agentsville/models.py` (`VacationInfo` + constants).
**Depends on:** Step 1.

New module-level constants (one place to change if the data changes):
```python
SUPPORTED_DESTINATION = "AgentsVille"
TRIP_WINDOW_START = date(2025, 6, 10)   # first date with weather + activities in data/data.py
TRIP_WINDOW_END   = date(2025, 6, 15)   # last date
```

| Rule | Validator | Behavior |
|---|---|---|
| Destination is AgentsVille | `field_validator("destination")` | **normalize** case and whitespace (`" agentsville "` → `"AgentsVille"`); **reject** anything else: *"destination must be AgentsVille (the only city with data)"* |
| Arrival and departure inside the data window | `model_validator(mode="after")` (extends the existing date check) | **reject**: *"dates must be between 2025-06-10 and 2025-06-15 (the period with weather and activity data)"* |
| Departure ≥ arrival | existing `model_validator` | unchanged |

- Constants live in `models.py`, not read from `data/data.py`, so the models don't depend on mock data (a real API later won't break them). A **consistency test** checks they match the first and last dates in `WEATHER_FORECAST` and `ACTIVITY_CALENDAR`.

### Step 4 – Sample trip requests
**Purpose:** one shared set of realistic inputs, instead of every test and phase inventing its own.
**Output:** `agentsville/samples.py`.
**Depends on:** Step 3.

| Factory | Travelers | Dates | Budget | Why it exists |
|---|---|---|---|---|
| `sample_vacation_info()` | Yuri (technology, tennis, cooking), Hiro (reading, art, music) | 06-10 → 06-12 | 130 | **matches `sample_plan.json`** (same travelers, dates, total 108), so Phase 4 evals can be tested on a known-good pair |
| `tight_budget_vacation_info()` | same two | 06-10 → 06-12 | 40 | forces the agent to choose; drives the budget eval |
| `rainy_days_vacation_info()` | one traveler (hiking, photography, sports: outdoor-heavy) | 06-12 → 06-14 | 150 | thunderstorm + 2 rainy days, which drives the weather-suitability eval |

- Each is a function returning a **new** `VacationInfo`.
- Phase 7 will extend these into a larger eval dataset.

### Step 5 – Tests (Layer A)
**Purpose:** lock in the rules so CI catches regressions.
**Output:** `tests/test_models.py`.
**Depends on:** Steps 1–4.

| Area | Cases |
|---|---|
| Valid input | all three samples build; `sample_plan.json` parses as `TravelPlan` |
| Destination | `"AgentsVille"`, `" agentsville "` → normalized; `"Paris"` → error on `destination` |
| Dates | departure < arrival → error; arrival 06-09 or departure 06-16 → error; one-day trip (arrival = departure) → OK |
| Travelers | empty list, age −1 / 121, no interests, unknown interest `"skiing"` → errors; duplicate names → allowed |
| Budget | 0 and negative → error |
| Multiple errors | one bad request with several problems → a single `ValidationError` listing all of them (what the UI will rely on) |
| Model list | `OpenAIModel` has no `gpt-4.1-nano`; every model has a price |
| Consistency | window constants == first/last dates in `data/data.py` |

### Step 6 – Documentation
**Purpose:** keep `CLAUDE.md` accurate for future sessions.
**Output:** `CLAUDE.md` architecture section.
**Depends on:** Steps 1–5.
- Describe the `VacationInfo` rules, the window/destination constants, `samples.py`, and the updated `OpenAIModel` list.
- Remove the note about the temporary `models.py` lint ignore if present.

---

## Verification (definition of done)

```bash
ruff check .        # passes with NO models.py ignore in ruff.toml
pytest              # all tests pass (existing 18 + new model tests)
```
Plus green `CI / lint` and `CI / test` on the PR.

---

## Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Window constants or derived from data? | **Fixed constants** in `models.py` + consistency test |
| Q2 | Require unique traveler names? | **No.** Duplicate names are allowed; rule dropped |
| Q3 | Destination casing? | **Any casing accepted**, normalized to `"AgentsVille"` |
| Q4 | Budget for `sample_vacation_info()`? | **130** |
| Q5 | Commit style? | **One commit** for the phase |
| Q6 | Create the branch? | **Done:** `feature/phase-2-vacation-info` |
