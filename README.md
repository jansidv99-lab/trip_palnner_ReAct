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

> Status: the ReAct agent works end to end, from the command line and in a Streamlit web app. The
> eval harness (Phase 7 – B0), grounding (B1), constraints & completion (B2) and relevancy &
> reasoning (B3) evals are done. Deployment to Cloud Run (Phase 13) is being set up.

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

## Run the web app

```bash
streamlit run app.py                # http://localhost:8501
```

Fill in travelers, dates and budget (pre-filled with the sample trip) and click **Generate
itinerary**. You see every agent step live, then the day-by-day plan, the eval report, a free
quality panel (the B1–B3 code checks), and can leave 👍 / 👎 feedback (`logs/feedback.jsonl`).

## Deployment (Cloud Run)

Every merge to `main` runs [`deploy.yml`](.github/workflows/deploy.yml): lint, tests, a container
check and the eval replay must pass, then the image is built, pushed to Artifact Registry and
deployed to Cloud Run. GitHub signs in to GCP with Workload Identity Federation (no keys), the
OpenAI key and the app passcode come from Secret Manager, and the public URL asks for the passcode
because every run spends OpenAI credit.

- One-time setup: [`plan/13-cd/gcp-setup.md`](plan/13-cd/gcp-setup.md)
- Roll back, rotate secrets: [`plan/13-cd/runbook.md`](plan/13-cd/runbook.md)

## Experiments (golden dataset)

```bash
python scripts/run_experiment.py --check-expected     # replay the recorded golden v1.0.0 run: free, deterministic
python scripts/run_experiment.py --mode live --repeats 3   # fresh runs to see variance (~$0.60)
python scripts/compare_experiments.py experiments/<A> experiments/<B>
```

Each experiment writes a `report.md` with goal completion and per-grader pass rates (with 95% confidence intervals), cost, steps and latency. It also includes the B1 grounding section: activity and plan hallucination rates, trajectory grounding, reason references, and ungrounded reasons from the calibrated LLM judge.

The B2 section answers "does the plan satisfy the traveler's hard constraints?": a violation rate per constraint (city/dates, budget, cost accuracy, overlaps, weather vs the LLM judge and vs human labels) over the plans produced, how often the guardrail had to reject a final answer, whether an impossible request (nothing affordable) gets a correct empty plan, how well the weather judge agrees with human labels, and a **failure taxonomy** explaining every run that didn't complete (for example `eval_loop:total_cost_accurate`). See [`plan/09-b2-constraints/b2-findings.md`](plan/09-b2-constraints/b2-findings.md).

The B3 section answers "is the plan relevant to these travelers, and is its reasoning faithful?": a calibrated LLM judge scores how well each traveler is served relative to what was possible, code checks that the agent followed its procedure (weather and activities looked up for every day, the total computed by the calculator from the plan's own prices, the submitted plan verified first), and a second calibrated judge checks that every THOUGHT agrees with its ACTION. See [`plan/10-b3-relevancy-reasoning/b3-findings.md`](plan/10-b3-relevancy-reasoning/b3-findings.md).

```bash
python scripts/grade_runs.py experiments/<exp>            # grade stored runs without re-running the agent
python scripts/calibrate_judge.py --check-expected        # how well each LLM judge agrees with human labels
python scripts/run_experiment.py --check-thresholds       # pass/fail against evals/thresholds.toml
python scripts/run_experiment.py --update-expected        # after a code-grader change: refresh expected results (free)
```

## Tests and lint

```bash
pytest                              # unit tests (no network)
pytest -m llm                       # tests that call the real LLM (small cost)
ruff check .                        # lint
```

The same lint and unit tests run in CI (GitHub Actions) on every pull request and push to `main`,
plus a check that the production container builds and starts.

## Project layout

```
app.py         Streamlit web app (thin; logic in agentsville/ui/)
agentsville/   application code (config, LLM client, models, data API, evals, tools, agent, ui)
prompts/       versioned system prompts (prompts/itinerary/v1.md)
evals/         golden datasets (versioned, immutable) and recorded LLM cassettes
data/          mock activity and weather data (the "APIs")
scripts/       manual helper scripts
tests/         pytest suite
plan/          phase-by-phase plan documents
```
