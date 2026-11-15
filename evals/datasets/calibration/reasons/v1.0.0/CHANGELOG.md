# Reasons-judge calibration set – changelog

## v1.0.0 – 2026-11-15 (Phase 8, B1)

First release: 14 items, 32 reasons (20 grounded, 12 ungrounded). Built by
`scripts/build_calibration_dataset.py` and reviewed by the project owner.

Each item is one recommended activity with its reasons, plus a human label per reason
(grounded = every factual claim is supported by the activity, the day's forecast or the
travelers' interests).

Ungrounded categories:
- wrong interest (4): c02, c03, c09, c11
- unknown traveler (2): c06, c14
- false venue/weather claim (3): c04, c07, c08
- invented feature/price (3): c05, c10, c13

Tricky grounded cases:
- c06: rain fallback to Harmony Hall (data review D4).
- c10: held indoors despite the keyword trap (D5).

Valid only for the `data/data.py` matching `manifest.json` → `data_fingerprint`.
