# Phase 9 – Step 2: B2 constraint graders – "does the plan satisfy the traveler's hard constraints?"
"""Code graders, no LLM calls. Three read the golden labels (GradingContext.case); budget reads only
the run. The other hard constraints (city/dates, cost accuracy, overlaps, weather judge) are already
graded in-loop (Phase 4) and stored in CaseResult.eval_results, so B2 aggregates them instead.
"""

from collections.abc import Iterator

from agentsville.agent import AgentRun
from agentsville.data_api import get_weather, is_inclement
from agentsville.harness.dataset import GoldenLabels
from agentsville.harness.grading import (
    GraderOutcome,
    GradingContext,
    RunGrader,
    not_applicable,
)
from agentsville.harness.grading import outcome as make_outcome


# Phase 9 – Step 4: the labeled units – planned activities on REALLY inclement days, minus ambiguous
def _labeled_inclement(run: AgentRun, labels: GoldenLabels) -> Iterator[tuple]:
    ambiguous = set(labels.ambiguous_activity_ids)
    for day in run.travel_plan.itinerary_days:
        forecast = get_weather(day.date)  # the real forecast, not what the plan claims
        if forecast is None or not is_inclement(forecast):
            continue
        for rec in day.activity_recommendations:
            if rec.activity.activity_id not in ambiguous:  # ambiguous: no verdict either way
                yield day, forecast, rec.activity


# Phase 9 – Step 2: planned activities on inclement days vs the human must-avoid labels
def weather_label_compliance(run: AgentRun, ctx: GradingContext) -> GraderOutcome:
    name = "weather_label_compliance"
    if ctx.case is None:
        return not_applicable(name, "deterministic", "no golden case")
    must_avoid = set(ctx.case.labels.must_avoid_activity_ids)
    units, problems = 0, []
    for day, forecast, activity in _labeled_inclement(run, ctx.case.labels):
        units += 1
        if activity.activity_id in must_avoid:
            problems.append(f"{day.date}: {activity.activity_id} ({activity.name}) is labeled "
                            f"must-avoid in {forecast.condition} weather")
    counts = {"must_avoid": len(problems)} if problems else {}
    return make_outcome(name, "deterministic", units, problems, counts)


# Phase 9 – Step 4: does the LLM weather judge agree with the human labels on REAL picks?
def weather_judge_agreement(run: AgentRun, ctx: GradingContext) -> GraderOutcome:
    name = "weather_judge_agreement"
    if ctx.case is None:
        return not_applicable(name, "deterministic", "no golden case")
    report = run.final_eval_report
    judge = next((r for r in report.results if r.name == "weather_suitability"), None) \
        if report else None
    if judge is None:
        return not_applicable(name, "deterministic", "weather judge did not run")
    # judge details read "<activity_id> on <date> (<condition>): <reason>" (evals.py)
    flagged = {detail.split(" ", 1)[0] for detail in judge.details}
    must_avoid = set(ctx.case.labels.must_avoid_activity_ids)
    units, problems, counts = 0, [], {}
    for day, _, activity in _labeled_inclement(run, ctx.case.labels):
        units += 1
        label_avoid = activity.activity_id in must_avoid
        judge_avoid = activity.activity_id in flagged
        if label_avoid and not judge_avoid:
            counts["missed"] = counts.get("missed", 0) + 1
            problems.append(f"{day.date}: {activity.activity_id} labeled must-avoid, judge "
                            "said suitable")
        elif judge_avoid and not label_avoid:
            counts["false_alarm"] = counts.get("false_alarm", 0) + 1
            problems.append(f"{day.date}: {activity.activity_id} flagged by the judge, label "
                            "says suitable")
    return make_outcome(name, "deterministic", units, problems, counts)


# Phase 9 – Step 2: when nothing is affordable, the right answer is an empty plan, delivered
def infeasible_handling(run: AgentRun, ctx: GradingContext) -> GraderOutcome:
    name = "infeasible_handling"
    if ctx.case is None:
        return not_applicable(name, "deterministic", "no golden case")
    if ctx.case.labels.max_affordable_activities != 0:
        return not_applicable(name, "deterministic", "feasible case")
    plan = run.travel_plan
    problems, counts = [], {}
    if run.stop_reason != "final_answer" or plan is None:
        counts["no_final_answer"] = 1
        problems.append(f"no empty plan delivered (stop_reason={run.stop_reason})")
    else:
        planned = sum(len(day.activity_recommendations) for day in plan.itinerary_days)
        if planned:
            counts["activities_planned"] = 1
            problems.append(f"{planned} activities planned although none is affordable")
        if plan.total_cost != 0:
            counts["nonzero_total"] = 1
            problems.append(f"total_cost is {plan.total_cost}, expected 0")
    failed = int(bool(problems))  # one unit (the run), however many problems it has
    return make_outcome(name, "deterministic", 1, problems, counts, failed_units=failed)


# Phase 9 – Step 2: the ACTUAL price sum fits the budget (never trusts the reported total)
def budget_respected(run: AgentRun, ctx: GradingContext | None = None) -> GraderOutcome:
    plan, budget = run.travel_plan, run.vacation_info.budget
    actual = sum(rec.activity.price for day in plan.itinerary_days
                 for rec in day.activity_recommendations)
    problems, counts = [], {}
    if actual > budget:
        counts["over_budget"] = 1
        note = f" (plan reports {plan.total_cost})" if plan.total_cost != actual else ""
        problems.append(f"activities cost {actual}{note}, budget is {budget} "
                        f"(over by {actual - budget})")
    return make_outcome("budget_respected", "deterministic", 1, problems, counts)


B2_GRADERS = [
    RunGrader("weather_label_compliance", "deterministic", weather_label_compliance),
    RunGrader("infeasible_handling", "deterministic", infeasible_handling, needs_plan=False),
    RunGrader("budget_respected", "deterministic", budget_respected),
    RunGrader("weather_judge_agreement", "deterministic", weather_judge_agreement),
]
