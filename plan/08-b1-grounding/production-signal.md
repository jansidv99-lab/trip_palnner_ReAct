# Phase 8 – Step 10: B1 production-signal contract

> Implemented as `agentsville/graders/signals.py` (`GroundingSignal`, `grounding_signal`).
> Consumed by C1 (Phase 14, logging + BigQuery) and C2 (Phase 15, metrics/dashboard).

## What every production run logs (`schema_version = "b1.v1"`)

| Field | Type | Meaning |
|---|---|---|
| `plan_produced` | bool | the agent returned a plan |
| `planned_activities` | int | activities in the plan |
| `fabricated_activities` | int | activity IDs not in the data |
| `altered_activities` | int | real IDs with changed fields |
| `wrong_day_activities` | int | real, unaltered, but on the wrong day |
| `trajectory_ungrounded` | int | activities/days used but never retrieved by a tool |
| `reasons_total` | int | recommendation reasons in the plan |
| `reason_reference_errors` | int | reasons naming unknown travelers or interests they don't have |
| `judge_sampled` | bool | whether the reasons judge ran for this run |
| `ungrounded_reasons` | int \| null | judge-flagged reasons; null when not sampled |

## Online grading policy
- **Code graders on every run:** activity, weather and trajectory grounding, plus reason references. They're free and fast.
- **Reasons judge on a 10% sample** (`JUDGE_SAMPLE_RATE`). It costs about 1–2 cents per judged run.

## Metrics for C2 (Phase 15)

| Metric | Formula | Offline threshold to compare with |
|---|---|---|
| `b1/activity_hallucination_rate` | Σ(fabricated + altered + wrong_day) ÷ Σ planned_activities | `max_activity_hallucination_rate` |
| `b1/plan_hallucination_rate` | runs with any of those > 0 ÷ runs with a plan | `max_plan_hallucination_rate` |
| `b1/trajectory_ungrounded_rate` | Σ trajectory_ungrounded ÷ Σ (planned_activities + plan days) | `max_trajectory_ungrounded_rate` |
| `b1/reason_reference_error_rate` | Σ reason_reference_errors ÷ Σ reasons_total | `max_reason_reference_error_rate` |
| `b1/ungrounded_reason_rate` | Σ ungrounded_reasons ÷ Σ reasons_total (judged runs only) | `max_ungrounded_reason_rate` |

C3 (Phase 16) alerts when an online rate exceeds its offline threshold over a rolling window.

---

# Phase 9 – Step 7: B2 production-signal contract

> Implemented as `agentsville/graders/signals.py` (`ConstraintSignal`, `constraint_signal`).
> Logged **next to** the B1 signal for every production run. Built from the run alone: production
> has no golden labels, so the label-based graders (`weather_label_compliance`,
> `infeasible_handling`, `weather_judge_agreement`) stay offline-only.

## What every production run logs (`schema_version = "b2.v1"`)

| Field | Type | Meaning |
|---|---|---|
| `stop_reason` | str \| null | `final_answer` · `max_steps` · `llm_error` |
| `plan_produced` | bool | the agent returned a plan |
| `goal_completed` | bool | final answer **and** every hard (error) eval passed – the harness's goal-completion rule |
| `failure_mode` | str \| null | failure-taxonomy label (`eval_loop:total_cost_accurate`, …); null when completed |
| `steps` | int | ReAct steps used (`max_steps` is 20) |
| `final_rejections` | int | guardrail rejections before the final answer |
| `constraints` | {str: bool} | hard eval → passed, from the in-loop final evals; `{}` without a plan |
| `budget` | int | the request's budget |
| `total_cost` | int \| null | the plan's reported total; null without a plan |

`constraints` keys today: `city_and_dates`, `total_cost_accurate`, `within_budget`,
`no_hallucinated_activities`, `weather_matches_forecast`, `no_overlapping_activities`, and
`weather_suitability` when the weather judge runs. In BigQuery, flatten with
`UNNEST`/`JSON_EXTRACT` – new evals add keys without a schema change.

## Online grading policy
- **Free:** every field comes from the run itself – the failure taxonomy is deterministic and the
  constraint verdicts are the final evals the agent already ran. No extra LLM calls.

## Metrics for C2 (Phase 15) – "C2 … after B2" in goal.md

| Metric | Formula | Offline threshold to compare with |
|---|---|---|
| `b2/goal_completion_rate` | runs with `goal_completed` ÷ runs | `min_goal_completion_rate` |
| `b2/failure_mode_share/<category>` | runs with that `failure_mode` ÷ non-completed runs | – (watch the mix; today's top: `eval_loop:total_cost_accurate`) |
| `b2/<constraint>_violation_rate` | runs with `constraints[<constraint>] == false` ÷ runs with a plan | `max_city_dates_…`, `max_budget_…`, `max_overlap_…`, `max_cost_accuracy_violation_rate` |
| `b2/guardrail_rejection_rate` | final-answer runs with `final_rejections > 0` ÷ final-answer runs | – |
| `b2/steps_p95` | p95 of `steps` over completed runs | – (near 20 = runs barely finishing) |

C3 (Phase 16) alerts when `goal_completion_rate` drops below its offline threshold, or a
violation rate exceeds its threshold, over a rolling window.

---

# Phase 10 – Step 9: B3 production-signal contract

> Implemented as `agentsville/graders/signals.py` (`RelevancySignal`, `relevancy_signal`).
> Logged **next to** the B1 and B2 signals for every production run. Despite the name it carries
> both halves of B3: relevancy and reasoning faithfulness.

## What every production run logs (`schema_version = "b3.v1"`)

| Field | Type | Meaning |
|---|---|---|
| `plan_produced` | bool | the agent returned a plan |
| `planned_activities` / `activities_matching_nobody` | int | activities, and those matching no traveler's interest |
| `trip_days` | int | days of the requested trip (0 without a plan) |
| `days_without_weather_lookup` / `days_without_activity_lookup` | int | trip days never looked up before the final answer |
| `total_from_calculator` | bool \| null | `total_cost` came from a calculator call and equals the real price sum; null without activities |
| `verified_before_final` | bool \| null | the submitted plan passed `run_evals_tool`; null without an accepted final answer |
| `faithful` | bool \| null | both of the above; null when either is null |
| `lookup_calls` / `redundant_lookups` / `error_steps` | int | trajectory efficiency |
| `judges_sampled` | bool | whether the two B3 judges ran for this run |
| `travelers_judged` / `relevant_travelers` / `poorly_served_travelers` | int \| null | relevancy judge: travelers, scores ≥ 4, scores ≤ 2; null when not sampled or nothing to judge |
| `mean_relevancy_score` | float \| null | mean 1–5 score |
| `judged_steps` / `inconsistent_steps` | int \| null | thought↔action judge; null when not sampled |

**Offline only:** `interest_coverage_labeled` needs the golden `uncoverable_travelers` label, which
production traffic doesn't have.

## Online grading policy
- **Code graders on every run** ($0): interest match, lookup coverage, calculator total,
  verified-before-final, tool efficiency.
- **Both judges on the 10% sample** (`JUDGE_SAMPLE_RATE`), like the B1 reasons judge – about
  2–4 cents per judged run (relevancy ~1 call, thought↔action ~1 call with the whole trajectory).
- `inconsistent_steps` is a **lower bound**: the thought↔action judge's calibration recall is 0.83.

## Metrics for C2 (Phase 15)

| Metric | Formula | Offline threshold to compare with |
|---|---|---|
| `b3/relevant_rate` | Σ relevant_travelers ÷ Σ travelers_judged (sampled runs) | `min_relevant_rate` |
| `b3/mean_relevancy_score` | mean of `mean_relevancy_score` weighted by travelers_judged | – |
| `b3/weather_lookup_coverage` | 1 − Σ days_without_weather_lookup ÷ Σ trip_days | `min_weather_lookup_coverage` |
| `b3/calculator_faithfulness` | runs with total_from_calculator ÷ runs where it isn't null | `min_calculator_faithfulness` |
| `b3/verified_before_final_rate` | runs with verified_before_final ÷ runs where it isn't null | `min_verified_before_final_rate` |
| `b3/faithfulness` | runs with faithful ÷ runs where it isn't null | `min_faithfulness` |
| `b3/thought_action_inconsistency` | Σ inconsistent_steps ÷ Σ judged_steps (sampled runs) | `max_thought_action_inconsistency` |
| `b3/redundant_call_rate` | Σ redundant_lookups ÷ Σ lookup_calls | `max_redundant_call_rate` |
| `b3/error_step_rate` | Σ error_steps ÷ Σ steps (from the B2 signal) | `max_error_step_rate` |

C3 (Phase 16) alerts when an online rate crosses its offline threshold over a rolling window.
Worth watching first: `b3/faithfulness` (B0 recording at 50%) and `b3/thought_action_inconsistency`
(the "says it changed the plan, sends the same plan" pattern behind B2's loops).
