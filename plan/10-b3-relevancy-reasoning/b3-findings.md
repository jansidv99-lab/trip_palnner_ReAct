# Phase 10 – Step 7: B3 findings – is the plan relevant, and is its reasoning faithful?

> Golden v1.0.0 · config `gpt-4o-mini__v1__t0` · prompt `v1` · judges `gpt-4.1`
> (traveler_relevancy prompt v2, thought_action prompt v1).
> **Spend: ~$0.93** of the $3 cap – calibration ~$0.18, B0 recording $0.18, 36 live runs $0.57.
> Status: **APPROVED (2026-11-15)** – §6 threshold proposals accepted as written (Step 8).

## 1. What was measured

| Source | Runs | How |
|---|---|---|
| 36 stored live runs (`experiments/live-v1-r3`) | 36 | `grade_runs.py … --record-graders traveler_relevancy,thought_action_consistency` |
| B0 recording (committed cassettes, the CI path) | 12 | `run_experiment.py --record-graders …`; 24 new grading cassettes + refreshed `expected_results.jsonl` |

Only the two new judges called the LLM (per-judge cassettes, Step 1). Checked by script: agent and B1
cassettes byte-identical, **0 existing fields or B1/B2 outcomes changed**, **0 judge failures**,
and `--check-expected` still passes.

## 2. Judge calibration (before trusting any number)

| Judge | Set | Result | Note |
|---|---|---|---|
| traveler_relevancy v2 | 25 traveler scores | 25/25 exact, weighted κ 1.00 | v1 was κ 0.51; v2 = "LLM extracts per-day facts, code verifies and scores". **Optimistic**: improved on the same set that measures it. |
| thought_action v1 | 41 steps, 18 inconsistent | precision 0.94, recall 0.83, κ 0.80 | Accepted as is (owner decision). It misses ~1 in 6 → measured inconsistency is a **lower bound**. |

**Fresh data found a scoring bug the calibration set could not.** Live run g09 r1: Ben (music) was
served on 06-11 by three planned music activities, so the judge correctly saw no further *unplanned*
option that day – and the code then didn't count 06-11 as a possible day, scoring Ben 1 instead of 4.
Fix (consistent with the approved rule): a served day is a possible day. Calibration unchanged
(25/25; no labeled item had a day whose every match was already planned); after the replay re-grade
exactly one result changed (g09 r1 Ben 1 → 4). This is the overfitting caution made concrete: a
perfect calibration score on 25 items does not prove the judge on new data.

## 3. B3 numbers

| Metric | 36 live runs (95% CI) | B0 recording (12 runs, CI path) |
|---|---|---|
| Coverable travelers matched (labeled coverage) | 97.6% [88–100%] (41/42) | 100% (14/14) |
| Activities matching nobody | 8.8% [5–16%] (9/102) | 10.3% (3/29) |
| **Relevant travelers** (judge score ≥ 4) | **93.6% [83–98%] (44/47)** | 100% (15/15) |
| Poorly served travelers (score ≤ 2) | 2.1% (1/47) | 0% |
| Mean relevancy score | 4.72 (5: 39 · 4: 5 · 3: 2 · 1: 1) | 4.93 |
| Weather / activities looked up for every day | 98.6% / 100% | 100% / 100% |
| **Total came from the calculator** | **80.0% [61–91%] (20/25)** | **50% (4/8)** |
| Submitted plan passed run_evals_tool | 92.9% [77–98%] (26/28) | 100% (8/8) |
| **Faithful** (both) | **76.0% [57–89%] (19/25)** | **50% (4/8)** |
| **Thought↔action inconsistency** (lower bound) | **15.8% [13–19%] (74/468 steps)** | 11.0% (17/154) |
| Redundant lookups | 9.2% [6–13%] (23/250) | 8.1% (6/74) |
| Error steps | 9.4% [7–12%] (44/468) | 9.7% (15/154) |

## 4. What we learned

1. **Relevancy is good.** 44 of 47 travelers are well served relative to what was possible. The
   three below 4: Hiro in g01 r1/r2 (score 3 – missed 06-10 and 06-12, the same plan as calibration
   item r01) and Ava in g09 r2 (score 1 – art was possible on 06-11, never chosen). Uncoverable
   travelers (Tess, Mika) are not penalized.

2. **The reasoning is the weak spot – "says it, doesn't do it".** Thought↔action inconsistency is
   **23.6% of steps in runs that didn't complete vs 10.5% in completed runs**, and **62% in the two
   invalid-argument loops** (g09 r3: 13/20 steps, g07 r3: 12/20). The dominant pattern (≈ 43 of 74
   flagged steps, grouping the judge's stated reasons by keyword): the thought claims a change ("I will remove the most expensive activity", "I will
   add reasons") and the plan sent is **IDENTICAL** to the previous one. Independently, code found
   **73 of 129 plan resubmissions identical** to the previous one. This is the mechanism behind B2's
   loops: the agent believes it fixed the plan and re-sends it unchanged.

3. **The agent misreads numbers.** "93, which exceeds the budget of 130" (g01 r1 and r2, identical
   wording) and "68, which exceeds the budget of 200" (g09 r2) – a comparison error that sends the
   agent into needless rework.

4. **Correct-but-unfaithful plans exist.** 4 live runs completed with a correct total that **no
   calculator call produced** (g03 r1, g04 r2, g08 r3, g12 r1); B2 scored them fully passing. On the
   B0 recording CI replays, half the completed plans (4/8) are like this. Faithfulness (76% live,
   50% B0) is a separate dimension from outcome correctness.

5. **Procedure lookups are fine** (≥ 98.6% of days); the problems are in bookkeeping and in
   acting on observations, not in gathering data.

**Candidates for B4 (eval-driven improvement – not done here, per Q7):**
- Compute `total_cost` in code (removes the calculator-faithfulness and cost-loop problems at once).
- When a submitted plan is identical to the previous failed one, say so in the observation
  ("This is the same plan you sent at step N – nothing changed") – turning B3's code fact into
  feedback the agent can act on.
- Show a minimal valid example in invalid-argument errors (B2 finding, confirmed: those loops have
  62% inconsistent steps).
- Expected effect to measure in B4: thought↔action inconsistency and B2 loops down, faithfulness up.

## 5. Statistical caveats

- 36 runs / 47 travelers / 468 steps: CIs above. The relevancy judge's perfect calibration is
  optimistic (§2); the thought↔action rate is a lower bound (recall 0.83).
- Both calibration sets are small (25 scores, 41 steps) and were built from the same stored runs
  that are measured here. B5 should add fresh calibration items from new traffic.
- The CI path (B0, 12 runs) differs from the live set on faithfulness (50% vs 76%) – thresholds must
  pass on the B0 recording or CI fails.

## 6. Threshold proposals for Step 8 (`[b3]` – your decision)

Same approach as B1/B2: **targets** where we're near-perfect, **regression guards** just below
today's level elsewhere – every value must pass on the B0 recording (the CI path).

| Rule | Live (95% CI) | B0 | Proposal | Kind |
|---|---|---|---|---|
| `min_interest_coverage` | 97.6% [88–100%] | 100% | 0.90 | target |
| `min_relevant_rate` | 93.6% [83–98%] | 100% | 0.80 | regression guard |
| `min_weather_lookup_coverage` | 98.6% [92–100%] | 100% | 0.95 | target |
| `min_verified_before_final_rate` | 92.9% [77–98%] | 100% | 0.85 | regression guard |
| `min_calculator_faithfulness` | 80.0% [61–91%] | 50% | **0.45** | regression guard – raise after B4 |
| `min_faithfulness` | 76.0% [57–89%] | 50% | **0.45** | regression guard – raise after B4 |
| `max_thought_action_inconsistency` | 15.8% [13–19%] | 11.0% | 0.20 | regression guard |
| `max_redundant_call_rate` | 9.2% [6–13%] | 8.1% | 0.15 | regression guard |
| `max_error_step_rate` | 9.4% [7–12%] | 9.7% | 0.15 | regression guard |
| `min_relevancy_judge_qwk` | 1.00 (optimistic) | – | 0.80 | judge trust bar |
| `min_thought_action_judge_recall` | 0.83 | – | 0.80 | judge trust bar (below B1's 0.90 by decision) |
| `min_thought_action_judge_precision` | 0.94 | – | 0.85 | judge trust bar |

Faithfulness at 0.45 is deliberately loose: a 0.70 target would fail CI today (B0 = 50%). It
catches getting worse; B4 should raise it once `total_cost` is computed in code.

## 7. Production signal (Step 9)

Code graders on every production run (coverage, match, lookup coverage, calculator and
verified-before-final flags, redundant/error counts – $0); both judges on the 10% sample, like B1.
