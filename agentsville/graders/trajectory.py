# Phase 10 – Step 3: B3 trajectory graders – did the agent follow its procedure, faithfully?
"""Code graders over AgentRun.steps, no LLM calls. They check the procedure prompt v1 prescribes
(rule 1: weather for every day; rule 2: activities for every day; rule 5: total via calculator_tool;
rule 7: run_evals_tool before final_answer_tool) and whether the output follows from the reasoning.

"Before the final answer" means before the ACCEPTED final_answer_tool step (the last step of a
final_answer run); guardrail-rejected final answers are ordinary steps.
"""

import json
import re
from collections import Counter
from datetime import date, timedelta

from pydantic import BaseModel, ValidationError

from agentsville.agent import AgentRun, AgentStep
from agentsville.harness.grading import (
    GraderOutcome,
    GradingContext,
    RunGrader,
    not_applicable,
)
from agentsville.harness.grading import outcome as make_outcome
from agentsville.llm import LLMError
from agentsville.models import TravelPlan
from agentsville.prompts import render_prompt

WEATHER_TOOL = "get_weather_for_date_tool"
ACTIVITY_TOOLS = ("get_activities_by_date_tool", "filter_activities_by_interest_tool")
LOOKUP_TOOLS = (WEATHER_TOOL, *ACTIVITY_TOOLS, "get_activity_by_id_tool")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
THOUGHT_ACTION_JUDGE_MODEL = "gpt-4.1"
THOUGHT_ACTION_JUDGE_PROMPT_VERSION = "v1"
PLAN_TOOLS = ("run_evals_tool", "final_answer_tool")
OBSERVATION_CHARS = 1500  # cap for free-text observations (tool data is rendered compactly)
RUN_START = "(start of the run – the agent has only the traveler's request)"


# Phase 10 – Step 3: steps the agent took before its accepted final answer
def steps_before_final(run: AgentRun) -> list[AgentStep]:
    if run.stop_reason == "final_answer" and run.steps:
        return run.steps[:-1]
    return run.steps


def _trip_days(run: AgentRun) -> list[date]:
    info = run.vacation_info
    n = (info.date_of_departure - info.date_of_arrival).days
    return [info.date_of_arrival + timedelta(days=i) for i in range(n + 1)]


def _step_date(step: AgentStep) -> date | None:
    try:
        return date.fromisoformat(str((step.arguments or {}).get("date")))
    except ValueError:
        return None


def _looked_up_days(run: AgentRun, tools: tuple[str, ...]) -> set[date]:
    return {_step_date(s) for s in steps_before_final(run)
            if s.tool_name in tools and not s.is_error} - {None}


def _lookup_coverage(name: str, run: AgentRun, tools: tuple[str, ...]) -> GraderOutcome:
    seen = _looked_up_days(run, tools)
    problems = [f"{day}: never looked up before the final answer"
                for day in _trip_days(run) if day not in seen]
    counts = {"missing_day": len(problems)} if problems else {}
    return make_outcome(name, "deterministic", len(_trip_days(run)), problems, counts)


# Phase 10 – Step 3: prompt rule 1 – the weather was fetched for every trip day
def weather_lookup_coverage(run: AgentRun, ctx: GradingContext | None = None) -> GraderOutcome:
    return _lookup_coverage("weather_lookup_coverage", run, (WEATHER_TOOL,))


# Phase 10 – Step 3: prompt rule 2 – activities were fetched for every trip day
def activity_lookup_coverage(run: AgentRun, ctx: GradingContext | None = None) -> GraderOutcome:
    return _lookup_coverage("activity_lookup_coverage", run, ACTIVITY_TOOLS)


def _as_number(text: str) -> float | None:
    try:
        return float(text.strip())
    except ValueError:
        return None


# Phase 10 – Step 3: prompt rule 5 – total_cost came from the calculator AND is the real price sum
def calculator_total(run: AgentRun, ctx: GradingContext | None = None) -> GraderOutcome:
    name = "calculator_total"
    plan = run.travel_plan
    prices = [rec.activity.price for day in plan.itinerary_days
              for rec in day.activity_recommendations]
    if not prices:
        return not_applicable(name, "deterministic", "no activities to add up")
    calls = [s for s in steps_before_final(run) if s.tool_name == "calculator_tool"
             and not s.is_error]
    matching = [s for s in calls if _as_number(s.observation) == plan.total_cost]
    actual = sum(prices)
    if not calls:
        kind, problem = "no_calculator", "calculator_tool was never used"
    elif not matching:
        kind = "total_not_from_calculator"
        problem = (f"total_cost {plan.total_cost} is not the result of any calculator call "
                   f"(last result: {calls[-1].observation})")
    elif plan.total_cost != actual:
        expression = str((matching[-1].arguments or {}).get("expression", ""))
        used = Counter(int(float(n)) for n in _NUMBER.findall(expression))
        missing, extra = Counter(prices) - used, used - Counter(prices)
        kind = "wrong_price_list"
        problem = (f"calculator gave {plan.total_cost} but the plan's prices sum to {actual} "
                   f"(missing {sorted(missing.elements())}, extra {sorted(extra.elements())})")
    else:
        return make_outcome(name, "deterministic", 1, [])
    return make_outcome(name, "deterministic", 1, [problem], {kind: 1})


def _canonical(plan_args) -> str:
    try:
        return TravelPlan.model_validate(plan_args).model_dump_json()
    except ValidationError:
        return json.dumps(plan_args, sort_keys=True)


# Phase 10 – Step 3: prompt rule 7 – the plan submitted is the plan that passed run_evals_tool
def verified_before_final(run: AgentRun, ctx: GradingContext | None = None) -> GraderOutcome:
    name = "verified_before_final"
    if run.stop_reason != "final_answer":
        return not_applicable(name, "deterministic", "no accepted final answer")
    final = _canonical((run.steps[-1].arguments or {}).get("travel_plan"))
    evals = [s for s in steps_before_final(run)
             if s.tool_name == "run_evals_tool" and s.observation.startswith("EVALS ")]
    passed_same = any(s.observation.startswith("EVALS PASSED")
                      and _canonical((s.arguments or {}).get("travel_plan")) == final
                      for s in evals)
    if passed_same:
        return make_outcome(name, "deterministic", 1, [])
    if not evals:
        kind, problem = "never_ran_evals", "run_evals_tool was never run successfully"
    elif evals[-1].observation.startswith("EVALS FAILED"):
        kind, problem = "last_evals_failed", (f"last run_evals_tool (step {evals[-1].step}) "
                                             "FAILED and no passing check of this plan")
    else:
        kind, problem = "plan_changed_after_evals", ("the submitted plan differs from every plan "
                                                     "that passed run_evals_tool")
    return make_outcome(name, "deterministic", 1, [problem], {kind: 1})


# Phase 10 – Step 3: repeated identical lookups (data never changes mid-run) and error steps
def tool_efficiency(run: AgentRun, ctx: GradingContext | None = None) -> GraderOutcome:
    succeeded: set[str] = set()
    units, problems = 0, []
    for step in run.steps:
        if step.tool_name not in LOOKUP_TOOLS:
            continue
        units += 1
        key = f"{step.tool_name}:{json.dumps(step.arguments, sort_keys=True)}"
        if key in succeeded:  # a retry after an ERROR is not redundant
            problems.append(f"step {step.step}: repeats {step.tool_name} {step.arguments}")
        elif not step.is_error:
            succeeded.add(key)
    counts = {"redundant": len(problems)} if problems else {}
    errors = sum(s.is_error for s in run.steps)
    if errors:
        counts["error_steps"] = errors
    return make_outcome("tool_efficiency", "deterministic", units, problems, counts,
                        failed_units=len(problems))


B3_TRAJECTORY_GRADERS = [
    RunGrader("weather_lookup_coverage", "deterministic", weather_lookup_coverage),
    RunGrader("activity_lookup_coverage", "deterministic", activity_lookup_coverage),
    RunGrader("calculator_total", "deterministic", calculator_total),
    RunGrader("verified_before_final", "deterministic", verified_before_final),
    RunGrader("tool_efficiency", "deterministic", tool_efficiency, needs_plan=False),
]


# ---------------------------------------------------------------------------
# Phase 10 – Step 5: thought↔action consistency judge. Code supplies the facts it can compute
# (is this plan identical to the last one sent? do its prices fit the budget?); the LLM judges
# whether the thought agrees; code then checks the LLM's quote really is in the thought.
# ---------------------------------------------------------------------------


class StepVerdict(BaseModel):
    step: int
    consistent: bool
    type: str = ""
    quote: str = ""
    why: str = ""


class ThoughtActionVerdict(BaseModel):
    steps: list[StepVerdict]


# Phase 10 – Step 5: the judge's decision for one step, after code verification
class StepJudgment(BaseModel):
    step: int
    consistent: bool
    type: str = ""  # action_mismatch | misreads_observation | "" (or judge_failure)
    reason: str = ""


def thought_action_prompt(version: str = THOUGHT_ACTION_JUDGE_PROMPT_VERSION) -> str:
    return render_prompt("judges/thought_action", version, {})


def _plan_summary(plan, budget: int) -> str:
    if not isinstance(plan, dict) or not isinstance(plan.get("itinerary_days"), list):
        return "travel_plan (malformed)"
    days, prices = [], []
    for day in plan["itinerary_days"]:
        recs = day.get("activity_recommendations", []) if isinstance(day, dict) else []
        acts = [r.get("activity", {}) for r in recs if isinstance(r, dict)]
        acts = [a for a in acts if isinstance(a, dict)]
        prices += [a.get("price") for a in acts if isinstance(a.get("price"), int | float)]
        days.append(f"{str(day.get('date', '?'))[5:] if isinstance(day, dict) else '?'}: "
                    f"[{', '.join(str(a.get('activity_id', '?'))[-4:] for a in acts)}]")
    return (f"travel_plan {'; '.join(days)} | reported total_cost={plan.get('total_cost')} | "
            f"FACT: prices sum to {sum(prices):g}, budget {budget}")


# Phase 10 – Step 5: the trajectory as the judge sees it (only steps with a parsed action)
def thought_action_input(steps: list[AgentStep], budget: int,
                         start_observation: str = RUN_START) -> str:
    lines, previous, last_plan = [], start_observation, None
    for step in steps:
        if step.tool_name is not None:
            args = dict(step.arguments or {})
            plan_note = ""
            if step.tool_name in PLAN_TOOLS and "travel_plan" in args:
                plan = args.pop("travel_plan")
                key = json.dumps(plan, sort_keys=True)
                if last_plan is None:
                    plan_note = "FACT: first travel_plan sent in this trajectory"
                elif key == last_plan[1]:
                    plan_note = f"FACT: IDENTICAL to the travel_plan sent at step {last_plan[0]}"
                else:
                    plan_note = f"FACT: changed since the travel_plan sent at step {last_plan[0]}"
                last_plan = (step.step, key)
                args_text = _plan_summary(plan, budget) + (f" {json.dumps(args)}" if args else "")
            else:
                args_text = json.dumps(args)
            obs = compact_observation(previous)
            lines += [f"STEP {step.step}", f"PREVIOUS OBSERVATION: {obs}",
                      f"THOUGHT: {step.thought}", f"ACTION: {step.tool_name} {args_text}"]
            if plan_note:
                lines.append(plan_note)
            lines.append("")
        previous = step.observation
    return "\n".join(lines).strip()


def _activity_brief(a: dict) -> str:
    start, end = str(a.get("start_time", "")), str(a.get("end_time", ""))
    interests = ", ".join(map(str, a.get("related_interests", [])))
    return (f"{a.get('activity_id')} | {a.get('name')} | {start[11:16]}-{end[11:16]} | "
            f"price {a.get('price')} | interests: {interests}")


# Phase 10 – Step 5: tool data rendered compactly but COMPLETELY (truncating an activity list
# would hide the evidence for "misreads_observation"); free text is capped.
def compact_observation(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, list) and all(isinstance(a, dict) and "activity_id" in a for a in data):
        return f"{len(data)} activities: " + " || ".join(_activity_brief(a) for a in data)
    if isinstance(data, dict) and "activity_id" in data:
        return "activity: " + _activity_brief(data)
    if isinstance(data, dict) and "condition" in data:
        return (f"weather {data.get('date')}: {data.get('condition')}, {data.get('temperature')} "
                f"{data.get('temperature_unit')}. {data.get('description', '')}")
    flat = text.replace("\n", " | ")
    return flat if len(flat) <= OBSERVATION_CHARS else flat[:OBSERVATION_CHARS] + " …(abbreviated)"


def _normalize(text: str) -> str:
    return " ".join(text.casefold().replace("\u2019", "'").strip(" .'\"").split())


# Phase 10 – Step 5: one call per trajectory; fails closed (every step inconsistent)
def judge_thought_action(llm, steps: list[AgentStep], budget: int,
                         start_observation: str = RUN_START,
                         model: str = THOUGHT_ACTION_JUDGE_MODEL) -> list[StepJudgment]:
    judged = [s for s in steps if s.tool_name is not None]
    if not judged:
        return []
    messages = [{"role": "system", "content": thought_action_prompt()},
                {"role": "user", "content": thought_action_input(steps, budget,
                                                                 start_observation)}]
    failure = None
    try:
        reply = llm.chat(messages, model=model, json_mode=True)
        verdicts = ThoughtActionVerdict.model_validate_json(reply.text).steps
        if [v.step for v in verdicts] != [s.step for s in judged]:
            failure = (f"judge returned steps {[v.step for v in verdicts]}, expected "
                       f"{[s.step for s in judged]}")
    except LLMError as exc:
        failure = f"judge call failed: {exc}"
    except ValidationError:
        failure = "judge reply unparseable"
    if failure:
        return [StepJudgment(step=s.step, consistent=False, type="judge_failure", reason=failure)
                for s in judged]
    judgments = []
    for step, v in zip(judged, verdicts, strict=True):
        if v.consistent:
            judgments.append(StepJudgment(step=step.step, consistent=True))
        elif not v.quote or _normalize(v.quote) not in _normalize(step.thought):
            judgments.append(StepJudgment(  # a claim code can disprove is dropped
                step=step.step, consistent=True,
                reason=f"judge claim rejected – quote not in the thought: {v.quote!r}"))
        else:
            judgments.append(StepJudgment(step=step.step, consistent=False,
                                          type=v.type or "action_mismatch",
                                          reason=f"{v.quote!r} – {v.why}"))
    return judgments


# Phase 10 – Step 5: LLM judge – does every THOUGHT agree with its ACTION and the last observation?
def thought_action_consistency(run: AgentRun, ctx: GradingContext) -> GraderOutcome:
    judgments = judge_thought_action(ctx.llm, run.steps, run.vacation_info.budget)
    problems = [f"step {j.step} ({j.type}): {j.reason}" for j in judgments if not j.consistent]
    counts: dict[str, int] = {}
    for j in judgments:
        if not j.consistent:
            counts[j.type] = counts.get(j.type, 0) + 1
    return make_outcome("thought_action_consistency", "llm", len(judgments), problems,
                        dict(sorted(counts.items())), failed_units=len(problems))


# Phase 10 – Step 5: defined and calibrated now; registered in ALL_GRADERS in Step 7 with recording
THOUGHT_ACTION_JUDGE = RunGrader("thought_action_consistency", "llm", thought_action_consistency,
                                 needs_plan=False)
