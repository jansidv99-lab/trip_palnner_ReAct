# Phase 10 – Step 4: build the traveler-relevancy calibration set v1.0.0 (provenance script).
"""Run from the repo root:

    python scripts/build_relevancy_calibration.py           # print the items for human review
    python scripts/build_relevancy_calibration.py --write   # write v1.0.0 (only after review)

Each item is a plan (activity ids per day, copied from a stored live run or deliberately
constructed) for a golden case, with a HUMAN 1–5 score per traveler. Plans are rebuilt here from
data_api, so the set doesn't depend on the git-ignored experiments/ folder.

Labeling rule (applied to every score, written in each justification):
  For each traveler and day: was there a POSSIBLE matching option – an activity matching one of
  their interests that is weather-suitable, affordable within the budget, and not overlapping?
  A possible day on which the traveler got NO matching activity is a MISS.
  5 = no miss (or no possible day on the whole trip)
  4 = exactly one miss
  3 = misses on some days, served on others
  2 = served on only a minority of possible days
  1 = every possible day missed
Released versions are immutable – bump the version to change anything.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.data_api import get_activity_by_id, get_weather  # noqa: E402
from agentsville.harness.dataset import (  # noqa: E402
    RelevancyCalibrationItem,
    load_golden,
    write_calibration,
)
from agentsville.models import TravelPlan  # noqa: E402

VERSION = "v1.0.0"

# (item_id, case_id, source, {day: [activity ids]}, [(score, justification) per traveler])
ITEMS = [
    ("r01-yuri-hiro-misses", "g01-sample-yuri-hiro", "live-v1-r3 g01 r1",
     {"06-10": ["10-0", "10-1"], "06-11": ["11-1", "11-2"], "06-12": ["12-3"]},
     [(5, "Yuri: tech/cooking/tennis matched on all 3 days (10-0, 10-1, 11-1, 12-3). No miss."),
      (3, "Hiro: served 06-11 (11-1, 11-2). Missed 06-10 (10-3 writing/reading/art, 19:00, +15 "
          "fits the budget) and 06-12 (12-1 movies/music, indoor). 2 misses, 1 served day.")]),
    ("r02-theatre-uncoverable", "g04-theatre-uncoverable", "live-v1-r3 g04 r1",
     {"06-10": ["10-0", "10-3"], "06-11": ["11-1", "11-3"], "06-12": ["12-3"]},
     [(5, "Tess: no theatre activity exists on any day – no possible day. Plan gives her "
          "sensible indoor activities. Rule: 5."),
      (5, "Ken: every technology option chosen (10-0, 11-1, 12-3). No miss.")]),
    ("r03-group-of-six", "g09-group-of-six", "live-v1-r3 g09 r2",
     {"06-11": ["11-0", "11-1"], "06-12": ["12-3"]},
     [(1, "Ava: art possible only on 06-11 (11-2 outdoor in partly cloudy weather, 11-3 indoor); "
          "neither chosen, budget 200 has room. Every possible day missed."),
      (4, "Ben: music on 06-11 (11-0, 11-1). Missed 06-12 (12-1 movies/music, indoor, no "
          "overlap with 12-3). 1 miss."),
      (5, "Cara: technology on both days (11-1, 12-3). No miss."),
      (5, "Dev: writing on 06-11 (11-1); the only writing option on 06-12 is 12-2, an outdoor "
          "hike in the afternoon storm – not suitable. No miss."),
      (5, "Eli: no movies option on 06-11; 06-12 served by 12-3. No miss."),
      (5, "Fay: fitness on 06-11 (11-0); no fitness option on 06-12. No miss.")]),
    ("r04-family-full-window", "g06-family-full-window", "live-v1-r3 g06 r1",
     {"06-10": ["10-1", "10-2"], "06-11": ["11-0", "11-3"], "06-12": ["12-3"],
      "06-13": ["13-0"], "06-14": ["14-3"], "06-15": ["15-0", "15-1", "15-2"]},
     [(5, "Raj: cooking on 06-10 (10-1) and 06-11 (11-3); gardening only outdoors on rainy "
          "06-14 or as the early 12-0 hike before the storm (left unlabeled). No miss."),
      (5, "Priya: art/reading on 06-10 (10-2), 06-11 (11-3), 06-15 (15-0); 13-2 and 14-2 are "
          "outdoor on rainy days. No miss."),
      (4, "Arjun: 06-10 (10-2 sports), 06-12 (12-3 tech). Missed 06-11 (11-1 technology, "
          "12:00–13:30, no overlap). 1 miss."),
      (5, "Meera: dancing/movies on every possible day: 06-11, 06-12, 06-13, 06-14, 06-15. "
          "No miss.")]),
    ("r05-rainy-outdoor-lover", "g03-rainy-outdoor-lover", "live-v1-r3 g03 r1",
     {"06-12": ["12-0"], "06-13": ["13-0"], "06-14": ["14-3"]},
     [(5, "Mika: hiking/photography/sports options are outdoor on rainy 06-13/06-14 or in the "
          "06-12 storm; the plan even uses the early 12-0 hike before the storm, plus indoor "
          "fills. No miss.")]),
    ("r06-generous-one-miss", "g12-generous-budget", "live-v1-r3 g12 r3",
     {"06-11": ["11-0"], "06-12": ["12-3"], "06-13": ["13-0"]},
     [(4, "Lina: served 06-11 (11-0) and 06-13 (13-0). 06-12: plan picks 12-3 (tech/movies, not "
          "hers) while 12-1 (movies/music, indoor) matches her music. 1 miss.")]),
    ("r07-solo-tech-ignored", "g08-solo-tech", "synthetic: non-tech activities only",
     {"06-10": ["10-3"], "06-11": ["11-0"], "06-12": ["12-1"]},
     [(1, "Sam: a technology option existed every day (10-0, 11-1, 12-3, all indoor, no "
          "overlap, budget 100); none chosen. Every possible day missed.")]),
    ("r08-storm-day-ignored", "g11-storm-day-only", "synthetic: outdoor hike only",
     {"06-12": ["12-0"]},
     [(1, "Omar: 12-1 (movies/music) and 12-3 (tech/movies) are indoor, affordable together "
          "(budget 50) and match him; plan gives only a hiking/gardening walk. Day missed.")]),
    ("r09-yuri-ignored", "g01-sample-yuri-hiro", "synthetic: Hiro-only activities",
     {"06-10": ["10-3"], "06-11": ["11-2"], "06-12": ["12-1"]},
     [(1, "Yuri: tech/cooking/tennis options every day (10-0, 10-1, 11-1, 12-3), none "
          "overlapping the plan; none chosen. Every possible day missed."),
      (5, "Hiro: matched every day (10-3, 11-2, 12-1). No miss.")]),
    ("r10-meera-starved", "g06-family-full-window", "synthetic: g06 r1 minus Meera's picks",
     {"06-10": ["10-1", "10-2"], "06-11": ["11-3"], "06-12": ["12-3"], "06-15": ["15-0"]},
     [(5, "Raj: cooking 06-10 (10-1), 06-11 (11-3). No miss."),
      (5, "Priya: art/reading 06-10 (10-2), 06-11 (11-3), 06-15 (15-0). No miss."),
      (4, "Arjun: 06-10 (10-2), 06-12 (12-3). Missed 06-11 (11-1 technology). 1 miss."),
      (2, "Meera: possible on 06-11 (11-0), 06-12, 06-13 (13-0 indoor), 06-14 (14-3 indoor), "
          "06-15 (15-1); served only 06-12 (12-3). 1 of 5 possible days.")]),
    ("r11-generous-two-misses", "g12-generous-budget", "synthetic: g12 r3 minus 13-0",
     {"06-11": ["11-0"], "06-12": ["12-3"], "06-13": []},
     [(3, "Lina: served 06-11 (11-0). Missed 06-12 (12-1 music, indoor) and 06-13 (13-0 "
          "dancing, indoor). 2 misses, 1 served day.")]),
]


# Phase 10 – Step 4: a valid TravelPlan from activity ids – real data, the real forecast
def build_plan(case, days: dict[str, list[str]]) -> TravelPlan:
    itinerary, total = [], 0
    for md, ids in days.items():
        day = date.fromisoformat(f"2025-{md}")
        forecast = get_weather(day)
        recs = []
        for short in ids:
            activity = get_activity_by_id(f"event-2025-06-{short}")
            total += activity.price
            recs.append({"activity": activity.model_dump(mode="json"),
                         "reasons_for_recommendation": ["Chosen for the group."]})
        itinerary.append({"date": day.isoformat(),
                          "weather": {"temperature": forecast.temperature,
                                      "temperature_unit": forecast.temperature_unit,
                                      "condition": forecast.condition},
                          "activity_recommendations": recs})
    info = case.vacation_info
    return TravelPlan.model_validate({"city": info.destination,
                                      "start_date": info.date_of_arrival.isoformat(),
                                      "end_date": info.date_of_departure.isoformat(),
                                      "total_cost": total, "itinerary_days": itinerary})


def build_items() -> list[RelevancyCalibrationItem]:
    golden = load_golden("v1.0.0")
    items = []
    for item_id, case_id, source, days, labels in ITEMS:
        case = golden.case(case_id)
        items.append(RelevancyCalibrationItem(
            item_id=item_id, source=f"{case_id} · {source}", vacation_info=case.vacation_info,
            travel_plan=build_plan(case, days), scores=[s for s, _ in labels],
            justifications=[j for _, j in labels]))
    return items


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build the relevancy calibration set.")
    parser.add_argument("--write", action="store_true", help=f"write {VERSION} (after review)")
    args = parser.parse_args()
    items = build_items()
    for item in items:
        plan = item.travel_plan
        print(f"\n{item.item_id}  [{item.source}]  budget {item.vacation_info.budget}, "
              f"total {plan.total_cost}")
        for day in plan.itinerary_days:
            ids = [r.activity.activity_id[-4:] for r in day.activity_recommendations]
            print(f"   {day.date}: {', '.join(ids) or '-'}")
        for score, why in zip(item.scores, item.justifications, strict=True):
            print(f"   {score}  {why}")
    scores = [s for i in items for s in i.scores]
    print(f"\n{len(items)} items, {len(scores)} traveler scores, distribution "
          f"{ {k: scores.count(k) for k in range(5, 0, -1)} }")
    if args.write:
        manifest = write_calibration("relevancy", VERSION, items, created=date.today())
        print(f"wrote calibration/relevancy {VERSION} (sha256 {manifest.cases_sha256[:12]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
