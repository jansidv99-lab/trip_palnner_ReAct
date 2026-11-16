# Phase 12 – Step 3: unit tests for running the agent from the UI (fake LLM, no network).
from pathlib import Path

from agentsville.agent import DEFAULT_LOG_PATH, AgentStep
from agentsville.llm import LLMError
from agentsville.models import OpenAIModel
from agentsville.samples import sample_vacation_info
from agentsville.ui.form import RunOptions
from agentsville.ui.run import (
    OBSERVATION_PREVIEW_CHARS,
    AgentBackend,
    explain_failure,
    outcome,
    run_agent,
    run_log_path,
    run_stats,
    step_markdown,
)
from tests.test_agent import HAPPY_SCRIPT, ScriptedLLM, action, bad_total_plan


def _backend(llm, log_path=None) -> AgentBackend:
    return AgentBackend(llm=llm, prompt_version="v1", log_path=log_path)


def test_run_agent_passes_options_and_reports_every_step(tmp_path):
    llm = ScriptedLLM(*HAPPY_SCRIPT)
    seen: list[AgentStep] = []
    options = RunOptions(model=OpenAIModel.GPT_41_MINI, include_llm_evals=False, max_steps=10)
    backend = _backend(llm, tmp_path / "r.jsonl")
    run = run_agent(sample_vacation_info(), options, backend, seen.append)
    assert run.stop_reason == "final_answer"
    assert run.model == "gpt-4.1-mini"
    assert [s.step for s in seen] == [1, 2, 3, 4]
    assert llm.judge_calls == 0  # weather judge off
    assert (tmp_path / "r.jsonl").exists()


def test_run_agent_respects_max_steps():
    run = run_agent(sample_vacation_info(), RunOptions(max_steps=3), _backend(ScriptedLLM()))
    assert run.stop_reason == "max_steps" and run.step_count == 3


def test_outcome_success():
    run = run_agent(sample_vacation_info(), RunOptions(), _backend(ScriptedLLM(*HAPPY_SCRIPT)))
    level, message = outcome(run)
    assert level == "success" and "passed every plan check" in message


def test_outcome_warning_when_plan_fails_after_guardrail():
    bad = action("final_answer_tool", travel_plan=bad_total_plan())
    run = run_agent(sample_vacation_info(), RunOptions(), _backend(ScriptedLLM(bad, bad, bad)))
    level, message = outcome(run)
    assert level == "warning"
    assert "'total cost calculation' check, even after it was sent back" in message


def test_outcome_error_for_llm_error():
    llm = ScriptedLLM(error=LLMError("connection refused"))
    run = run_agent(sample_vacation_info(), RunOptions(), _backend(llm))
    level, message = outcome(run)
    assert level == "error"
    assert "the call to the language model failed (connection refused)" in message


def test_explain_failure_labels():
    assert explain_failure("llm_error:timeout") == "the language model took too long to answer"
    assert explain_failure("eval_loop:total_cost_accurate") == (
        "the agent kept failing the 'total cost calculation' check while revising the plan"
    )
    assert "calculator_tool with invalid arguments" in explain_failure(
        "invalid_args_loop:calculator_tool"
    )
    assert explain_failure("final_failed:some_new_eval") == (
        "the final plan failed the 'some new eval' check"
    )
    assert explain_failure("max_steps:other") == "the agent ran out of steps before finishing"
    assert explain_failure("unknown:x") == "unknown:x"


def test_step_markdown_abbreviates_long_observations():
    step = AgentStep(
        step=2, raw_reply="", thought="Check the weather.", tool_name="get_weather_for_date_tool",
        observation="x" * 1000,
    )
    text = step_markdown(step)
    assert "**Step 2** ▶ `get_weather_for_date_tool`" in text
    assert "> Check the weather." in text
    assert "x" * OBSERVATION_PREVIEW_CHARS + "…" in text
    assert "x" * (OBSERVATION_PREVIEW_CHARS + 1) not in text


def test_step_markdown_marks_errors_and_unparseable_replies():
    step = AgentStep(step=1, raw_reply="?", observation="ERROR: bad", is_error=True)
    assert "⚠️ `unparseable reply`" in step_markdown(step)


def test_run_stats():
    run = run_agent(sample_vacation_info(), RunOptions(), _backend(ScriptedLLM(*HAPPY_SCRIPT)))
    assert run_stats(run).startswith("4 steps · ")


def test_run_log_path():
    assert run_log_path({}) == DEFAULT_LOG_PATH
    assert run_log_path({"AGENTSVILLE_RUN_LOG": "off"}) is None
    assert run_log_path({"AGENTSVILLE_RUN_LOG": ""}) is None
    assert run_log_path({"AGENTSVILLE_RUN_LOG": " /tmp/x.jsonl "}) == Path("/tmp/x.jsonl")
