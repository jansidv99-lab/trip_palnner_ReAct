# Phase 5 – Step 1: tools the ReAct agent can call, and a registry that runs them safely.
"""Agent tools.

The LLM asks for a tool by name with JSON arguments. `ToolRegistry.execute()` validates the
arguments, runs the tool and returns a ToolResult whose `observation` string goes back to the LLM.
It never raises: unknown tools, bad arguments and tool failures become "ERROR: ..." observations.
"""

import ast
import datetime
import json
import operator
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from agentsville import data_api
from agentsville.evals import run_all_evals
from agentsville.llm import LLMClient
from agentsville.models import (
    TRIP_WINDOW_END,
    TRIP_WINDOW_START,
    Activity,
    Interest,
    TravelPlan,
    VacationInfo,
)

DATA_WINDOW = f"Data exists for {TRIP_WINDOW_START} to {TRIP_WINDOW_END} (AgentsVille only)."

# ---------------------------------------------------------------------------
# Step 1 – contract and registry
# ---------------------------------------------------------------------------


# Phase 5 – Step 1: run-specific objects some tools need (injected, not global)
@dataclass
class ToolContext:
    vacation_info: VacationInfo
    llm: LLMClient | None = None  # used by run_evals_tool's weather judge
    include_llm_evals: bool = True


# Phase 5 – Step 1: what the agent loop gets back from every tool call
class ToolResult(BaseModel):
    observation: str
    is_error: bool = False
    is_final: bool = False  # True only for a successful final_answer_tool
    travel_plan: TravelPlan | None = None


# Phase 5 – Step 1: one capability – name and description for the LLM, validated arguments
@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[BaseModel, ToolContext], ToolResult]


def _error(message: str) -> ToolResult:
    return ToolResult(observation=f"ERROR: {message}", is_error=True)


def _format_validation_error(exc: ValidationError, limit: int = 5) -> str:
    parts = []
    for err in exc.errors()[:limit]:
        location = ".".join(str(p) for p in err["loc"]) or "arguments"
        parts.append(f"{location} – {err['msg']}")
    more = f" (+{len(exc.errors()) - limit} more)" if len(exc.errors()) > limit else ""
    return "; ".join(parts) + more


# Phase 5 – Step 1: human-readable type label for the tool catalog
def _type_label(annotation: typing.Any) -> str:
    origin = typing.get_origin(annotation)
    if origin is list:
        (inner,) = typing.get_args(annotation)
        return f"list of {_type_label(inner)}"
    if origin in (typing.Union, types.UnionType):
        return " or ".join(_type_label(a) for a in typing.get_args(annotation))
    if annotation is datetime.date:
        return "string YYYY-MM-DD"
    if annotation is str:
        return "string"
    if annotation is Interest:
        return "interest (" + ", ".join(i.value for i in Interest) + ")"
    if annotation is TravelPlan:
        return "TravelPlan object (schema below)"
    return getattr(annotation, "__name__", str(annotation))


# Phase 5 – Step 1: name → Tool; executes LLM-requested calls without ever raising
class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    # Phase 5 – Step 1: validate arguments, run the tool, turn every failure into an observation
    def execute(self, tool_name: str, arguments: dict, context: ToolContext) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            return _error(
                f"unknown tool '{tool_name}'. Available tools: {', '.join(self.names)}"
            )
        try:
            args = tool.args_model.model_validate(arguments or {})
        except ValidationError as exc:
            return _error(f"invalid arguments for {tool_name}: {_format_validation_error(exc)}")
        try:
            return tool.run(args, context)
        except Exception as exc:  # noqa: BLE001 – a tool bug must never crash the agent loop
            return _error(f"{tool_name} failed: {type(exc).__name__}: {exc}")

    # Phase 5 – Step 1: tool list for the system prompt (Phase 6)
    def catalog(self) -> str:
        blocks = []
        for tool in self._tools.values():
            params = ", ".join(
                f"{name}: {_type_label(field.annotation)}"
                for name, field in tool.args_model.model_fields.items()
            )
            blocks.append(f"- {tool.name}({params})\n  {tool.description}")
        return "\n".join(blocks)


def _activities_json(activities: list[Activity]) -> str:
    return json.dumps([a.model_dump(mode="json") for a in activities], ensure_ascii=False)


# ---------------------------------------------------------------------------
# Step 2 – safe calculator
# ---------------------------------------------------------------------------

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
MAX_EXPRESSION_LENGTH = 200
MAX_EXPONENT = 100


# Phase 5 – Step 2: evaluate arithmetic only – no names, calls or attributes (never eval())
def safe_eval(expression: str) -> float:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expression longer than {MAX_EXPRESSION_LENGTH} characters")

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int | float)
            and not isinstance(node.value, bool)
        ):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError(f"exponent larger than {MAX_EXPONENT}")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](visit(node.operand))
        raise ValueError(f"unsupported element: {type(node).__name__}")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"not a valid arithmetic expression: {exc.msg}") from exc
    return visit(tree)


class CalculatorArgs(BaseModel):
    expression: str = Field(description="arithmetic expression, e.g. '20 + 20 + 15'")


# Phase 5 – Step 2: calculator_tool – exact arithmetic for cost totals
def calculator_tool(args: CalculatorArgs, context: ToolContext) -> ToolResult:
    try:
        value = safe_eval(args.expression)
    except ZeroDivisionError:
        return _error("division by zero")
    except ValueError as exc:
        return _error(str(exc))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return ToolResult(observation=str(value))


# ---------------------------------------------------------------------------
# Step 3 – data tools (through data_api only)
# ---------------------------------------------------------------------------


class DateArgs(BaseModel):
    date: datetime.date


class ActivityIdArgs(BaseModel):
    activity_id: str


class FilterArgs(BaseModel):
    date: datetime.date
    interests: list[Interest] = Field(min_length=1)


# Phase 5 – Step 3: get_weather_for_date_tool – forecast JSON plus an inclement flag
def get_weather_for_date_tool(args: DateArgs, context: ToolContext) -> ToolResult:
    forecast = data_api.get_weather(args.date)
    if forecast is None:
        return ToolResult(observation=f"No weather data for {args.date}. {DATA_WINDOW}")
    data = forecast.model_dump(mode="json") | {"inclement": data_api.is_inclement(forecast)}
    return ToolResult(observation=json.dumps(data, ensure_ascii=False))


# Phase 5 – Step 3: get_activities_by_date_tool – that day's activities as JSON
def get_activities_by_date_tool(args: DateArgs, context: ToolContext) -> ToolResult:
    activities = data_api.get_activities(args.date)
    if not activities:
        return ToolResult(observation=f"No activities on {args.date}. {DATA_WINDOW}")
    return ToolResult(observation=_activities_json(activities))


# Phase 5 – Step 3: get_activity_by_id_tool – exact details to copy into the plan
def get_activity_by_id_tool(args: ActivityIdArgs, context: ToolContext) -> ToolResult:
    activity = data_api.get_activity_by_id(args.activity_id)
    if activity is None:
        return ToolResult(observation=f"No activity with id '{args.activity_id}'.")
    return ToolResult(observation=json.dumps(activity.model_dump(mode="json"), ensure_ascii=False))


# Phase 5 – Step 3: filter_activities_by_interest_tool – activities matching ANY interest
def filter_activities_by_interest_tool(args: FilterArgs, context: ToolContext) -> ToolResult:
    wanted = set(args.interests)
    matches = [a for a in data_api.get_activities(args.date) if wanted & set(a.related_interests)]
    if not matches:
        names = ", ".join(i.value for i in args.interests)
        return ToolResult(observation=f"No activities on {args.date} match: {names}.")
    return ToolResult(observation=_activities_json(matches))


# ---------------------------------------------------------------------------
# Step 4 – self-check and finish
# ---------------------------------------------------------------------------


class TravelPlanArgs(BaseModel):
    travel_plan: TravelPlan


# Phase 5 – Step 4: run_evals_tool – evaluate a draft plan against the traveler's request
def run_evals_tool(args: TravelPlanArgs, context: ToolContext) -> ToolResult:
    use_llm = context.include_llm_evals and context.llm is not None
    report = run_all_evals(
        context.vacation_info, args.travel_plan, llm=context.llm, include_llm=use_llm
    )
    note = ""
    if context.include_llm_evals and context.llm is None:
        note = "\n(weather_suitability skipped: no LLM client available)"
    return ToolResult(observation=report.summary() + note)


# Phase 5 – Step 4: final_answer_tool – terminal tool; a valid plan ends the agent loop
def final_answer_tool(args: TravelPlanArgs, context: ToolContext) -> ToolResult:
    return ToolResult(
        observation="Final answer accepted.", is_final=True, travel_plan=args.travel_plan
    )


# ---------------------------------------------------------------------------
# Step 5 – default registry
# ---------------------------------------------------------------------------


# Phase 5 – Step 5: all seven tools, in the order they appear in the prompt catalog
def build_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                "calculator_tool",
                "Evaluate an arithmetic expression exactly (+ - * / // % ** and parentheses). "
                "Use it for every cost total.",
                CalculatorArgs,
                calculator_tool,
            ),
            Tool(
                "get_weather_for_date_tool",
                "Get the weather forecast for one date: temperature, condition, a description, "
                "and whether it is inclement (rain or thunderstorm).",
                DateArgs,
                get_weather_for_date_tool,
            ),
            Tool(
                "get_activities_by_date_tool",
                "List all activities on one date with every field (id, times, location, "
                "description, price, interests), sorted by start time.",
                DateArgs,
                get_activities_by_date_tool,
            ),
            Tool(
                "get_activity_by_id_tool",
                "Get the exact details of one activity by its activity_id. Copy these fields "
                "unchanged into the travel plan.",
                ActivityIdArgs,
                get_activity_by_id_tool,
            ),
            Tool(
                "filter_activities_by_interest_tool",
                "List activities on one date that match ANY of the given interests.",
                FilterArgs,
                filter_activities_by_interest_tool,
            ),
            Tool(
                "run_evals_tool",
                "Check a draft travel plan against the traveler's request (dates, costs, budget, "
                "real activities, weather suitability). Fix every ✗ before the final answer.",
                TravelPlanArgs,
                run_evals_tool,
            ),
            Tool(
                "final_answer_tool",
                "Submit the finished travel plan. This ends the conversation.",
                TravelPlanArgs,
                final_answer_tool,
            ),
        ]
    )
