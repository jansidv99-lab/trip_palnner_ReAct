# Phase 8 – Step 8: B1 findings – is everything in the plan real?

> Golden v1.0.0 · config `gpt-4o-mini__v1__t0` · judge `gpt-4.1` prompt `v1`.
> Spend: calibration $0.03 · re-grade of the B0 recording ~$0.05 · 36 stored runs ~$0.20.

## 1. Can the judge be trusted? (calibration reasons-v1.0.0, 32 human-labeled reasons)

| TP | FP | TN | FN | Precision | Recall | F1 | κ |
|---|---|---|---|---|---|---|---|
| 12 | 0 | 20 | 0 | 1.00 | 1.00 | 1.00 | 1.00 |

**Yes, against the bar** (recall ≥ 0.90, precision ≥ 0.80).

**Caveat:** 32 reasons is small, and the crafted negatives are fairly blatant. B5 adds real production
disagreements to grow this set (v1.1.0).

## 2. Decoupling works

Re-grading the committed B0 recording (`--mode replay --grade-mode record`):
- The agent cassettes are **byte-identical** before and after (same sha256 over all 12 files).
- Only the new `*.grading.jsonl` files were recorded.
- Replay of agent + grading reproduces `expected_results.jsonl` exactly.

## 3. B1 numbers – 36 stored live runs (102 activities, 114 reasons, 28 plans)

| Metric | Rate (95% CI) | Threshold | Verdict |
|---|---|---|---|
| Activity hallucination (fabricated / altered / wrong day) | **1.0%** [0–5%] (1/102) | ≤ 5% | ✅ |
| Plan hallucination | 3.6% [1–18%] (1/28) | ≤ 10% | ✅ |
| Trajectory-ungrounded (used, never retrieved) | 0.6% [0–3%] (1/173) | ≤ 5% | ✅ |
| Reason reference errors (code) | 7.9% [4–14%] (9/114) | ≤ 10% | ✅ |
| **Ungrounded reasons (judge)** | **19.3% [13–27%]** (22/114) | ≤ 25% (regression guard) | ✅ |

On the committed 12-run recording: activity/plan/trajectory 0%, reason references 3.2%, ungrounded
reasons 12.9%.

## 4. What we learned

1. **The data is real; the explanations aren't always.**
   - **Data hallucination is rare:** the one altered activity is g05 dropping the trailing *"Related interests: …"* sentence. The new `first_difference` hint points straight at it, which the in-loop eval never did.
   - **The agent does look things up:** only one day's weather was used without being fetched.
2. **About 1 in 5 reasons makes an unsupported claim.** The judge catches what the code grader can't:
   - *Interest belongs to the traveler but not to the activity:* "Matches Hiro's interest in art" on the tennis/cooking luncheon.
   - *Weather or venue claims on the wrong day:* "Indoor venue avoids the storm" on clear 06-10.
   - *Interests the traveler doesn't have:* "Matches Tess's interest in art" (Tess: theatre only). The code grader catches these too.
3. **The code grader is a cheap lower bound** (7.9%) for the judge (19.3%). In production (C1) it runs on every run, and the judge on a 10% sample.

## 5. Threshold decisions
- The data-grounding thresholds are set with headroom above the measured rates.
- `max_ungrounded_reason_rate = 0.25` is a **regression guard** just above today's upper CI (owner decision). It accepts the current level and catches it getting worse.
- **Follow-up for B4 (prompt v2):** reduce ungrounded reasons. For example, require each reason to cite only the traveler interests that appear in the activity's `related_interests`, and the day's actual forecast. Then tighten this threshold.

## 6. Production-signal contract
`GroundingSignal` (`b1.v1`): see `production-signal.md`. Code graders run on every run, and the judge on 10%.
