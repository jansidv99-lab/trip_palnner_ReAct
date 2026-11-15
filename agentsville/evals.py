# Phase 4 – Step 1: evals – score a TravelPlan against the VacationInfo it was made for.
"""Itinerary evals.

Each eval is a function (request, plan) -> EvalResult. `run_all_evals` runs them and returns an
EvalReport, reused by the agent (run_evals_tool), the offline eval suite, the UI and monitoring.

Severity: "error" evals decide pass/fail; "warning" evals are informational, because a perfect
score is sometimes impossible (e.g. no activity matches a traveler's interests).
"""

from collections import Counter
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ValidationError, computed_field

from agentsville.data_api import get_activity_by_id, get_weather, is_inclement
from agentsville.llm import LLMClient, LLMError
from agentsville.models import Activity, ItineraryDay, TravelPlan, VacationInfo, WeatherForecast

Severity = Literal["error", "warning"]
Kind = Literal["deterministic", "llm"]


# ---------------------------------------------------------------------------
# Step 1 – result objects and helpers
# ---------------------------------------------------------------------------


# Phase 4 – Step 1: outcome of one eval
class EvalResult(BaseModel):
    name: str
    passed: bool
    severity: Severity = "error"
    kind: Kind = "deterministic"
    score: float | None = None  # 0–1 where meaningful
    details: list[str] = []  # one human-readable line per problem


# Phase 4 – Step 1: outcome of a full eval run
class EvalReport(BaseModel):
    results: list[EvalResult]

    # Only error-severity evals decide the overall verdict.
    @computed_field
    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results if r.severity == "error")

    # Phase 4 – Step 1: compact text – this is what the agent reads as its OBSERVATION
    def summary(self) -> str:
        ok = sum(r.passed for r in self.results)
        lines = [f"EVALS {'PASSED' if self.passed else 'FAILED'} ({ok}/{len(self.results)} ok)"]
        for r in self.results:
            if r.passed:
                mark = "✓"
            else:
                mark = "!" if r.severity == "warning" else "✗"
            label = f"{r.name} (warning)" if r.severity == "warning" else r.name
            score = f" score={r.score:.2f}" if r.score is not None else ""
            lines.append(f"{mark} {label}{score}")
            lines.extend(f"    - {d}" for d in r.details)
        return "\n".join(lines)


def _result(
    name: str,
    problems: list[str],
    severity: Severity = "error",
    kind: Kind = "deterministic",
    score: float | None = None,
) -> EvalResult:
    return EvalResult(
        name=name,
        passed=not problems,
        severity=severity,
        kind=kind,
        score=score,
        details=problems,
    )


def _activities(plan: TravelPlan) -> Iterator[tuple[ItineraryDay, Activity]]:
    for day in plan.itinerary_days:
        for rec in day.activity_recommendations:
            yield day, rec.activity


def _trip_dates(request: VacationInfo) -> list[date]:
    days = (request.date_of_departure - request.date_of_arrival).days
    return [request.date_of_arrival + timedelta(days=i) for i in range(days + 1)]


def _actual_cost(plan: TravelPlan) -> int:
    return sum(activity.price for _, activity in _activities(plan))


# ---------------------------------------------------------------------------
# Step 2 – required deterministic evals (goal.md §4)
# ---------------------------------------------------------------------------


# Phase 4 – Step 2: E1 – right city, right dates, every trip day exactly once and in order
def eval_city_and_dates(request: VacationInfo, plan: TravelPlan) -> EvalResult:
    problems = []
    if plan.city.strip().casefold() != request.destination.casefold():
        problems.append(f"city is '{plan.city}', expected '{request.destination}'")
    if plan.start_date != request.date_of_arrival:
        problems.append(f"start_date is {plan.start_date}, expected {request.date_of_arrival}")
    if plan.end_date != request.date_of_departure:
        problems.append(f"end_date is {plan.end_date}, expected {request.date_of_departure}")

    expected = _trip_dates(request)
    actual = [day.date for day in plan.itinerary_days]
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        duplicates = sorted(d for d, n in Counter(actual).items() if n > 1)
        if missing:
            problems.append(f"missing days: {', '.join(map(str, missing))}")
        if extra:
            problems.append(f"days outside the trip: {', '.join(map(str, extra))}")
        if duplicates:
            problems.append(f"days listed more than once: {', '.join(map(str, duplicates))}")
        if not (missing or extra or duplicates):
            problems.append("itinerary days are out of order")
    return _result("city_and_dates", problems)


# Phase 4 – Step 2: E2 – total_cost equals the plain sum of activity prices
def eval_total_cost_accurate(request: VacationInfo, plan: TravelPlan) -> EvalResult:
    actual = _actual_cost(plan)
    problems = []
    if plan.total_cost != actual:
        problems.append(f"plan says total_cost={plan.total_cost}, activities sum to {actual}")
    return _result("total_cost_accurate", problems)


# Phase 4 – Step 2: E3 – the real cost (not the reported total) fits the budget
def eval_within_budget(request: VacationInfo, plan: TravelPlan) -> EvalResult:
    actual = _actual_cost(plan)
    problems = []
    if actual > request.budget:
        problems.append(
            f"activities cost {actual}, budget is {request.budget} "
            f"(over by {actual - request.budget})"
        )
    return _result("within_budget", problems)


# Phase 4 – Step 2: E4 – every activity exists, matches the source exactly, and is on its day
def eval_no_hallucinated_activities(request: VacationInfo, plan: TravelPlan) -> EvalResult:
    problems = []
    for day, activity in _activities(plan):
        source = get_activity_by_id(activity.activity_id)
        if source is None:
            problems.append(f"{activity.activity_id} ('{activity.name}') does not exist")
            continue
        changed = [f for f in Activity.model_fields if getattr(activity, f) != getattr(source, f)]
        if changed:
            problems.append(
                f"{activity.activity_id}: fields differ from the source data: {', '.join(changed)}"
            )
        if source.start_time.date() != day.date:
            problems.append(
                f"{activity.activity_id}: listed on {day.date} "
                f"but takes place on {source.start_time.date()}"
            )
    return _result("no_hallucinated_activities", problems)


# ---------------------------------------------------------------------------
# Step 3 – extra deterministic evals
# ---------------------------------------------------------------------------


# Phase 4 – Step 3: X1 – each day's weather was copied correctly from the forecast
def eval_weather_matches_forecast(request: VacationInfo, plan: TravelPlan) -> EvalResult:
    problems = []
    for day in plan.itinerary_days:
        forecast = get_weather(day.date)
        if forecast is None:
            problems.append(f"{day.date}: no forecast exists for this date")
            continue
        w = day.weather
        if (
            w.temperature != forecast.temperature
            or w.temperature_unit.casefold() != forecast.temperature_unit.casefold()
            or w.condition.casefold() != forecast.condition.casefold()
        ):
            problems.append(
                f"{day.date}: plan says {w.condition} {w.temperature:g} {w.temperature_unit}, "
                f"forecast is {forecast.condition} {forecast.temperature:g} "
                f"{forecast.temperature_unit}"
            )
    return _result("weather_matches_forecast", problems)


# Phase 4 – Step 3: X2 – no time clashes within a day, no activity booked twice
def eval_no_overlapping_activities(request: VacationInfo, plan: TravelPlan) -> EvalResult:
    problems = []
    counts = Counter(activity.activity_id for _, activity in _activities(plan))
    problems += [f"{aid} appears {n} times" for aid, n in counts.items() if n > 1]
    for day in plan.itinerary_days:
        acts = [r.activity for r in day.activity_recommendations]
        ordered = sorted(acts, key=lambda a: a.start_time)
        for earlier, later in zip(ordered, ordered[1:], strict=False):
            if later.activity_id != earlier.activity_id and later.start_time < earlier.end_time:
                problems.append(
                    f"{day.date}: {earlier.activity_id} ({earlier.start_time:%H:%M}-"
                    f"{earlier.end_time:%H:%M}) overlaps {later.activity_id} "
                    f"({later.start_time:%H:%M}-{later.end_time:%H:%M})"
                )
    return _result("no_overlapping_activities", problems)


# Phase 4 – Step 3: X3 – share of travelers with at least one activity matching their interests
def eval_interest_coverage(request: VacationInfo, plan: TravelPlan) -> EvalResult:
    planned = {i for _, activity in _activities(plan) for i in activity.related_interests}
    problems = [
        f"{t.name}: no activity matches interests "
        f"({', '.join(i.value for i in t.interests)})"
        for t in request.travelers
        if not planned & set(t.interests)
    ]
    covered = len(request.travelers) - len(problems)
    return _result(
        "interest_coverage", problems, severity="warning", score=covered / len(request.travelers)
    )


# Phase 4 – Step 3: X4 – flag days with too few activities (Phase 11 will use minimum=2)
def eval_activities_per_day(
    request: VacationInfo, plan: TravelPlan, minimum: int = 1
) -> EvalResult:
    problems = [
        f"{day.date}: {len(day.activity_recommendations)} activities (minimum {minimum})"
        for day in plan.itinerary_days
        if len(day.activity_recommendations) < minimum
    ]
    return _result("activities_per_day", problems, severity="warning")


# ---------------------------------------------------------------------------
# Step 5 – weather suitability (LLM judge)
# ---------------------------------------------------------------------------

WEATHER_JUDGE_MODEL = "gpt-4.1"  # a judge should be at least as strong as the agent it grades

WEATHER_JUDGE_PROMPT = """\
You are a strict travel-safety reviewer. Decide whether a reasonable traveler could enjoy the
given activity in the given weather.

Rules:
- Indoor venues are suitable in any weather.
- Outdoor activities that state an indoor rain fallback are suitable in rain or thunderstorms.
- Outdoor-only activities during rain or thunderstorms are NOT suitable.
- If the forecast says when the bad weather arrives (e.g. "in the afternoon"), consider whether
  the activity's time avoids it.
- Base your decision only on the activity description and the forecast provided.

Reply with a JSON object only: {"suitable": true or false, "reason": "<one short sentence>"}"""


# Phase 4 – Step 5: the judge's structured verdict for one activity
class WeatherVerdict(BaseModel):
    suitable: bool
    reason: str


# Phase 4 – Step 5: ask the judge about one activity; fail closed on any problem
def judge_activity_weather(
    llm: LLMClient,
    activity: Activity,
    forecast: WeatherForecast,
    model: str = WEATHER_JUDGE_MODEL,
) -> WeatherVerdict:
    user_prompt = (
        f"ACTIVITY: {activity.name}\n"
        f"TIME: {activity.start_time:%Y-%m-%d %H:%M} to {activity.end_time:%H:%M}\n"
        f"LOCATION: {activity.location}\n"
        f"DESCRIPTION: {activity.description}\n\n"
        f"FORECAST: {forecast.condition}, {forecast.temperature:g} {forecast.temperature_unit}\n"
        f"FORECAST DESCRIPTION: {forecast.description}"
    )
    messages = [
        {"role": "system", "content": WEATHER_JUDGE_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    try:
        reply = llm.chat(messages, model=model, json_mode=True)
    except LLMError as exc:
        return WeatherVerdict(suitable=False, reason=f"judge call failed: {exc}")
    try:
        return WeatherVerdict.model_validate_json(reply.text)
    except ValidationError:
        return WeatherVerdict(suitable=False, reason="judge reply unparseable")


# Phase 4 – Step 5: E5 – judge every activity on an inclement day; other days pass without a call
def eval_weather_suitability(
    request: VacationInfo,
    plan: TravelPlan,
    llm: LLMClient,
    model: str = WEATHER_JUDGE_MODEL,
) -> EvalResult:
    problems = []
    for day in plan.itinerary_days:
        forecast = get_weather(day.date)
        if forecast is None or not is_inclement(forecast):
            continue
        for rec in day.activity_recommendations:
            verdict = judge_activity_weather(llm, rec.activity, forecast, model)
            if not verdict.suitable:
                problems.append(
                    f"{rec.activity.activity_id} on {day.date} ({forecast.condition}): "
                    f"{verdict.reason}"
                )
    return _result("weather_suitability", problems, kind="llm")


# ---------------------------------------------------------------------------
# Step 1 – runner
# ---------------------------------------------------------------------------


# Phase 4 – Step 1: run every eval; include_llm=False skips the LLM judge (no cost, no network)
def run_all_evals(
    request: VacationInfo,
    plan: TravelPlan,
    llm: LLMClient | None = None,
    include_llm: bool = True,
    min_activities_per_day: int = 1,
) -> EvalReport:
    if include_llm and llm is None:
        raise ValueError("an LLMClient is required when include_llm=True")

    results = [
        eval_city_and_dates(request, plan),
        eval_total_cost_accurate(request, plan),
        eval_within_budget(request, plan),
        eval_no_hallucinated_activities(request, plan),
        eval_weather_matches_forecast(request, plan),
        eval_no_overlapping_activities(request, plan),
    ]
    if include_llm:
        results.append(eval_weather_suitability(request, plan, llm))
    results += [
        eval_interest_coverage(request, plan),
        eval_activities_per_day(request, plan, minimum=min_activities_per_day),
    ]
    return EvalReport(results=results)
