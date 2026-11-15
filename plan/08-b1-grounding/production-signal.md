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
