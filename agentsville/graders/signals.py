# Phase 8 – Step 10: production-signal contract for B1 – what C1 (Phase 14) logs per production run.
# Phase 9 – Step 7: B2 signal (constraints & completion) added.
# Phase 10 – Step 9: B3 signal (relevancy & reasoning) added.
"""Spec: plan/08-b1-grounding/production-signal.md. Code graders run on EVERY production run; the
reasons judge runs on a sample (default 10%) to control cost, so `ungrounded_reasons` is None for
unsampled runs and C2 rates over judged runs only.
"""

from pydantic import BaseModel

from agentsville.agent import AgentRun, StopReason
from agentsville.graders.completion import classify_failure
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


# Phase 9 – Step 7: one production run's constraint & completion outcome (flat, stable log schema).
# Built from the run alone – production has no golden labels, so label-based graders don't apply.
class ConstraintSignal(BaseModel):
    schema_version: str = "b2.v1"
    stop_reason: StopReason | None
    plan_produced: bool
    goal_completed: bool  # final answer AND every hard (error) eval passed
    failure_mode: str | None  # failure taxonomy label; None when completed
    steps: int
    final_rejections: int  # guardrail rejections before the final answer
    constraints: dict[str, bool]  # hard eval → passed (in-loop final evals); {} without a plan
    budget: int
    total_cost: int | None  # the plan's reported total; None without a plan


# Phase 9 – Step 7: build the signal from a finished run
def constraint_signal(run: AgentRun) -> ConstraintSignal:
    report = run.final_eval_report
    results = report.results if report else []
    constraints = {r.name: r.passed for r in results if r.severity == "error"}
    failure_mode = classify_failure(run)
    return ConstraintSignal(
        stop_reason=run.stop_reason,
        plan_produced=run.travel_plan is not None,
        goal_completed=failure_mode is None,
        failure_mode=failure_mode,
        steps=run.step_count,
        final_rejections=run.final_rejections,
        constraints=constraints,
        budget=run.vacation_info.budget,
        total_cost=run.travel_plan.total_cost if run.travel_plan else None,
    )


# Phase 10 – Step 9: one production run's relevancy AND reasoning outcome (flat, stable schema).
# Code graders run on every run ($0). Label-based coverage needs a golden case, so it stays
# offline; the two judges run on the JUDGE_SAMPLE_RATE sample, their fields None otherwise.
class RelevancySignal(BaseModel):
    schema_version: str = "b3.v1"
    plan_produced: bool
    # relevancy (code)
    planned_activities: int
    activities_matching_nobody: int
    # reasoning (code)
    trip_days: int
    days_without_weather_lookup: int
    days_without_activity_lookup: int
    total_from_calculator: bool | None  # None: no plan, or no activities to add up
    verified_before_final: bool | None  # None: no accepted final answer
    faithful: bool | None  # both of the above; None when either is None
    lookup_calls: int
    redundant_lookups: int
    error_steps: int
    # judges (sampled)
    judges_sampled: bool
    travelers_judged: int | None
    relevant_travelers: int | None  # relevancy score ≥ 4
    poorly_served_travelers: int | None  # score ≤ 2
    mean_relevancy_score: float | None
    judged_steps: int | None
    inconsistent_steps: int | None  # thought↔action (a lower bound – judge recall 0.83)


def _flag(outcome: GraderOutcome | None) -> bool | None:
    return outcome.passed if outcome is not None and outcome.units else None


# Phase 10 – Step 9: build the signal from a run's grader outcomes
def relevancy_signal(outcomes: dict[str, GraderOutcome], judges_sampled: bool) -> RelevancySignal:
    match = outcomes.get("interest_match")
    weather = outcomes.get("weather_lookup_coverage")
    activity = outcomes.get("activity_lookup_coverage")
    efficiency = outcomes.get("tool_efficiency")
    calculator = _flag(outcomes.get("calculator_total"))
    verified = _flag(outcomes.get("verified_before_final"))
    # a judge that examined nothing (no plan, not applicable) is "not measured", not "zero"
    relevancy = outcomes.get("traveler_relevancy") if judges_sampled else None
    relevancy = relevancy if relevancy is not None and relevancy.units else None
    consistency = outcomes.get("thought_action_consistency") if judges_sampled else None
    consistency = consistency if consistency is not None and consistency.units else None
    scores = {int(k[-1]): v for k, v in (relevancy.counts if relevancy else {}).items()
              if k.startswith("score_")}
    judged = sum(scores.values())
    return RelevancySignal(
        plan_produced=bool(match and match.details != ["no plan produced"]),
        planned_activities=match.units if match else 0,
        activities_matching_nobody=match.failed_units if match else 0,
        trip_days=weather.units if weather else 0,
        days_without_weather_lookup=weather.failed_units if weather else 0,
        days_without_activity_lookup=activity.failed_units if activity else 0,
        total_from_calculator=calculator,
        verified_before_final=verified,
        faithful=None if calculator is None or verified is None else calculator and verified,
        lookup_calls=efficiency.units if efficiency else 0,
        redundant_lookups=efficiency.failed_units if efficiency else 0,
        error_steps=efficiency.counts.get("error_steps", 0) if efficiency else 0,
        judges_sampled=judges_sampled,
        travelers_judged=judged if relevancy else None,
        relevant_travelers=(scores.get(4, 0) + scores.get(5, 0)) if relevancy else None,
        poorly_served_travelers=relevancy.failed_units if relevancy else None,
        mean_relevancy_score=(sum(k * v for k, v in scores.items()) / judged
                              if relevancy and judged else None),
        judged_steps=consistency.units if consistency else None,
        inconsistent_steps=consistency.failed_units if consistency else None,
    )
