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
