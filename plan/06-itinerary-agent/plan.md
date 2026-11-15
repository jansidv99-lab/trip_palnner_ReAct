# Phase 6 – ReAct ItineraryAgent

> Status: **APPROVED** – all recommendations accepted (Q1 gpt-4o-mini, Q2 guardrail, Q3 replace PromptTrace, Q4 full JSONL runs, Q5 max_steps 20, Q6 one commit)
> Branch: `feature/phase-6-itinerary-agent`
>
> **Change during implementation (approved):** the first real run failed. gpt-4o-mini wrote the ~6,000-character
> final plan as free text with miscounted closing brackets, repeated the error 13 times and hit `max_steps`
> ($0.046, 5 min). Replies are now ONE JSON object `{"thought", "action": {"tool_name", "arguments"}}` requested in
> **JSON mode** (valid JSON guaranteed); the stop sequence was dropped (not needed); judge calls are metered into the
> run cost. After the fix: 10 steps, $0.012, all evals passed. The sections below describe the original design;
> `THOUGHT:/ACTION:` text and `stop=[...]` were replaced as described here.
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md)
> Depends on: Phase 0 (`LLMClient`, config) ✅, Phase 2 (models, samples) ✅, Phase 4 (evals) ✅, Phase 5 (tools, registry) ✅

## Purpose

Build the core of the project (`goal.md` §3): an agent that turns a `VacationInfo` into a
`TravelPlan` through the **THOUGHT → ACTION → OBSERVATION** cycle:

1. The LLM writes a `THOUGHT` (reasoning) and one `ACTION` (a tool call as JSON).
2. Our code parses the action, runs the tool through the Phase 5 registry, and sends the result back as an `OBSERVATION`.
3. This repeats until the LLM calls `final_answer_tool`, or a step limit is hit.

Every run is **recorded** (steps, tokens, cost, eval results) to a JSONL log from the very first
run. That history becomes the raw material for the offline eval suite (Phase 7) and drift
monitoring (Phase 10).

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **ReAct loop** | Reason + Act. The LLM never runs anything itself. It *asks* for a tool, our code runs it, and the result goes back into the conversation. The conversation grows by one assistant message and one observation per step. |
| **Text-based tool calling** | (Decision Q2 from the master plan.) The LLM writes `ACTION: {"tool_name": …, "arguments": {…}}` as plain text, and we parse it ourselves, instead of using the API's native function calling. You see every moving part. |
| **System prompt as a versioned file** | The instructions live in `prompts/itinerary/v1.md`, not in Python. `PROMPT_VERSION` picks the file, so prompt changes are reviewable diffs and Phase 7 can compare `v1` vs `v2`. |
| **Prompt template** | The file has placeholders (`{{TOOL_CATALOG}}`, `{{TRAVEL_PLAN_SCHEMA}}`) filled at runtime, so the prompt always matches the real tools and models. |
| **Stop sequence** | We pass `stop=["OBSERVATION:"]` to the API. If the LLM starts inventing its own observation, generation is cut off right there. It can't hallucinate tool results. |
| **Max steps** | A hard limit on loop iterations. Without it, a confused model could loop forever and burn money. |
| **Guardrail** | Code-level checks that don't rely on the LLM obeying the prompt. Here, a final answer that fails deterministic evals is sent back for fixing (Q2). |
| **Run trace** | A structured record of everything in one run: prompts, every step, tokens, latency, cost, and final eval results. It's essential for debugging and for monitoring quality over time. |
| **Fake LLM testing** | The loop is tested with a scripted fake that replays predefined replies. That's deterministic, free, and runs in CI. |

---

## Design

### Conversation shape

```
system:     prompts/itinerary/v1.md   (role, rules, tool catalog, TravelPlan schema, cost rule)
user:       the trip request (VacationInfo as JSON) + "Plan this trip."
assistant:  THOUGHT: … ACTION: {"tool_name": "get_weather_for_date_tool", "arguments": {"date": "2025-06-10"}}
user:       OBSERVATION: {"temperature": 31.0, …, "inclement": false}
assistant:  THOUGHT: … ACTION: {...}
user:       OBSERVATION: …
…
assistant:  THOUGHT: Evals passed. ACTION: {"tool_name": "final_answer_tool", "arguments": {"travel_plan": {…}}}
```

### Prompt `v1` content (`prompts/itinerary/v1.md`)
- **Role:** expert AgentsVille trip planner.
- **Format rules:** each reply is exactly one `THOUGHT:` and one `ACTION:` with a single JSON object; never write `OBSERVATION:` yourself; one tool call per reply.
- **Process:**
  1. Get the weather for **every** trip day.
  2. Get the activities for each day.
  3. Choose activities that fit the travelers' interests **and** the weather.
  4. Copy activity and weather fields **exactly** as returned.
  5. Compute `total_cost` with `calculator_tool`.
  6. Stay within budget.
  7. Call `run_evals_tool` on the draft and fix every ✗.
  8. Then call `final_answer_tool`.
- **Domain rules from the data review (Phase 3):**
  - Read the weather *description*, not just the condition (D2).
  - On inclement days, prefer indoor activities or ones with a stated rain fallback (D4).
  - An activity outside a traveler's interests is acceptable, with a reason, when weather rules out the matching ones (D9).
  - Activities must not overlap.
  - `total_cost` is the **plain sum of activity prices for the whole group, not × travelers** (master plan Q4).
  - `reasons_for_recommendation` name the traveler(s) and the interest or weather reason.
- **Placeholders:**
  - `{{TOOL_CATALOG}}` ← `registry.catalog()`
  - `{{TRAVEL_PLAN_SCHEMA}}` ← `TravelPlan.model_json_schema()`

  Filled with plain string replacement, because the JSON schema is full of `{}` and `str.format` would choke on it.

### Reply parser
`parse_agent_reply(text) -> ParsedReply(thought, tool_name, arguments)`
- `thought` = the text before `ACTION:`, with the `THOUGHT:` prefix removed (empty is allowed).
- Find the **first** `ACTION:`, then decode the first JSON object after it with `json.JSONDecoder.raw_decode` (it tolerates ```` ```json ```` fences and trailing text).
- It must be an object with a string `tool_name` and an object `arguments`.
- On any problem it raises `ReplyParseError` with a message written *for the LLM*, for example `"No ACTION found. Reply with THOUGHT: … then ACTION: {"tool_name": …, "arguments": {…}}"`. The loop sends that back as the observation, so the model can self-correct.

### Run records (replaces the unused `PromptTrace`)
`PromptTrace` was designed for a single LLM call; an agent run makes many. It's replaced (Q3) by:

```python
class AgentStep(BaseModel):          # one THOUGHT → ACTION → OBSERVATION cycle
    step: int
    raw_reply: str
    thought: str
    tool_name: str | None            # None when the reply couldn't be parsed
    arguments: dict | None
    observation: str
    is_error: bool
    latency_ms: float; prompt_tokens: int | None; completion_tokens: int | None; cost_usd: float | None

class AgentRun(BaseModel):           # one full agent run = the trace
    run_id: str; started_at: datetime; model: str; prompt_version: str
    vacation_info: VacationInfo
    system_prompt: str; user_prompt: str
    steps: list[AgentStep]
    stop_reason: Literal["final_answer", "max_steps", "llm_error"]
    travel_plan: TravelPlan | None
    final_eval_report: EvalReport | None   # evals on the accepted plan (incl. weather judge)
    # computed totals: step_count, total_latency_ms, total_prompt_tokens, total_completion_tokens, total_cost_usd
```

### Agent loop (`ItineraryAgent.run(vacation_info) -> AgentRun`)

```
messages = [system, user]
for step in 1..max_steps:
    reply = llm.chat(messages, stop=["OBSERVATION:"])       # LLMError → stop_reason="llm_error"
    try:   parsed = parse_agent_reply(reply.text)
    except ReplyParseError as e: observation = "ERROR: " + e
    else:  result = registry.execute(parsed.tool_name, parsed.arguments, context)
           if result.is_final:
               guard = deterministic evals on result.travel_plan            (Q2)
               if guard fails and rejections < 2: observation = "Final answer rejected:\n" + guard.summary(); continue
               accept → final_eval_report = run_all_evals(full, incl. judge) → stop_reason="final_answer"
           observation = result.observation
    record AgentStep; append assistant reply + "OBSERVATION: …" user message
else: stop_reason = "max_steps"
log the AgentRun to JSONL
```

| Setting | Default | Why |
|---|---|---|
| model | `settings.model` (`gpt-4o-mini`) | cheap; Phase 7 compares models |
| temperature | 0.0 | as repeatable as possible |
| max_steps | 20 | a 3-day trip needs roughly 3 weather + 3 activity + 1–2 eval + 1 final ≈ 9 steps; 20 leaves room for corrections |
| max_final_rejections | 2 | the guardrail can't cause an endless loop |
| `on_step` callback | `None` | lets the CLI (and later the UI) show steps live |

### Run log
- `log_run(run, path)` appends `run.model_dump_json()` as **one line** to `logs/agent_runs.jsonl` (JSON Lines: one run per line, append-only, easy to load later).
- `logs/` is added to `.gitignore`. `log_path=None` disables logging (tests use a temporary path).

### Small change to `llm.py`
Add an optional `stop: list[str] | None = None` to `LLMClient.chat()`, passed through to the API only when set.

---

## Steps

### Step 1 – Prompt file and loader
**Purpose:** versioned, reviewable agent instructions that always match the real tools and schema.
**Output:** `prompts/itinerary/v1.md`; `agentsville/prompts.py` (`load_itinerary_prompt(version, catalog)` fills the placeholders, and raises a clear error for an unknown version).
**Depends on:** Phase 5 (`registry.catalog()`), Phase 2 (`TravelPlan`).

### Step 2 – Stop sequences in `LLMClient`
**Purpose:** cut generation off before the model invents an observation.
**Output:** `agentsville/llm.py` (`stop` parameter) + a unit test.
**Depends on:** Phase 0.

### Step 3 – Reply parser
**Purpose:** turn the LLM's text into a tool call, or a helpful error the LLM can act on.
**Output:** `parse_agent_reply`, `ParsedReply`, `ReplyParseError` in `agentsville/agent.py`.
**Depends on:** nothing.

### Step 4 – Run records
**Purpose:** a structured trace of every run.
**Output:** `AgentStep`, `AgentRun` in `agentsville/agent.py`; `PromptTrace` removed from `models.py` (Q3).
**Depends on:** Phase 4 (`EvalReport`).

### Step 5 – Agent loop with guardrail
**Purpose:** the ReAct cycle itself.
**Output:** `ItineraryAgent` in `agentsville/agent.py`.
**Depends on:** Steps 1–4, Phase 5 registry, Phase 4 evals.

### Step 6 – Run logging
**Purpose:** start the Layer C history from the first run.
**Output:** `log_run()` in `agent.py`; `logs/` in `.gitignore`.
**Depends on:** Step 4.

### Step 7 – Tests
**Purpose:** prove the loop's behavior deterministically, without LLM cost.
**Output:** `tests/test_agent.py` (fake LLM) and `tests/test_agent_live.py` (`@pytest.mark.llm`).
**Depends on:** Steps 1–6.

| Area | Cases |
|---|---|
| Prompt | v1 loads, contains every tool name, the TravelPlan schema and the cost rule; unknown version → clear error; no unfilled `{{…}}` left |
| Parser | normal reply; JSON in ```` ```json ```` fences; multi-line JSON; text after the JSON ignored; missing ACTION / invalid JSON / missing `tool_name` / non-object `arguments` → `ReplyParseError` with guidance |
| Happy path | scripted: weather → activities → run_evals → final with the golden plan; result is `stop_reason="final_answer"`, `travel_plan` set, 4 steps, `final_eval_report.passed` |
| Recovery | a garbage reply then a valid one → step 1 has an error observation, the run still finishes |
| Unknown tool / bad args | error observation, loop continues |
| Guardrail | final with a wrong `total_cost` → rejected with an eval summary; a corrected final → accepted; 3 bad finals → accepted after 2 rejections with a failing report |
| Max steps | the fake never finishes → `stop_reason="max_steps"`, exactly `max_steps` steps, `travel_plan=None` |
| LLM error | the fake raises `LLMError` → `stop_reason="llm_error"` |
| Conversation | each observation is sent back as `"OBSERVATION: …"`; `stop=["OBSERVATION:"]` is passed on every call |
| Metrics & log | totals summed from steps; the JSONL file gets exactly one valid line per run that parses back into `AgentRun` |

Live test (`pytest -m llm`, ~1–3 cents): run the real agent on `sample_vacation_info()`; it must finish with `final_answer` within `max_steps`, and `city_and_dates` must pass. Full quality is *measured* in Phase 7, not asserted here (LLM output varies).

### Step 8 – CLI script
**Purpose:** watch the agent think, step by step (learning).
**Output:** `scripts/run_agent.py [--sample default|tight|rainy] [--model NAME] [--max-steps N] [--no-log]` prints each THOUGHT / ACTION / OBSERVATION live, then the final plan summary, eval report, steps, tokens and cost.
**Depends on:** Step 5.

### Step 9 – Documentation
**Purpose:** keep `CLAUDE.md` and README accurate.
**Output:** `CLAUDE.md` architecture (agent loop, parser, guardrail, prompt files, run log); a README "Run the agent" section.
**Depends on:** Steps 1–8.

---

## Verification (definition of done)

```bash
ruff check .
pytest                                    # incl. tests/test_agent.py (fake LLM, no network)
pytest -m llm                             # incl. one real agent run
python scripts/run_agent.py               # watch a real run on the sample request
python scripts/run_agent.py --sample rainy
```
Plus `logs/agent_runs.jsonl` gains one line per run, and green `CI / lint` + `CI / test` on the PR.

---

## Decisions (all recommendations accepted)

| # | Question | My recommendation |
|---|---|---|
| Q1 | Agent default model: `gpt-4o-mini` (from `.env`) or `gpt-4.1-mini`? | **`gpt-4o-mini`** for development (cheapest); Phase 7 measures whether a bigger model is worth it |
| Q2 | Code guardrail: reject a final answer that fails **deterministic** evals (max 2 rejections), or rely only on the prompt? | **Guardrail.** It's cheap (no LLM), and catches wrong totals and invented activities even if the model skips `run_evals_tool` |
| Q3 | Replace the unused single-call `PromptTrace` with `AgentStep` + `AgentRun`? | **Yes.** One run = many LLM calls; `AgentRun` keeps all of `PromptTrace`'s fields and adds steps |
| Q4 | Log full runs (all steps) to `logs/agent_runs.jsonl` (git-ignored)? | **Yes**, full runs. Easy debugging; Phase 10 moves production logs to Cloud Logging |
| Q5 | `max_steps` = 20? | 20 |
| Q6 | One commit for the phase? | Yes |
| Q7 | May I create branch `feature/phase-6-itinerary-agent` from `main`? | Yes |
