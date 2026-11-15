# Phase 10 – Step 2: B3 relevancy graders – "is the plan relevant to THESE travelers?"
"""Code graders count interest overlap only; how WELL a plan serves each traveler relative to
what was possible is the LLM judge's job (Phase 10 – Step 4, traveler_relevancy).
"""

from datetime import date, timedelta

from pydantic import BaseModel, Field, ValidationError

from agentsville.agent import AgentRun
from agentsville.data_api import get_activities, get_weather
from agentsville.harness.grading import (
    GraderOutcome,
    GradingContext,
    RunGrader,
    not_applicable,
)
from agentsville.harness.grading import outcome as make_outcome
from agentsville.llm import LLMError
from agentsville.models import Activity, Traveler, TravelPlan, VacationInfo
from agentsville.prompts import render_prompt

RELEVANCY_JUDGE_MODEL = "gpt-4.1"
RELEVANCY_JUDGE_PROMPT_VERSION = "v2"  # v1 failed calibration (weighted kappa 0.51)
NOT_RELEVANT_MAX_SCORE = 2  # a traveler scored ≤ 2 counts as a failed unit


def _planned_activities(run: AgentRun):
    return [rec.activity for day in run.travel_plan.itinerary_days
            for rec in day.activity_recommendations]


# Phase 10 – Step 2: every COVERABLE traveler gets at least one activity matching their interests
def interest_coverage_labeled(run: AgentRun, ctx: GradingContext) -> GraderOutcome:
    name = "interest_coverage_labeled"
    if ctx.case is None:
        return not_applicable(name, "deterministic", "no golden case")
    labels = ctx.case.labels
    if labels.max_affordable_activities == 0:
        return not_applicable(name, "deterministic", "nothing affordable – coverage impossible")
    uncoverable = set(labels.uncoverable_travelers)  # no weather-suitable matching activity exists
    coverable = [t for t in run.vacation_info.travelers if t.name not in uncoverable]
    planned = {i for a in _planned_activities(run) for i in a.related_interests}
    problems = [f"{t.name}: no activity matches {', '.join(i.value for i in t.interests)}"
                for t in coverable if not planned & set(t.interests)]
    counts = {"uncovered": len(problems)} if problems else {}
    return make_outcome(name, "deterministic", len(coverable), problems, counts)


# Phase 10 – Step 2: activities matching no traveler's interest (informational: weather may justify)
def interest_match(run: AgentRun, ctx: GradingContext | None = None) -> GraderOutcome:
    wanted = {i for t in run.vacation_info.travelers for i in t.interests}
    activities = _planned_activities(run)
    problems = [f"{a.activity_id} ({a.name}): interests "
                f"{', '.join(i.value for i in a.related_interests)} match no traveler"
                for a in activities if not wanted & set(a.related_interests)]
    counts = {"no_matching_interest": len(problems)} if problems else {}
    return make_outcome("interest_match", "deterministic", len(activities), problems, counts)


# Phase 10 – Step 4: one traveler's 1–5 relevancy score (computed by code from the judge's facts)
class TravelerScore(BaseModel):
    name: str
    score: int = Field(ge=1, le=5)
    reason: str = ""


# Phase 10 – Step 4 (judge v2): the judge's per-day fact for one traveler
class DayFact(BaseModel):
    date: str
    possible: bool  # a CLEARLY suitable, matching, affordable, non-overlapping option existed
    option: str = ""
    why: str = ""


class TravelerFacts(BaseModel):
    name: str
    days: list[DayFact]


class RelevancyFacts(BaseModel):
    travelers: list[TravelerFacts]


# Phase 10 – Step 4: the human labeling rule (calibration relevancy v1.0.0), applied in code.
# A MISS is a possible day on which the traveler got no matching activity.
#   5 = no miss (or no possible day)   4 = exactly one miss   1 = every possible day missed
#   2 = served on fewer than a third of possible days   3 = otherwise (some missed, some served)
# "Fewer than a third" is the threshold that reproduces all 25 owner-approved labels (the dataset's
# CHANGELOG says "a minority", which would contradict r01 Hiro and r11 Lina: 1 of 3 → 3).
def score_from_days(possible: list[bool], served: list[bool]) -> int:
    # Phase 10 – Step 7: a SERVED day was a possible day (the planned activity matched) even when
    # the judge saw no further unplanned option – found on live run g09 r1 (Ben scored 1, not 4)
    possible = [p or s for p, s in zip(possible, served, strict=True)]
    possible_days = sum(possible)
    misses = sum(p and not s for p, s in zip(possible, served, strict=True))
    served_possible = possible_days - misses
    if misses == 0:
        return 5
    if served_possible == 0:
        return 1
    if misses == 1:
        return 4
    return 2 if 3 * served_possible < possible_days else 3


# Phase 10 – Step 4: the versioned judge system prompt
def relevancy_judge_prompt(version: str = RELEVANCY_JUDGE_PROMPT_VERSION) -> str:
    return render_prompt("judges/traveler_relevancy", version, {})


def _activity_line(a: Activity) -> str:
    return (f"- {a.activity_id} | {a.name} | {a.start_time:%H:%M}-{a.end_time:%H:%M} | "
            f"price {a.price} | interests: {', '.join(i.value for i in a.related_interests)}")


# Phase 10 – Step 4: every day of the REQUESTED trip – a plan that drops a day can't hide from it
def trip_days(info: VacationInfo) -> list[date]:
    n = (info.date_of_departure - info.date_of_arrival).days
    return [info.date_of_arrival + timedelta(days=i) for i in range(n + 1)]


def planned_on(plan: TravelPlan, day: date) -> list[Activity]:
    return [rec.activity for d in plan.itinerary_days if d.date == day
            for rec in d.activity_recommendations]


# Phase 10 – Step 4: what the judge sees – the plan AND everything that was possible each day
def relevancy_judge_input(info: VacationInfo, plan: TravelPlan) -> str:
    lines = ["TRAVELERS:",
             *[f"- {t.name} (age {t.age}): {', '.join(i.value for i in t.interests)}"
               for t in info.travelers],
             f"BUDGET: {info.budget} (plan total_cost: {plan.total_cost})", ""]
    for day in trip_days(info):
        forecast = get_weather(day)
        weather = (f"{forecast.condition}, {forecast.temperature:g} {forecast.temperature_unit}. "
                   f"{forecast.description}") if forecast else "unknown"
        lines += [f"DAY {day}", f"FORECAST: {weather}", "PLANNED:",
                  *([_activity_line(a) for a in planned_on(plan, day)] or ["- (nothing)"]),
                  "AVAILABLE THAT DAY:"]
        for a in get_activities(day):
            lines += [_activity_line(a), f"  {a.description}"]
        lines.append("")
    return "\n".join(lines).strip()


# Phase 10 – Step 4: did this traveler get a matching activity on each trip day? (pure code)
def served_days(traveler: Traveler, plan: TravelPlan, days: list[date]) -> list[bool]:
    wanted = set(traveler.interests)
    return [any(wanted & set(a.related_interests) for a in planned_on(plan, day)) for day in days]


# Phase 10 – Step 4: code verifies everything about a "possible" claim that code CAN verify –
# a real, unplanned activity that day, matching the traveler, affordable, not overlapping.
# Only weather suitability is left to the judge. Returns why the claim is rejected, or None.
def verify_possible(fact: DayFact, traveler: Traveler, plan: TravelPlan, budget: int,
                    day: date) -> str | None:
    option = next((a for a in get_activities(day) if a.activity_id == fact.option), None)
    planned = planned_on(plan, day)
    if option is None:
        return f"{fact.option or 'no option'} is not an activity on {day}"
    if any(a.activity_id == option.activity_id for a in planned):
        return f"{option.activity_id} is already planned"
    if not set(traveler.interests) & set(option.related_interests):
        return f"{option.activity_id} doesn't match the interests of {traveler.name}"
    spent = sum(rec.activity.price for d in plan.itinerary_days
                for rec in d.activity_recommendations)
    if spent + option.price > budget:
        return f"{option.activity_id} doesn't fit the budget ({spent} + {option.price} > {budget})"
    if any(option.start_time < a.end_time and a.start_time < option.end_time for a in planned):
        return f"{option.activity_id} overlaps a planned activity"
    return None


def _check_shape(facts: RelevancyFacts, info: VacationInfo) -> str | None:
    if len(facts.travelers) != len(info.travelers):
        return f"judge returned {len(facts.travelers)} travelers, expected {len(info.travelers)}"
    dates = [d.isoformat() for d in trip_days(info)]
    for t in facts.travelers:
        if [d.date for d in t.days] != dates:
            return f"judge days for {t.name} don't match the trip's days"
    return None


# Phase 10 – Step 4: ONE call for all travelers. v2: the judge gives per-day "possible" facts,
# code verifies them, computes "served" and the score. Fails closed: every traveler scored 1.
def judge_relevancy(
    llm, info: VacationInfo, plan: TravelPlan, model: str = RELEVANCY_JUDGE_MODEL,
) -> list[TravelerScore]:
    messages = [
        {"role": "system", "content": relevancy_judge_prompt()},
        {"role": "user", "content": relevancy_judge_input(info, plan)},
    ]
    failure = None
    try:
        reply = llm.chat(messages, model=model, json_mode=True)
        facts = RelevancyFacts.model_validate_json(reply.text)
        failure = _check_shape(facts, info)
    except LLMError as exc:
        failure = f"judge call failed: {exc}"
    except ValidationError:
        failure = "judge reply unparseable"
    if failure:
        return [TravelerScore(name=t.name, score=1, reason=failure) for t in info.travelers]
    days = trip_days(info)
    scores = []
    for traveler, judged in zip(info.travelers, facts.travelers, strict=True):  # by position
        served = served_days(traveler, plan, days)
        possible, notes = [], []
        for fact, day, was_served in zip(judged.days, days, served, strict=True):
            claimed = fact.possible and not was_served  # only unserved days can be misses
            rejected = verify_possible(fact, traveler, plan, info.budget, day) if claimed else None
            possible.append(fact.possible and rejected is None)
            if rejected:
                notes.append(f"{day}: judge claim rejected – {rejected}")
            elif claimed:
                notes.append(f"missed {day}: {fact.option} – {fact.why}")
        scores.append(TravelerScore(name=traveler.name, score=score_from_days(possible, served),
                                    reason="; ".join(notes) or "no missed day"))
    return scores


# Phase 10 – Step 4: LLM judge – how well the plan serves each traveler, relative to what existed
def traveler_relevancy(run: AgentRun, ctx: GradingContext) -> GraderOutcome:
    name = "traveler_relevancy"
    if ctx.case is not None and ctx.case.labels.max_affordable_activities == 0:
        return not_applicable(name, "llm", "nothing affordable – an empty plan is correct")
    travelers = run.vacation_info.travelers
    scores = judge_relevancy(ctx.llm, run.vacation_info, run.travel_plan)
    counts: dict[str, int] = {}
    problems = []
    for traveler, s in zip(travelers, scores, strict=True):
        counts[f"score_{s.score}"] = counts.get(f"score_{s.score}", 0) + 1
        if s.score <= NOT_RELEVANT_MAX_SCORE:
            problems.append(f"{traveler.name}: score {s.score} – {s.reason}")
    return make_outcome(name, "llm", len(travelers), problems, dict(sorted(counts.items())))


B3_RELEVANCY_GRADERS = [
    RunGrader("interest_coverage_labeled", "deterministic", interest_coverage_labeled),
    RunGrader("interest_match", "deterministic", interest_match),
]

# Phase 10 – Step 4: defined and calibrated now; registered in ALL_GRADERS in Step 7, together with
# recording its cassettes – registering earlier would make every replay miss its cassette.
TRAVELER_RELEVANCY_JUDGE = RunGrader("traveler_relevancy", "llm", traveler_relevancy)
