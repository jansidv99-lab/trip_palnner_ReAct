# Phase 8 – Step 2: B1 grounding graders – is everything in the plan real?
"""Code graders (exact, free) and one LLM judge for the recommendation reasons.

Sources of truth: data_api (activities, weather), the request (travelers, interests) and the run's
own tool observations (what the agent actually saw).
"""

import json
import re
from collections.abc import Iterator

from pydantic import BaseModel, ValidationError

from agentsville.agent import AgentRun
from agentsville.data_api import get_activity_by_id, get_weather
from agentsville.harness.grading import GraderOutcome, RunGrader, outcome
from agentsville.llm import LLMError
from agentsville.models import Activity, Interest, ItineraryDay, Traveler, WeatherForecast
from agentsville.prompts import render_prompt

ACTIVITY_TOOLS = {
    "get_activities_by_date_tool",
    "get_activity_by_id_tool",
    "filter_activities_by_interest_tool",
}
WEATHER_TOOL = "get_weather_for_date_tool"
REASONS_JUDGE_MODEL = "gpt-4.1"
REASONS_JUDGE_PROMPT_VERSION = "v1"


def _planned(run: AgentRun) -> Iterator[tuple[ItineraryDay, Activity, list[str]]]:
    for day in run.travel_plan.itinerary_days:
        for rec in day.activity_recommendations:
            yield day, rec.activity, rec.reasons_for_recommendation


# Phase 8 – Step 2: show where two texts first differ (the hint the in-loop eval lacks, finding g05)
def first_difference(planned: str, source: str, context: int = 25) -> str:
    index = next(
        (i for i, (a, b) in enumerate(zip(planned, source, strict=False)) if a != b),
        min(len(planned), len(source)),
    )
    start = max(0, index - context)
    return (f"at char {index}: plan …{planned[start:index + context]!r}… vs source "
            f"…{source[start:index + context]!r}…")


# ---------------------------------------------------------------------------
# Code graders
# ---------------------------------------------------------------------------


# Phase 8 – Step 2: every planned activity exists, matches the source exactly and sits on its day
def activity_grounding(run: AgentRun, llm=None) -> GraderOutcome:
    problems, counts, units = [], {"fabricated": 0, "altered": 0, "wrong_day": 0}, 0
    for day, activity, _ in _planned(run):
        units += 1
        source = get_activity_by_id(activity.activity_id)
        if source is None:
            counts["fabricated"] += 1
            problems.append(f"fabricated: {activity.activity_id} ('{activity.name}') not in data")
            continue
        changed = [f for f in Activity.model_fields if getattr(activity, f) != getattr(source, f)]
        if changed:
            counts["altered"] += 1
            hint = ""
            if "description" in changed:
                diff = first_difference(activity.description, source.description)
                hint = f" – description {diff}"
            problems.append(f"altered: {activity.activity_id} fields {', '.join(changed)}{hint}")
        elif source.start_time.date() != day.date:
            counts["wrong_day"] += 1
            problems.append(f"wrong_day: {activity.activity_id} listed on {day.date}, "
                            f"takes place on {source.start_time.date()}")
    return outcome("activity_grounding", "deterministic", units, problems, counts)


# Phase 8 – Step 2: each day's weather equals the forecast for that date
def weather_grounding(run: AgentRun, llm=None) -> GraderOutcome:
    problems = []
    days = run.travel_plan.itinerary_days
    for day in days:
        forecast = get_weather(day.date)
        w = day.weather
        if forecast is None:
            problems.append(f"{day.date}: no forecast exists")
        elif (w.temperature, w.temperature_unit.casefold(), w.condition.casefold()) != (
            forecast.temperature, forecast.temperature_unit.casefold(),
            forecast.condition.casefold(),
        ):
            problems.append(f"{day.date}: plan says {w.condition} {w.temperature:g}, "
                            f"forecast {forecast.condition} {forecast.temperature:g}")
    return outcome("weather_grounding", "deterministic", len(days), problems)


def _observed(run: AgentRun) -> tuple[set[str], set[str]]:
    activity_ids, weather_dates = set(), set()
    for step in run.steps:
        if step.is_error or step.tool_name not in ACTIVITY_TOOLS | {WEATHER_TOOL}:
            continue
        try:
            data = json.loads(step.observation)
        except json.JSONDecodeError:
            continue  # "No activities on …" style messages
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if step.tool_name == WEATHER_TOOL and "date" in item:
                weather_dates.add(str(item["date"]))
            elif "activity_id" in item:
                activity_ids.add(item["activity_id"])
    return activity_ids, weather_dates


# Phase 8 – Step 2: the agent actually retrieved every activity and day's weather it used
def trajectory_grounding(run: AgentRun, llm=None) -> GraderOutcome:
    seen_activities, seen_weather = _observed(run)
    problems, counts = [], {"activity_not_retrieved": 0, "weather_not_retrieved": 0}
    days = run.travel_plan.itinerary_days
    for day in days:
        if str(day.date) not in seen_weather:
            counts["weather_not_retrieved"] += 1
            problems.append(f"{day.date}: weather used but never retrieved with {WEATHER_TOOL}")
    planned = list(_planned(run))
    for _day, activity, _ in planned:
        if activity.activity_id not in seen_activities:
            counts["activity_not_retrieved"] += 1
            problems.append(f"{activity.activity_id}: in the plan but never seen in a tool result")
    return outcome("trajectory_grounding", "deterministic", len(days) + len(planned),
                   problems, counts)


_POSSESSIVE = re.compile(r"\b([A-Z][a-zA-Z]+)'s\b")
_INTEREST_WORDS = {i.value: i for i in Interest}


# Phase 8 – Step 2: possessive names must be travelers, and their claimed interests theirs
def check_reason_references(reason: str, travelers: list[Traveler]) -> list[str]:
    by_name = {t.name.casefold(): t for t in travelers}
    matches = list(_POSSESSIVE.finditer(reason))
    problems = []
    for index, match in enumerate(matches):
        name = match.group(1)
        traveler = by_name.get(name.casefold())
        if traveler is None:
            problems.append(f"'{name}' is not a traveler")
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(reason)
        window = reason[match.end():end].casefold()
        for word, interest in _INTEREST_WORDS.items():
            if re.search(rf"\b{word}\b", window) and interest not in traveler.interests:
                problems.append(f"{traveler.name} has no interest in {word}")
    return problems


# Phase 8 – Step 2: cheap pattern check of the reasons against the request
def reason_references(run: AgentRun, llm=None) -> GraderOutcome:
    travelers = run.vacation_info.travelers
    problems, units, failed = [], 0, 0
    for _, activity, reasons in _planned(run):
        for reason in reasons:
            units += 1
            issues = check_reason_references(reason, travelers)
            if issues:
                failed += 1
                problems.append(f"{activity.activity_id}: {reason!r} – {'; '.join(issues)}")
    return outcome("reason_references", "deterministic", units, problems, failed_units=failed)


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------


class ReasonVerdict(BaseModel):
    index: int
    grounded: bool
    unsupported_claim: str = ""


class ReasonsVerdict(BaseModel):
    reasons: list[ReasonVerdict]


# Phase 8 – Step 4: the versioned judge system prompt
def reasons_judge_prompt(version: str = REASONS_JUDGE_PROMPT_VERSION) -> str:
    return render_prompt("judges/reasons_grounded", version, {})


# Phase 8 – Step 4: everything the judge may use, nothing more
def reasons_judge_input(
    activity: Activity,
    forecast: WeatherForecast | None,
    travelers: list[Traveler],
    reasons: list[str],
) -> str:
    weather = (f"{forecast.condition}, {forecast.temperature:g} {forecast.temperature_unit}. "
               f"{forecast.description}") if forecast else "unknown"
    lines = [
        f"ACTIVITY: {activity.name} ({activity.activity_id})",
        f"TIME: {activity.start_time:%Y-%m-%d %H:%M} to {activity.end_time:%H:%M}",
        f"LOCATION: {activity.location}",
        f"PRICE: {activity.price}",
        f"RELATED INTERESTS: {', '.join(i.value for i in activity.related_interests)}",
        f"DESCRIPTION: {activity.description}",
        f"FORECAST: {weather}",
        "TRAVELERS:",
        *[f"- {t.name}: {', '.join(i.value for i in t.interests)}" for t in travelers],
        "REASONS:",
        *[f"{n}. {reason}" for n, reason in enumerate(reasons, start=1)],
    ]
    return "\n".join(lines)


# Phase 8 – Step 4: judge one activity's reasons → one bool per reason (fails closed)
def judge_reasons(
    llm, activity: Activity, forecast: WeatherForecast | None, travelers: list[Traveler],
    reasons: list[str], model: str = REASONS_JUDGE_MODEL,
) -> list[ReasonVerdict]:
    if not reasons:
        return []
    messages = [
        {"role": "system", "content": reasons_judge_prompt()},
        {"role": "user", "content": reasons_judge_input(activity, forecast, travelers, reasons)},
    ]
    failure = None
    try:
        reply = llm.chat(messages, model=model, json_mode=True)
        verdicts = ReasonsVerdict.model_validate_json(reply.text).reasons
        if len(verdicts) != len(reasons):
            failure = f"judge returned {len(verdicts)} verdicts for {len(reasons)} reasons"
    except LLMError as exc:
        failure = f"judge call failed: {exc}"
    except ValidationError:
        failure = "judge reply unparseable"
    if failure:
        return [ReasonVerdict(index=n, grounded=False, unsupported_claim=failure)
                for n in range(1, len(reasons) + 1)]
    return verdicts


# Phase 8 – Step 4: LLM judge – every claim in every reason is supported by the provided facts
def reasons_grounded(run: AgentRun, llm) -> GraderOutcome:
    travelers = run.vacation_info.travelers
    problems, units, failed = [], 0, 0
    for day, activity, reasons in _planned(run):
        source = get_activity_by_id(activity.activity_id) or activity
        verdicts = judge_reasons(llm, source, get_weather(day.date), travelers, reasons)
        for reason, verdict in zip(reasons, verdicts, strict=True):
            units += 1
            if not verdict.grounded:
                failed += 1
                problems.append(f"{activity.activity_id}: {reason!r} – unsupported: "
                                f"{verdict.unsupported_claim or 'unspecified'}")
    return outcome("reasons_grounded", "llm", units, problems, failed_units=failed)


B1_GRADERS = [
    RunGrader("activity_grounding", "deterministic", activity_grounding),
    RunGrader("weather_grounding", "deterministic", weather_grounding),
    RunGrader("trajectory_grounding", "deterministic", trajectory_grounding),
    RunGrader("reason_references", "deterministic", reason_references),
    RunGrader("reasons_grounded", "llm", reasons_grounded),
]
