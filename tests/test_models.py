# Phase 2 – Step 5: VacationInfo rules, samples, model list, and data-window consistency.

import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentsville.llm import PRICES_PER_1M_TOKENS
from agentsville.models import (
    SUPPORTED_DESTINATION,
    TRIP_WINDOW_END,
    TRIP_WINDOW_START,
    OpenAIModel,
    TravelPlan,
    VacationInfo,
)
from agentsville.samples import (
    rainy_days_vacation_info,
    sample_vacation_info,
    tight_budget_vacation_info,
)
from data.data import ACTIVITY_CALENDAR, WEATHER_FORECAST

REPO_ROOT = Path(__file__).resolve().parent.parent


# Phase 2 – Step 5: a valid request as a dict; tests override one field at a time
def valid_request(**overrides) -> dict:
    request = {
        "travelers": [{"name": "Yuri", "age": 30, "interests": ["technology"]}],
        "destination": "AgentsVille",
        "date_of_arrival": "2025-06-10",
        "date_of_departure": "2025-06-12",
        "budget": 130,
    }
    request.update(overrides)
    return request


def error_fields(exc: ValidationError) -> set:
    """Top-level field names that have errors ('' for model-level errors)."""
    return {str(err["loc"][0]) if err["loc"] else "" for err in exc.errors()}


# --- valid input -----------------------------------------------------------


@pytest.mark.parametrize(
    "factory", [sample_vacation_info, tight_budget_vacation_info, rainy_days_vacation_info]
)
def test_samples_are_valid(factory):
    assert isinstance(factory(), VacationInfo)


def test_samples_return_new_objects():
    assert sample_vacation_info() is not sample_vacation_info()


def test_sample_plan_json_parses_and_matches_sample_request():
    plan_json = (REPO_ROOT / "sample_plan.json").read_text(encoding="utf-8")
    plan = TravelPlan.model_validate_json(plan_json)
    request = sample_vacation_info()
    assert plan.city == request.destination
    assert (plan.start_date, plan.end_date) == (request.date_of_arrival, request.date_of_departure)
    assert plan.total_cost <= request.budget


def test_one_day_trip_is_valid():
    VacationInfo(**valid_request(date_of_arrival="2025-06-11", date_of_departure="2025-06-11"))


def test_duplicate_traveler_names_allowed():
    traveler = {"name": "Yuri", "age": 30, "interests": ["art"]}
    VacationInfo(**valid_request(travelers=[traveler, {**traveler, "name": "yuri"}]))


# --- destination -------------------------------------------------------------


@pytest.mark.parametrize("value", ["AgentsVille", "agentsville", "  AGENTSVILLE  "])
def test_destination_normalized(value):
    assert VacationInfo(**valid_request(destination=value)).destination == SUPPORTED_DESTINATION


def test_other_destination_rejected():
    with pytest.raises(ValidationError, match="destination must be AgentsVille") as exc:
        VacationInfo(**valid_request(destination="Paris"))
    assert error_fields(exc.value) == {"destination"}


# --- dates -------------------------------------------------------------------


def test_departure_before_arrival_rejected():
    with pytest.raises(ValidationError, match="on or after date_of_arrival"):
        VacationInfo(**valid_request(date_of_arrival="2025-06-12", date_of_departure="2025-06-10"))


@pytest.mark.parametrize(
    "arrival, departure",
    [("2025-06-09", "2025-06-11"), ("2025-06-14", "2025-06-16"), ("2026-01-01", "2026-01-02")],
)
def test_dates_outside_window_rejected(arrival, departure):
    with pytest.raises(ValidationError, match="dates must be between 2025-06-10 and 2025-06-15"):
        VacationInfo(**valid_request(date_of_arrival=arrival, date_of_departure=departure))


def test_full_window_is_valid():
    VacationInfo(**valid_request(date_of_arrival="2025-06-10", date_of_departure="2025-06-15"))


# --- travelers and budget ----------------------------------------------------


@pytest.mark.parametrize(
    "travelers",
    [
        [],
        [{"name": "", "age": 30, "interests": ["art"]}],
        [{"name": "A", "age": -1, "interests": ["art"]}],
        [{"name": "A", "age": 121, "interests": ["art"]}],
        [{"name": "A", "age": 30, "interests": []}],
        [{"name": "A", "age": 30, "interests": ["skiing"]}],
    ],
)
def test_invalid_travelers_rejected(travelers):
    with pytest.raises(ValidationError) as exc:
        VacationInfo(**valid_request(travelers=travelers))
    assert error_fields(exc.value) == {"travelers"}


@pytest.mark.parametrize("budget", [0, -10])
def test_non_positive_budget_rejected(budget):
    with pytest.raises(ValidationError) as exc:
        VacationInfo(**valid_request(budget=budget))
    assert error_fields(exc.value) == {"budget"}


def test_all_field_errors_reported_together():
    with pytest.raises(ValidationError) as exc:
        VacationInfo(**valid_request(travelers=[], destination="Paris", budget=0))
    assert error_fields(exc.value) == {"travelers", "destination", "budget"}


# --- model list --------------------------------------------------------------


def test_model_list_matches_proxy():
    assert {m.value for m in OpenAIModel} == {"gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1"}


def test_every_model_has_a_price():
    missing = [m.value for m in OpenAIModel if m.value not in PRICES_PER_1M_TOKENS]
    assert not missing, f"add prices for: {missing}"


# --- consistency with the mock data ------------------------------------------


def test_window_matches_weather_data():
    dates = sorted(datetime.date.fromisoformat(d["date"]) for d in WEATHER_FORECAST)
    assert (dates[0], dates[-1]) == (TRIP_WINDOW_START, TRIP_WINDOW_END)


def test_window_matches_activity_data():
    dates = sorted(datetime.date.fromisoformat(a["start_time"][:10]) for a in ACTIVITY_CALENDAR)
    assert (dates[0], dates[-1]) == (TRIP_WINDOW_START, TRIP_WINDOW_END)
