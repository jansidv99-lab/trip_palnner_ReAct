# Phase 3 – Step 2: mock weather/activity API – the ONLY module that reads data/data.py.
"""Data access layer.

Functions behave like calls to real weather and activity APIs (date + city in, models out).
Evals, tools and the agent use these functions, never `data.data` directly, so a real API
can replace the mock later without touching callers.

"Not found" is a normal answer: `None` for a single item, `[]` for a list.
"""

import datetime
from functools import cache

from agentsville.models import SUPPORTED_DESTINATION, Activity, WeatherForecast
from data.data import ACTIVITY_CALENDAR, INCLIMATE_WEATHER_CONDITIONS, WEATHER_FORECAST

DateLike = datetime.date | str


# Phase 3 – Step 2: accept a date object or an ISO string ("2025-06-12") – the LLM sends strings
def _to_date(value: DateLike) -> datetime.date:
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(value.strip())


# Phase 3 – Step 2: only AgentsVille has data; match case-insensitively like VacationInfo
def _is_supported_city(city: str) -> bool:
    return city.strip().casefold() == SUPPORTED_DESTINATION.casefold()


# Phase 3 – Step 2: build lookup tables once (the mock data never changes at runtime)
@cache
def _weather_by_date() -> dict[datetime.date, WeatherForecast]:
    forecasts = (WeatherForecast(**record) for record in WEATHER_FORECAST)
    return {forecast.date: forecast for forecast in forecasts}


@cache
def _activities_by_date() -> dict[datetime.date, tuple[Activity, ...]]:
    index: dict[datetime.date, list[Activity]] = {}
    for record in ACTIVITY_CALENDAR:
        activity = Activity(**record)
        index.setdefault(activity.start_time.date(), []).append(activity)
    return {day: tuple(sorted(acts, key=lambda a: a.start_time)) for day, acts in index.items()}


@cache
def _activities_by_id() -> dict[str, Activity]:
    return {a.activity_id: a for acts in _activities_by_date().values() for a in acts}


# Phase 3 – Step 2: validate a date range for the bulk functions
def _date_range(start: DateLike, end: DateLike) -> list[datetime.date]:
    start_date, end_date = _to_date(start), _to_date(end)
    if start_date > end_date:
        raise ValueError(f"start ({start_date}) must be on or before end ({end_date})")
    days = (end_date - start_date).days
    return [start_date + datetime.timedelta(days=i) for i in range(days + 1)]


# Phase 3 – Step 2: weather forecast for one day, or None if there's no data
def get_weather(date: DateLike, city: str = SUPPORTED_DESTINATION) -> WeatherForecast | None:
    if not _is_supported_city(city):
        return None
    forecast = _weather_by_date().get(_to_date(date))
    return forecast.model_copy() if forecast else None


# Phase 3 – Step 2: activities for one day, sorted by start time ([] if none)
def get_activities(date: DateLike, city: str = SUPPORTED_DESTINATION) -> list[Activity]:
    if not _is_supported_city(city):
        return []
    return [a.model_copy(deep=True) for a in _activities_by_date().get(_to_date(date), ())]


# Phase 3 – Step 2: bulk weather for a date range; dates without data are left out
def get_weather_for_range(
    start: DateLike, end: DateLike, city: str = SUPPORTED_DESTINATION
) -> dict[datetime.date, WeatherForecast]:
    result = {day: get_weather(day, city) for day in _date_range(start, end)}
    return {day: forecast for day, forecast in result.items() if forecast is not None}


# Phase 3 – Step 2: bulk activities for a date range; every date present ([] if none)
def get_activities_for_range(
    start: DateLike, end: DateLike, city: str = SUPPORTED_DESTINATION
) -> dict[datetime.date, list[Activity]]:
    return {day: get_activities(day, city) for day in _date_range(start, end)}


# Phase 3 – Step 2: exact activity details by ID (used by evals and tools), or None
def get_activity_by_id(activity_id: str) -> Activity | None:
    activity = _activities_by_id().get(activity_id.strip())
    return activity.model_copy(deep=True) if activity else None


# Phase 3 – Step 2: is this day's weather bad for outdoor plans?
def is_inclement(forecast: WeatherForecast) -> bool:
    return forecast.condition.casefold() in INCLIMATE_WEATHER_CONDITIONS
