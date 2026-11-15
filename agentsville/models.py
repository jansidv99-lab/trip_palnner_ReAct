# Phase 2 – Step 1: Pydantic data models shared by the agent, tools, evals and UI.

import datetime
import uuid
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# Phase 2 – Step 3: the only city and date range covered by data/data.py.
# Kept as constants (not read from the mock data); tests/test_models.py checks they match.
SUPPORTED_DESTINATION = "AgentsVille"
TRIP_WINDOW_START = datetime.date(2025, 6, 10)
TRIP_WINDOW_END = datetime.date(2025, 6, 15)


# Phase 2 – Step 1: interests a traveler can have (and activities are tagged with)
class Interest(str, Enum):
    ART = "art"
    COOKING = "cooking"
    COMEDY = "comedy"
    DANCING = "dancing"
    FITNESS = "fitness"
    GARDENING = "gardening"
    HIKING = "hiking"
    MOVIES = "movies"
    MUSIC = "music"
    PHOTOGRAPHY = "photography"
    READING = "reading"
    SPORTS = "sports"
    TECHNOLOGY = "technology"
    THEATRE = "theatre"
    TENNIS = "tennis"
    WRITING = "writing"

    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


# Phase 2 – Step 2: models offered in the UI (all verified to work through the LLM proxy)
class OpenAIModel(str, Enum):
    GPT_4O_MINI = "gpt-4o-mini"  # default: fast and cheap
    GPT_41_MINI = "gpt-4.1-mini"  # stronger, still affordable
    GPT_41 = "gpt-4.1"  # strongest: demanding reasoning, LLM-judge evals


# ---------------------------------------------------------------------------
# Input: what the traveler tells us
# ---------------------------------------------------------------------------


# Phase 2 – Step 1: one traveler and their interests
class Traveler(BaseModel):
    name: str = Field(min_length=1)
    age: int = Field(ge=0, le=120)
    interests: list[Interest] = Field(min_length=1)


# Phase 2 – Step 1: the full trip request – the agent's only input
class VacationInfo(BaseModel):
    travelers: list[Traveler] = Field(min_length=1)
    destination: str
    date_of_arrival: datetime.date
    date_of_departure: datetime.date
    budget: int = Field(gt=0)  # fictional currency units, for the whole group

    # Phase 2 – Step 3: accept any casing/spacing of AgentsVille; reject other cities
    @field_validator("destination")
    @classmethod
    def check_destination(cls, value: str) -> str:
        if value.strip().casefold() != SUPPORTED_DESTINATION.casefold():
            raise ValueError(
                f"destination must be {SUPPORTED_DESTINATION} (the only city with data)"
            )
        return SUPPORTED_DESTINATION

    # Phase 2 – Step 1: departure must not be before arrival (needs two fields → model validator)
    # Phase 2 – Step 3: both dates must fall inside the data window
    @model_validator(mode="after")
    def check_dates(self) -> "VacationInfo":
        if self.date_of_departure < self.date_of_arrival:
            raise ValueError("date_of_departure must be on or after date_of_arrival")
        if self.date_of_arrival < TRIP_WINDOW_START or self.date_of_departure > TRIP_WINDOW_END:
            raise ValueError(
                f"dates must be between {TRIP_WINDOW_START} and {TRIP_WINDOW_END} "
                "(the period with weather and activity data)"
            )
        return self


# ---------------------------------------------------------------------------
# Output: the itinerary the agent must return
# ---------------------------------------------------------------------------


# Phase 2 – Step 1: weather for one day
class Weather(BaseModel):
    temperature: float
    temperature_unit: str
    condition: str


# Phase 3 – Step 1: full forecast from the weather API – a Weather plus date, city, description.
# The description feeds the LLM-judge weather eval; TravelPlan keeps the plain Weather shape.
class WeatherForecast(Weather):
    date: datetime.date
    city: str
    description: str


# Phase 2 – Step 1: one bookable activity (mirrors the mock activities API)
class Activity(BaseModel):
    activity_id: str
    name: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    location: str
    description: str
    price: int
    related_interests: list[Interest]


# Phase 2 – Step 1: an activity plus why the agent picked it
class ActivityRecommendation(BaseModel):
    activity: Activity
    reasons_for_recommendation: list[str]


# Phase 2 – Step 1: one day of the itinerary
class ItineraryDay(BaseModel):
    date: datetime.date
    weather: Weather
    activity_recommendations: list[ActivityRecommendation]


# Phase 2 – Step 1: the complete plan returned by the agent's final_answer_tool
class TravelPlan(BaseModel):
    city: str
    start_date: datetime.date
    end_date: datetime.date
    total_cost: int  # plain sum of activity prices (per group, not × travelers)
    itinerary_days: list[ItineraryDay]


# ---------------------------------------------------------------------------
# Observability: what was sent to and received from the LLM
# ---------------------------------------------------------------------------


# Phase 2 – Step 1: one agent run's prompts, reply and metrics (used from Phase 6 on)
class PromptTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    model: str
    prompt_version: str | None = None  # which prompts/itinerary/<version>.md was used
    system_prompt: str
    user_prompt: str
    raw_response: str
    travel_plan: TravelPlan | None = None  # None when the reply couldn't be parsed
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
