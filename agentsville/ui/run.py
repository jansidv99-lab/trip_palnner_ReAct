# Phase 12 – Step 3: build the LLM + agent for the UI, run it, and explain the outcome.
"""Everything the UI needs to run the agent, without any Streamlit code.

`AgentBackend` bundles what a run needs from the environment (LLM client, prompt version, run-log
path). The app builds it once per session with `make_backend()`; tests put a backend with a fake
LLM into session state instead, so no API key or network is needed.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agentsville.agent import DEFAULT_LOG_PATH, AgentRun, AgentStep, ItineraryAgent
from agentsville.config import get_settings
from agentsville.graders.completion import classify_failure
from agentsville.llm import LLMClient
from agentsville.models import VacationInfo
from agentsville.ui.form import RunOptions
from agentsville.ui.views import eval_label

# Phase 12 – Step 3: run-log location; "off" disables it (Cloud Run's disk is temporary, Phase 13)
RUN_LOG_ENV = "AGENTSVILLE_RUN_LOG"

SETUP_HELP = (
    "The app can't reach the language model because it isn't configured. Copy `.env.example` to "
    "`.env`, fill in `OPENAI_API_KEY` (and `OPENAI_BASE_URL` if you use a proxy), then restart "
    "`streamlit run app.py`."
)

OBSERVATION_PREVIEW_CHARS = 300

# Phase 12 – Step 3: what a run needs from the environment
@dataclass(frozen=True)
class AgentBackend:
    llm: LLMClient
    prompt_version: str
    log_path: Path | None


# Phase 12 – Step 3: run-log path from the environment (unset → logs/agent_runs.jsonl)
def run_log_path(environ: dict[str, str] | None = None) -> Path | None:
    value = (os.environ if environ is None else environ).get(RUN_LOG_ENV)
    if value is None:
        return DEFAULT_LOG_PATH
    if value.strip().casefold() in ("", "off", "none", "false", "0"):
        return None
    return Path(value.strip())


# Phase 12 – Step 3: the real backend from .env; raises ConfigError when the key is missing
def make_backend() -> AgentBackend:
    settings = get_settings()
    return AgentBackend(
        llm=LLMClient(settings),
        prompt_version=settings.prompt_version,
        log_path=run_log_path(),
    )


# Phase 12 – Step 3: one agent run with the user's options; on_step sees every step as it happens
def run_agent(
    info: VacationInfo,
    options: RunOptions,
    backend: AgentBackend,
    on_step: Callable[[AgentStep], None] | None = None,
) -> AgentRun:
    agent = ItineraryAgent(
        backend.llm,
        model=options.model.value,
        prompt_version=backend.prompt_version,
        max_steps=options.max_steps,
        include_llm_evals=options.include_llm_evals,
        log_path=backend.log_path,
        on_step=on_step,
    )
    return agent.run(info)


# Phase 12 – Step 3: one step as short markdown for the live progress box
def step_markdown(step: AgentStep) -> str:
    tool = step.tool_name or "unparseable reply"
    marker = "⚠️" if step.is_error else "▶"
    observation = step.observation.replace("\n", " ")
    if len(observation) > OBSERVATION_PREVIEW_CHARS:
        observation = observation[:OBSERVATION_PREVIEW_CHARS] + "…"
    lines = [f"**Step {step.step}** {marker} `{tool}`"]
    if step.thought:
        lines.append(f"> {step.thought}")
    lines.append(f"<small>{observation}</small>")
    return "\n\n".join(lines)


# Phase 12 – Step 3: a failure-taxonomy label (graders/completion.py) in plain words
def explain_failure(mode: str) -> str:
    category, _, detail = mode.partition(":")
    check = eval_label(detail)
    explanations = {
        "llm_error": (
            "the language model took too long to answer"
            if detail == "timeout"
            else "the call to the language model failed"
        ),
        "guardrail_exhausted": (
            f"the plan kept failing the '{check}' check, even after it was sent back for fixing"
        ),
        "final_failed": f"the final plan failed the '{check}' check",
        "invalid_args_loop": f"the agent kept calling {detail} with invalid arguments",
        "eval_loop": f"the agent kept failing the '{check}' check while revising the plan",
        "max_steps": "the agent ran out of steps before finishing",
    }
    return explanations.get(category, mode)


# Phase 12 – Step 6: success wording separates plan checks from the quality panel
# Phase 12 – Step 3: overall result as (level, message); level is "success" | "warning" | "error"
def outcome(run: AgentRun) -> tuple[str, str]:
    mode = classify_failure(run)
    if mode is None:
        return "success", (
            "Your itinerary is ready – it passed every plan check. See Quality checks for how "
            "carefully the agent worked."
        )
    reason = explain_failure(mode)
    if run.travel_plan is not None:
        return "warning", f"Here is the agent's plan, but {reason}. Review it before using it."
    detail = f" ({run.error})" if run.stop_reason == "llm_error" and run.error else ""
    return "error", f"No itinerary this time: {reason}{detail}. Please try again."


# Phase 12 – Step 3: one-line run stats for the progress box label
def run_stats(run: AgentRun) -> str:
    return (
        f"{run.step_count} steps · {run.total_latency_ms / 1000:.0f} s · "
        f"${run.total_cost_usd:.3f} · {run.model}"
    )
