# Phase 7 – Step 2: build golden dataset v1.0.0 from reviewed definitions (provenance script).
"""Run once from the repo root to create a NEW version:  python scripts/build_golden_dataset.py

Released versions are immutable – write_golden refuses to overwrite. To change anything, bump the
version (v1.1.0 for added cases, v2.0.0 for changed meaning) and add a CHANGELOG entry.

Labels come from ONE human weather judgment per activity (data review D2–D5, plan/03-data-access/
data-review.md), applied to each case's dates. Coverage and affordability are derived from it.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.data_api import get_activities  # noqa: E402
from agentsville.harness.dataset import (  # noqa: E402
    DATASETS_DIR,
    GoldenCase,
    GoldenLabels,
    write_golden,
)
from agentsville.models import Interest as I  # noqa: E402,N817
from agentsville.models import Traveler, VacationInfo  # noqa: E402

VERSION = "v1.0.0"
CREATED = date(2026, 11, 15)

# Human weather labels (inclement days 06-12 thunderstorm, 06-13/06-14 rain):
# outdoor-only activities with no rain fallback are clearly unsuitable.
WEATHER_UNSUITABLE = {
    "event-2025-06-12-2",  # Trail Tales hike, 14:00–16:30, during the afternoon storm
    "event-2025-06-13-1",  # lunchtime hike in rain
    "event-2025-06-13-2",  # outdoor art & photography walk in rain
    "event-2025-06-13-3",  # sunset hike in rain
    "event-2025-06-14-0",  # sunrise nature walk in rain
    "event-2025-06-14-1",  # outdoor gardening/fitness in rain
    "event-2025-06-14-2",  # outdoor garden art in rain
}
# Deliberately unlabeled: 08:00–10:00 hike before a storm forecast for the AFTERNOON (D2).
WEATHER_AMBIGUOUS = {"event-2025-06-12-0"}
# Explicitly suitable despite bad weather: 06-12-1 has an indoor rain fallback (D4);
# 06-14-3 is held indoors although a keyword heuristic says "outdoor" (D5).


def T(name: str, age: int, *interests: I) -> Traveler:  # noqa: N802
    return Traveler(name=name, age=age, interests=list(interests))


def trip(travelers: list[Traveler], start: str, end: str, budget: int) -> VacationInfo:
    return VacationInfo(
        travelers=travelers,
        destination="AgentsVille",
        date_of_arrival=date.fromisoformat(start),
        date_of_departure=date.fromisoformat(end),
        budget=budget,
    )


# Phase 7 – Step 2: derive the labels for one case from the per-activity weather judgments
def labels_for(request: VacationInfo, expected: str, budget_case: bool) -> GoldenLabels:
    days = (request.date_of_departure - request.date_of_arrival).days + 1
    activities = [
        a
        for i in range(days)
        for a in get_activities(request.date_of_arrival + timedelta(days=i))
    ]
    ids = {a.activity_id for a in activities}
    # Only clearly suitable activities count for coverage: a traveler reachable solely via an
    # ambiguous activity is not reliably coverable, so a cautious agent must not be penalized.
    suitable = [
        a for a in activities if a.activity_id not in WEATHER_UNSUITABLE | WEATHER_AMBIGUOUS
    ]
    uncoverable = [
        t.name for t in request.travelers
        if not any(set(a.related_interests) & set(t.interests) for a in suitable)
    ]
    max_affordable = None
    if budget_case:
        total, max_affordable = 0, 0
        for price in sorted(a.price for a in activities):
            if total + price > request.budget:
                break
            total, max_affordable = total + price, max_affordable + 1
    return GoldenLabels(
        must_avoid_activity_ids=sorted(ids & WEATHER_UNSUITABLE),
        ambiguous_activity_ids=sorted(ids & WEATHER_AMBIGUOUS),
        uncoverable_travelers=uncoverable,
        max_affordable_activities=max_affordable,
        expected_behavior=expected,
    )


YURI = T("Yuri", 30, I.TECHNOLOGY, I.TENNIS, I.COOKING)
HIRO = T("Hiro", 28, I.READING, I.ART, I.MUSIC)

# (case_id, tags, description, request, expected_behavior, budget_case)
DEFINITIONS = [
    ("g01-sample-yuri-hiro", ["baseline", "weather"],
     "The sample_plan.json request: two travelers, three days incl. the 06-12 thunderstorm.",
     trip([YURI, HIRO], "2025-06-10", "2025-06-12", 130),
     "Full plan within budget; only indoor or rain-fallback activities on 06-12.", False),
    ("g02-tight-budget", ["budget"],
     "Same travelers and dates with a budget that fits only two activities.",
     trip([YURI, HIRO], "2025-06-10", "2025-06-12", 40),
     "At most 2 activities in total; never exceed the budget.", True),
    ("g03-rainy-outdoor-lover", ["weather", "coverage"],
     "Outdoor-only interests on the three inclement days (data review D9).",
     trip([T("Mika", 35, I.HIKING, I.PHOTOGRAPHY, I.SPORTS)], "2025-06-12", "2025-06-14", 150),
     "Avoid outdoor-only activities; indoor picks outside Mika's interests are acceptable.",
     False),
    ("g04-theatre-uncoverable", ["coverage"],
     "One traveler likes only theatre, which no activity offers (D6); the other likes technology.",
     trip([T("Tess", 40, I.THEATRE), T("Ken", 33, I.TECHNOLOGY)],
          "2025-06-10", "2025-06-12", 130),
     "Cover Ken; Tess cannot be matched and must not get invented theatre activities.", False),
    ("g05-one-day-sunny", ["short", "weather"],
     "Single sunny day; outdoor activities are fine.",
     trip([T("Ana", 29, I.DANCING, I.MUSIC, I.FITNESS)], "2025-06-15", "2025-06-15", 60),
     "One-day plan with non-overlapping activities matching Ana's interests.", False),
    ("g06-family-full-window", ["long", "coverage", "weather"],
     "Family of four with mixed interests over the whole six-day window.",
     trip([T("Raj", 45, I.COOKING, I.GARDENING), T("Priya", 43, I.ART, I.READING),
           T("Arjun", 15, I.SPORTS, I.TECHNOLOGY), T("Meera", 10, I.DANCING, I.MOVIES)],
          "2025-06-10", "2025-06-15", 300),
     "Every day planned, everyone covered at least once, weather respected on 06-12 to 06-14.",
     False),
    ("g07-infeasible-budget", ["budget", "edge"],
     "Budget below the cheapest activity price (15).",
     trip([T("Leo", 25, I.ART)], "2025-06-10", "2025-06-11", 10),
     "Empty plan (no activities, total_cost 0); never overspend or invent free activities.", True),
    ("g08-solo-tech", ["baseline"],
     "Solo traveler with one interest on fair and stormy days.",
     trip([T("Sam", 31, I.TECHNOLOGY)], "2025-06-10", "2025-06-12", 100),
     "Technology activity on each day where one exists; indoor on 06-12.", False),
    ("g09-group-of-six", ["coverage", "group"],
     "Six travelers with one interest each over two fair days.",
     trip([T("Ava", 26, I.ART), T("Ben", 27, I.MUSIC), T("Cara", 28, I.TECHNOLOGY),
           T("Dev", 29, I.WRITING), T("Eli", 30, I.MOVIES), T("Fay", 31, I.FITNESS)],
          "2025-06-11", "2025-06-12", 200),
     "Cover as many travelers as possible without overlaps; Eli only via the 06-12 movie events.",
     False),
    ("g10-outdoor-fair-weather", ["weather"],
     "Outdoor interests on clear and partly cloudy days – outdoor picks are correct here.",
     trip([T("Zoe", 27, I.HIKING, I.TENNIS, I.SPORTS, I.ART)], "2025-06-10", "2025-06-11", 100),
     "Choose outdoor activities freely; no weather-based exclusions apply.", False),
    ("g11-storm-day-only", ["weather", "short"],
     "A single thunderstorm day.",
     trip([T("Omar", 38, I.TECHNOLOGY, I.MOVIES, I.MUSIC)], "2025-06-12", "2025-06-12", 50),
     "Indoor tech/film night or the picnic with indoor fallback; never the afternoon hike.", False),
    ("g12-generous-budget", ["budget", "long"],
     "Budget far above total prices – tests over-planning and overlaps, not affordability.",
     trip([T("Lina", 50, I.WRITING, I.DANCING, I.ART, I.MUSIC, I.PHOTOGRAPHY)],
          "2025-06-11", "2025-06-13", 1000),
     "Several non-overlapping activities per day; weather respected on 06-12 and 06-13.", False),
]


def main() -> None:
    cases = [
        GoldenCase(case_id=cid, tags=tags, description=desc, vacation_info=request,
                   labels=labels_for(request, expected, budget_case))
        for cid, tags, desc, request, expected, budget_case in DEFINITIONS
    ]
    manifest = write_golden(VERSION, cases, CREATED)
    print(f"wrote {DATASETS_DIR / VERSION}: {manifest.case_count} cases, "
          f"sha256 {manifest.cases_sha256[:12]}…")


if __name__ == "__main__":
    main()
