# Phase 3 – Step 3: behavior of the mock weather/activity API.

import datetime

import pytest

from agentsville.data_api import (
    get_activities,
    get_activities_for_range,
    get_activity_by_id,
    get_weather,
    get_weather_for_range,
    is_inclement,
)
from agentsville.models import TRIP_WINDOW_END, TRIP_WINDOW_START, Activity, WeatherForecast

D = datetime.date

# --- weather -------------------------------------------------------------------


def test_weather_for_known_date():
    forecast = get_weather("2025-06-12")
    assert isinstance(forecast, WeatherForecast)
    assert forecast.condition == "thunderstorm"
    assert forecast.date == D(2025, 6, 12)
    assert "thunderstorm" in forecast.description.lower()


def test_weather_accepts_date_object():
    assert get_weather(D(2025, 6, 10)).condition == "clear"


@pytest.mark.parametrize("city", ["AgentsVille", "agentsville", " AGENTSVILLE "])
def test_weather_city_case_insensitive(city):
    assert get_weather("2025-06-10", city) is not None


def test_weather_unknown_date_is_none():
    assert get_weather("2025-06-09") is None


def test_weather_other_city_is_none():
    assert get_weather("2025-06-10", city="Paris") is None


def test_invalid_date_string_raises():
    with pytest.raises(ValueError):
        get_weather("not-a-date")


# --- activities ----------------------------------------------------------------


def test_activities_for_known_date():
    activities = get_activities("2025-06-11")
    assert len(activities) == 4
    assert all(isinstance(a, Activity) for a in activities)
    assert all(a.start_time.date() == D(2025, 6, 11) for a in activities)
    assert [a.start_time for a in activities] == sorted(a.start_time for a in activities)


def test_activities_unknown_date_is_empty():
    assert get_activities("2025-07-01") == []


def test_activities_other_city_is_empty():
    assert get_activities("2025-06-11", city="Paris") == []


def test_every_activity_reachable_by_date():
    days = get_activities_for_range(TRIP_WINDOW_START, TRIP_WINDOW_END)
    assert sum(len(acts) for acts in days.values()) == 24


# --- bulk ------------------------------------------------------------------------


def test_bulk_weather_three_days():
    result = get_weather_for_range("2025-06-10", "2025-06-12")
    assert list(result) == [D(2025, 6, 10), D(2025, 6, 11), D(2025, 6, 12)]


def test_bulk_weather_wider_than_data_returns_known_dates_only():
    result = get_weather_for_range("2025-06-08", "2025-06-17")
    assert list(result) == [TRIP_WINDOW_START + datetime.timedelta(days=i) for i in range(6)]


def test_bulk_activities_includes_empty_days():
    result = get_activities_for_range("2025-06-15", "2025-06-16")
    assert len(result[D(2025, 6, 15)]) == 4
    assert result[D(2025, 6, 16)] == []


@pytest.mark.parametrize("bulk", [get_weather_for_range, get_activities_for_range])
def test_bulk_start_after_end_raises(bulk):
    with pytest.raises(ValueError, match="must be on or before"):
        bulk("2025-06-12", "2025-06-10")


# --- by id -----------------------------------------------------------------------


def test_activity_by_id_known():
    activity = get_activity_by_id("event-2025-06-12-3")
    assert activity is not None
    assert activity.price == 15
    assert activity.start_time.date() == D(2025, 6, 12)


def test_activity_by_id_unknown_is_none():
    assert get_activity_by_id("event-2025-06-12-9") is None


# --- inclement -------------------------------------------------------------------


@pytest.mark.parametrize(
    "date, expected",
    [
        ("2025-06-10", False),
        ("2025-06-11", False),
        ("2025-06-12", True),
        ("2025-06-13", True),
        ("2025-06-14", True),
        ("2025-06-15", False),
    ],
)
def test_is_inclement(date, expected):
    assert is_inclement(get_weather(date)) is expected


# --- isolation from the cached data ----------------------------------------------


def test_mutating_results_does_not_change_later_calls():
    first = get_activities("2025-06-10")
    first.clear()
    get_activity_by_id("event-2025-06-10-0").price = 999
    get_activities("2025-06-10")[0].related_interests.clear()  # nested list
    get_weather("2025-06-10").condition = "snow"

    assert len(get_activities("2025-06-10")) == 4
    assert get_activity_by_id("event-2025-06-10-0").price == 20
    assert get_activities("2025-06-10")[0].related_interests == ["technology"]
    assert get_weather("2025-06-10").condition == "clear"
