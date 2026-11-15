# Phase 9 – Step 3: failure taxonomy – WHY a run didn't complete, from deterministic rules.
"""A run completes when it ends with a final answer AND every hard (error) eval passes – the same
definition as goal completion in harness/metrics.py. Every other run gets exactly one category,
"<category>:<detail>", from the first rule that matches (the order below matters):

    llm_error:timeout | llm_error:other     the LLM call failed
    guardrail_exhausted:<eval>              accepted after all guardrail rejections, still failing
    final_failed:<eval>                     accepted earlier but failing (e.g. the judge-only check)
    invalid_args_loop:<tool>                >= 3 "invalid arguments" errors on the same tool
    eval_loop:<eval>                        >= 2 "EVALS FAILED" observations; the most frequent ✗
    max_steps:other                         anything else that ran out of steps
"""

import re
from collections import Counter

from agentsville.agent import AgentRun

INVALID_ARGS_LOOP = 3  # same-tool argument errors before it counts as a loop
EVAL_LOOP = 2  # failed eval observations before it counts as a loop
_INVALID_ARGS = re.compile(r"^ERROR: invalid arguments for (\S+?):")
_FAILED_EVAL = re.compile(r"^✗ (\w+)", re.MULTILINE)


# Phase 9 – Step 3: tool → number of "invalid arguments" errors in the trajectory
def invalid_argument_errors(run: AgentRun) -> Counter:
    counts: Counter = Counter()
    for step in run.steps:
        match = _INVALID_ARGS.match(step.observation)
        if match:
            counts[match.group(1)] += 1
    return counts


# Phase 9 – Step 3: eval → how often it appeared as ✗ across "EVALS FAILED" observations
def failed_eval_observations(run: AgentRun) -> tuple[int, Counter]:
    observations, failing = 0, Counter()
    for step in run.steps:
        if "EVALS FAILED" in step.observation:
            observations += 1
            failing.update(_FAILED_EVAL.findall(step.observation))
    return observations, failing


# Phase 9 – Step 3: None = completed; otherwise one "<category>:<detail>" label
def classify_failure(run: AgentRun, max_rejections: int = 2) -> str | None:
    report = run.final_eval_report
    if run.stop_reason == "final_answer" and report is not None and report.passed:
        return None
    if run.stop_reason == "llm_error":
        error = (run.error or "").casefold()
        timeout = "timeout" in error or "timed out" in error
        return "llm_error:timeout" if timeout else "llm_error:other"
    if run.stop_reason == "final_answer":
        results = report.results if report else []
        failing = [r.name for r in results if not r.passed and r.severity == "error"]
        first = failing[0] if failing else "unknown"
        if run.final_rejections >= max_rejections:
            return f"guardrail_exhausted:{first}"
        return f"final_failed:{first}"

    tool_errors = invalid_argument_errors(run)
    if tool_errors:
        tool, count = tool_errors.most_common(1)[0]
        if count >= INVALID_ARGS_LOOP:
            return f"invalid_args_loop:{tool}"
    observations, failing = failed_eval_observations(run)
    if observations >= EVAL_LOOP:
        return f"eval_loop:{failing.most_common(1)[0][0] if failing else 'unknown'}"
    return "max_steps:other"
