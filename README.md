# AgentsVille Trip Planner (ReAct)

<!-- Phase 0 – Step 8: project overview and setup instructions -->
<!-- Phase 1 – Step 2: CI status badge -->
[![CI](https://github.com/jansidv99-lab/trip_palnner_ReAct/actions/workflows/ci.yml/badge.svg)](https://github.com/jansidv99-lab/trip_palnner_ReAct/actions/workflows/ci.yml)

An LLM agent that plans a day-by-day trip to the fictional city of **AgentsVille**. It uses the
**ReAct** cycle (THOUGHT → ACTION → OBSERVATION): the model reasons, calls tools (weather,
activities, calculator, evals), reads the results, and repeats until it returns a validated
`TravelPlan`.

- Requirements: [`goal.md`](goal.md)
- Roadmap: [`plan/00-master/master-plan.md`](plan/00-master/master-plan.md)

> Status: **Phase 6 – ReAct agent** works end to end from the command line. The Streamlit UI comes in Phase 8.

## Setup

Requires Python 3.11.

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate              # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env              # then fill in OPENAI_API_KEY (macOS/Linux: cp)
```

## Check the setup

```bash
python scripts/smoke_llm.py         # one tiny LLM call: prints reply, latency, tokens, est. cost
```

## Run the agent

```bash
python scripts/run_agent.py                  # plan the sample trip, printing every THOUGHT / ACTION / OBSERVATION
python scripts/run_agent.py --sample rainy   # a harder trip on the rainy days
python scripts/run_evals.py                  # evaluate sample_plan.json
```

Each run is appended to `logs/agent_runs.jsonl` and typically costs 1–3 cents.

## Tests and lint

```bash
pytest                              # unit tests (no network)
pytest -m llm                       # tests that call the real LLM (small cost)
ruff check .                        # lint
```

The same lint and unit tests run in CI (GitHub Actions) on every pull request and push to `main`.

## Project layout

```
agentsville/   application code (config, LLM client, models, data API, evals, tools, agent)
prompts/       versioned system prompts (prompts/itinerary/v1.md)
data/          mock activity and weather data (the "APIs")
scripts/       manual helper scripts
tests/         pytest suite
plan/          phase-by-phase plan documents
```
