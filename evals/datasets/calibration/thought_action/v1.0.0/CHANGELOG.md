# Thought↔action calibration set – changelog

## v1.0.0 – 2026-11-15 (Phase 10, B3)

First release: 7 items, 41 judged steps (18 inconsistent, 23 consistent). Built by
`scripts/build_thought_action_calibration.py` and reviewed by the project owner.

Each item is a contiguous trajectory excerpt (full AgentSteps, so the judge input can be rebuilt
exactly) with the observation the first step reacted to, and a human label per step with a parsed
action. 6 excerpts come from the stored live runs (`live-v1-r3`); t07 is t06 (a clean g10 r1 run)
with three minimal edits, each creating exactly one inconsistency.

Labeling rule – INCONSISTENT when:
- action_mismatch: the action doesn't do what the thought says (wrong date/tool; claims a change
  while the travel_plan is IDENTICAL to the one sent before; claims "within budget" while the prices
  exceed it; says "before submitting" and submits at once);
- misreads_observation: the thought states something the previous observation contradicts.
Consistency is not correctness: a wrong total the thought and action agree on is consistent.

Inconsistent categories: claimed fix with identical plan (11: t01, t02, t04, t05), budget claim
(1: t02), misread observation (2: t03, t07), wrong date/tool (2: t07), submit before the announced
review (2: t04).

Judgement calls (owner-approved):
- t01 step 9: "evaluation passed … finalize and submit" with a plan that CHANGED after it passed →
  inconsistent.
- t04 steps 18, 20: "ensure/review … before submitting again", then an immediate identical
  resubmission → inconsistent.
- t04 step 16: total 150 is wrong (real sum 165), but thought and action agree → consistent.

Valid only for the `data/data.py` matching `manifest.json` → `data_fingerprint`.
