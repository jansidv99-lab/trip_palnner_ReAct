# Phase 3 – Step 4: print review tables of the mock data (goal.md §2 "review the data manually").
"""Run from the repo root:  python scripts/review_data.py"""

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville import samples  # noqa: E402
from agentsville.data_api import (  # noqa: E402
    get_activities_for_range,
    get_weather_for_range,
    is_inclement,
)
from agentsville.models import TRIP_WINDOW_END, TRIP_WINDOW_START, Interest  # noqa: E402

OUTDOOR = re.compile(r"outdoor|open[- ]air|park|open sky|courts|trail", re.I)
INDOOR = re.compile(r"indoor|inside|atrium|hall|studio|theat(er|re)|gallery|caf[eé]|library", re.I)
FALLBACK = re.compile(r"in case of rain|if it rains|rain or shine|move(s)? indoors", re.I)


# Phase 3 – Step 4: rough keyword hint only – the real judgment is the Phase 4 LLM-judge eval
def setting_hint(description: str) -> str:
    parts = [
        name
        for name, pattern in (("outdoor", OUTDOOR), ("indoor", INDOOR), ("rain-fallback", FALLBACK))
        if pattern.search(description)
    ]
    return "/".join(parts) or "?"


def heading(title: str) -> None:
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")


# Phase 3 – Step 4: one line per day – weather, inclement flag, activity count, price range
def daily_overview(weather, activities) -> None:
    heading("1. Daily overview")
    print(f"{'date':<12}{'condition':<15}{'temp':>6}  {'inclement':<10}{'#acts':>6}  prices")
    for day, forecast in weather.items():
        prices = [a.price for a in activities[day]]
        temp = f"{forecast.temperature:.0f}°C"
        flag = "YES" if is_inclement(forecast) else "-"
        price_range = f"{min(prices)}–{max(prices)}" if prices else "-"
        print(
            f"{day!s:<12}{forecast.condition:<15}{temp:>6}  {flag:<10}"
            f"{len(prices):>6}  {price_range}"
        )


# Phase 3 – Step 4: every activity with time slot, price, interests and setting hint
def activity_table(weather, activities) -> None:
    heading("2. Activities (setting = keyword HINT from the description, not ground truth)")
    print(f"{'id':<21}{'slot':<14}{'price':>5}  {'setting':<30}interests")
    for day, acts in activities.items():
        bad = "  <-- " + weather[day].condition if is_inclement(weather[day]) else ""
        print(f"-- {day}{bad}")
        for a in acts:
            slot = f"{a.start_time:%H:%M}-{a.end_time:%H:%M}"
            interests = ", ".join(i.value for i in a.related_interests)
            print(
                f"{a.activity_id:<21}{slot:<14}{a.price:>5}  "
                f"{setting_hint(a.description):<30}{interests}"
            )


# Phase 3 – Step 4: how many activities match each interest, and on which days
def interest_coverage(activities) -> None:
    heading("3. Interest coverage")
    days_by_interest = defaultdict(list)
    for day, acts in activities.items():
        for a in acts:
            for interest in a.related_interests:
                days_by_interest[interest].append(f"{day:%m-%d}")
    for interest in Interest:
        days = days_by_interest.get(interest, [])
        warning = "  <-- NEVER" if not days else ("  <-- rare" if len(days) == 1 else "")
        print(f"{interest.value:<13}{len(days):>3}  {', '.join(days)}{warning}")


# Phase 3 – Step 4: for each sample request, matching activities per traveler per day
def sample_check(weather, activities) -> None:
    heading("4. Sample requests vs available activities")
    for factory in (
        samples.sample_vacation_info,
        samples.tight_budget_vacation_info,
        samples.rainy_days_vacation_info,
    ):
        request = factory()
        print(
            f"\n{factory.__name__}: {request.date_of_arrival} → {request.date_of_departure}, "
            f"budget {request.budget}"
        )
        for day in get_weather_for_range(request.date_of_arrival, request.date_of_departure):
            flag = f" ({weather[day].condition}, INCLEMENT)" if is_inclement(weather[day]) else ""
            print(f"  {day}{flag}")
            for traveler in request.travelers:
                matches = [
                    f"{a.activity_id[-1]}:{a.name[:28]} [{setting_hint(a.description)}]"
                    for a in activities[day]
                    if set(a.related_interests) & set(traveler.interests)
                ]
                print(f"    {traveler.name:<6}{'; '.join(matches) or '— no matching activity —'}")


# Phase 3 – Step 4: print all four review tables
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252 (no → or °)
    weather = get_weather_for_range(TRIP_WINDOW_START, TRIP_WINDOW_END)
    activities = get_activities_for_range(TRIP_WINDOW_START, TRIP_WINDOW_END)
    daily_overview(weather, activities)
    activity_table(weather, activities)
    interest_coverage(activities)
    sample_check(weather, activities)


if __name__ == "__main__":
    main()
