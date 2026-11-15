# Phase 7 – Step 7: first baseline on golden v1.0.0

> Config `gpt-4o-mini__v1__t0` (prompt v1, temperature 0, max_steps 20, gpt-4.1 judge on).
> Recorded experiment: 12 cases × 1 repeat, $0.195, 6 min 12 s. Cassettes:
> `evals/cassettes/golden-v1.0.0/gpt-4o-mini__v1__t0/` (352 KB, committed).

## B0's question: is the experiment repeatable?

**Yes.** `run_experiment.py --check-expected` replayed all 12 runs in **2 seconds** with **zero LLM
calls** and produced results identical to the recording (`expected_results.jsonl`). CI does the
same on every relevant PR (`Evals / eval-replay`).

## Baseline numbers (1 repeat)

| Metric | Value (95% Wilson CI) |
|---|---|
| **Goal completion** | **66.7% [39%–86%]** (8/12) |
| Stop reasons | final_answer 8, max_steps 3, llm_error 1 |
| Cost per run | mean $0.016, p95 $0.031 |
| Steps per run | mean 12.8, p95 20 |
| Latency per run | mean 83 s, p95 145 s |

The interval is wide (39–86%) because 12 runs is a small sample. That's why later slices use repeats.

## Failure modes found (B0 measures; later slices fix)

| Case | What happened | Failure mode | Owned by |
|---|---|---|---|
| g05 one sunny day | 13× `run_evals_tool`, never copied `event-2025-06-15-1`'s description exactly. The eval message says *that* it differs, not *where* | copy fidelity / hallucination; unhelpful eval feedback | **B1** |
| g04 theatre | total_cost wrong again and again (95 vs 110); summed by hand instead of using the calculator result | calculation faithfulness | **B2 / B3** |
| g07 infeasible budget | 15× `final_answer_tool` **without** a `travel_plan` argument; prompt v1 never says an empty plan is allowed | infeasible-case handling | **B2** (prompt v2 in **B4**) |
| g06 family, 6 days | `APITimeoutError` at 60 s (long context + large final plan) | goal completion / infra timeout | **B2** |

## Variance: 3-repeat live run (36 runs, $0.66, ~16 min, not committed)

| Metric | 1-repeat recording | 3-repeat live |
|---|---|---|
| **Goal completion** | 66.7% [39%–86%] (8/12) | **72.2% [56%–84%]** (26/36) |
| Plan produced | 66.7% | 77.8% |
| Stop reasons | final 8, max_steps 3, llm_error 1 | final 28, max_steps 8 |
| Cost / steps / latency per run | $0.016 / 12.8 / 83 s | $0.019 / 13.0 / 111 s (p95 263 s) |

`compare_experiments.py` marks every difference **"not clearly different"**: the intervals overlap.

**Temperature 0 is not deterministic.** The same config gives opposite verdicts:

| Case | Recording | Live ×3 |
|---|---|---|
| g02 tight budget | ✓ | **0/3** (all max_steps) |
| g04 theatre | ✗ (max_steps) | **3/3** |
| g06 family | ✗ (timeout) | 1/3 (one cost error, one max_steps; no timeouts this time) |
| g08, g10, g11, g12 | ✓ | 3/3 (stable) |

**Lessons for the next slices:**
1. A single run, or a single recording, can't tell a good config from a bad one. Decisions need repeats (B4: 5 repeats for baselines, pass^k for consistency).
2. Record/replay is what makes CI deterministic despite (1). CI checks the *code path*, while live repeats measure the *model*.
3. `max_steps` is the dominant failure (8 of 10 failing runs). Loops on cost totals and copy fidelity, and g02 in every repeat, point B1/B2 at loop causes and at better eval feedback.
4. `interest_coverage` (a warning) is the lowest-scoring grader at 58%. B3 should split it into what's achievable vs what's uncoverable, using the golden labels.
