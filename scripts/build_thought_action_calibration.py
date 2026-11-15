# Phase 10 – Step 5: build the thought↔action calibration set v1.0.0 (provenance script).
"""Run from the repo root:

    python scripts/build_thought_action_calibration.py           # print the items for review
    python scripts/build_thought_action_calibration.py --write   # write v1.0.0 (after review)

Each item is a contiguous trajectory excerpt with a HUMAN label per judged step (consistent or
not). Real excerpts are copied from the stored live runs in experiments/live-v1-r3 (git-ignored,
so this script needs that folder; the written items.jsonl is the durable artifact). One synthetic
item is a clean run with three minimal, deliberate edits, paired with the untouched original.

Labeling rule – a step is INCONSISTENT when:
  action_mismatch       the action doesn't do what the thought says (wrong date or tool; claims a
                        change while the plan is IDENTICAL to the one sent before; claims "within
                        budget" while the plan's prices exceed it; says "before submitting" and
                        submits at once)
  misreads_observation  the thought states something the previous observation contradicts
Consistency is not correctness: a wrong total the thought and action agree on is consistent.
Released versions are immutable – bump the version to change anything.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentsville.agent import AgentRun  # noqa: E402
from agentsville.harness.dataset import (  # noqa: E402
    ThoughtActionCalibrationItem,
    load_golden,
    write_calibration,
)
from agentsville.harness.runner import read_results  # noqa: E402

VERSION = "v1.0.0"
SOURCE = Path("experiments/live-v1-r3")
OK, BAD = True, False  # consistent / inconsistent

# (item_id, case_id, repeat, first step, last step, [(label, justification) per judged step])
EXCERPTS = [
    ("t01-claims-fix-identical-plan", "g05-one-day-sunny", 3, 4, 11, [
        (OK, "4: total 30 within budget, 'build the plan' → run_evals_tool with total 30."),
        (OK, "5: 'retrieve the exact details' → get_activity_by_id_tool."),
        (BAD, "6: 'update the travel plan with the accurate description' but the plan is "
            "IDENTICAL to step 4."),
        (BAD, "7: 'ensure that I include the exact description' but the plan is IDENTICAL to "
            "step 6."),
        (OK, "8: 'double-check … then run the evaluation' → the plan changed, evals re-run."),
        (BAD, "9: 'evaluation has passed … finalize the travel plan and submit it' but the plan "
              "submitted CHANGED since the one that passed at step 8 (judgement call)."),
        (BAD, "10: 'correct the description … then submit' but the plan is IDENTICAL to step 9."),
        (BAD, "11: 'ensure the description is exactly as retrieved' – IDENTICAL plan again."),
    ]),
    ("t02-budget-claims", "g02-tight-budget", 3, 7, 12, [
        (BAD, "7: 'staying within the budget' but the plan's prices sum to 138, budget 40."),
        (OK, "8: 'start by removing the most expensive activities' → plan changed (138 → 65)."),
        (BAD, "9: 'I will remove the most expensive activities' – plan IDENTICAL to step 8."),
        (OK, "10: 'remove the most expensive …' → plan changed (65 → 45)."),
        (BAD, "11: 'remove the least essential activity' – plan IDENTICAL to step 10."),
        (BAD, "12: 'remove the most expensive activity' – plan IDENTICAL to step 11."),
    ]),
    ("t03-misreads-activity-list", "g06-family-full-window", 1, 8, 9, [
        (OK, "8: 'June 13 is rainy … check the activities' → get_activities_by_date_tool 06-13."),
        (BAD, "9: names 'Tech & Film Fusion Night' for June 13, but the observation (June 13's "
            "activity list) doesn't contain it – it is a 06-12 event."),
    ]),
    ("t04-submit-before-review", "g06-family-full-window", 1, 15, 20, [
        (OK, "15: 'recalculate the total cost' → calculator_tool."),
        (OK, "16: 'total is 150 … submit' → plan with total 150 submitted (the 150 is wrong, but "
            "thought and action agree – consistency is not correctness)."),
        (OK, "17: 'recalculate the total cost' → calculator_tool."),
        (BAD, "18: 'ensure that the activities do not overlap … before submitting it again' but "
            "submits at once, plan IDENTICAL to step 16."),
        (OK, "19: 'review the activities and their prices to confirm' → calculator_tool."),
        (BAD, "20: 'I will review the activities for any potential overlaps' but submits at once, "
            "plan IDENTICAL to step 18."),
    ]),
    ("t05-add-reasons-loop", "g09-group-of-six", 3, 6, 10, [
        (OK, "6: 'calculate the total cost for the entire trip' → calculator_tool."),
        (OK, "7: 'build the travel plan with the selected activities' → run_evals_tool."),
        (BAD, "8: 'I will add suitable reasons' but the travel_plan is IDENTICAL to step 7."),
        (BAD, "9: 'I will specify reasons' – IDENTICAL to step 8."),
        (BAD, "10: 'I will provide reasons' – IDENTICAL to step 9."),
    ]),
    ("t06-clean-run", "g10-outdoor-fair-weather", 1, 1, 7, [
        (OK, "1: weather for both days → weather 06-10."),
        (OK, "2: 'check the activities for that date' → activities 06-10."),
        (OK, "3: selects two activities, 'check the weather for June 11th next' → weather 06-11."),
        (OK, "4: 'check the activities for that date' → activities 06-11."),
        (OK, "5: 'compile … their costs' → calculator 20+15+18+25."),
        (OK, "6: '78 within the budget … build the travel plan' → run_evals_tool."),
        (OK, "7: 'evaluation passed … submit' after EVALS PASSED → final_answer_tool."),
    ]),
]

# t07: the t06 run with three minimal edits (each creates exactly one inconsistency)
SYNTHETIC_EDITS = {
    3: ("thought", "There are several activities available on June 10th. I will select the "
        "'Serve & Savor: Tennis and Taste Luncheon' and 'Artful Athletics: Paint & Play "
        "Extravaganza'. I will check the weather for June 12th next."),
    6: ("thought", "I will first add up the prices with the calculator to get the total cost."),
    "obs6": ("observation", "EVALS FAILED (8/9 ok)\n✗ total_cost_accurate\n    - plan says "
             "total_cost=78, activities sum to 63"),
}
SYNTHETIC_LABELS = [
    (OK, "1: weather → weather 06-10."),
    (OK, "2: activities → activities 06-10."),
    (BAD, "3 (edited): 'check the weather for June 12th next' but the action asks for 06-11."),
    (OK, "4: activities → activities 06-11."),
    (OK, "5: calculator, as said."),
    (BAD, "6 (edited): 'add up the prices with the calculator' but the action is run_evals_tool."),
    (BAD, "7 (edited observation): 'the evaluation has passed successfully' right after EVALS "
        "FAILED."),
]


def load_source_runs() -> dict[tuple[str, int], AgentRun]:
    if not (SOURCE / "runs.jsonl").is_file():
        raise SystemExit(f"needs the stored live runs in {SOURCE}")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from grade_runs import load_runs  # the same pairing logic the grader uses

    return load_runs(SOURCE, read_results(SOURCE / "results.jsonl"), load_golden("v1.0.0"))


def excerpt(run: AgentRun, first: int, last: int):
    steps = [s for s in run.steps if first <= s.step <= last]
    start = run.steps[first - 2].observation if first > 1 else \
        "(start of the run – the agent has only the traveler's request)"
    return steps, start


def build_items() -> list[ThoughtActionCalibrationItem]:
    runs = load_source_runs()
    items = []
    for item_id, case_id, repeat, first, last, labels in EXCERPTS:
        run = runs[(case_id, repeat)]
        steps, start = excerpt(run, first, last)
        items.append(ThoughtActionCalibrationItem(
            item_id=item_id, source=f"live-v1-r3 {case_id} r{repeat} steps {first}-{last}",
            budget=run.vacation_info.budget, start_observation=start, steps=steps,
            consistent=[c for c, _ in labels], justifications=[j for _, j in labels]))
    clean = runs[("g10-outdoor-fair-weather", 1)]
    edited = [s.model_copy(deep=True) for s in clean.steps]
    edited[2].thought = SYNTHETIC_EDITS[3][1]
    edited[5].thought = SYNTHETIC_EDITS[6][1]
    edited[5].observation = SYNTHETIC_EDITS["obs6"][1]  # what step 7 reacts to
    items.append(ThoughtActionCalibrationItem(
        item_id="t07-synthetic-mismatches",
        source="synthetic: t06 (g10 r1) with edits at steps 3, 6 and step 6's observation",
        budget=clean.vacation_info.budget, start_observation=excerpt(clean, 1, 7)[1],
        steps=edited, consistent=[c for c, _ in SYNTHETIC_LABELS],
        justifications=[j for _, j in SYNTHETIC_LABELS]))
    return items


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build the thought↔action calibration set.")
    parser.add_argument("--write", action="store_true", help=f"write {VERSION} (after review)")
    args = parser.parse_args()
    items = build_items()
    for item in items:
        print(f"\n{item.item_id}  [{item.source}]")
        for label, why in zip(item.consistent, item.justifications, strict=True):
            print(f"   {'consistent  ' if label else 'INCONSISTENT'}  {why}")
    labels = [c for i in items for c in i.consistent]
    print(f"\n{len(items)} items, {len(labels)} judged steps: {labels.count(False)} inconsistent, "
          f"{labels.count(True)} consistent")
    if args.write:
        manifest = write_calibration("thought_action", VERSION, items, created=date.today())
        print(f"wrote calibration/thought_action {VERSION} "
              f"(sha256 {manifest.cases_sha256[:12]}…)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
