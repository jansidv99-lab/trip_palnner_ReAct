# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project goal

@goal.md

## Workflow rules

1. **Plan first:** before every step, write a detailed plan doc under `plan/` that explains each topic clearly. Keep plans organized by stage in numbered folders, e.g. `plan/00-master/`, `plan/01-vacation-info/`, `plan/02-tools/`.plans will have steps with clear purpose , output and dependence_on .
   Add new stage folders whenever needed, keeping the numeric prefix and never mixing topics.
   Each stage's `plan.md` opens with a header: `Status:` (e.g. `DRAFT – awaiting review`), the proposed branch, a link to the master plan, and `Depends on:` earlier phases.
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
9. **Sync before new work:** `git switch main && git pull` (Git Bash; in PowerShell 5.1, which has no `&&`: `git switch main; if ($?) { git pull }`) (the repo is configured with `pull.ff=only` and `fetch.prune=true`), confirm `git status` says "up to date with 'origin/main'", then create the new branch from `main`. After a PR is merged: `git switch main && git pull && git branch -d <merged-branch>`.
10. **GitHub activities:** do not perform any GitHub-related activities (push, opening/merging PRs, remote branch operations); the developer performs them manually. Always provide the exact commands to execute. Local git (switch, branch, pull, commit with permission per rule 5) is fine.

## Current state

Phases 0–10 are merged (agent, tools, evals, harness B0, B1–B3 graders). **Phase 12 – Streamlit UI**
(`plan/12-streamlit-ui/plan.md`) is in progress on `feature/phase-12-streamlit-ui`. Roadmap order
(master plan v5): 12 → 13 (Cloud Run CD) → 11 (B4) → 14–18. Phase numbers are stable IDs, not
execution order, so "until Phase 11" below means after 12 and 13.

## Commands

Python 3.11 in a local `.venv` (Windows paths shown; run everything from the repo root). The shell
lines below are for Git Bash; in PowerShell 5.1 replace `&&` with `;` and activate with
`.venv\Scripts\Activate.ps1`.

```bash
py -3.11 -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt          # runtime deps + pytest + ruff
copy .env.example .env                       # then fill in OPENAI_API_KEY etc.

ruff check .                                 # lint: line length 100, rules E,F,I,B,UP (data/data.py exempt from E501)
pytest                                       # unit tests; `llm`-marked tests are skipped by default
pytest tests/test_config.py::test_prompt_version_lowercased   # single test
pytest -m llm                                # opt-in tests that call the real LLM (cost money)
python scripts/smoke_llm.py [model]          # manual check that key/endpoint/model work
python scripts/run_agent.py [--sample rainy]  # real agent run, printed step by step
streamlit run app.py                         # the Streamlit UI (Phase 12)
python scripts/run_evals.py [--no-llm] [--plan FILE]  # eval report for a plan vs sample_vacation_info()
python scripts/try_tools.py [--catalog] [--llm]       # sample ACTIONs through the tool registry
python scripts/review_data.py                # data review tables (see plan/03-data-access/data-review.md)
python scripts/run_experiment.py --check-expected   # replay golden v1.0.0 (free) + repeatability check
python scripts/run_experiment.py --mode record      # re-record cassettes after prompt/agent changes (~$0.20)
python scripts/run_experiment.py --mode live --repeats 3   # fresh runs to measure variance (~$0.60)
python scripts/compare_experiments.py experiments/A experiments/B
python scripts/run_experiment.py --check-thresholds  # + evals/thresholds.toml verdicts (exit 4)
python scripts/run_experiment.py --grade-mode record # replay agent, re-record grading only
python scripts/run_experiment.py --record-graders traveler_relevancy  # record ONE judge, replay the rest
python scripts/run_experiment.py --update-expected   # code-grader change only: rewrite expected results ($0)
python scripts/grade_runs.py experiments/<exp>      # grade stored runs (no agent re-run)
python scripts/calibrate_judge.py --check-expected  # replay every judge vs its human labels (CI)
python scripts/calibrate_judge.py --judge thought_action --mode record  # re-record one judge
python scripts/build_golden_dataset.py              # provenance script: builds a NEW golden version (bump version first)
python scripts/build_calibration_dataset.py         # provenance script: builds a NEW calibration version
python scripts/build_relevancy_calibration.py       # prints items for review; --write writes a NEW version
python scripts/build_thought_action_calibration.py  # same; needs experiments/live-v1-r3 (git-ignored)
```

CI (`.github/workflows/ci.yml`) runs two jobs on every PR and push to `main`: `lint` (`ruff check .`) and `test` (`pytest`). Both are required checks on `main`. `llm`-marked tests never run in CI, and CI uses no secrets.
`.github/workflows/eval-gate.yml` (`Evals / eval-replay`, informational until Phase 11) replays the
committed cassettes and fails if replayed results differ from `expected_results.jsonl`. It
also replays the judge calibration, and shows threshold verdicts (`continue-on-error` until B4). Run both locally before committing.

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
- `agentsville/tools.py`: the agent's tools. `build_default_registry()` returns a `ToolRegistry` with 7 tools: `calculator_tool`, `get_weather_for_date_tool`, `get_activities_by_date_tool`, `get_activity_by_id_tool`, `filter_activities_by_interest_tool`, `run_evals_tool` and `final_answer_tool`.
  - `registry.execute(name, arguments, ToolContext)` returns a `ToolResult` (`observation`, `is_error`, `is_final`, `travel_plan`).
  - It **never raises**: unknown tools, Pydantic argument errors and exceptions inside a tool become `ERROR: …` observations.
  - Data observations are compact JSON with every model field, so the agent can copy them verbatim (eval E4).
  - `ToolContext` carries `vacation_info`, `llm` and `include_llm_evals`, the run-specific inputs `run_evals_tool` needs.
  - `final_answer_tool` is the only tool that sets `is_final=True`.
  - The calculator uses an AST whitelist (`safe_eval`), never `eval()`.
  - `registry.catalog()` renders the tool list for the system prompt. `travel_plan` arguments refer to a TravelPlan schema the prompt must include.
  - **To add a tool:** define a Pydantic args model and a `(args, context) -> ToolResult` function, then add a `Tool(...)` entry in `build_default_registry()`.
- `agentsville/agent.py`: `ItineraryAgent(llm, ...).run(vacation_info) -> AgentRun`, the ReAct loop.
  - **Reply format:** each reply is ONE JSON object `{"thought": ..., "action": {"tool_name": ..., "arguments": {...}}}`, requested with `json_mode=True` (don't go back to free-text `THOUGHT:/ACTION:`: gpt-4o-mini breaks the brackets of the large final plan). `parse_agent_reply` raises `ReplyParseError` with guidance, which the loop sends back as the observation.
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
    - Never edit a released version: bump the version in `scripts/build_golden_dataset.py` (v1.1.0 for added cases, v2.0.0 for changed meaning) and add a CHANGELOG entry; `write_golden` refuses to overwrite.
    - Labels: `must_avoid_activity_ids`, `ambiguous_activity_ids`, `uncoverable_travelers`, `max_affordable_activities`, `expected_behavior`.
  - `recording.py`: `CassetteLLM(mode, cassette, llm, default_model)` is a drop-in for `LLMClient.chat`, with modes `live` | `record` | `replay`.
    - Keys are the sha256 of (model, LF-normalized messages, temperature, json_mode). A repeated request is stored per occurrence, and recorded LLM errors replay as `LLMError`.
    - A replay miss raises `CassetteMissError`, which means the prompt, agent code or data changed. Re-record with `--mode record` and commit the new cassettes.
    - **Which refresh to use:** agent/prompt/data change → `--mode record` (~$0.20). Judge change → `--grade-mode record`. Code-grader or `CaseResult` change (no LLM requests change) → `--update-expected`: full replay only (refuses `--cases`, record/live modes), rewrites `expected_results.jsonl`, $0. Review that diff: only the intended fields should change.
  - `schema.py`: `ExperimentConfig` and `CaseResult` (shared by runner, metrics and report), plus the `ROOT`, `CASSETTES_DIR` and `EXPERIMENTS_DIR` paths.
  - `runner.py`: `run_experiment(ExperimentConfig, ...)` runs cases × repeats in a thread pool, with one cassette per (case, repeat) under `evals/cassettes/golden-<ver>/<config_id>/`.
    - Record mode also writes `expected_results.jsonl`.
    - Outputs go to the git-ignored `experiments/<ts>__<config_id>/`: `config.json`, `results.jsonl`, `runs.jsonl`, `summary.json`, `report.md`.
  - `metrics.py`: Wilson 95% intervals and `ExperimentSummary`.
    - Goal completion = `final_answer` AND all error graders passed.
    - A run without a plan counts as a failure for every grader.
  - `report.py`: `render_report` builds the markdown report. `compare` refuses different dataset versions or hashes unless `force=True`, and calls a difference "likely real" only when the intervals don't overlap.
  - **Line endings matter:** `.gitattributes` forces LF for `prompts/**` and `evals/**`, and `prompts.py` LF-normalizes too. Hashes must match between Windows (`core.autocrlf=true`) and Linux CI.
  - Harness tests use `tests/harness_fakes.py` (`ConversationFake`, `make_dataset`). The fake answers every judge by recognizing its system prompt: the reasons judge flags any reason containing `UNGROUNDED`; the relevancy judge says nothing more was possible (all 5s); the thought↔action judge says every step is consistent. A new judge must be added to the fake, or runner tests send its calls to the agent script. B2 is tested in `tests/test_constraints.py`; B3 in `test_relevancy.py`, `test_trajectory.py`, `test_b3_metrics.py`, `test_judge_cassettes.py`.
- **Run-level graders** (Phase 8, B1): `agentsville/harness/grading.py` + `agentsville/graders/`.
  - A `RunGrader(name, kind, fn(run, ctx), needs_plan=True)` grades a finished `AgentRun` and returns `GraderOutcome` (units / failed_units / counts / details).
  - `ctx` is a `GradingContext(llm, case)` (Phase 9): `ctx.llm` is set only for `kind="llm"` graders; `ctx.case` is the `GoldenCase` (labels) or `None` outside a dataset. Label-based graders return `not_applicable(...)` (passed, 0 units) when they can't apply. The runner and `grade_runs.py` pass the case.
  - `grade_run` gives a run without a plan a failing outcome for every grader with `needs_plan=True`; `needs_plan=False` graders (`infeasible_handling`) judge plan-less runs themselves.
  - Outcomes land in `CaseResult.grader_outcomes`; `ExperimentSummary.run_graders` holds micro unit rates, `.b1` the grounding headline and `.b2` the constraint headline.
  - `ALL_GRADERS` in `agentsville/graders/__init__.py` = `B1_GRADERS + B2_GRADERS`; adding a grader there changes `CaseResult`, so refresh expected results with `--update-expected`.
  - **Each LLM judge has its own grading cassette** (Phase 10), separate from the agent's `r<n>.jsonl`: `reasons_grounded` keeps the original `r<n>.grading.jsonl`, every other judge uses `r<n>.grading.<name>.jsonl` (`runner.judge_cassette`). `--record-graders a,b` (on `run_experiment.py` and `grade_runs.py`) records only those judges and replays the rest, so adding a judge never re-calls or changes another one (record mode empties a cassette before writing). A newly registered judge has no cassette yet: every replay fails with `CassetteMissError` until it's recorded – register and record in the same change.
  - Judge calls during grading never touch the agent's cassette. To change a judge, re-grade with `--grade-mode record` (agent replays), or use `scripts/grade_runs.py` on stored `experiments/*/runs.jsonl` (it also derives `failure_mode` / `final_rejections` for results stored before Phase 9). Never re-run the agent for that.
  - `runs.jsonl` lines are `{case_id, repeat, run}`; the B0 plain format is still readable.
- `agentsville/graders/grounding.py` (B1, "is everything in the plan real?"):
  - **Code graders:**
    - `activity_grounding`: fabricated / altered (with a `first_difference` snippet) / wrong_day.
    - `weather_grounding`: each day's weather against the forecast.
    - `trajectory_grounding`: every planned activity and day's weather must appear in a non-error tool observation.
    - `reason_references`: possessive names must be travelers, and the interests claimed must be theirs.
  - **LLM judge** `reasons_grounded`: `gpt-4.1`, one call per activity, prompt in `prompts/judges/reasons_grounded/v1.md`. It fails closed.
- **Judge calibration** (every LLM judge is measured against human labels before its numbers are trusted):
  - Human labels live in `evals/datasets/calibration/<name>/<version>/items.jsonl` (`reasons`, `relevancy`, `thought_action`), immutable like golden, each with a `CHANGELOG.md` recording the labeling rule and the owner-approved judgement calls. Loaders: `load_calibration`, `load_relevancy_calibration`, `load_thought_action_calibration`; `write_calibration` writes any item model.
  - `harness/calibration.py`: binary judges get precision/recall/F1/kappa with **the failure to catch as the positive class** (ungrounded; inconsistent). The 1–5 relevancy judge gets ordinal agreement: exact, within-1, MAE and **quadratic weighted kappa**.
  - Committed reports: `evals/cassettes/calibration/<name>-v1.0.0/<model>__<prompt>/report.json`. A prompt bump gets a new folder; the old report stays as history (relevancy `v2` is current). `calibrate_judge.py --judge all` (the default) skips a judge without a calibration set.
  - **Pattern for judges ("LLM extracts, code decides"):** ask the LLM only for what needs judgement, give it code-computed FACTs, verify every claim code can check, and compute scores in code. The relevancy judge returns per-day `possible` facts; code checks the named option (real, unplanned, matching, affordable, non-overlapping), computes `served`, and applies the labeling rule (`score_from_days`). The thought↔action judge gets "IDENTICAL to the travel_plan sent at step N" and "prices sum to X, budget Y" facts, and an inconsistent verdict must quote the thought verbatim or it's dropped.
  - Calibration sets are small and built from the stored runs they measure; a perfect score is optimistic.
- `agentsville/graders/constraints.py` (Phase 9, B2, "does the plan satisfy the hard constraints?"), all code, no LLM:
  - `weather_label_compliance`: planned activities on *really* inclement days (ambiguous ones skipped) vs the case's `must_avoid_activity_ids`.
  - `infeasible_handling` (`needs_plan=False`): only for cases with `max_affordable_activities == 0`; passes on `final_answer` + empty plan + `total_cost == 0`.
  - `budget_respected`: the actual price sum vs the budget (never the reported total).
  - `weather_judge_agreement`: the in-loop weather judge's verdicts (parsed from `weather_suitability` details, `"<activity_id> on …"`) vs the human labels; counts `missed` / `false_alarm`.
  - City/dates, cost accuracy and overlaps are **not** re-graded: `ConstraintMetrics` aggregates them from `CaseResult.eval_results`.
- **Failure taxonomy** `agentsville/graders/completion.py`: `classify_failure(run)` → `None` (completed = final answer AND every error eval passed) or one `<category>:<detail>`, first matching rule wins: `llm_error:timeout|other` → `guardrail_exhausted:<eval>` → `final_failed:<eval>` → `invalid_args_loop:<tool>` (≥ 3 same-tool argument errors) → `eval_loop:<eval>` (≥ 2 `EVALS FAILED`, most frequent ✗) → `max_steps:other`. It parses observation text (`ERROR: invalid arguments for <tool>:`, `EVALS FAILED`, `✗ <eval>`), so changing those strings in `tools.py`/`evals.py` changes the taxonomy. Stored on `CaseResult.failure_mode` / `final_rejections`.
- `agentsville/graders/relevancy.py` + `trajectory.py` (Phase 10, B3, "is it relevant, and is the reasoning faithful?"):
  - Code: `interest_coverage_labeled` (skips `uncoverable_travelers`), `interest_match`, `weather_lookup_coverage`, `activity_lookup_coverage`, `calculator_total` (total came from a calculator call AND equals the real price sum), `verified_before_final` (the submitted plan passed `run_evals_tool`; compared via the TravelPlan model), `tool_efficiency` (`needs_plan=False`; repeated identical lookups, `error_steps`).
  - "Before the final answer" = before the ACCEPTED final step (`trajectory.steps_before_final`); guardrail-rejected finals are ordinary steps.
  - Judges (`gpt-4.1`, one call per run, fail closed): `traveler_relevancy` (prompt v2; 1–5 per traveler relative to what was possible each trip day, failed unit = score ≤ 2) and `thought_action_consistency` (prompt v1, `needs_plan=False`; precision 0.94 / recall 0.83, so its rate is a **lower bound**). The thought↔action input renders tool data compactly but completely (`compact_observation`) – truncating an activity list would hide the evidence.
- **B3 metrics** (`summary.b3_relevancy` / `summary.b3_reasoning`): plan-dependent rates count only runs with a plan; efficiency, error steps and the thought↔action judge count every run. Findings: `plan/10-b3-relevancy-reasoning/b3-findings.md`.
- **B2 metrics** (`ConstraintMetrics`, `summary.b2`): violation rates are over **produced plans** (conditional); goal completion is over **all runs**. Also guardrail rejection, steps to completion, infeasible handled, judge-vs-label agreement and the failure-mode counts. `None` for results graded before B2. Findings: `plan/09-b2-constraints/b2-findings.md`.
- **Thresholds:** `evals/thresholds.toml` (`[b1]`, `[b2]`, `[b3]`), with rules `max_<metric>` / `min_<metric>`. `harness/thresholds.py` `METRICS` maps metric names to values; a rule whose metric isn't there shows as "unknown rule" (a test checks the committed file has none). An unmeasured metric shows as `None`, never as a pass or a crash. B3 judge trust bars (`JUDGE_METRICS`) read the committed calibration reports passed as `judge_reports=committed_judge_reports()`. Every threshold must pass on the B0 recording, because that's what CI replays (B3 faithfulness is at 0.50 there vs a 0.45 limit).
- **Production-signal contracts** (`graders/signals.py`, spec in `plan/08-b1-grounding/production-signal.md`):
  - `GroundingSignal` (`b1.v1`): code graders on every production run, the reasons judge on 10%.
  - `ConstraintSignal` (`b2.v1`), `constraint_signal(run)`: built from the run alone (no labels in production, so label graders stay offline), $0. `goal_completed` follows the harness rule; `constraints` is a dict of hard eval → passed.
  - `RelevancySignal` (`b3.v1`), `relevancy_signal(outcomes, judges_sampled)`: code graders on every run, both B3 judges on the 10% sample. "Not measured" is `null`, never `0` (a judge that examined nothing reports `null`).
- Always read text files with `encoding="utf-8"`. The Windows default (cp1252) garbles the data's em dashes and curly quotes, and CI on Linux won't catch it.
- `scripts/review_data.py` prints the data review tables. Findings and their implications for evals and the agent prompt are in `plan/03-data-access/data-review.md`.
- `data/data.py`: raw mock data. Tools must not invent data beyond it.
  - `ACTIVITY_CALENDAR`: 24 activities in AgentsVille, 2025-06-10 to 2025-06-15. IDs follow `event-YYYY-MM-DD-N`; the hallucination eval checks plan activities against these IDs.
  - `WEATHER_FORECAST`: one entry per date.
  - `INCLIMATE_WEATHER_CONDITIONS = ["thunderstorm", "rainy"]`: drives the weather-suitability eval (outdoor activities on these days should be flagged).

