# Phase 5 – Tools

> Status: **APPROVED** – all recommendations accepted (Q1 JSON, Q2 keep filter tool, Q3 judge on by default, Q4 no city arg, Q5 one commit)
> Branch: `feature/phase-5-tools`
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md)
> Depends on: Phase 2 (models) ✅, Phase 3 (`data_api`) ✅, Phase 4 (`run_all_evals`, `summary()`) ✅

## Purpose

Give the agent **precise, safe capabilities** instead of letting it guess (`goal.md` §5).
In the ReAct loop (Phase 6) the LLM writes:

```
THOUGHT: I need the weather on the 12th before choosing outdoor activities.
ACTION: {"tool_name": "get_weather_for_date_tool", "arguments": {"date": "2025-06-12"}}
```

Our code looks the tool up, **validates the arguments**, runs it, and returns a **string** that
goes back to the LLM as the `OBSERVATION`. This phase builds everything after the `ACTION:` is
parsed: the tools, their argument schemas, and a registry that executes them safely. Parsing the
LLM's text and the loop itself are Phase 6.

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Tool contract** | Every tool has a *name*, a *description* (for the LLM), an *argument schema*, and returns a *string*. The LLM only ever sees names, descriptions and observations. |
| **Argument model** | A small Pydantic model per tool (for example `DateArgs(date: date)`). The LLM's JSON arguments are validated before the tool runs. A bad date becomes a clear message, not a crash. |
| **JSON Schema** | Pydantic can describe a model as JSON Schema (`model_json_schema()`). We use it to tell the LLM exactly what arguments each tool expects. |
| **Registry** | A dict `name → Tool`. Adding a tool means one registry entry; the agent loop never changes. |
| **Errors as observations** | Tools **never raise** into the loop. Unknown tool, invalid arguments or an internal error become an `ERROR: …` observation the LLM can read and correct. |
| **Terminal tool** | `final_answer_tool` is special: a successful call tells the loop to **stop** and carries the validated `TravelPlan`. |
| **Safe evaluation (AST)** | Python's `eval()` would run *any* code the LLM writes. The calculator instead parses the expression into a syntax tree (`ast`) and allows only numbers and arithmetic operators. |
| **Context (dependency injection)** | Some tools need run-specific objects (the traveler's `VacationInfo` for evals, the `LLMClient` for the judge). They get them from a `ToolContext` passed at execution time, not from globals. |

---

## Design

### Core types (`agentsville/tools.py`)

```python
class ToolContext(BaseModel):          # per agent run
    vacation_info: VacationInfo
    llm: LLMClient | None = None       # needed by run_evals_tool's weather judge
    include_llm_evals: bool = True

class ToolResult(BaseModel):           # what the loop gets back
    observation: str                   # always set: sent to the LLM
    is_error: bool = False
    is_final: bool = False             # True only for a successful final_answer_tool
    travel_plan: TravelPlan | None = None

class Tool:                            # one capability
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[BaseModel, ToolContext], ToolResult]

class ToolRegistry:
    def execute(self, tool_name: str, arguments: dict, context: ToolContext) -> ToolResult
    def catalog(self) -> str           # tool list for the system prompt
```

`execute()` never raises:
| Situation | Observation |
|---|---|
| unknown tool name | `ERROR: unknown tool 'x'. Available tools: …` |
| arguments fail validation | `ERROR: invalid arguments for get_weather_for_date_tool: date – Input should be a valid date…` |
| tool raises unexpectedly | `ERROR: get_weather_for_date_tool failed: <message>` |

### Observation format
- **Data** (weather, activities) is returned as **compact JSON** with exactly the model fields. The agent must copy activities and weather into the `TravelPlan` *verbatim* (eval E4 checks every field), and JSON is far less error-prone to copy than prose.
- **Messages** (not found, errors, eval summaries, calculator results) are plain text.

### The tools

| Tool | Arguments | Observation | Notes |
|---|---|---|---|
| `calculator_tool` | `expression: str` | `108` | safe AST evaluation: `+ - * / // % **`, parentheses, unary minus; max 200 characters, exponent ≤ 100; rejects names, calls, attributes |
| `get_weather_for_date_tool` | `date: date` | forecast JSON (incl. `description`) + `"inclement": true/false` | unknown date → `No weather data for 2025-06-20. Data exists for 2025-06-10 to 2025-06-15.` |
| `get_activities_by_date_tool` | `date: date` | JSON list of that day's activities (all fields), sorted by time | none → `No activities on …` + the data window |
| `get_activity_by_id_tool` | `activity_id: str` | one activity's JSON | unknown → `No activity with id …` |
| `filter_activities_by_interest_tool` | `date: date`, `interests: list[Interest]` | JSON list of activities matching **any** of the interests | invalid interest → validation error listing the valid ones |
| `run_evals_tool` | `travel_plan: TravelPlan` | `EvalReport.summary()` | uses `context.vacation_info`, and runs the weather judge if `context.include_llm_evals` and `context.llm` are set |
| `final_answer_tool` | `travel_plan: TravelPlan` | `Final answer accepted.` → `is_final=True`, `travel_plan` set | schema validation only. Whether the agent must run evals first is a prompt rule (Phase 6) |

Weather, activities, lookup and filter go through **`data_api`** only (`CLAUDE.md` rule).
There's no `city` argument: AgentsVille is the only city, and dropping it removes a way for the LLM to go wrong.

### Catalog for the prompt
`registry.catalog()` renders one block per tool, for example:

```
- get_weather_for_date_tool(date: string YYYY-MM-DD)
  Get the weather forecast for one date, including a description and whether it is inclement.
```
For `travel_plan` arguments the catalog says `travel_plan: TravelPlan object (schema below)`. The full `TravelPlan` JSON Schema is inserted once by the Phase 6 prompt, not repeated per tool.

---

## Steps

### Step 1 – Tool contract and registry
**Purpose:** a single, safe way to run any tool from LLM-provided JSON.
**Output:** `agentsville/tools.py` (`ToolContext`, `ToolResult`, `Tool`, `ToolRegistry` with `execute()` and `catalog()`).
**Depends on:** Phase 2 models.

### Step 2 – Safe calculator
**Purpose:** exact arithmetic for cost totals without `eval()`.
**Output:** `calculator_tool` + `safe_eval(expression)` helper in `tools.py`.
**Depends on:** Step 1.

### Step 3 – Data tools
**Purpose:** let the agent look up weather and activities.
**Output:** `get_weather_for_date_tool`, `get_activities_by_date_tool`, `get_activity_by_id_tool`, `filter_activities_by_interest_tool`.
**Depends on:** Step 1, `data_api`.

### Step 4 – `run_evals_tool` and `final_answer_tool`
**Purpose:** self-checking and a clean way to finish.
**Output:** both tools in `tools.py`.
**Depends on:** Step 1, `evals.run_all_evals`.

### Step 5 – Default registry
**Purpose:** one function that assembles all seven tools; Phase 6 calls it.
**Output:** `build_default_registry()` in `tools.py`.
**Depends on:** Steps 2–4.

### Step 6 – Tests (Layer A)
**Purpose:** every tool's happy path and error path, and the registry's never-raise guarantee.
**Output:** `tests/test_tools.py`.
**Depends on:** Steps 1–5.

| Area | Cases |
|---|---|
| Registry | unknown tool → error listing tools; missing/invalid args → error naming the field; a tool that raises → error observation, no exception; `catalog()` lists all 7 names |
| Calculator | `20+20+15` → `55`; `(15*3)/2` → `22.5`; `-5+2` → `-3`; divide by zero → error; `__import__('os')`, `open('x')`, `a+1`, `2**1000`, a 300-character input → rejected |
| Weather | 06-12 → JSON with `"thunderstorm"`, description and `"inclement": true`; 06-20 → "No weather data" with the window; `"12/06/2025"` → invalid-argument error |
| Activities | 06-11 → 4 activities in time order, JSON parses back into `Activity`; 06-20 → "No activities" |
| By ID | known → JSON that parses into the exact `Activity`; unknown → "No activity" |
| Filter | 06-12 + `["technology"]` → only `event-2025-06-12-3`; `["skiing"]` → invalid-argument error |
| `run_evals_tool` | golden `sample_plan.json` → summary starting `EVALS PASSED` (fake LLM); broken total → `EVALS FAILED` naming `total_cost_accurate`; malformed plan → invalid-argument error |
| `final_answer_tool` | golden plan → `is_final=True` with `travel_plan` set; malformed plan → `is_error=True`, `is_final=False` |

### Step 7 – Demo script
**Purpose:** call tools exactly the way the agent will, and see the observations (learning).
**Output:** `scripts/try_tools.py`: runs a few example ACTION JSONs through the registry and prints each observation (and `--catalog` prints the tool catalog).
**Depends on:** Step 5.

### Step 8 – Documentation
**Purpose:** keep `CLAUDE.md` accurate.
**Output:** `CLAUDE.md`: the `tools.py` contract (string observations, never raise, `ToolContext`, the terminal tool) and how to add a tool.
**Depends on:** Steps 1–7.

---

## Verification (definition of done)

```bash
ruff check .
pytest                          # incl. tests/test_tools.py, no network
python scripts/try_tools.py     # prints observations for sample actions
```
Plus green `CI / lint` + `CI / test` on the PR.

---

## Decisions (all recommendations accepted)

| # | Question | My recommendation |
|---|---|---|
| Q1 | Data observations as compact **JSON** or readable prose? | **JSON.** The agent must copy activities and weather into the plan exactly (eval E4). |
| Q2 | Keep the suggested `filter_activities_by_interest_tool`? | **Yes.** It's cheap, and it shortens observations when travelers have narrow interests. |
| Q3 | Should `run_evals_tool` include the LLM weather judge (about 1 cent per call)? | **Yes, by default** (`ToolContext.include_llm_evals=True`). Self-checking without the weather check would miss the riskiest failure. It can be turned off for cheap runs. |
| Q4 | Drop the `city` argument from the data tools? | **Yes.** Only AgentsVille exists, and fewer arguments mean fewer LLM mistakes. |
| Q5 | One commit for the phase? | Yes |
| Q6 | May I create branch `feature/phase-5-tools` from `main`? | Yes |
