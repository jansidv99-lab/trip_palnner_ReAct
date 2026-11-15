# Phase 8 – Step 3: build the reasons-judge calibration set v1.0.0 (provenance script).
"""Run once from the repo root:  python scripts/build_calibration_dataset.py

Each item is one recommended activity with its reasons and a HUMAN label per reason
(True = every factual claim is supported by the activity, the day's forecast or the travelers'
interests). Released versions are immutable – bump the version to change anything.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.harness.dataset import (  # noqa: E402
    CALIBRATION_DIR,
    CalibrationItem,
    write_calibration,
)
from agentsville.models import Interest as I  # noqa: E402,N817
from agentsville.models import Traveler  # noqa: E402

VERSION = "v1.0.0"
CREATED = date(2026, 11, 15)

YURI = Traveler(name="Yuri", age=30, interests=[I.TECHNOLOGY, I.TENNIS, I.COOKING])
HIRO = Traveler(name="Hiro", age=28, interests=[I.READING, I.ART, I.MUSIC])
MIKA = Traveler(name="Mika", age=35, interests=[I.HIKING, I.PHOTOGRAPHY, I.SPORTS])
TESS = Traveler(name="Tess", age=40, interests=[I.THEATRE])
KEN = Traveler(name="Ken", age=33, interests=[I.TECHNOLOGY])

T, F = True, False

# (item_id, activity, travelers, [(reason, grounded)], notes)
ITEMS = [
    ("c01-futuretech", "event-2025-06-10-0", [YURI, HIRO],
     [("Matches Yuri's interest in technology", T),
      ("Indoor morning event, easy start to the trip", T)],
     "both from sample_plan.json; atrium is indoors, 09:00"),
    ("c02-tennis-luncheon", "event-2025-06-10-1", [YURI, HIRO],
     [("Matches Yuri's interests in tennis and cooking", T),
      ("Clear weather suits the outdoor courts", T),
      ("Matches Hiro's interest in tennis", F)],
     "wrong interest: Hiro likes reading/art/music"),
    ("c03-twilight-writing", "event-2025-06-10-3", [YURI, HIRO],
     [("Matches Hiro's interests in reading and art", T),
      ("Relaxed indoor evening", T),
      ("Matches Hiro's interest in movies", F)],
     "wrong interest"),
    ("c04-fusion-fest", "event-2025-06-11-2", [YURI, HIRO],
     [("Matches Hiro's interests in art and music", T),
      ("Indoor venue keeps everyone cool on the hottest day", F)],
     "venue claim false: outdoor amphitheater, gardens under the open sky"),
    ("c05-tech-film-night", "event-2025-06-12-3", [YURI, HIRO],
     [("Matches Yuri's technology interest", T),
      ("Indoor venue avoids the thunderstorm", T),
      ("Free popcorn and drinks are included", F)],
     "invented feature: description mentions no food or drinks"),
    ("c06-soundtrack-picnic", "event-2025-06-12-1", [YURI, HIRO],
     [("Matches Hiro's interest in music", T),
      ("It moves indoors to Harmony Hall if it rains, so the storm is not a problem", T),
      ("Perfect for Maria, who loves movies", F)],
     "tricky-grounded rain fallback (D4); unknown traveler Maria"),
    ("c07-trail-tales", "event-2025-06-12-2", [MIKA],
     [("Matches Mika's interest in hiking", T),
      ("Indoor venue avoids the storm", F)],
     "venue claim false: outdoor trail hike during the afternoon storm"),
    ("c08-lunch-hike", "event-2025-06-13-1", [MIKA],
     [("Matches Mika's interest in hiking", T),
      ("Sunny weather makes it ideal for a hike", F)],
     "weather claim false: 06-13 is rainy"),
    ("c09-comedy-dance", "event-2025-06-13-0", [MIKA],
     [("Indoor activity is a safe choice on a rainy day", T),
      ("Matches Mika's interest in comedy", F)],
     "wrong interest: Mika likes hiking/photography/sports"),
    ("c10-dancing-prose", "event-2025-06-14-3", [MIKA],
     [("Held indoors, so the rain won't interfere", T),
      ("Includes a guided photography walk", F)],
     "indoor is true despite the keyword trap (D5); photography walk invented"),
    ("c11-tech-lunch", "event-2025-06-11-1", [KEN, TESS],
     [("Matches Ken's interest in technology", T),
      ("Matches Tess's interest in theatre", F)],
     "no theatre in the activity (real failure mode seen in B0 runs)"),
    ("c12-lunchtime-groove", "event-2025-06-15-1", [HIRO],
     [("Matches Hiro's interest in music", T),
      ("Lunchtime timing leaves the evening free", T)],
     "12:00–13:30; music is a related interest"),
    ("c13-breakfast-details", "event-2025-06-10-0", [YURI],
     [("Coffee and fresh pastries are served", T),
      ("Costs only 10", F)],
     "food is in the description; the price is 20"),
    ("c14-fusion-fest-weather", "event-2025-06-11-2", [HIRO],
     [("Partly cloudy weather is fine for the outdoor amphitheater", T),
      ("Matches Ben's interest in art", F)],
     "unknown traveler Ben"),
]


def main() -> None:
    items = [
        CalibrationItem(item_id=item_id, activity_id=activity_id, travelers=travelers,
                        reasons=[r for r, _ in labeled], grounded=[g for _, g in labeled],
                        notes=notes)
        for item_id, activity_id, travelers, labeled, notes in ITEMS
    ]
    manifest = write_calibration("reasons", VERSION, items, CREATED)
    reasons = sum(len(i.reasons) for i in items)
    ungrounded = sum(not g for i in items for g in i.grounded)
    print(f"wrote {CALIBRATION_DIR / 'reasons' / VERSION}: {manifest.case_count} items, "
          f"{reasons} reasons ({ungrounded} ungrounded)")


if __name__ == "__main__":
    main()
