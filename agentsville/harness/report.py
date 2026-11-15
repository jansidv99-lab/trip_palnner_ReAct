# Phase 7 – Step 6: markdown experiment report and a safe comparison of two experiments.

from agentsville.harness.metrics import ExperimentSummary, RateStat
from agentsville.harness.schema import CaseResult
from agentsville.harness.thresholds import ThresholdResult


# Phase 7 – Step 6: comparing experiments on different datasets would be meaningless
class ComparisonError(RuntimeError):
    pass


def _pct(stat: RateStat) -> str:
    return f"{stat.rate:6.1%} [{stat.ci_low:.0%}–{stat.ci_high:.0%}] ({stat.successes}/{stat.n})"


# Phase 7 – Step 6: one experiment as a readable markdown report
def render_report(
    summary: ExperimentSummary,
    results: list[CaseResult],
    thresholds: list[ThresholdResult] | None = None,
) -> str:
    c = summary.config
    stops = ", ".join(f"{k}: {v}" for k, v in sorted(summary.stop_reasons.items()))
    lines = [
        f"# Experiment report – {c.config_id}",
        "",
        f"- **Dataset:** golden {summary.dataset_version} "
        f"(sha256 `{summary.dataset_sha256[:12]}…`), {summary.case_count} cases × "
        f"{c.repeats} repeat(s) = {summary.run_count} runs",
        f"- **Config:** model `{c.model}`, prompt `{c.prompt_version}`, temperature "
        f"{c.temperature:g}, max_steps {c.max_steps}, LLM judge "
        f"{'on' if c.include_llm_evals else 'off'}, mode `{c.mode}`",
        "",
        "## Headline",
        "",
        "| Metric | Value (95% CI) |",
        "|---|---|",
        f"| **Goal completion** (final answer + all error graders pass) | "
        f"{_pct(summary.goal_completion)} |",
        f"| Plan produced | {_pct(summary.plan_rate)} |",
        f"| Stop reasons | {stops} |",
        f"| Cost per run (USD) | mean {summary.cost_usd.mean:.4f}, p95 {summary.cost_usd.p95:.4f}, "
        f"total {summary.cost_usd.total:.4f} |",
        f"| Steps per run | mean {summary.steps.mean:.1f}, p95 {summary.steps.p95:.1f} |",
        f"| Latency per run (s) | mean {summary.latency_s.mean:.1f}, "
        f"p95 {summary.latency_s.p95:.1f} |",
        "",
        "## Graders (a run without a plan counts as a failure)",
        "",
        "| Grader | Pass rate (95% CI) |",
        "|---|---|",
        *[f"| {name} | {_pct(stat)} |" for name, stat in summary.graders.items()],
        "",
        "## Cases (goal completion across repeats)",
        "",
        "| Case | Completion |",
        "|---|---|",
        *[f"| {case_id} | {_pct(stat)} |" for case_id, stat in summary.per_case.items()],
    ]
    lines += _grounding_section(summary, results) + _constraints_section(summary, results)
    lines += _b3_section(summary, results)
    lines += _thresholds_section(thresholds)
    failing = [r for r in sorted(results, key=lambda r: (r.case_id, r.repeat))
               if not (r.stop_reason == "final_answer" and r.eval_passed)]
    lines += ["", "## Failing runs", ""]
    if not failing:
        lines.append("None.")
    for r in failing:
        reason = "; ".join(r.failures) or r.error or f"stopped: {r.stop_reason}"
        lines.append(f"- **{r.case_id} r{r.repeat}** ({r.stop_reason}, {r.steps} steps): {reason}")
    return "\n".join(lines) + "\n"


# Phase 8 – Step 6: "B1 – Grounding" section – hallucination rates and the worst examples
def _grounding_section(summary: ExperimentSummary, results: list[CaseResult]) -> list[str]:
    b1 = summary.b1
    if b1 is None:
        return []
    rows = [
        ("Activity hallucination rate (fabricated/altered/wrong day ÷ activities)",
         b1.activity_hallucination),
        ("Plan hallucination rate (plans with any activity/weather hallucination)",
         b1.plan_hallucination),
        ("Trajectory-ungrounded rate (used but never retrieved)", b1.trajectory_ungrounded),
        ("Reason reference errors (unknown traveler / wrong interest)",
         b1.reason_reference_errors),
        ("Ungrounded reasons (LLM judge)", b1.ungrounded_reasons),
    ]
    examples = [
        f"{r.case_id} r{r.repeat} · {name}: {detail}"
        for r in sorted(results, key=lambda r: (r.case_id, r.repeat))
        for name, o in r.grader_outcomes.items()
        for detail in o.details
        if detail != "no plan produced"
    ]
    lines = ["", "## B1 – Grounding (is everything in the plan real?)", "",
             "| Metric | Rate (95% CI) – lower is better |", "|---|---|"]
    lines += [f"| {label} | {_pct(stat) if stat else 'not measured'} |" for label, stat in rows]
    lines += ["", f"Examples ({min(5, len(examples))} of {len(examples)}):", ""]
    lines += [f"- {e}" for e in examples[:5]] or ["- none"]
    return lines


B2_VIOLATION_LABELS = {
    "city_dates": "City / dates wrong",
    "cost_accuracy": "Reported total ≠ sum of prices",
    "overlap": "Overlapping activities",
    "budget": "Over budget (actual price sum)",
    "weather_judge": "Weather-unsuitable (LLM judge)",
}


# Phase 9 – Step 4: "B2 – Constraints & completion" section
def _constraints_section(summary: ExperimentSummary, results: list[CaseResult]) -> list[str]:
    b2 = summary.b2
    if b2 is None:
        return []
    lines = ["", "## B2 – Constraints & completion (does the plan satisfy the hard constraints?)",
             "", "Violation rates are over **produced plans** (when it answers, is it valid?).", "",
             "| Constraint | Violation rate (95% CI) – lower is better |", "|---|---|"]
    lines += [f"| {B2_VIOLATION_LABELS.get(key, key)} | {_pct(stat)} |"
              for key, stat in b2.violations.items()]
    lines += [
        f"| Weather vs human labels (must-avoid picks ÷ labeled picks) | "
        f"{_pct(b2.weather_label_violations)} |",
        "",
        "| Completion metric | Value (95% CI) |",
        "|---|---|",
        f"| All hard constraints pass (÷ plans) | {_pct(b2.all_hard_pass)} |",
        f"| **Goal completion** (÷ all runs) | {_pct(summary.goal_completion)} |",
        f"| Guardrail rejected ≥ 1 final answer (÷ final-answer runs) | "
        f"{_pct(b2.guardrail_rejection)} |",
        f"| Steps to completion (completed runs) | p50 {b2.steps_to_completion.p50:.0f}, "
        f"p95 {b2.steps_to_completion.p95:.0f} |",
        f"| Infeasible request handled (empty plan delivered) | "
        f"{_pct(b2.infeasible_handled) if b2.infeasible_handled else 'no infeasible case'} |",
        "| Weather judge agrees with human labels | "
        + (f"{_pct(b2.weather_judge_agreement)} · missed {b2.judge_missed}, false alarms "
           f"{b2.judge_false_alarms} |" if b2.weather_judge_agreement else "not measured |"),
        "",
        "### Why runs didn't complete (failure taxonomy)",
        "",
    ]
    if not b2.failure_modes:
        return lines + ["Every run completed."]
    ordered = sorted(results, key=lambda r: (r.case_id, r.repeat))
    lines += ["| Failure mode | Runs | Example |", "|---|---|---|"]
    for mode, count in b2.failure_modes.items():
        example = next(r for r in ordered if r.failure_mode == mode)
        lines.append(f"| `{mode}` | {count} | {example.case_id} r{example.repeat} "
                     f"({example.steps} steps) |")
    return lines


B3_GRADERS_FOR_EXAMPLES = (
    "interest_coverage_labeled", "traveler_relevancy", "calculator_total",
    "verified_before_final", "weather_lookup_coverage", "thought_action_consistency",
)


def _stat_cell(stat: RateStat | None) -> str:
    return _pct(stat) if stat else "not measured"


# Phase 10 – Step 6: "B3 – Relevancy & reasoning" section
def _b3_section(summary: ExperimentSummary, results: list[CaseResult]) -> list[str]:
    rel, rea = summary.b3_relevancy, summary.b3_reasoning
    if rel is None and rea is None:
        return []
    lines = ["", "## B3 – Relevancy & reasoning (is it relevant, and is the reasoning faithful?)",
             "", "Plan-dependent rates count only runs that produced a plan.", ""]
    if rel is not None:
        mean = (f"{rel.mean_relevancy_score:.2f} "
                f"({', '.join(f'{k[-1]}: {v}' for k, v in rel.score_counts.items())})"
                if rel.mean_relevancy_score is not None else "not measured")
        lines += ["| Relevancy | Value (95% CI) |", "|---|---|",
                  f"| Coverable travelers matched (labeled coverage) | "
                  f"{_stat_cell(rel.interest_coverage)} |",
                  f"| Activities matching nobody – lower is better | "
                  f"{_stat_cell(rel.interest_mismatch)} |",
                  f"| **Relevant travelers** (judge score ≥ 4) | {_stat_cell(rel.relevant_rate)} |",
                  f"| Poorly served travelers (score ≤ 2) – lower is better | "
                  f"{_stat_cell(rel.low_relevancy)} |",
                  f"| Mean relevancy score (1–5) | {mean} |", ""]
    if rea is not None:
        lines += ["| Reasoning | Value (95% CI) |", "|---|---|",
                  f"| Weather looked up for every day (÷ trip days) | "
                  f"{_stat_cell(rea.weather_lookup_coverage)} |",
                  f"| Activities looked up for every day (÷ trip days) | "
                  f"{_stat_cell(rea.activity_lookup_coverage)} |",
                  f"| Total came from the calculator (÷ plans with activities) | "
                  f"{_stat_cell(rea.calculator_faithfulness)} |",
                  f"| Submitted plan passed run_evals_tool (÷ accepted plans) | "
                  f"{_stat_cell(rea.verified_before_final)} |",
                  f"| **Faithful** (both of the above) | {_stat_cell(rea.faithfulness)} |",
                  f"| Thought↔action inconsistency (÷ judged steps; a lower bound) – lower is "
                  f"better | {_stat_cell(rea.thought_action_inconsistency)} |",
                  f"| Redundant lookups – lower is better | "
                  f"{_stat_cell(rea.redundant_call_rate)} |",
                  f"| Error steps – lower is better | {_stat_cell(rea.error_step_rate)} |"]
        kinds = [f"{name}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items()))
                 for name, c in rea.failure_counts.items() if c]
        if kinds:
            lines += ["", "Failure kinds: " + " · ".join(kinds)]
    examples = [f"{r.case_id} r{r.repeat} · {name}: {o.details[0]}"
                for r in sorted(results, key=lambda r: (r.case_id, r.repeat))
                for name in B3_GRADERS_FOR_EXAMPLES
                if (o := r.grader_outcomes.get(name)) and not o.passed and o.units and o.details]
    lines += ["", f"Examples ({min(5, len(examples))} of {len(examples)}):", ""]
    lines += [f"- {e}" for e in examples[:5]] or ["- none"]
    return lines


# Phase 8 – Step 7: threshold verdicts
def _thresholds_section(thresholds: list[ThresholdResult] | None) -> list[str]:
    if not thresholds:
        return []
    mark = {True: "✅ pass", False: "❌ FAIL", None: "– not measured"}
    lines = ["", "## Thresholds (evals/thresholds.toml)", "",
             "| Rule | Limit | Value | Verdict |", "|---|---|---|---|"]
    for t in thresholds:
        value = "—" if t.value is None else f"{t.value:.3f}"
        lines.append(f"| {t.section}.{t.rule} | {t.limit:g} | {value} | {mark[t.passed]} |")
    return lines


def _overlap(a: RateStat, b: RateStat) -> bool:
    return a.ci_low <= b.ci_high and b.ci_low <= a.ci_high


def _row(name: str, a: RateStat | None, b: RateStat | None) -> str:
    if a is None or b is None:
        return f"| {name} | {_pct(a) if a else '—'} | {_pct(b) if b else '—'} | – | only in one |"
    verdict = "not clearly different" if _overlap(a, b) else "**likely real difference**"
    return f"| {name} | {_pct(a)} | {_pct(b)} | {b.rate - a.rate:+.1%} | {verdict} |"


# Phase 9 – Step 4: B2 comparison rows (violations are lower-is-better)
def _b2_rows(a: ExperimentSummary, b: ExperimentSummary) -> list[str]:
    if not (a.b2 or b.b2):
        return []
    keys = sorted(set(a.b2.violations if a.b2 else {}) | set(b.b2.violations if b.b2 else {}))
    rows = [_row(f"b2.{k}_violation (lower is better)",
                 a.b2.violations.get(k) if a.b2 else None, b.b2.violations.get(k) if b.b2 else None)
            for k in keys]
    lower = " (lower is better)"
    for attr, label in [("weather_label_violations", "b2.weather_label_violation" + lower),
                        ("all_hard_pass", "b2.all_hard_pass"),
                        ("guardrail_rejection", "b2.guardrail_rejection" + lower),
                        ("infeasible_handled", "b2.infeasible_handled"),
                        ("weather_judge_agreement", "b2.weather_judge_agreement")]:
        stat_a = getattr(a.b2, attr, None) if a.b2 else None
        stat_b = getattr(b.b2, attr, None) if b.b2 else None
        if stat_a or stat_b:  # skip metrics neither side measured
            rows.append(_row(label, stat_a, stat_b))
    return rows


B3_COMPARE_ROWS = [
    ("b3_relevancy", "interest_coverage", "b3.interest_coverage"),
    ("b3_relevancy", "interest_mismatch", "b3.interest_mismatch (lower is better)"),
    ("b3_relevancy", "relevant_rate", "b3.relevant_rate"),
    ("b3_relevancy", "low_relevancy", "b3.low_relevancy (lower is better)"),
    ("b3_reasoning", "weather_lookup_coverage", "b3.weather_lookup_coverage"),
    ("b3_reasoning", "calculator_faithfulness", "b3.calculator_faithfulness"),
    ("b3_reasoning", "verified_before_final", "b3.verified_before_final"),
    ("b3_reasoning", "faithfulness", "b3.faithfulness"),
    ("b3_reasoning", "thought_action_inconsistency",
     "b3.thought_action_inconsistency (lower is better)"),
    ("b3_reasoning", "redundant_call_rate", "b3.redundant_call_rate (lower is better)"),
    ("b3_reasoning", "error_step_rate", "b3.error_step_rate (lower is better)"),
]


# Phase 10 – Step 6: B3 comparison rows; metrics neither side measured are left out
def _b3_rows(a: ExperimentSummary, b: ExperimentSummary) -> list[str]:
    rows = []
    for group, attr, label in B3_COMPARE_ROWS:
        stat_a = getattr(getattr(a, group), attr, None) if getattr(a, group) else None
        stat_b = getattr(getattr(b, group), attr, None) if getattr(b, group) else None
        if stat_a or stat_b:
            rows.append(_row(label, stat_a, stat_b))
    return rows


# Phase 7 – Step 6: A vs B side by side; refuses different datasets unless forced
def compare(a: ExperimentSummary, b: ExperimentSummary, force: bool = False) -> str:
    if (a.dataset_version, a.dataset_sha256) != (b.dataset_version, b.dataset_sha256) and not force:
        raise ComparisonError(
            f"different datasets ({a.dataset_version} vs {b.dataset_version}) – results are not "
            "comparable. Use --force to compare anyway."
        )
    lines = [
        f"# Comparison: A = {a.config.config_id} ({a.config.mode}) vs "
        f"B = {b.config.config_id} ({b.config.mode})",
        "",
        f"Dataset: golden {a.dataset_version} · runs A={a.run_count}, B={b.run_count}. "
        "A difference is called likely real only when the 95% intervals don't overlap.",
        "",
        "| Metric | A | B | Δ (B−A) | Verdict |",
        "|---|---|---|---|---|",
        _row("goal_completion", a.goal_completion, b.goal_completion),
        _row("plan_rate", a.plan_rate, b.plan_rate),
        *[_row(g, a.graders.get(g), b.graders.get(g)) for g in sorted(a.graders | b.graders)],
        *[_row(f"b1.{m} (lower is better)", getattr(a.b1, m, None) if a.b1 else None,
               getattr(b.b1, m, None) if b.b1 else None)
          for m in ("activity_hallucination", "plan_hallucination", "trajectory_ungrounded",
                    "reason_reference_errors", "ungrounded_reasons")
          if a.b1 or b.b1],
        # Phase 9 – Step 4: B2 rows
        *_b2_rows(a, b),
        # Phase 10 – Step 6: B3 rows
        *_b3_rows(a, b),
        "",
        f"Cost per run: A {a.cost_usd.mean:.4f} → B {b.cost_usd.mean:.4f} USD · "
        f"steps: A {a.steps.mean:.1f} → B {b.steps.mean:.1f} · "
        f"latency: A {a.latency_s.mean:.1f}s → B {b.latency_s.mean:.1f}s",
    ]
    return "\n".join(lines) + "\n"
