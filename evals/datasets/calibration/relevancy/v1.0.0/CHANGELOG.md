# Traveler-relevancy calibration set – changelog

## v1.0.0 – 2026-11-15 (Phase 10, B3)

First release: 11 items, 25 traveler scores (5: 14 · 4: 4 · 3: 2 · 2: 1 · 1: 4). Built by
`scripts/build_relevancy_calibration.py` and reviewed by the project owner.

Each item is a plan (activity ids per day) for a golden v1.0.0 case plus a human 1–5 score per
traveler, with a written justification. 6 plans copy the activity selection of stored live runs
(`live-v1-r3`); 5 are synthetic plans built from real activities to cover low scores.

Labeling rule: per traveler and day, a day with a POSSIBLE matching option (weather-suitable,
affordable, non-overlapping) on which the traveler got no matching activity is a miss.
5 = no miss (or no possible day) · 4 = one miss · 3 = some days missed, some served ·
2 = served on a minority of possible days · 1 = every possible day missed.

Judgement calls (owner-approved):
- r02 Tess: no theatre activity exists → 5 (never penalize an interest nothing offers).
- r04 Raj, r05 Mika: the early 12-0 hike before the afternoon storm is "ambiguous" in the golden
  labels → counted neither as a miss nor as required.
- A day counts as served with one matching activity, however many others were available.

Valid only for the `data/data.py` matching `manifest.json` → `data_fingerprint`.
