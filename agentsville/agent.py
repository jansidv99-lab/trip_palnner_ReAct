# Phase 6 – Step 5: the ReAct ItineraryAgent – THOUGHT → ACTION → OBSERVATION until a final answer.
"""Itinerary agent.

Loop: the LLM replies with one JSON object {thought, action} (requested in JSON mode). We parse
it, run the tool via the Phase 5 registry, and send the result back as an OBSERVATION.
The loop ends when final_answer_tool returns a plan (and passes the guardrail), or after
max_steps.

Every run is returned as an AgentRun (the trace) and appended to a JSONL log.
"""

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from agentsville.evals import EvalReport, run_all_evals
from agentsville.llm import LLMClient, LLMError, LLMResponse
from agentsville.models import TravelPlan, VacationInfo
from agentsville.prompts import load_itinerary_prompt
from agentsville.tools import ToolContext, ToolRegistry, build_default_registry

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "agent_runs.jsonl"
FORMAT_HINT = (
    'Reply with ONE JSON object: {"thought": "<reasoning>", '
    '"action": {"tool_name": "<tool>", "arguments": {...}}}'
)

# ---------------------------------------------------------------------------
# Step 3 – reply parser
# ---------------------------------------------------------------------------


# Phase 6 – Step 3: a reply that couldn't be turned into a tool call (message is for the LLM)
class ReplyParseError(ValueError):
    pass


# Phase 6 – Step 3: the parts of one assistant reply
class ParsedReply(BaseModel):
    thought: str
    tool_name: str
    arguments: dict


# Phase 6 – Step 3: read the {"thought", "action": {"tool_name", "arguments"}} JSON reply.
# Replies are requested in JSON mode (valid JSON guaranteed); parsing still tolerates code
# fences or text around the object, and reports problems in words the LLM can act on.
def parse_agent_reply(text: str) -> ParsedReply:
    brace = text.find("{")
    if brace == -1:
        raise ReplyParseError(f"No JSON object found. {FORMAT_HINT}")
    try:
        reply, _ = json.JSONDecoder().raw_decode(text[brace:])
    except json.JSONDecodeError as exc:
        raise ReplyParseError(
            f"Reply is not valid JSON ({exc.msg} at position {exc.pos}). {FORMAT_HINT}"
        ) from exc
    if not isinstance(reply, dict):
        raise ReplyParseError(f"Reply must be a JSON object. {FORMAT_HINT}")

    thought = reply.get("thought", "")
    action = reply.get("action")
    if not isinstance(action, dict):
        raise ReplyParseError(f'Reply is missing an "action" object. {FORMAT_HINT}')
    tool_name = action.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ReplyParseError(f'"action" is missing a "tool_name" string. {FORMAT_HINT}')
    arguments = action.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ReplyParseError(f'"arguments" must be a JSON object. {FORMAT_HINT}')
    return ParsedReply(
        thought=str(thought).strip(), tool_name=tool_name.strip(), arguments=arguments
    )


# ---------------------------------------------------------------------------
# Step 4 – run records (the trace)
# ---------------------------------------------------------------------------

StopReason = Literal["final_answer", "max_steps", "llm_error"]


# Phase 6 – Step 4: one THOUGHT → ACTION → OBSERVATION cycle, with the agent call's metrics
class AgentStep(BaseModel):
    step: int
    raw_reply: str
    thought: str = ""
    tool_name: str | None = None  # None when the reply couldn't be parsed
    arguments: dict | None = None
    observation: str
    is_error: bool = False
    latency_ms: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None


# Phase 6 – Step 4: one complete agent run – inputs, every step, outcome, evals and costs
class AgentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str
    prompt_version: str
    vacation_info: VacationInfo
    system_prompt: str
    user_prompt: str
    steps: list[AgentStep] = []
    stop_reason: StopReason | None = None
    error: str | None = None
    travel_plan: TravelPlan | None = None
    final_eval_report: EvalReport | None = None
    final_rejections: int = 0
    judge_calls: int = 0  # LLM-judge calls made by evals (run_evals_tool + final evals)
    judge_cost_usd: float = 0.0

    @computed_field
    @property
    def step_count(self) -> int:
        return len(self.steps)

    @computed_field
    @property
    def total_latency_ms(self) -> float:
        return sum(s.latency_ms for s in self.steps)

    @computed_field
    @property
    def total_prompt_tokens(self) -> int:
        return sum(s.prompt_tokens or 0 for s in self.steps)

    @computed_field
    @property
    def total_completion_tokens(self) -> int:
        return sum(s.completion_tokens or 0 for s in self.steps)

    @computed_field
    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd or 0.0 for s in self.steps) + self.judge_cost_usd


# ---------------------------------------------------------------------------
# Step 6 – run log
# ---------------------------------------------------------------------------


# Phase 6 – Step 6: append one run as one JSON line (JSON Lines: append-only, easy to load)
def log_run(run: AgentRun, path: Path = DEFAULT_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(run.model_dump_json() + "\n")


# ---------------------------------------------------------------------------
# Step 5 – agent loop
# ---------------------------------------------------------------------------


# Phase 6 – Step 5: wraps the LLM client given to evals so judge calls are counted in the run
class _MeteredLLM:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self.calls = 0
        self.cost_usd = 0.0

    def chat(self, *args, **kwargs) -> LLMResponse:
        reply = self._llm.chat(*args, **kwargs)
        self.calls += 1
        self.cost_usd += reply.cost_usd or 0.0
        return reply


# Phase 6 – Step 5: the ReAct itinerary agent
class ItineraryAgent:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry | None = None,
        model: str | None = None,
        prompt_version: str = "v1",
        max_steps: int = 20,
        max_final_rejections: int = 2,
        include_llm_evals: bool = True,
        log_path: Path | None = DEFAULT_LOG_PATH,
        on_step: Callable[[AgentStep], None] | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry or build_default_registry()
        self.model = model or llm.default_model
        self.prompt_version = prompt_version.lower()
        self.max_steps = max_steps
        self.max_final_rejections = max_final_rejections
        self.include_llm_evals = include_llm_evals
        self.log_path = log_path
        self.on_step = on_step

    # Phase 6 – Step 5: run the full ReAct loop for one trip request
    def run(self, vacation_info: VacationInfo) -> AgentRun:
        system_prompt = load_itinerary_prompt(self.prompt_version, self.registry.catalog())
        user_prompt = "Plan this trip:\n" + vacation_info.model_dump_json(indent=2)
        run = AgentRun(
            model=self.model,
            prompt_version=self.prompt_version,
            vacation_info=vacation_info,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        eval_llm = _MeteredLLM(self.llm)
        context = ToolContext(
            vacation_info=vacation_info, llm=eval_llm, include_llm_evals=self.include_llm_evals
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        for number in range(1, self.max_steps + 1):
            try:
                reply = self.llm.chat(messages, model=self.model, json_mode=True)
            except LLMError as exc:
                run.stop_reason, run.error = "llm_error", str(exc)
                break

            step, accepted_plan = self._handle_reply(number, reply, run, context)
            run.steps.append(step)
            if self.on_step:
                self.on_step(step)

            if accepted_plan is not None:
                run.travel_plan = accepted_plan
                run.stop_reason = "final_answer"
                run.final_eval_report = run_all_evals(
                    vacation_info,
                    accepted_plan,
                    llm=eval_llm if self.include_llm_evals else None,
                    include_llm=self.include_llm_evals,
                )
                break

            messages.append({"role": "assistant", "content": reply.text})
            messages.append({"role": "user", "content": f"OBSERVATION: {step.observation}"})
        else:
            run.stop_reason = "max_steps"

        run.judge_calls, run.judge_cost_usd = eval_llm.calls, eval_llm.cost_usd
        if self.log_path is not None:
            log_run(run, self.log_path)
        return run

    # Phase 6 – Step 5: parse one reply, run its tool, apply the final-answer guardrail
    def _handle_reply(
        self, number: int, reply: LLMResponse, run: AgentRun, context: ToolContext
    ) -> tuple[AgentStep, TravelPlan | None]:
        step = AgentStep(
            step=number,
            raw_reply=reply.text,
            observation="",
            latency_ms=reply.latency_ms,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            cost_usd=reply.cost_usd,
        )
        try:
            parsed = parse_agent_reply(reply.text)
        except ReplyParseError as exc:
            step.observation, step.is_error = f"ERROR: {exc}", True
            return step, None

        step.thought, step.tool_name, step.arguments = (
            parsed.thought,
            parsed.tool_name,
            parsed.arguments,
        )
        result = self.registry.execute(parsed.tool_name, parsed.arguments, context)
        step.observation, step.is_error = result.observation, result.is_error
        if not result.is_final:
            return step, None

        # Guardrail: free deterministic evals must pass before a final answer is accepted.
        guard = run_all_evals(run.vacation_info, result.travel_plan, include_llm=False)
        if not guard.passed and run.final_rejections < self.max_final_rejections:
            run.final_rejections += 1
            step.is_error = True
            step.observation = (
                "Final answer REJECTED. Fix these problems, then call final_answer_tool again.\n"
                + guard.summary()
            )
            return step, None
        return step, result.travel_plan
