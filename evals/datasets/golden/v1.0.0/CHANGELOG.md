# Golden dataset – changelog

## v1.0.0 – 2026-11-15 (Phase 7, B0)

First release: 12 cases built by `scripts/build_golden_dataset.py` and reviewed by the project owner.

| Case | Purpose |
|---|---|
| g01 | baseline = `sample_plan.json` request (storm day 06-12) |
| g02 | budget pressure: at most 2 activities fit |
| g03 | outdoor-only interests on three inclement days (Mika uncoverable) |
| g04 | uncoverable interest (theatre) next to an easy one |
| g05 | one sunny day |
| g06 | family of four over the full six-day window |
| g07 | infeasible budget: empty plan expected |
| g08 | solo traveler, single interest |
| g09 | group of six, one interest each |
| g10 | outdoor interests on fair-weather days (outdoor picks correct) |
| g11 | single thunderstorm day |
| g12 | generous budget: over-planning / overlaps |

**Label policy:**
- One human weather judgment per activity (data review D2–D5) is applied to each case's dates.
- `must_avoid`: outdoor-only activities with no rain fallback on 06-12 (afternoon storm), 06-13 and 06-14 (rain).
- `ambiguous`: `event-2025-06-12-0` (08:00–10:00, before the forecast afternoon storm). It's left unlabeled and doesn't count toward coverage.
- Explicitly suitable: `event-2025-06-12-1` (indoor rain fallback) and `event-2025-06-14-3` (held indoors).
- Coverage and affordability labels are derived from the weather labels and the activity prices.

Valid only for the `data/data.py` matching `manifest.json` → `data_fingerprint`.
