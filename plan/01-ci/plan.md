# Phase 1 – CI (Continuous Integration)

> Status: **APPROVED**. Decisions: Q1 = **two separate jobs** (`lint`, `test`), Q2 = coverage later, Q3 = do the Step 5 demo, Q4 = Steps 1–2 in one commit
> Branch: `chore/phase-1-ci` (plan and implementation together)
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md)
> Depends on: Phase 0 (`ruff.toml`, `pytest.ini`, `requirements-dev.txt`, test suite) ✅ merged

## Purpose

From now on, every pull request and every push to `main` is **automatically linted and tested on
GitHub's servers**, and `main` can't receive code that fails those checks. Each later phase adds
tests, and CI runs them without anyone having to remember.

**In scope:** lint and unit tests (Layer A) on every PR/push, and branch protection on `main`.
**Out of scope:** tests that call the real LLM (`@pytest.mark.llm`), deployment (Phase 9 CD), and
scheduled eval runs (Phase 7).

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **GitHub Actions** | GitHub's built-in automation. YAML files in `.github/workflows/` describe what to run and when. |
| **Workflow / job / step** | A *workflow* (one YAML file) contains *jobs*. A job runs on one fresh machine and is a list of *steps* (shell commands or reusable actions). |
| **Runner** | The temporary virtual machine GitHub starts for a job (here `ubuntu-latest`). It's thrown away afterwards, so every run starts clean. |
| **Trigger (`on:`)** | The events that start a workflow: `pull_request`, `push`, or a manual button (`workflow_dispatch`). |
| **Action** | A reusable step published by someone else, for example `actions/checkout` (gets the code) and `actions/setup-python` (installs Python). Pinned to a major version (`@v4`). |
| **Dependency cache** | Saves downloaded pip packages between runs, keyed on `requirements*.txt`. Runs get faster, and the cache refreshes automatically when requirements change. |
| **Status check** | The ✅/❌ a workflow job reports on a PR. Branch protection can *require* it before merging. |
| **Least-privilege permissions** | The workflow's token gets only `contents: read`, because CI only needs to read code, not write to the repo. |
| **Concurrency** | If you push twice quickly to the same PR, the older run is cancelled, saving minutes and avoiding confusing results. |

---

## Why CI won't need any secrets

- `pytest.ini` skips `llm`-marked tests by default, so CI never calls the LLM.
- Unit tests build settings with `load_settings({...})` and use `FakeOpenAIClient`. Nothing reads `.env` or needs `OPENAI_API_KEY`.
- Result: the workflow has **no secrets at all**, so forks and PRs can't leak anything. Secrets are introduced deliberately in Phase 9 (CD).

---

## Steps

### Step 1 – CI workflow file
**Purpose:** define the automated checks.
**Output:** `.github/workflows/ci.yml`
**Depends on:** Phase 0 config files and tests.

Design:

| Setting | Value | Why |
|---|---|---|
| Name | `CI` | shows in the PR checks list as **`CI / lint`** and **`CI / test`** |
| Triggers | `pull_request` (to `main`), `push` (to `main`), `workflow_dispatch` | check every PR, re-check `main` after each merge, allow a manual re-run |
| Permissions | `contents: read` | least privilege |
| Concurrency | group by workflow + ref, `cancel-in-progress: true` | drop stale runs |
| Jobs | two **parallel** jobs, `lint` (timeout 5 min) and `test` (timeout 10 min), on `ubuntu-latest` | each reports its own status check, so a failure tells you at a glance whether it's style or behavior; both run even if the other fails |
| Python | `actions/setup-python@v5`, `python-version: "3.11"`, `cache: pip` | same version as the local `.venv` |

`lint` job:
1. `actions/checkout@v4`: get the code.
2. `actions/setup-python@v5`: Python 3.11 with the pip cache.
3. Install **only ruff**, at the exact version pinned in `requirements-dev.txt` (read with `grep`, so the version lives in one place). This keeps the lint job fast.
4. `ruff check . --output-format=github`: lint errors show up as inline comments on the PR's changed lines.

`test` job:
1. `actions/checkout@v4`.
2. `actions/setup-python@v5`: Python 3.11, pip cache keyed on both requirements files.
3. `pip install -r requirements-dev.txt`: the same pinned versions as local.
4. `pytest -q`.

The file gets the `# Phase 1 – Step 1: …` comment at the top (CLAUDE.md rule 7; YAML uses `#` comments too).

### Step 2 – Documentation
**Purpose:** make CI visible and documented.
**Output:** `README.md` and `CLAUDE.md` updated.
**Depends on:** Step 1.
- `README.md`: a CI status badge at the top (`https://github.com/jansidv99-lab/trip_palnner_ReAct/actions/workflows/ci.yml/badge.svg`), and one line under "Tests and lint": *"The same checks run in CI on every PR."*
- `CLAUDE.md`: under Commands, add *"CI (`.github/workflows/ci.yml`) runs `ruff check .` and `pytest` on every PR and push to `main`; `llm`-marked tests are never run in CI. Run both locally before committing."*

### Step 3 – First CI run (you, on GitHub)
**Purpose:** confirm the workflow works on GitHub's runner.
**Output:** green **`CI / lint`** and **`CI / test`** on the Phase 1 PR.
**Depends on:** Steps 1–2 committed and pushed.
- After you push the branch and open the PR, the workflow starts automatically (it runs on the PR itself, so the PR checks its own CI file).
- Expected: lint passes, `18 passed, 1 deselected`, and the run takes about 1–2 minutes the first time and less afterwards thanks to the cache.
- Where to look: the PR's **Checks** tab, or the repo's **Actions** tab.

### Step 4 – Branch protection on `main` (you, on GitHub)
**Purpose:** make the checks *mandatory*, not just informational.
**Output:** a rule on `main`.
**Depends on:** Step 3. GitHub only lets you pick a required check after it has run at least once.

In the repo: **Settings → Rules → Rulesets → New branch ruleset** (or the classic **Settings → Branches → Add rule**):
- Target: `main` (Default branch)
- ✅ Restrict deletions; ✅ Block force pushes
- ✅ Require a pull request before merging (approvals: 0, since you're the only developer)
- ✅ Require status checks to pass → add **`lint`** and **`test`** (from the `CI` workflow); ✅ require branches to be up to date before merging
- Enforcement status: **Active**

I'll give these steps again, click by click, when we get there.

### Step 5 – Prove the gate works (optional, recommended for learning)
**Purpose:** see CI block a bad change with your own eyes.
**Output:** a red ❌ run that blocks merge; the branch is then deleted.
**Depends on:** Step 4.
- On a throwaway branch (`test/ci-gate-demo`), change one assertion in `tests/test_imports.py` (for example expect 25 activities) and open a PR.
- Expected: `CI / test` fails (while `CI / lint` stays green), the merge button is blocked, and the failing assertion shows in the log.
- Close the PR without merging and delete the branch. Nothing reaches `main`.

---

## Verification (definition of done)

| Check | Expected |
|---|---|
| Local: `ruff check .` and `pytest` | still pass (no code changes in this phase) |
| PR for this branch | `CI / lint` ✅ and `CI / test` ✅ |
| After merge, push to `main` | the CI run on `main` ✅, and the README badge shows "passing" |
| Branch protection | the merge button is disabled while either check is failing or pending |
| (Optional) Step 5 demo | the failing PR is blocked |

---

## Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | One job or two parallel jobs (`lint`, `test`)? | **Decided: two jobs.** Separate status checks show at a glance whether a failure is style or behavior. |
| Q2 | Add test coverage reporting (`pytest-cov`) now? | **Decided: later.** |
| Q3 | Do the optional Step 5 demo? | **Decided: yes.** |
| Q4 | Steps 1–2 in a single commit (like Phase 0)? | **Decided: yes, one commit.** |
