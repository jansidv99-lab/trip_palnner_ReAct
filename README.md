# AgentsVille Trip Planner (ReAct)

<!-- Phase 0 – Step 8: project overview and setup instructions -->

An LLM agent that plans a day-by-day trip to the fictional city of **AgentsVille**. It uses the
**ReAct** cycle (THOUGHT → ACTION → OBSERVATION): the model reasons, calls tools (weather,
activities, calculator, evals), reads the results, and repeats until it returns a validated
`TravelPlan`.

- Requirements: [`goal.md`](goal.md)
- Roadmap: [`plan/00-master/master-plan.md`](plan/00-master/master-plan.md)

> Status: **Phase 0 – Foundations** (config, LLM client, tests). The agent and UI come in later phases.

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

## Tests and lint

```bash
pytest                              # unit tests (no network)
pytest -m llm                       # tests that call the real LLM (small cost)
ruff check .                        # lint
```

## Project layout

```
agentsville/   application code (config, LLM client, models; later evals, tools, agent)
data/          mock activity and weather data (the "APIs")
scripts/       manual helper scripts
tests/         pytest suite
plan/          phase-by-phase plan documents
```
