# Phase 12 – Step 4: TravelPlan / AgentRun -> plain display data (no Streamlit code).
"""Everything the results section shows, as simple dataclasses that tests can check.

Cost figures always use the *actual* sum of activity prices (the same rule as the evals), and
the inclement-weather badge comes from the real forecast in `data_api`, not from the plan.
The quality panel (Step 5) runs only the free, deterministic B1–B3 graders.
"""

import datetime
from dataclasses import dataclass

from agentsville import data_api
from agentsville.agent import AgentRun
from agentsville.evals import EvalReport
from agentsville.graders import B1_GRADERS, B2_GRADERS, B3_GRADERS
from agentsville.harness.grading import GraderOutcome, RunGrader, grade_run
from agentsville.models import ItineraryDay, TravelPlan, VacationInfo

# Phase 12 – Step 3: eval names (evals.py) in plain words – moved here in Step 4 and shared
EVAL_LABELS = {
    "city_and_dates": "city and dates",
    "total_cost_accurate": "total cost calculation",
    "within_budget": "budget",
    "no_hallucinated_activities": "real activities only",
    "weather_matches_forecast": "weather matches the forecast",
    "no_overlapping_activities": "no overlapping activities",
    "weather_suitability": "activities suit the weather",
    "interest_coverage": "every traveler's interests covered",
    "activities_per_day": "activities per day",
}


# Phase 12 – Step 4: an eval name in plain words (unknown names fall back to spaced words)
def eval_label(name: str) -> str:
    return EVAL_LABELS.get(name, name.replace("_", " "))


# Phase 12 – Step 4: the money side of a plan
@dataclass(frozen=True)
class CostSummary:
    actual_total: int  # sum of activity prices (what the traveler pays)
    reported_total: int  # plan.total_cost as the agent wrote it
    budget: int

    @property
    def remaining(self) -> int:
        return self.budget - self.actual_total

    @property
    def within_budget(self) -> bool:
        return self.actual_total <= self.budget

    @property
    def total_matches(self) -> bool:
        return self.actual_total == self.reported_total


# Phase 12 – Step 4: one activity line in a day card
@dataclass(frozen=True)
class ActivityRow:
    activity_id: str
    time: str  # "09:00–11:00"
    name: str
    location: str
    price: int
    interests: str  # "technology, tennis"
    description: str
    reasons: list[str]


# Phase 12 – Step 4: one day of the itinerary, ready to draw
@dataclass(frozen=True)
class DayCard:
    date: datetime.date
    title: str  # "Tue, Jun 10"
    weather: str  # "clear · 31 °C"
    inclement: bool  # the real forecast is rainy / thunderstorm
    activities: list[ActivityRow]

    @property
    def day_cost(self) -> int:
        return sum(a.price for a in self.activities)


# Phase 12 – Step 4: one row of the eval report
@dataclass(frozen=True)
class EvalRow:
    icon: str  # ✓ passed, ✗ failed (error), ! failed (warning)
    label: str
    severity: str
    passed: bool
    details: list[str]


# Phase 12 – Step 4: actual vs reported total vs budget
def cost_summary(plan: TravelPlan, info: VacationInfo) -> CostSummary:
    actual = sum(
        rec.activity.price for day in plan.itinerary_days for rec in day.activity_recommendations
    )
    return CostSummary(actual_total=actual, reported_total=plan.total_cost, budget=info.budget)


# Phase 12 – Step 4: the plan's days as cards, in date order
def day_cards(plan: TravelPlan) -> list[DayCard]:
    return [_day_card(day) for day in sorted(plan.itinerary_days, key=lambda d: d.date)]


def _day_card(day: ItineraryDay) -> DayCard:
    forecast = data_api.get_weather(day.date)
    unit = day.weather.temperature_unit.strip()[:1].upper() or "?"
    activities = sorted(
        (rec for rec in day.activity_recommendations), key=lambda rec: rec.activity.start_time
    )
    return DayCard(
        date=day.date,
        title=f"{day.date:%a, %b %d}",
        weather=f"{day.weather.condition} · {day.weather.temperature:g} °{unit}",
        inclement=forecast is not None and data_api.is_inclement(forecast),
        activities=[
            ActivityRow(
                activity_id=rec.activity.activity_id,
                time=f"{rec.activity.start_time:%H:%M}–{rec.activity.end_time:%H:%M}",
                name=rec.activity.name,
                location=rec.activity.location,
                price=rec.activity.price,
                interests=", ".join(str(i) for i in rec.activity.related_interests),
                description=rec.activity.description,
                reasons=list(rec.reasons_for_recommendation),
            )
            for rec in activities
        ],
    )


# Phase 12 – Step 4: the final eval report as rows – failed errors first, then warnings, then passes
def eval_rows(report: EvalReport) -> list[EvalRow]:
    rows = [
        EvalRow(
            icon="✓" if r.passed else ("!" if r.severity == "warning" else "✗"),
            label=eval_label(r.name),
            severity=r.severity,
            passed=r.passed,
            details=list(r.details),
        )
        for r in report.results
    ]
    order = {"✗": 0, "!": 1, "✓": 2}
    return sorted(rows, key=lambda row: order[row.icon])


# Phase 12 – Step 4: summary bar as (label, value, help) – empty plans and plan-less runs included
def summary_metrics(run: AgentRun) -> list[tuple[str, str, str]]:
    plan = run.travel_plan
    metrics = []
    if plan is not None:
        cost = cost_summary(plan, run.vacation_info)
        activities = sum(len(d.activity_recommendations) for d in plan.itinerary_days)
        metrics += [
            (
                "Total cost",
                f"{cost.actual_total} / {cost.budget}",
                "Sum of activity prices vs your budget. Prices are added once for the whole "
                "group, not per person.",
            ),
            ("Days", str(len(plan.itinerary_days)), "Days in the itinerary"),
            ("Activities", str(activities), "Planned activities across all days"),
        ]
    metrics += [
        ("Agent steps", str(run.step_count), "THOUGHT → ACTION → OBSERVATION cycles"),
        ("Run cost", f"${run.total_cost_usd:.3f}", "LLM cost of this run, including judge calls"),
        ("Time", f"{run.total_latency_ms / 1000:.0f} s", "Total LLM time"),
    ]
    return metrics


# Phase 12 – Step 4: plain-words note on the total, or None when it's correct and within budget
def cost_note(cost: CostSummary) -> str | None:
    notes = []
    if not cost.total_matches:
        notes.append(
            f"The agent reported a total of {cost.reported_total}, but the prices add up to "
            f"{cost.actual_total}."
        )
    if not cost.within_budget:
        notes.append(f"This is {-cost.remaining} over your budget of {cost.budget}.")
    return " ".join(notes) or None


# Phase 12 – Step 4: True when the agent returned a plan with no activities at all
def is_empty_plan(plan: TravelPlan) -> bool:
    return not any(day.activity_recommendations for day in plan.itinerary_days)


# ---------------------------------------------------------------------------
# Step 5 – quality panel: the B1–B3 code graders on this run, free
# ---------------------------------------------------------------------------

# Phase 12 – Step 5: grader names (graders/*.py) in plain words
GRADER_LABELS = {
    "activity_grounding": "No invented or altered activities",
    "weather_grounding": "Weather matches the forecast",
    "trajectory_grounding": "Everything in the plan was looked up by a tool first",
    "reason_references": "Reasons name the right travelers and their interests",
    "weather_label_compliance": "No unsuitable activities on bad-weather days",
    "infeasible_handling": "Impossible requests get an empty plan",
    "budget_respected": "Within budget",
    "weather_judge_agreement": "Weather judge agrees with human labels",
    "interest_coverage_labeled": "Every traveler's interests covered",
    "interest_match": "Activities match the travelers' interests",
    "weather_lookup_coverage": "Weather looked up for every day",
    "activity_lookup_coverage": "Activities looked up for every day",
    "calculator_total": "Total computed with the calculator",
    "verified_before_final": "Plan checked with the evals before the final answer",
    "tool_efficiency": "No repeated lookups or tool errors",
}

QUALITY_GROUPS: tuple[tuple[str, list[RunGrader]], ...] = (
    ("Grounding – is everything in the plan real?", B1_GRADERS),
    ("Constraints – does it respect the hard limits?", B2_GRADERS),
    ("Relevancy & reasoning – does it fit you, and did the agent work carefully?", B3_GRADERS),
)

NOT_APPLICABLE_PREFIX = "not applicable"


# Phase 12 – Step 5: one grader's result, ready to draw
@dataclass(frozen=True)
class QualityRow:
    name: str
    label: str
    status: str  # "pass" | "fail" | "n/a"
    summary: str  # "6/6 ok", "2 of 3 failed", "needs a golden test case"
    details: list[str]


# Phase 12 – Step 5: one quality question with its graders
@dataclass(frozen=True)
class QualityGroup:
    title: str
    rows: list[QualityRow]

    @property
    def failed(self) -> int:
        return sum(row.status == "fail" for row in self.rows)


# Phase 12 – Step 5: the panel – code graders only (LLM judges cost money and aren't run here)
def quality_panel(run: AgentRun) -> list[QualityGroup]:
    groups = []
    for title, graders in QUALITY_GROUPS:
        code_graders = [g for g in graders if g.kind == "deterministic"]
        outcomes = grade_run(run, code_graders)  # no golden case: label graders say n/a
        rows = [_quality_row(g, outcomes[g.name], run) for g in code_graders]
        groups.append(QualityGroup(title=title, rows=rows))
    return groups


# Phase 12 – Step 5: the LLM judges the panel skips, in plain words (for the note under it)
def skipped_judges() -> list[str]:
    return [
        g.name.replace("_", " ")
        for _, graders in QUALITY_GROUPS
        for g in graders
        if g.kind == "llm"
    ]


def _quality_row(grader: RunGrader, result: GraderOutcome, run: AgentRun) -> QualityRow:
    label = GRADER_LABELS.get(grader.name, grader.name.replace("_", " "))
    if run.travel_plan is None and grader.needs_plan:
        return QualityRow(grader.name, label, "n/a", "no plan to check", [])
    if any(d.startswith(NOT_APPLICABLE_PREFIX) for d in result.details):
        return QualityRow(grader.name, label, "n/a", "needs a golden test case", [])
    if result.passed:
        summary = f"{result.units}/{result.units} ok" if result.units else "ok"
        return QualityRow(grader.name, label, "pass", summary, [])
    summary = f"{result.failed_units} of {result.units} failed"
    return QualityRow(grader.name, label, "fail", summary, list(result.details))
