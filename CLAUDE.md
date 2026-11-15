# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

@goal.md

## Workflow rules

1. **Plan first:** before every step, write a detailed plan doc under `plan/` that explains each topic clearly. Keep plans organized by stage in numbered folders, e.g. `plan/00-master/`, `plan/01-vacation-info/`, `plan/02-tools/`.plans will have steps with clear purpose , output and dependence_on .
   Add new stage folders whenever needed, keeping the numeric prefix and never mixing topics.
2. **Review:** ask the user to review each plan doc before implementing it.
3. **Permission:** always ask for permission before making any change to code.
4. **Phased implementation:** start with the master plan, then plan the code phase by phase and step by step, stating each step's purpose and dependencies.
5. **Commits, new branch creation PRs, merges:** always ask for permission before every commit, new branch creation ,pull request, and merge.
6. **Branch naming:** use professional, descriptive names prefixed by type, e.g. `feature/streamlit-itinerary-form`, `fix/llm-timeout-handling`, `bugfix/date-parsing`, `chore/cloudrun-dockerfile`, `docs/master-plan`.
7. **Phase comments in code:** mark which phase/step produced the code, at the top of each new file and on each new function/class, for future reference:
   ```python
   # Phase 2 – Step 3: <purpose of this code>
   ```
8. **Learning-oriented:** this project is a hands-on learning exercise. Go step by step, explain new concepts as they come up, and never build everything in one go.
9. **Sync before new work:** `git switch main && git pull` (the repo is configured with `pull.ff=only` and `fetch.prune=true`), confirm `git status` says "up to date with 'origin/main'", then create the new branch from `main`. After a PR is merged: `git switch main && git pull && git branch -d <merged-branch>`.
10. **GitHub activities:** do not perform any GitHub-related activities (push, opening/merging PRs, remote branch operations); the developer performs them manually. Always provide the exact commands to execute. Local git (switch, branch, pull, commit with permission per rule 5) is fine.

## Commands

Python 3.11 in a local `.venv` (Windows paths shown; run everything from the repo root):

```bash
py -3.11 -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt          # runtime deps + pytest + ruff

ruff check .                                 # lint (config in ruff.toml)
pytest                                       # unit tests; `llm`-marked tests are skipped by default
pytest tests/test_config.py::test_prompt_version_lowercased   # single test
pytest -m llm                                # opt-in tests that call the real LLM (cost money)
python scripts/smoke_llm.py [model]          # manual check that key/endpoint/model work
```

CI (`.github/workflows/ci.yml`) runs two jobs on every PR and push to `main`: `lint` (`ruff check .`) and `test` (`pytest`). Both are required checks on `main`. `llm`-marked tests never run in CI, and CI uses no secrets. Run both locally before committing.

`pytest.ini` sets `pythonpath = .`, registers the `llm` marker and skips it by default. Tests never touch the network unless marked `@pytest.mark.llm`; unit tests use `FakeOpenAIClient` from `tests/conftest.py` and `load_settings({...})` instead of the real `.env`.

## Configuration

`.env` (loaded via python-dotenv) provides: `OPENAI_API_KEY`, `OPENAI_BASE_URL` (OpenAI-compatible endpoint, may not be api.openai.com), `MODEL`, `PROMPT_VERSION`, `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `REGION`, `GIT_REPO`. Use the existing GCP project/region; don't create new ones.

## Architecture

Application code lives in the `agentsville/` package (imports: `from agentsville.models import ...`); mock data stays in `data/` (`from data.data import ...`); `pytest` resolves imports via `pythonpath = .` in `pytest.ini`.

- `agentsville/config.py`: `get_settings()` (cached) loads `.env` then real env vars (env wins) into a frozen `Settings`; raises `ConfigError` listing missing vars. `load_settings(mapping)` is the pure, testable core.
- `agentsville/llm.py`: `LLMClient.chat()` is the **only** place that calls the OpenAI SDK. Returns `LLMResponse` (text, latency, tokens, estimated cost) and wraps all SDK failures in `LLMError`. Inject a fake via `LLMClient(settings, client=...)`. `chat(..., json_mode=True)` sends `response_format={"type": "json_object"}`. The Vocareum proxy accepts `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-4.1`; `gpt-4.1-nano` returns 404.
- `agentsville/models.py`: the single source of truth for data shapes, shared by the agent, tools, evals, and UI.
  - Input: `VacationInfo` → `Traveler` → `Interest` (enum). Validators enforce: ≥ 1 traveler, ≥ 1 interest each, age 0–120, budget > 0, departure ≥ arrival, both dates within `TRIP_WINDOW_START`–`TRIP_WINDOW_END` (2025-06-10 → 06-15), and destination = `SUPPORTED_DESTINATION` (any casing, normalized to "AgentsVille"). Duplicate traveler names are allowed by design. The window constants are fixed, and `tests/test_models.py` checks they match `data/data.py`.
  - Output: `TravelPlan` → `ItineraryDay` → `ActivityRecommendation` → `Activity` + `Weather`. The agent's `final_answer_tool` must produce JSON that validates as `TravelPlan`; `sample_plan.json` is a reference example.
  - `PromptTrace`: one LLM call's prompts, raw reply, parsed plan, latency, tokens, and cost. Used for observability (QA layer C).
  - `OpenAIModel`: models selectable in the UI (`gpt-4o-mini` default, `gpt-4.1-mini`, `gpt-4.1`). Every member must have a price in `llm.PRICES_PER_1M_TOKENS` (enforced by a test). `config.MODEL` stays free-form.
- `agentsville/samples.py`: factory functions returning fresh `VacationInfo` objects. `sample_vacation_info()` matches `sample_plan.json` (Yuri + Hiro, 06-10 → 06-12, budget 130); `tight_budget_vacation_info()` and `rainy_days_vacation_info()` cover edge cases.
- `agentsville/data_api.py`: the mock weather and activity API, and the **only** module that reads `data/data.py`. Evals, tools and the agent must go through it.
  - Functions: `get_weather`, `get_activities`, `get_weather_for_range`, `get_activities_for_range`, `get_activity_by_id`, `is_inclement`.
  - Dates can be `date` objects or ISO strings; city matching is case-insensitive.
  - "Not found" returns `None` / `[]` (no exception). Range functions raise `ValueError` if start > end.
  - Lookup tables are built once with `functools.cache`; results are deep copies, so callers can't change the cached data.
  - Returns `WeatherForecast`, which is `Weather` plus `date`, `city` and `description`. The description feeds the LLM-judge weather eval; `TravelPlan` still uses plain `Weather`.
- `agentsville/evals.py`: `run_all_evals(request, plan, llm=None, include_llm=True)` returns an `EvalReport` (`passed`, `results: list[EvalResult]`, `summary()`, the compact text the agent reads as its observation).
  - **Severity:** only `"error"` evals decide `passed`; `"warning"` evals (`interest_coverage`, `activities_per_day`) are informational.
  - **Error evals:** `city_and_dates`, `total_cost_accurate`, `within_budget` (uses the *actual* price sum, not `plan.total_cost`), `no_hallucinated_activities` (every field must equal the `data_api` source, and the activity must be on its own date), `weather_matches_forecast`, `no_overlapping_activities`, and the LLM judge `weather_suitability`.
  - **The judge** (`gpt-4.1`, JSON mode) only runs for activities on inclement days. It **fails closed**: an unparseable reply or an LLM error counts as unsuitable.
  - Pass `include_llm=False` for free, offline runs; unit tests use a `FakeLLM` in `tests/test_evals.py`.
  - The judge's calibration cases live in `tests/test_evals_live.py` (`pytest -m llm`).
  - `scripts/run_evals.py [--no-llm] [--plan FILE]` prints a report against `sample_vacation_info()`.
- Always read text files with `encoding="utf-8"`. The Windows default (cp1252) garbles the data's em dashes and curly quotes, and CI on Linux won't catch it.
- `scripts/review_data.py` prints the data review tables. Findings and their implications for evals and the agent prompt are in `plan/03-data-access/data-review.md`.
- `data/data.py`: raw mock data. Tools must not invent data beyond it.
  - `ACTIVITY_CALENDAR`: 24 activities in AgentsVille, 2025-06-10 to 2025-06-15. IDs follow `event-YYYY-MM-DD-N`; the hallucination eval checks plan activities against these IDs.
  - `WEATHER_FORECAST`: one entry per date.
  - `INCLIMATE_WEATHER_CONDITIONS = ["thunderstorm", "rainy"]`: drives the weather-suitability eval (outdoor activities on these days should be flagged).
- Agent flow (planned): the LLM emits THOUGHT + a single ACTION tool call → Python parses it, runs the tool, returns an OBSERVATION string → repeat until the LLM calls `final_answer_tool`, whose payload is parsed into `TravelPlan`.

