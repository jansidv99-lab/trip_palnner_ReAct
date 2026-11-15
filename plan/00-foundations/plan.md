# Phase 0 – Foundations

> Status: **APPROVED**. Decisions: Q5 = B (`agentsville/` package), Q-A = keep `MODEL` free-form and align in Phase 2, Q-B = done (`REGION` fixed), Q-C = all 8 steps in **one commit**
> Branch: `chore/phase-0-foundations` (plan and implementation together)
> Review change: tool config split into `pytest.ini` + `ruff.toml` (the `pyproject.toml` name was misleading for a non-packaged project)
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md)

## Purpose

Build the shared plumbing every later phase relies on, so no phase has to reinvent setup:

- a decided **project layout** (open question Q5),
- a reproducible **Python environment** with dev tools,
- one place that loads **configuration** and fails fast,
- one wrapper for **LLM calls** that also measures latency, tokens and cost,
- a **smoke call** proving the LLM endpoint and key work,
- a **test and lint** setup that CI (Phase 1) will run.

No AgentsVille features are built in this phase.

---

## Findings from inspecting the environment

These shaped the plan:

| # | Finding | Impact |
|---|---|---|
| F1 | Four Python versions are installed (3.8, 3.11, 3.13, Store alias). Packages are installed **globally** into 3.11. | Use a **virtual environment** pinned to 3.11, so the project's packages are isolated and reproducible. |
| F2 | `ruff` isn't installed. `pytest` 9.0.3 is installed globally. | Add a `requirements-dev.txt` with pinned versions. |
| F3 | `.env` has `REGION=` with the value wrapped in **backticks**. python-dotenv reads it literally as `` `asia-south1` ``, backticks included. | Region-based GCP calls would break. **You** fix the line in `.env` (it's your file and it's git-ignored): `REGION="asia-south1"`. |
| F4 | `.env` has `MODEL="gpt-4o-mini"`, but the `OpenAIModel` enum in `models.py` lists only `gpt-4.1`, `gpt-4.1-mini`, `gpt-4.1-nano`. | Needs a decision (Q-A below). |
| F5 | `OPENAI_BASE_URL` points to an **OpenAI-compatible proxy** (Vocareum), not api.openai.com. | The wrapper must pass `base_url`. Token usage is still returned, so cost can be estimated. Billing is the proxy's, so our cost figure is an **estimate**. |
| F6 | `PROMPT_VERSION="V1"` (uppercase). | Normalize to lowercase (`v1`) in config, so file names like `prompts/itinerary/v1.md` stay predictable. |

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Virtual environment (venv)** | A private folder of packages for one project. Different projects can't break each other, and `requirements*.txt` describe it exactly. |
| **Fail-fast configuration** | Read and validate all settings once at startup. A missing API key gives one clear error now, instead of a confusing failure deep inside the agent later. |
| **Wrapper (adapter) around the SDK** | All code calls *our* `chat()` function, never the OpenAI SDK directly. Swapping the provider, adding retries or measuring cost happens in one place, and tests can substitute a fake. |
| **Smoke test** | The smallest possible end-to-end check ("can we talk to the LLM at all?"). It isn't a quality test. |
| **pytest markers** | Labels on tests (`@pytest.mark.llm`) so slow or paid tests can be included or skipped with a flag. |
| **Linter (ruff)** | A tool that flags bugs and style problems without running the code. CI will enforce it. |
| **`pytest.ini` / `ruff.toml`** | Each tool's own config file. The tools find them automatically by these exact names, so plain `pytest` and `ruff check .` pick up the settings with no extra flags. |

---

## Steps

Each step lists its purpose, outputs and dependencies. Every new file and function gets a `# Phase 0 – Step N: <purpose>` comment.

### Step 1 – Decide the project layout (Q5)
**Purpose:** choose where code lives before writing any, because moving modules later means rewriting every import.

| | **A. Flat files in repo root** | **B. `agentsville/` package in repo root** (recommended) |
|---|---|---|
| Looks like | `models.py config.py llm.py data_api.py evals.py tools.py agent.py app.py …` next to `README.md`, `goal.md`, `plan/` | `agentsville/{models,config,llm,data_api,evals,tools,agent}.py`, with `app.py`, `tests/`, `data/`, `plan/` at the root |
| Imports | `from models import TravelPlan` | `from agentsville.models import TravelPlan` |
| Simplicity now | ✅ simplest | ✅ almost as simple: one `__init__.py`, no install step |
| As the project grows (~10 modules, prompts, eval suite) | ❌ root gets crowded; code mixed with docs and config | ✅ code, UI, tests, data and docs clearly separated |
| Name clashes | ⚠️ generic names like `config`, `tools`, `data` can shadow installed packages | ✅ everything is namespaced |
| Docker / CD (Phase 9) | copy many loose files | copy one folder + `app.py` |
| Cost of changing later | high (every import changes) | – |

**Recommendation: B.** It costs almost nothing extra now and avoids a disruptive move later. Details:
- `data/data.py` **stays in `/data`** (`goal.md`: "always refer data in folder /data"). We add `data/__init__.py` so it imports cleanly as `from data.data import ACTIVITY_CALENDAR`.
- `app.py` (Phase 8) stays at the root, so `streamlit run app.py` works.
- `models.py` moves to `agentsville/models.py` with `git mv`, so git keeps its history. Its content is untouched until Phase 2, Step 1 (the comment cleanup).
- Imports resolve from the repo root: pytest via `pythonpath = .` in `pytest.ini`, and Streamlit because it runs from the root.

**Output:** decision recorded here; `agentsville/__init__.py`, `data/__init__.py`, `models.py` moved.
**Depends on:** nothing.

### Step 2 – Virtual environment and dependencies
**Purpose:** a reproducible environment that CI can recreate exactly.
- Create `.venv` with Python 3.11: `py -3.11 -m venv .venv` (`.venv/` is already git-ignored).
- Keep `requirements.txt` for runtime deps (unchanged).
- Add `requirements-dev.txt`:
  ```
  -r requirements.txt
  pytest==8.3.5
  ruff==0.11.13
  ```
- Commands (documented in README and CLAUDE.md):
  ```bash
  .venv\Scripts\activate            # Windows PowerShell / cmd
  pip install -r requirements-dev.txt
  ```

**Output:** `requirements-dev.txt`.
**Depends on:** Step 1.

### Step 3 – Tool configuration (`pytest.ini`, `ruff.toml`)
**Purpose:** pytest and ruff settings shared by local runs and CI, one clearly named file per tool.
- `pytest.ini`: `testpaths = tests`, `pythonpath = .`, register the marker `llm: calls the real LLM (slow, costs money)`, and default `addopts = -m "not llm"` so paid tests never run by accident.
- `ruff.toml`: `target-version = "py311"`, `line-length = 100`; `[lint]` select `E, F, I, B, UP` (errors, pyflakes, import order, bugbear, pyupgrade). `data/data.py` is excluded from line-length checks because of its long descriptions. `agentsville/models.py` has a temporary exception until Phase 2 – Step 1.

**Output:** `pytest.ini`, `ruff.toml`.
**Depends on:** Step 2.

### Step 4 – Configuration loader (`agentsville/config.py`)
**Purpose:** read `.env` once, validate it, and expose typed settings to the whole app.
- A Pydantic model `Settings`:

  | Field | Source | Required | Notes |
  |---|---|---|---|
  | `openai_api_key` | `OPENAI_API_KEY` | ✅ | stored as `SecretStr`, so it's masked when printed or logged |
  | `openai_base_url` | `OPENAI_BASE_URL` | optional | `None` → the SDK default endpoint |
  | `model` | `MODEL` | optional | default decided by Q-A |
  | `prompt_version` | `PROMPT_VERSION` | optional | default `v1`; normalized to lowercase |
  | `gcp_project_id`, `gcp_project_number`, `region` | `GCP_*`, `REGION` | optional now | required later by CD (Phase 9); stray quotes/backticks are stripped defensively |
- `get_settings()` loads `.env` with python-dotenv, builds `Settings`, and caches it (`functools.lru_cache`) so the file is read once.
- On a missing or invalid value: raise one `ConfigError` that names **every** missing variable and points to `.env.example`.
- Add `.env.example` (committed) listing every variable with placeholder values. This documents setup for anyone cloning the repo.

**Output:** `agentsville/config.py`, `.env.example`.
**Depends on:** Steps 1–3.

### Step 5 – LLM client wrapper (`agentsville/llm.py`)
**Purpose:** the only place in the project that talks to the OpenAI SDK.
- `LLMResponse` (Pydantic): `text`, `model`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `cost_usd`. These match the metric fields on `PromptTrace`, so Phase 6 can copy them straight across.
- `LLMClient`:
  - built from `Settings` (`api_key`, `base_url`), with an explicit **timeout** (60 s) and **retries** (2), both supported by the OpenAI SDK.
  - `chat(messages, model=None, temperature=0.0) -> LLMResponse`: times the call with `time.perf_counter()`, reads `usage` from the reply, computes cost.
  - SDK errors (auth, timeout, rate limit, connection) are wrapped in a single `LLMError` with a readable message. Callers handle one exception type.
- `estimate_cost(model, prompt_tokens, completion_tokens)` uses a price table (USD per 1M tokens, OpenAI list prices; an estimate, since the proxy bills separately):

  | Model | Input | Output |
  |---|---|---|
  | gpt-4.1 | 2.00 | 8.00 |
  | gpt-4.1-mini | 0.40 | 1.60 |
  | gpt-4.1-nano | 0.10 | 0.40 |
  | gpt-4o-mini | 0.15 | 0.60 |

  An unknown model returns `cost_usd = None` instead of guessing.

**Output:** `agentsville/llm.py`.
**Depends on:** Step 4.

### Step 6 – Smoke call script (`scripts/smoke_llm.py`)
**Purpose:** prove, by hand, that the key, endpoint and model work, before any agent code exists.
- Sends one tiny prompt ("Reply with exactly: OK"), then prints the reply, model, latency, tokens and estimated cost.
- Exit code 0 on success, 1 with a clear message on `ConfigError` / `LLMError`.
- Run manually: `python scripts/smoke_llm.py`. Never run in CI (it needs the secret and costs money).

**Output:** `scripts/smoke_llm.py`.
**Depends on:** Step 5.

### Step 7 – First tests (Layer A)
**Purpose:** a test suite exists from day one, so CI in Phase 1 has something real to run.

| Test file | What it checks | Calls the LLM? |
|---|---|---|
| `tests/test_imports.py` | `agentsville.models` and `data.data` import; data has 24 activities and 6 weather days | no |
| `tests/test_config.py` | valid env → `Settings`; missing key → `ConfigError` naming it; `PROMPT_VERSION` lowercased; backticks stripped; key masked in `repr` (uses pytest's `monkeypatch` for env vars) | no |
| `tests/test_llm.py` | `estimate_cost` math; unknown model → `None`; `chat()` with a **fake SDK client** returns the right `LLMResponse` and wraps errors in `LLMError` | no |
| `tests/test_llm_live.py` | one real call returns non-empty text and token counts | **yes** (`@pytest.mark.llm`, skipped by default) |

- `tests/conftest.py`: shared fixtures (a fake settings object, a fake OpenAI client).

**Output:** `tests/` folder.
**Depends on:** Steps 4–5.

### Step 8 – Documentation
**Purpose:** anyone (including future Claude sessions) can set up and run the project.
- `README.md` (currently empty): a short project description, setup (venv, install, `.env` from `.env.example`), and how to run the smoke call, tests and lint.
- `CLAUDE.md` **Commands** section: replace the placeholder with the real commands, including how to run a single test and the `llm` marker.

**Output:** `README.md`, `CLAUDE.md` updated.
**Depends on:** Steps 2–7.

---

## Resulting layout (end of Phase 0)

```
.
├── agentsville/
│   ├── __init__.py
│   ├── config.py
│   ├── llm.py
│   └── models.py          (moved, content unchanged)
├── data/
│   ├── __init__.py
│   └── data.py
├── scripts/
│   └── smoke_llm.py
├── tests/
│   ├── conftest.py
│   ├── test_imports.py
│   ├── test_config.py
│   ├── test_llm.py
│   └── test_llm_live.py
├── plan/ …
├── .env.example
├── pytest.ini
├── ruff.toml
├── requirements.txt
├── requirements-dev.txt
├── sample_plan.json
├── README.md  CLAUDE.md  goal.md
```

---

## Verification (definition of done)

```bash
pip install -r requirements-dev.txt     # inside .venv, installs cleanly
ruff check .                            # no errors
pytest                                  # all non-LLM tests pass
python scripts/smoke_llm.py             # prints "OK" + latency/tokens/cost
pytest -m llm                           # live test passes (optional, costs a fraction of a cent)
```

---

## Questions for you

| # | Question | My recommendation |
|---|---|---|
| Q5 | Project layout: flat files (A) or `agentsville/` package (B)? | **B**, for the reasons in Step 1 |
| Q-A | `.env` uses `gpt-4o-mini`, but the UI's `OpenAIModel` list is the gpt-4.1 family. Which is right? | Keep `MODEL` free-form in config. Check in the smoke call which models the Vocareum proxy accepts, then align `OpenAIModel` and the `.env` default in Phase 2 when `models.py` is touched anyway. |
| Q-B | Fix `REGION` in `.env` yourself (`REGION="asia-south1"`)? | Yes. Config also strips backticks defensively, but the source should be clean. |
| Q-C | Steps 1–8 on a single branch `chore/phase-0-foundations`, one commit per step? | Yes: one branch, one PR, small commits you approve one at a time |
