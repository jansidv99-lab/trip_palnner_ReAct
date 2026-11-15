# Phase 9 – Step 5: B2 findings – does the plan satisfy the hard constraints?

> Golden v1.0.0 · config `gpt-4o-mini__v1__t0` · prompt `v1` · weather judge `gpt-4.1`.
> **Spend: $0.** Everything was re-graded by replay; B2 graders make no LLM calls.
> Status: **APPROVED (2026-11-15)** – §5 threshold proposals accepted as written (Step 6).

## 1. What was measured

| Source | Runs | How |
|---|---|---|
| 36 stored live runs (`experiments/live-v1-r3`, 12 cases × 3) | 36 | `grade_runs.py experiments/live-v1-r3 --mode replay` |
| B0 recording (committed cassettes) | 12 | `run_experiment.py --update-expected`, then `--check-expected` |

Re-grading changed **no** existing field and **no** B1 outcome in either set (checked by script
against a backup / `git show HEAD`). B1 headline numbers are identical to `b1-findings.md`.

## 2. B2 numbers – 36 live runs (28 plans)

**Constraint violations (over produced plans – lower is better)**

| Constraint | Violations (95% CI) |
|---|---|
| City / dates wrong | 0.0% [0–12%] (0/28) |
| Over budget (actual price sum) | 0.0% [0–12%] (0/28) |
| Reported total ≠ sum of prices | **3.6% [1–18%] (1/28)** |
| Overlapping activities | 0.0% [0–12%] (0/28) |
| Weather-unsuitable (LLM judge) | 0.0% [0–12%] (0/28) |
| Weather vs human labels (must-avoid picks ÷ labeled picks) | 0.0% [0–11%] (0/30) |

**Completion**

| Metric | Value (95% CI) |
|---|---|
| All hard constraints pass (÷ plans) | 92.9% [77–98%] (26/28) |
| **Goal completion (÷ all runs)** | **72.2% [56–84%] (26/36)** |
| Guardrail rejected ≥ 1 final answer (÷ final-answer runs) | 17.9% [8–36%] (5/28) |
| Steps to completion | p50 10, p95 19 (max_steps is 20) |
| Infeasible request handled (g07) | 66.7% [21–94%] (2/3) |
| Weather judge agrees with human labels | 100% [89–100%] (30/30) · missed 0 · false alarms 0 |

**Failure taxonomy – the 10 runs that didn't complete**

| Failure mode | Runs | Cases |
|---|---|---|
| `eval_loop:total_cost_accurate` | **6** | g01 r3, g02 r1/r2/r3, g03 r2, g06 r2 |
| `invalid_args_loop:run_evals_tool` | 2 | g07 r3, g09 r3 |
| `guardrail_exhausted:total_cost_accurate` | 1 | g06 r1 |
| `guardrail_exhausted:no_hallucinated_activities` | 1 | g05 r3 |

B0 recording (12 runs) gives the same picture: 0 violations in its 8 plans, judge agreement
11/11, 4 failures (`eval_loop` ×2, `llm_error:timeout`, `invalid_args_loop:final_answer_tool` on g07).

## 3. What we learned

1. **Constraints aren't the problem – finishing is.** When the agent answers, its plan is almost
   always valid (26/28). The gap between that and goal completion (72%) is runs that never deliver
   an acceptable answer. A single pass/fail number would have hidden this; the conditional vs
   unconditional split shows it.

2. **Cost is the #1 blocker: 7 of 10 failures (6 loops + 1 guardrail exhausted).** It is a
   **bookkeeping error, not an arithmetic error.** The calculator is always right; the agent feeds
   it the wrong list of prices:
   - g01 r3: the calculator sums 6 prices (108) while the plan has 7 activities (123) – repeated 5×.
   - g06 r1: sums 9 prices (150) for a 10-activity plan (165) – submitted 3× to `final_answer_tool`.
   - g02 r3: `total_cost=0` in all 13 `run_evals_tool` calls; the calculator is never used.
   - g02 r1: the total stays at 40 while the activities change (93 → 88 → 70).

   The eval message **already contains the right number** ("plan says total_cost=108, activities
   sum to 123"), and the agent doesn't use it. All three tight-budget runs (g02) loop: budget
   pressure makes the agent keep changing activities without recomputing the total.

3. **Argument loops are one schema mistake, never fixed.** Both `invalid_args_loop` runs repeat the
   same error 13–14 times: `reasons_for_recommendation – Field required`. The error message names the
   field exactly; the agent resubmits the same shape.

4. **The guardrail helps, but not much.** 7 runs had ≥ 1 rejection; 3 recovered (g05 r1, g06 r3,
   g09 r2), 2 exhausted it, 2 went on to loop until `max_steps`.

5. **Weather is handled well – and the judge proves itself on real picks.** Final plans contain
   no must-avoid activity (0/30). That means the final-plan agreement (30/30) only shows the judge
   doesn't raise false alarms; it can't show it catches bad picks. The trajectory does: the agent
   submitted a must-avoid activity to `run_evals_tool` **3 times** (g03 r1, g03 r2, g06 r2), the judge
   flagged **all 3**, and the agent removed them. Together with the B1 calibration, the weather judge
   is trustworthy on this data.

6. **Infeasible requests mostly work.** g07 delivered the correct empty plan in 2/3 live runs;
   the third failure is the schema loop from (3), not a planning mistake. The 1-case denominator
   makes the interval very wide (21–94%).

7. **Plan guesses vs rules.** The plan's "seen in stored runs" column expected g03 r2 to be
   `max_steps:other`; the deterministic rules put it in `eval_loop:total_cost_accurate` (≥ 2
   `EVALS FAILED` observations). No run falls into `max_steps:other` or `unknown`.

**Candidates for B4 (eval-driven improvement – not done here, per Q4):**
- Let `final_answer_tool` / `run_evals_tool` compute `total_cost` from the plan's own activities
  (removes the bookkeeping error class entirely), **or** tell the prompt to copy the sum the eval
  reports.
- Show a minimal valid `ActivityRecommendation` example in the invalid-arguments error.
- Expected effect to measure in B4: goal completion up from 72%, `eval_loop:total_cost_accurate` → 0.

## 4. Statistical caveats

- 36 runs: intervals are wide. "0/28" still allows up to 12% true violation rate.
- Weather-label units are few (30) and contain no must-avoid picks in final plans – see (5).
- Infeasible handling rests on **one** case (g07) × 3 runs.
- Growing the dataset is B5's job (Q1: golden v1.0.0 kept for comparability).

## 5. Threshold proposals for Step 6 (`[b2]` – your decision)

Same approach as B1: a **regression guard** just above today's upper CI where we already do well,
and a **target** only where you want to force improvement.

| Rule | Today (95% CI) | Proposal | Kind |
|---|---|---|---|
| `max_city_dates_violation_rate` | 0% [0–12%] | 0.05 | target – must stay ~0 |
| `max_budget_violation_rate` | 0% [0–12%] | 0.05 | target – must stay ~0 |
| `max_overlap_violation_rate` | 0% [0–12%] | 0.05 | target – must stay ~0 |
| `max_weather_label_violation_rate` | 0% [0–11%] | 0.05 | target – must stay ~0 |
| `max_cost_accuracy_violation_rate` | 3.6% [1–18%] | 0.10 | regression guard |
| `min_goal_completion_rate` | 72.2% [56–84%] | 0.60 | regression guard (raise after B4) |
| `min_weather_judge_agreement` | 100% [89–100%] | 0.90 | judge trust bar (like B1's recall) |

Note: the B0 recording (12 runs, the CI path) has goal completion 66.7% – above 0.60, so the
CI gate stays green. A `0.70` target would fail CI today.

## 6. Production signal (Step 7)

The C2 dashboard should chart: goal completion, the failure-mode mix (top category today:
`eval_loop:total_cost_accurate`), and per-constraint violation rates – all of which
`ConstraintSignal` will carry per production run.
