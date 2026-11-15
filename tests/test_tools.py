# Phase 5 – Step 6: every tool's happy and error path, and the registry's never-raise guarantee.

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from agentsville.data_api import get_activity_by_id
from agentsville.llm import LLMResponse
from agentsville.models import Activity
from agentsville.samples import sample_vacation_info
from agentsville.tools import (
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    build_default_registry,
    safe_eval,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ALL_TOOLS = [
    "calculator_tool",
    "get_weather_for_date_tool",
    "get_activities_by_date_tool",
    "get_activity_by_id_tool",
    "filter_activities_by_interest_tool",
    "run_evals_tool",
    "final_answer_tool",
]


# Phase 5 – Step 6: judge stand-in that always says "suitable" and counts calls
class FakeLLM:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, model=None, temperature=0.0, json_mode=False):
        self.calls += 1
        return LLMResponse(text='{"suitable": true, "reason": "ok"}', model="fake", latency_ms=1)


@pytest.fixture
def registry() -> ToolRegistry:
    return build_default_registry()


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(vacation_info=sample_vacation_info(), include_llm_evals=False)


@pytest.fixture
def golden_plan_dict() -> dict:
    return json.loads((REPO_ROOT / "sample_plan.json").read_text(encoding="utf-8"))


def run(registry, context, name, **arguments) -> ToolResult:
    return registry.execute(name, arguments, context)


# --- registry ---------------------------------------------------------------------------


def test_registry_has_all_tools(registry):
    assert registry.names == ALL_TOOLS


def test_catalog_lists_every_tool_with_arguments(registry):
    catalog = registry.catalog()
    for name in ALL_TOOLS:
        assert f"- {name}(" in catalog
    assert "date: string YYYY-MM-DD" in catalog
    assert "travel_plan: TravelPlan object (schema below)" in catalog


def test_unknown_tool_is_error_listing_tools(registry, context):
    result = run(registry, context, "book_flight_tool")
    assert result.is_error and "unknown tool 'book_flight_tool'" in result.observation
    assert "calculator_tool" in result.observation


def test_missing_argument_is_error_naming_field(registry, context):
    result = run(registry, context, "get_weather_for_date_tool")
    assert result.is_error and "date – Field required" in result.observation


def test_none_arguments_treated_as_empty(registry, context):
    result = registry.execute("get_weather_for_date_tool", None, context)
    assert result.is_error and "Field required" in result.observation


def test_tool_exception_becomes_observation(context):
    class NoArgs(BaseModel):
        pass

    def broken(args, ctx):
        raise RuntimeError("boom")

    registry = ToolRegistry([Tool("broken_tool", "always fails", NoArgs, broken)])
    result = registry.execute("broken_tool", {}, context)
    assert result.is_error and result.observation == "ERROR: broken_tool failed: RuntimeError: boom"


# --- calculator -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression, expected",
    [("20+20+15", "55"), ("(15*3)/2", "22.5"), ("-5+2", "-3"), ("10/2", "5"), ("2**10", "1024")],
)
def test_calculator(registry, context, expression, expected):
    result = run(registry, context, "calculator_tool", expression=expression)
    assert not result.is_error and result.observation == expected


def test_calculator_division_by_zero(registry, context):
    result = run(registry, context, "calculator_tool", expression="1/0")
    assert result.is_error and "division by zero" in result.observation


@pytest.mark.parametrize(
    "expression",
    ["__import__('os')", "open('x')", "a+1", "(1).real", "2**1000", "1" * 300, "True+1", "1 +"],
)
def test_calculator_rejects_unsafe_or_invalid(registry, context, expression):
    result = run(registry, context, "calculator_tool", expression=expression)
    assert result.is_error


def test_safe_eval_never_runs_code():
    with pytest.raises(ValueError, match="unsupported element: Call"):
        safe_eval("print('hacked')")


# --- weather ---------------------------------------------------------------------------------


def test_weather_known_date(registry, context):
    result = run(registry, context, "get_weather_for_date_tool", date="2025-06-12")
    data = json.loads(result.observation)
    assert data["condition"] == "thunderstorm" and data["inclement"] is True
    assert "afternoon" in data["description"]


def test_weather_unknown_date(registry, context):
    result = run(registry, context, "get_weather_for_date_tool", date="2025-06-20")
    assert not result.is_error
    assert "No weather data for 2025-06-20" in result.observation
    assert "2025-06-10 to 2025-06-15" in result.observation


def test_weather_bad_date_format(registry, context):
    assert run(registry, context, "get_weather_for_date_tool", date="12/06/2025").is_error


# --- activities --------------------------------------------------------------------------------


def test_activities_by_date(registry, context):
    result = run(registry, context, "get_activities_by_date_tool", date="2025-06-11")
    activities = [Activity(**a) for a in json.loads(result.observation)]
    assert len(activities) == 4
    assert [a.start_time for a in activities] == sorted(a.start_time for a in activities)


def test_activities_unknown_date(registry, context):
    result = run(registry, context, "get_activities_by_date_tool", date="2025-06-20")
    assert "No activities on 2025-06-20" in result.observation


def test_activity_by_id_round_trips_exactly(registry, context):
    result = run(registry, context, "get_activity_by_id_tool", activity_id="event-2025-06-10-3")
    assert Activity(**json.loads(result.observation)) == get_activity_by_id("event-2025-06-10-3")


def test_activity_by_id_unknown(registry, context):
    result = run(registry, context, "get_activity_by_id_tool", activity_id="event-x")
    assert result.observation == "No activity with id 'event-x'."


def test_filter_by_interest(registry, context):
    result = run(
        registry, context, "filter_activities_by_interest_tool",
        date="2025-06-12", interests=["technology"],
    )
    assert [a["activity_id"] for a in json.loads(result.observation)] == ["event-2025-06-12-3"]


def test_filter_no_match(registry, context):
    result = run(
        registry, context, "filter_activities_by_interest_tool",
        date="2025-06-12", interests=["theatre"],
    )
    assert result.observation == "No activities on 2025-06-12 match: theatre."


@pytest.mark.parametrize("interests", [["skiing"], []])
def test_filter_invalid_interests(registry, context, interests):
    result = run(
        registry, context, "filter_activities_by_interest_tool",
        date="2025-06-12", interests=interests,
    )
    assert result.is_error


# --- run_evals_tool ------------------------------------------------------------------------------


def test_run_evals_golden_plan_with_judge(registry, golden_plan_dict):
    llm = FakeLLM()
    context = ToolContext(vacation_info=sample_vacation_info(), llm=llm)
    result = run(registry, context, "run_evals_tool", travel_plan=golden_plan_dict)
    assert result.observation.startswith("EVALS PASSED")
    assert "weather_suitability" in result.observation and llm.calls == 1


def test_run_evals_without_llm_notes_skipped_judge(registry, golden_plan_dict):
    context = ToolContext(vacation_info=sample_vacation_info(), llm=None, include_llm_evals=True)
    result = run(registry, context, "run_evals_tool", travel_plan=golden_plan_dict)
    assert "weather_suitability skipped" in result.observation


def test_run_evals_broken_plan(registry, context, golden_plan_dict):
    golden_plan_dict["total_cost"] = 120
    result = run(registry, context, "run_evals_tool", travel_plan=golden_plan_dict)
    assert result.observation.startswith("EVALS FAILED")
    assert "✗ total_cost_accurate" in result.observation


def test_run_evals_malformed_plan(registry, context):
    result = run(registry, context, "run_evals_tool", travel_plan={"city": "AgentsVille"})
    assert result.is_error and "invalid arguments for run_evals_tool" in result.observation


# --- final_answer_tool ------------------------------------------------------------


def test_final_answer_accepts_valid_plan(registry, context, golden_plan_dict):
    result = run(registry, context, "final_answer_tool", travel_plan=golden_plan_dict)
    assert result.is_final and not result.is_error
    assert result.travel_plan.total_cost == 108


def test_final_answer_rejects_malformed_plan(registry, context, golden_plan_dict):
    del golden_plan_dict["itinerary_days"]
    result = run(registry, context, "final_answer_tool", travel_plan=golden_plan_dict)
    assert result.is_error and not result.is_final and result.travel_plan is None
