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
5. **Commits, PRs, merges:** always ask for permission before every commit, pull request, and merge.
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

`pytest.ini` sets `pythonpath = .`, registers the `llm` marker and skips it by default. Tests never touch the network unless marked `@pytest.mark.llm`; unit tests use `FakeOpenAIClient` from `tests/conftest.py` and `load_settings({...})` instead of the real `.env`.

## Configuration

`.env` (loaded via python-dotenv) provides: `OPENAI_API_KEY`, `OPENAI_BASE_URL` (OpenAI-compatible endpoint, may not be api.openai.com), `MODEL`, `PROMPT_VERSION`, `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `REGION`, `GIT_REPO`. Use the existing GCP project/region; don't create new ones.

## Architecture

Application code lives in the `agentsville/` package (imports: `from agentsville.models import ...`); mock data stays in `data/` (`from data.data import ...`); `pytest` resolves imports via `pythonpath = .` in `pytest.ini`.

- `agentsville/config.py`: `get_settings()` (cached) loads `.env` then real env vars (env wins) into a frozen `Settings`; raises `ConfigError` listing missing vars. `load_settings(mapping)` is the pure, testable core.
- `agentsville/llm.py`: `LLMClient.chat()` is the **only** place that calls the OpenAI SDK. Returns `LLMResponse` (text, latency, tokens, estimated cost) and wraps all SDK failures in `LLMError`. Inject a fake via `LLMClient(settings, client=...)`. The Vocareum proxy accepts `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-4.1`; `gpt-4.1-nano` returns 404.
- `agentsville/models.py`: the single source of truth for data shapes, shared by the agent, tools, evals, and UI.
  - Input: `VacationInfo` → `Traveler` → `Interest` (enum). Validators enforce departure ≥ arrival, budget > 0, and ≥ 1 interest per traveler.
  - Output: `TravelPlan` → `ItineraryDay` → `ActivityRecommendation` → `Activity` + `Weather`. The agent's `final_answer_tool` must produce JSON that validates as `TravelPlan`; `sample_plan.json` is a reference example.
  - `PromptTrace`: one LLM call's prompts, raw reply, parsed plan, latency, tokens, and cost. Used for observability (QA layer C).
  - `OpenAIModel`: models selectable in the UI (gpt-4.1 / -mini / -nano).
- `data/data.py`: mocked "APIs". Tools must read from here and must not invent data.
  - `ACTIVITY_CALENDAR`: 24 activities in AgentsVille, 2025-06-10 to 2025-06-15. IDs follow `event-YYYY-MM-DD-N`; the hallucination eval checks plan activities against these IDs.
  - `WEATHER_FORECAST`: one entry per date.
  - `INCLIMATE_WEATHER_CONDITIONS = ["thunderstorm", "rainy"]`: drives the weather-suitability eval (outdoor activities on these days should be flagged).
- Agent flow (planned): the LLM emits THOUGHT + a single ACTION tool call → Python parses it, runs the tool, returns an OBSERVATION string → repeat until the LLM calls `final_answer_tool`, whose payload is parsed into `TravelPlan`.

