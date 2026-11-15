# Phase 2 – Step 4: shared sample trip requests for tests, evals, the agent and the eval suite.
"""Each function returns a NEW VacationInfo, so callers can't affect each other ."""

import datetime

from agentsville.models import Interest, Traveler, VacationInfo


# Phase 2 – Step 4: the two travelers that appear in sample_plan.json
def _yuri_and_hiro() -> list[Traveler]:
    return [
        Traveler(
            name="Yuri",
            age=30,
            interests=[Interest.TECHNOLOGY, Interest.TENNIS, Interest.COOKING],
        ),
        Traveler(name="Hiro", age=28, interests=[Interest.READING, Interest.ART, Interest.MUSIC]),
    ]


# Phase 2 – Step 4: matches sample_plan.json (same travelers and dates; its 108 total fits 130)
def sample_vacation_info() -> VacationInfo:
    return VacationInfo(
        travelers=_yuri_and_hiro(),
        destination="AgentsVille",
        date_of_arrival=datetime.date(2025, 6, 10),
        date_of_departure=datetime.date(2025, 6, 12),
        budget=130,
    )


# Phase 2 – Step 4: same trip with a budget that forces the agent to choose
def tight_budget_vacation_info() -> VacationInfo:
    return VacationInfo(
        travelers=_yuri_and_hiro(),
        destination="AgentsVille",
        date_of_arrival=datetime.date(2025, 6, 10),
        date_of_departure=datetime.date(2025, 6, 12),
        budget=40,
    )


# Phase 2 – Step 4: outdoor-loving traveler on the thunderstorm + rainy days (06-12 → 06-14)
def rainy_days_vacation_info() -> VacationInfo:
    return VacationInfo(
        travelers=[
            Traveler(
                name="Mika",
                age=35,
                interests=[Interest.HIKING, Interest.PHOTOGRAPHY, Interest.SPORTS],
            )
        ],
        destination="AgentsVille",
        date_of_arrival=datetime.date(2025, 6, 12),
        date_of_departure=datetime.date(2025, 6, 14),
        budget=150,
    )
