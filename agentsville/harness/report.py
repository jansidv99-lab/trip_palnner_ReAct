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
    lines += _grounding_section(summary, results) + _thresholds_section(thresholds)
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
        "",
        f"Cost per run: A {a.cost_usd.mean:.4f} → B {b.cost_usd.mean:.4f} USD · "
        f"steps: A {a.steps.mean:.1f} → B {b.steps.mean:.1f} · "
        f"latency: A {a.latency_s.mean:.1f}s → B {b.latency_s.mean:.1f}s",
    ]
    return "\n".join(lines) + "\n"
