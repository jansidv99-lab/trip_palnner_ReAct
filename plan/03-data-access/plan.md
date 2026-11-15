# Phase 3 – Data access & review

> Status: **APPROVED** – all recommendations accepted (Q1 subclass, Q2 None/[], Q3 hint only, Q4 one commit)
> Branch: `feature/phase-3-data-access`
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md)
> Depends on: Phase 0 (package) ✅, Phase 2 (`Weather`, `Activity`, window constants) ✅

## Purpose

`goal.md` §2: *"Simulate API calls to gather weather data and available activities in bulk;
review the data manually to understand the available options."*

1. Wrap `data/data.py` in functions that **behave like real API calls**. Later phases (evals,
   tools, agent) call these functions and never touch the raw lists, so swapping in a real weather
   or activity API later changes only this module.
2. Return **validated Pydantic models**, not raw dicts, so bad data fails here, loudly, and not
   inside an LLM prompt.
3. **Look at the data** before asking an LLM to reason about it, and write down what we learn. Those
   findings shape the agent prompt (Phase 6) and the evals (Phase 4).

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Data access layer** | One module owns *how* data is fetched. Everyone else asks it *what* they need (`get_weather(date)`), so the source can change without touching callers. |
| **Mock API** | A function with the same inputs/outputs a real API would have (date + city in, data out), backed by local data. |
| **Index (lookup table)** | Group the 24 activities by date **once** into a dict, so each lookup is instant instead of scanning the list every call. |
| **Caching (`functools.cache`)** | Remember a function's result. The data never changes at runtime, so we build models and indexes only once. |
| **"Not found" design** | Decide what a missing result looks like: `None` for "no weather that day", `[]` for "no activities that day". The caller never has to catch exceptions for normal cases. |
| **Exploratory data review** | Reading the data with simple scripts and tables before modeling or prompting, to find gaps, edge cases and traps. |

---

## Findings from a first look at the data

From a quick analysis run while planning (the full review is Step 4):

| # | Finding | Why it matters |
|---|---|---|
| D1 | All 24 activities **parse cleanly** into `Activity` (times like `"2025-06-10 09:00"` are accepted, and all interests are valid). | No data fixes needed |
| D2 | Weather records carry a **`description`** (for example *"thunderstorm expected to roll in during the afternoon…"*) and `city`/`date`, but our `Weather` model only keeps temperature, unit and condition. | The description is exactly what the **LLM-judge weather eval** (Phase 4) needs. See Step 1. |
| D3 | Inclement days are **06-12 (thunderstorm), 06-13 and 06-14 (rainy)**. On those days most activities are **outdoor** (hiking, gardening, outdoor art). | That's where the agent is most likely to make bad picks, and where the weather eval earns its keep. |
| D4 | Several descriptions mention a **rain fallback** (for example *"in case of rain, we move indoors to the Community Gym"*). | A keyword "outdoor = bad in rain" rule would be wrong, which justifies an LLM judge rather than a regex. |
| D5 | Interest **`theatre` never appears** in any activity. `sports` and `comedy` appear only once. | A traveler who likes theatre can never be matched, so the agent must handle "no match" gracefully. Worth a UI hint later. |
| D6 | `rainy_days_vacation_info()` (hiking, photography, sports on 06-12 → 06-14) matches **almost only outdoor** activities. | A deliberately hard sample: the "right" answer may be fewer activities or indoor picks outside the traveler's interests. |
| D7 | Prices range **15–25**; all 24 activities together cost 393. Activities never overlap within a day (4 time slots per day). | Budget evals and the cost rule (plain sum) are simple to compute and test. |

---

## Steps

### Step 1 – `WeatherForecast` model
**Purpose:** keep the weather `description`, `date` and `city` (D2) without changing the `Weather` shape the agent must produce in `TravelPlan`.
**Output:** `agentsville/models.py`, a new class.
**Depends on:** Phase 2 models.

```python
class WeatherForecast(Weather):       # inherits temperature, temperature_unit, condition
    date: datetime.date
    city: str
    description: str
```
- **Inheritance:** a `WeatherForecast` *is a* `Weather` with extra fields. Where a `Weather` is needed (for example `ItineraryDay.weather`), we can build one from the forecast's base fields.
- `TravelPlan` / `ItineraryDay` stay **unchanged**, so `sample_plan.json` keeps validating.

### Step 2 – Mock API module
**Purpose:** the single access point to weather and activity data.
**Output:** `agentsville/data_api.py`.
**Depends on:** Step 1.

| Function | Returns | "Not found" |
|---|---|---|
| `get_weather(date, city="AgentsVille")` | `WeatherForecast \| None` | `None` (unknown date or city) |
| `get_activities(date, city="AgentsVille")` | `list[Activity]`, sorted by start time | `[]` |
| `get_weather_for_range(start, end, city=…)` | `dict[date, WeatherForecast]` (bulk) | missing dates simply absent |
| `get_activities_for_range(start, end, city=…)` | `dict[date, list[Activity]]` (bulk) | dates with no activities → `[]` |
| `get_activity_by_id(activity_id)` | `Activity \| None` | `None` |
| `is_inclement(forecast)` | `bool`: condition in `INCLIMATE_WEATHER_CONDITIONS` | – |

Design details:
- **Inputs:** `date` accepts a `datetime.date` *or* an ISO string (`"2025-06-12"`), because the LLM will pass strings through tools later. City matching is case-insensitive, like `VacationInfo`.
- **Bulk functions** validate `start <= end` and raise `ValueError` otherwise (a programming error, not a "not found").
- **Indexes built once** with `functools.cache`: weather by date, activities by date, activities by ID. Raw data is converted to models a single time.
- **Returned lists are fresh copies**, so a caller can't modify the cached data by accident.
- `get_activity_by_id` is added now because Phase 4 (hallucination eval) and Phase 5 (`get_activity_by_id_tool`) both need it.

### Step 3 – Tests (Layer A)
**Purpose:** pin down the API's behavior so later phases can rely on it.
**Output:** `tests/test_data_api.py`.
**Depends on:** Step 2.

| Area | Cases |
|---|---|
| Weather | `get_weather("2025-06-12")` → thunderstorm with description; a `date` object works too; `"2025-06-09"` → `None`; `city="Paris"` → `None`; `"agentsville"` works |
| Activities | 4 per day, sorted by start time, all on the requested date; unknown date → `[]`; other city → `[]` |
| Bulk | 06-10 → 06-12 returns 3 days; `start > end` → `ValueError`; a range wider than the data returns only known dates |
| By ID | known ID returns the matching `Activity`; unknown ID → `None` |
| Inclement | 06-12/13/14 → `True`; 06-10/11/15 → `False` |
| Isolation | mutating a returned list doesn't affect the next call |
| Coverage | every activity is reachable through `get_activities` (24 total) |

### Step 4 – Manual data review
**Purpose:** `goal.md` asks us to *review the data manually*. A small script prints the tables, and we write down the conclusions.
**Output:** `scripts/review_data.py` (prints the tables) and `plan/03-data-access/data-review.md` (findings, written from the script output).
**Depends on:** Step 2. The script uses the new API, which also proves the API is convenient to use.

The script prints:
1. **Daily overview:** date, condition, temperature, inclement flag, number of activities, price range.
2. **Activity table:** ID, time slot, price, interests, and a rough *outdoor/indoor/fallback* hint from keywords (clearly labeled as a hint, D4).
3. **Interest coverage:** how many activities per interest, and which days. Highlights interests with 0 or 1 matches (D5).
4. **Sample check:** for each sample in `agentsville/samples.py`, the activities matching each traveler's interests on each trip day, plus the inclement days.

`data-review.md` records D1–D7 plus anything new, and a short **"implications"** list for Phase 4 (evals) and Phase 6 (agent prompt).

### Step 5 – Documentation
**Purpose:** keep `CLAUDE.md` accurate.
**Output:** `CLAUDE.md` architecture section.
**Depends on:** Steps 1–4.
- Add `agentsville/data_api.py` (the only module that reads `data/data.py`; functions, `None`/`[]` conventions) and `WeatherForecast`.
- Add a rule: *"Evals, tools and agent must read data through `data_api`, never `data.data` directly."*

---

## Verification (definition of done)

```bash
ruff check .
pytest                          # all tests pass, including tests/test_data_api.py
python scripts/review_data.py   # prints the four review tables
```
Plus `data-review.md` written, and green `CI / lint` + `CI / test` on the PR.

---

## Decisions (all recommendations accepted)

| # | Question | My recommendation |
|---|---|---|
| Q1 | Add `WeatherForecast` (subclass with `date`, `city`, `description`), or add an optional `description` to `Weather` itself? | **Subclass.** `TravelPlan`'s shape stays unchanged, and the agent doesn't have to copy long descriptions into the plan. |
| Q2 | "Not found" style: return `None` / `[]` (as above), or raise a `DataNotFoundError`? | **`None` / `[]`.** Missing data is a normal answer, not an error. The Phase 5 tools turn it into a clear observation for the LLM. |
| Q3 | Should the review script's indoor/outdoor *hint* become real data (an `is_outdoor` field)? | **No.** Keep it as a review aid only. The judgment belongs to the Phase 4 LLM-judge eval (D4). |
| Q4 | One commit for the phase? | Yes |
| Q5 | May I create branch `feature/phase-3-data-access` from `main`? | Yes |
