# Phase 3 – Step 4: Data review

> Source: `python scripts/review_data.py` (reads through `agentsville/data_api.py`)
> Data: `data/data.py`, AgentsVille, 2025-06-10 → 2025-06-15

## 1. Daily overview

| Date | Condition | Temp | Inclement | Activities | Prices |
|---|---|---|---|---|---|
| 06-10 | clear | 31 °C | – | 4 | 15–20 |
| 06-11 | partly cloudy | 34 °C | – | 4 | 15–25 |
| 06-12 | **thunderstorm** (afternoon, per description) | 28 °C | **yes** | 4 | 15–20 |
| 06-13 | **rainy** | 15 °C | **yes** | 4 | 15 |
| 06-14 | **rainy** | 14 °C | **yes** | 4 | 15 |
| 06-15 | sunny | 31 °C | – | 4 | 15 |

- Each day has 4 activities in **non-overlapping** time slots (morning, lunch, afternoon, evening).
- All 24 activities cost 393 in total. Prices are 15–25, and from 06-13 on every activity costs 15.

## 2. Findings

| # | Finding | Evidence |
|---|---|---|
| D1 | Data is clean: all 24 activities and 6 forecasts validate into `Activity` / `WeatherForecast`. | `tests/test_data_api.py` |
| D2 | Weather descriptions add detail the condition lacks: 06-12's storm arrives **in the afternoon**, so a morning outdoor event may be fine. | 06-12 description |
| D3 | Half the window (06-12 → 06-14) is inclement, and **most of those activities are outdoor**: 06-13 has 3 of 4 outdoor, 06-14 has 3 of 4. | table 2 |
| D4 | **Rain fallbacks exist.** `event-2025-06-10-2` ("in case of rain, we move indoors to the Community Gym") and `event-2025-06-12-1` ("will move indoors to the adjacent Harmony Hall") stay acceptable in rain. | descriptions |
| D5 | **Keyword rules mislabel activities:** `event-2025-06-14-3` is held indoors but tagged outdoor ("s**park**" matches "park"); `event-2025-06-11-2` is an *outdoor* art gallery but tagged indoor ("gallery"). | table 2 vs descriptions |
| D6 | Interest coverage is uneven: **`theatre` never appears**; `sports` and `comedy` appear once each. Art and music are the most common (7 each). | table 3 |
| D7 | `sample_vacation_info()` has good matches every day. On thunderstorm 06-12, Yuri's only match is indoor (`06-12-3`) and Hiro's only match is the picnic with an indoor fallback (`06-12-1`). This agrees with `sample_plan.json`, which picks only `06-12-3` that day. | table 4 |
| D8 | `tight_budget_vacation_info()` (budget 40): at most **2 activities** fit for the whole 3-day trip (2 × 15–20). | prices |
| D9 | `rainy_days_vacation_info()` (Mika: hiking, photography, sports; 06-12 → 06-14): **every** interest match is outdoor, with no rain fallback. A good plan must pick indoor activities outside Mika's interests, or fewer activities. | table 4 |
| D10 | 06-11 is the hottest day (34 °C) but not "inclement" under `INCLIMATE_WEATHER_CONDITIONS`. Heat isn't covered by the rule. | table 1 |

## 3. Implications

**For Phase 4 – Evals**
- The weather-suitability eval must be an **LLM judge** reading the full activity description *and* the forecast description (D2, D4, D5). Keyword matching is demonstrably wrong.
- Test cases for the judge:
  - `06-13-1` outdoor hike in the rain → **not OK**
  - `06-12-1` picnic with indoor fallback in a thunderstorm → **OK**
  - `06-14-3` indoor evening event on a rainy day → **OK**
- The cost and budget evals are simple sums (D8 gives a crisp tight-budget test).
- Interest coverage can't always be 100% (D6, D9). The eval should *report* coverage, not fail hard when no matching activity exists.

**For Phase 6 – Agent prompt**
- Tell the agent to read the **weather description**, not just the condition, and to prefer indoor or rain-fallback activities on inclement days.
- Tell it that recommending activities outside a traveler's interests is acceptable (with a reason) when weather rules out the matching ones (D9).
- Heat (D10) is out of scope for now. Revisit if the judge flags it.

**For Phase 8 – UI**
- Show a hint when a selected interest has no activities in the window (theatre).
