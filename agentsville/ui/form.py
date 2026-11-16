# Phase 12 – Step 2: trip form state <-> VacationInfo, readable field errors, interest hints.
"""Pure functions behind the trip form; `app.py` only draws the widgets.

The form holds raw widget values (`TripForm`). `to_vacation_info` validates them with the same
Pydantic models the agent uses and turns any `ValidationError` into one readable `FieldError`
per problem, e.g. "Traveler 2 (Hiro) – age: must be at most 120".
"""

import datetime
from dataclasses import dataclass, field

from pydantic import ValidationError

from agentsville import data_api
from agentsville.models import (
    SUPPORTED_DESTINATION,
    Interest,
    OpenAIModel,
    VacationInfo,
)
from agentsville.samples import sample_vacation_info

# Phase 12 – Step 2: shown next to the budget (Q4) – the agent and evals add prices once per group
COST_RULE = "Prices are added once for the whole group, not per person."

DEFAULT_MAX_STEPS = 20

_FIELD_LABELS = {
    "name": "name",
    "age": "age",
    "interests": "interests",
    "travelers": "Travelers",
    "destination": "Destination",
    "date_of_arrival": "Arrival date",
    "date_of_departure": "Departure date",
    "budget": "Budget",
}


# Phase 12 – Step 2: raw values of one traveler row (strings/ints as the widgets return them)
@dataclass
class TravelerInput:
    name: str = ""
    age: int = 30
    interests: list[Interest] = field(default_factory=list)


# Phase 12 – Step 2: raw values of the whole form
@dataclass
class TripForm:
    travelers: list[TravelerInput]
    date_of_arrival: datetime.date
    date_of_departure: datetime.date
    budget: int


# Phase 12 – Step 2: "Advanced" settings – not part of VacationInfo, consumed by the run (Step 3)
@dataclass(frozen=True)
class RunOptions:
    model: OpenAIModel = OpenAIModel.GPT_4O_MINI
    include_llm_evals: bool = True  # the in-loop weather judge
    max_steps: int = DEFAULT_MAX_STEPS


# Phase 12 – Step 2: one readable problem with the form
@dataclass(frozen=True)
class FieldError:
    field: str  # e.g. "Traveler 2 (Hiro) – age", "Budget", "Dates"
    message: str

    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


# Phase 12 – Step 2: pre-filled form = the sample trip, so a first-time user can just click Generate
def default_form() -> TripForm:
    info = sample_vacation_info()
    return TripForm(
        travelers=[
            TravelerInput(name=t.name, age=t.age, interests=list(t.interests))
            for t in info.travelers
        ],
        date_of_arrival=info.date_of_arrival,
        date_of_departure=info.date_of_departure,
        budget=info.budget,
    )


# Phase 12 – Step 2: validate the form; a VacationInfo on success, otherwise every problem found
def to_vacation_info(form: TripForm) -> VacationInfo | list[FieldError]:
    try:
        return VacationInfo(
            travelers=[
                {"name": t.name.strip(), "age": t.age, "interests": t.interests}
                for t in form.travelers
            ],
            destination=SUPPORTED_DESTINATION,
            date_of_arrival=form.date_of_arrival,
            date_of_departure=form.date_of_departure,
            budget=form.budget,
        )
    except ValidationError as exc:
        errors = [_to_field_error(err, form) for err in exc.errors(include_url=False)]
    # Pydantic skips the model-level date check when a field fails; check it here so the user
    # sees every problem at once instead of fixing them one round at a time.
    if form.date_of_departure < form.date_of_arrival and not any(
        e.field == "Dates" for e in errors
    ):
        errors.append(FieldError("Dates", "departure must be on or after arrival"))
    return errors


# Phase 12 – Step 2: one Pydantic error dict -> FieldError with a plain-words label and message
def _to_field_error(err: dict, form: TripForm) -> FieldError:
    loc = err["loc"]
    if not loc:  # model-level validator (the date checks)
        return FieldError("Dates", _plain_message(err))
    if loc[0] == "travelers" and len(loc) >= 3 and isinstance(loc[1], int):
        index = loc[1]
        name = form.travelers[index].name.strip() if index < len(form.travelers) else ""
        who = f"Traveler {index + 1}" + (f" ({name})" if name else "")
        return FieldError(f"{who} – {_FIELD_LABELS.get(loc[2], loc[2])}", _plain_message(err))
    return FieldError(_FIELD_LABELS.get(loc[0], str(loc[0])), _plain_message(err))


# Phase 12 – Step 2: Pydantic's technical messages -> short user-facing ones
def _plain_message(err: dict) -> str:
    ctx = err.get("ctx") or {}
    kind = err["type"]
    field_name = err["loc"][-1] if err["loc"] else None
    if kind == "string_too_short":
        return "is required"
    if kind == "too_short":
        if field_name == "interests":
            return "pick at least one interest"
        if field_name == "travelers":
            return "add at least one traveler"
        return f"needs at least {ctx.get('min_length', 1)} item(s)"
    if kind == "greater_than":
        return f"must be greater than {ctx['gt']}"
    if kind == "greater_than_equal":
        return f"must be at least {ctx['ge']}"
    if kind == "less_than_equal":
        return f"must be at most {ctx['le']}"
    if kind == "value_error":
        message = str(ctx.get("error", err["msg"]))
        return message.replace("date_of_departure", "departure").replace(
            "date_of_arrival", "arrival"
        )
    return err["msg"]


# Phase 12 – Step 2: interests that NO activity offers on the chosen dates (from data_api, not LLM)
def unavailable_interests(start: datetime.date, end: datetime.date) -> set[Interest]:
    if start > end:
        return set()  # the date error is shown instead
    offered = {
        interest
        for activities in data_api.get_activities_for_range(start, end).values()
        for activity in activities
        for interest in activity.related_interests
    }
    return set(Interest) - offered


# Phase 12 – Step 2: hint for one traveler, or None when all their interests can be served
def interest_hint(interests: list[Interest], unavailable: set[Interest]) -> str | None:
    missing = [str(i) for i in interests if i in unavailable]
    if not missing:
        return None
    return f"No activity for {', '.join(missing)} on these dates."
