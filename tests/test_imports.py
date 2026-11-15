# Phase 0 – Step 7: the package and the mock data import, and the data has the expected shape.

from data.data import ACTIVITY_CALENDAR, INCLIMATE_WEATHER_CONDITIONS, WEATHER_FORECAST


def test_models_import():
    from agentsville.models import TravelPlan, VacationInfo  # noqa: F401


def test_activity_calendar_has_24_activities():
    assert len(ACTIVITY_CALENDAR) == 25  # DEMO: deliberately wrong, never merge


def test_weather_forecast_covers_six_days():
    dates = [day["date"] for day in WEATHER_FORECAST]
    assert dates == [f"2025-06-{d}" for d in range(10, 16)]


def test_inclement_conditions():
    assert set(INCLIMATE_WEATHER_CONDITIONS) == {"thunderstorm", "rainy"}
