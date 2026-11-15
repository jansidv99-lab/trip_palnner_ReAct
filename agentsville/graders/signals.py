# Phase 8 – Step 10: production-signal contract for B1 – what C1 (Phase 14) logs per production run.
"""Spec: plan/08-b1-grounding/production-signal.md. Code graders run on EVERY production run; the
reasons judge runs on a sample (default 10%) to control cost, so `ungrounded_reasons` is None for
unsampled runs and C2 rates over judged runs only.
"""

from pydantic import BaseModel

from agentsville.harness.grading import GraderOutcome

JUDGE_SAMPLE_RATE = 0.10


# Phase 8 – Step 10: one production run's grounding counts (a stable, flat log schema)
class GroundingSignal(BaseModel):
    schema_version: str = "b1.v1"
    plan_produced: bool
    planned_activities: int
    fabricated_activities: int
    altered_activities: int
    wrong_day_activities: int
    trajectory_ungrounded: int
    reasons_total: int
    reason_reference_errors: int
    judge_sampled: bool
    ungrounded_reasons: int | None  # None when the judge wasn't sampled


# Phase 8 – Step 10: build the signal from a run's grader outcomes
def grounding_signal(outcomes: dict[str, GraderOutcome], judge_sampled: bool) -> GroundingSignal:
    activity = outcomes.get("activity_grounding")
    plan_produced = bool(activity and activity.details != ["no plan produced"])
    trajectory = outcomes.get("trajectory_grounding")
    references = outcomes.get("reason_references")
    judge = outcomes.get("reasons_grounded") if judge_sampled else None
    return GroundingSignal(
        plan_produced=plan_produced,
        planned_activities=activity.units if activity else 0,
        fabricated_activities=activity.counts.get("fabricated", 0) if activity else 0,
        altered_activities=activity.counts.get("altered", 0) if activity else 0,
        wrong_day_activities=activity.counts.get("wrong_day", 0) if activity else 0,
        trajectory_ungrounded=trajectory.failed_units if trajectory else 0,
        reasons_total=references.units if references else 0,
        reason_reference_errors=references.failed_units if references else 0,
        judge_sampled=judge is not None,
        ungrounded_reasons=judge.failed_units if judge else None,
    )
