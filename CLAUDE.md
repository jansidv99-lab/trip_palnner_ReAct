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
python scripts/run_agent.py [--sample rainy]  # real agent run, printed step by step
python scripts/run_experiment.py --check-expected   # replay golden v1.0.0 (free) + repeatability check
python scripts/run_experiment.py --mode record      # re-record cassettes after prompt/agent changes (~$0.20)
python scripts/compare_experiments.py experiments/A experiments/B
```

CI (`.github/workflows/ci.yml`) runs two jobs on every PR and push to `main`: `lint` (`ruff check .`) and `test` (`pytest`). Both are required checks on `main`. `llm`-marked tests never run in CI, and CI uses no secrets.
`.github/workflows/eval-gate.yml` (`Evals / eval-replay`, informational until Phase 11) replays the
committed cassettes and fails if replayed results differ from `expected_results.jsonl`. Run both locally before committing.

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
- `agentsville/tools.py`: the agent's tools. `build_default_registry()` returns a `ToolRegistry` with 7 tools: `calculator_tool`, `get_weather_for_date_tool`, `get_activities_by_date_tool`, `get_activity_by_id_tool`, `filter_activities_by_interest_tool`, `run_evals_tool` and `final_answer_tool`.
  - `registry.execute(name, arguments, ToolContext)` returns a `ToolResult` (`observation`, `is_error`, `is_final`, `travel_plan`).
  - It **never raises**: unknown tools, Pydantic argument errors and exceptions inside a tool become `ERROR: …` observations.
  - Data observations are compact JSON with every model field, so the agent can copy them verbatim (eval E4).
  - `ToolContext` carries `vacation_info`, `llm` and `include_llm_evals`, the run-specific inputs `run_evals_tool` needs.
  - `final_answer_tool` is the only tool that sets `is_final=True`.
  - The calculator uses an AST whitelist (`safe_eval`), never `eval()`.
  - `registry.catalog()` renders the tool list for the system prompt. `travel_plan` arguments refer to a TravelPlan schema the prompt must include.
  - **To add a tool:** define a Pydantic args model and a `(args, context) -> ToolResult` function, then add a `Tool(...)` entry in `build_default_registry()`.
  - `scripts/try_tools.py [--catalog] [--llm]` runs sample ACTIONs through the registry.
- `agentsville/agent.py`: `ItineraryAgent(llm, ...).run(vacation_info) -> AgentRun`, the ReAct loop.
  - **Reply format:** each reply is ONE JSON object `{"thought": ..., "action": {"tool_name": ..., "arguments": {...}}}`, requested with `json_mode=True`. We switched from free-text `THOUGHT:/ACTION:` because gpt-4o-mini miscounted brackets in the ~6k-char final plan and looped until `max_steps`; JSON mode guarantees valid JSON. `parse_agent_reply` raises `ReplyParseError` with guidance, which the loop sends back as the observation.
  - **Each step:** the tool's observation goes back as a user message `"OBSERVATION: …"`.
  - **Guardrail:** a `final_answer_tool` plan that fails the deterministic evals is rejected, up to `max_final_rejections=2`. After that it's accepted, and the failure shows in `final_eval_report`.
  - **Stop reasons:** `final_answer` | `max_steps` (default 20) | `llm_error`.
  - **Final evals:** the accepted plan always gets `run_all_evals` (including the judge when `include_llm_evals`).
  - **Judge cost metering:** judge calls made by evals go through `_MeteredLLM`, so `AgentRun.judge_calls` and `judge_cost_usd` are counted in `total_cost_usd`.
  - **`AgentRun` is the trace:** prompts, `steps: list[AgentStep]`, stop reason, plan, eval report, and computed token/latency/cost totals. It replaced the old single-call `PromptTrace`.
  - **Run log:** each run is appended as one JSON line to `logs/agent_runs.jsonl` (git-ignored; `log_path=None` disables it).
- `agentsville/prompts.py` + `prompts/itinerary/<version>.md`: the system prompt is a versioned file selected by `PROMPT_VERSION`. `{{TOOL_CATALOG}}` and `{{TRAVEL_PLAN_SCHEMA}}` are filled by plain string replacement (JSON braces break `str.format`), and HTML comments are stripped. Agent tests use `ScriptedLLM` in `tests/test_agent.py`, which replays JSON replies and answers judge calls separately.
- `scripts/run_agent.py [--sample default|tight|rainy] [--model M] [--max-steps N] [--no-log]` shows a real run step by step (~1–3 cents, 1–2 min).
- `agentsville/harness/` (Phase 7, B0): the Layer B experiment harness.
  - `dataset.py`: golden datasets in `evals/datasets/golden/<version>/` (`cases.jsonl`, `manifest.json`, `CHANGELOG.md`).
    - **Released versions are immutable.** `load_golden` verifies the cases' sha256 and a fingerprint of `data/data.py`, and refuses to load on a mismatch.
    - Never edit a released version: run a new `scripts/build_golden_dataset.py`-style build for v1.1.0/v2.0.0.
    - Labels: `must_avoid_activity_ids`, `ambiguous_activity_ids`, `uncoverable_travelers`, `max_affordable_activities`, `expected_behavior`.
  - `recording.py`: `CassetteLLM(mode, cassette, llm, default_model)` is a drop-in for `LLMClient.chat`, with modes `live` | `record` | `replay`.
    - Keys are the sha256 of (model, LF-normalized messages, temperature, json_mode). A repeated request is stored per occurrence, and recorded LLM errors replay as `LLMError`.
    - A replay miss raises `CassetteMissError`, which means the prompt, agent code or data changed. Re-record with `--mode record` and commit the new cassettes.
  - `runner.py`: `run_experiment(ExperimentConfig, ...)` runs cases × repeats in a thread pool, with one cassette per (case, repeat) under `evals/cassettes/golden-<ver>/<config_id>/`.
    - Record mode also writes `expected_results.jsonl`.
    - Outputs go to the git-ignored `experiments/<ts>__<config_id>/`: `config.json`, `results.jsonl`, `runs.jsonl`, `summary.json`, `report.md`.
  - `metrics.py`: Wilson 95% intervals and `ExperimentSummary`.
    - Goal completion = `final_answer` AND all error graders passed.
    - A run without a plan counts as a failure for every grader.
  - `report.py`: `render_report` builds the markdown report. `compare` refuses different dataset versions or hashes unless `force=True`, and calls a difference "likely real" only when the intervals don't overlap.
  - **Line endings matter:** `.gitattributes` forces LF for `prompts/**` and `evals/**`, and `prompts.py` LF-normalizes too. Hashes must match between Windows (`core.autocrlf=true`) and Linux CI.
  - Harness tests use `tests/harness_fakes.py` (`ConversationFake`, `make_dataset`).
- Always read text files with `encoding="utf-8"`. The Windows default (cp1252) garbles the data's em dashes and curly quotes, and CI on Linux won't catch it.
- `scripts/review_data.py` prints the data review tables. Findings and their implications for evals and the agent prompt are in `plan/03-data-access/data-review.md`.
- `data/data.py`: raw mock data. Tools must not invent data beyond it.
  - `ACTIVITY_CALENDAR`: 24 activities in AgentsVille, 2025-06-10 to 2025-06-15. IDs follow `event-YYYY-MM-DD-N`; the hallucination eval checks plan activities against these IDs.
  - `WEATHER_FORECAST`: one entry per date.
  - `INCLIMATE_WEATHER_CONDITIONS = ["thunderstorm", "rainy"]`: drives the weather-suitability eval (outdoor activities on these days should be flagged).
- Agent flow (planned): the LLM emits THOUGHT + a single ACTION tool call → Python parses it, runs the tool, returns an OBSERVATION string → repeat until the LLM calls `final_answer_tool`, whose payload is parsed into `TravelPlan`.

