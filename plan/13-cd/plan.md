# Phase 13 – CD → Cloud Run

> Status: **IN PROGRESS** – approved 2026-11-16 (Q1–Q9 = recommendations); Steps 1–7 implemented,
> Step 8 after merge. Owner decision 2026-11-16: **no local Docker build/run** – the image is
> built and verified only by the CI `container` job and the deploy pipeline; testing happens on
> the deployed app.
> Branch: `feature/phase-13-cloud-run-cd` (from `main` after Phase 12 merged, PR #14)
> Master plan: [`plan/00-master/master-plan.md`](../00-master/master-plan.md) (v5: 12 → **13** → 11)
> Depends on: Phase 1 (CI) ✅, Phase 7 (eval replay) ✅, Phase 12 (Streamlit UI, Steps 1–6) ✅ –
> committed on `feature/phase-12-streamlit-ui`, not yet merged

## Purpose

**goal.md §7 + master plan:** every merge to `main` produces a running, up-to-date app on GCP – but
only after the same checks that protect `main` pass: **CI (`lint`, `test`) and the eval replay**
(decision Q9; B4 adds the regression gate later).

| Part | What you get |
|---|---|
| **Container** | A small, non-root Docker image of the Streamlit app that listens on `$PORT` |
| **Secrets** | `OPENAI_API_KEY` in Secret Manager, injected at runtime – never in the image or the repo |
| **Keyless CI → GCP** | GitHub Actions signs in with Workload Identity Federation – no JSON key files |
| **Gated deploy** | `deploy.yml`: lint + tests + eval replay → build → push to Artifact Registry → deploy → smoke test |
| **Access control** | The public URL asks for a passcode, so strangers can't spend OpenAI credit (Q3) |
| **Rollback** | One command back to the previous Cloud Run revision (runbook) |

Delivered as **one commit** (your instruction). Out of scope: structured logging / BigQuery (Phase
14), dashboards (15), alerts (16).

---

## Key concepts introduced in this phase

| Concept | Short explanation |
|---|---|
| **Container image** | The app plus Python and its dependencies, frozen into one file system. Built from a `Dockerfile`; the same image runs on your laptop and on Cloud Run. |
| **Cloud Run** | Runs a container on demand behind an HTTPS URL; scales to zero when idle (no cost) and starts instances when requests arrive. Each deploy creates an immutable **revision**. |
| **Artifact Registry** | GCP's private image store. CD pushes `…/agentsville/app:<git sha>`, so every revision maps to an exact commit. |
| **Secret Manager** | Stores the API key encrypted; Cloud Run mounts it as an env var at start-up. Rotating it never needs a rebuild. |
| **Workload Identity Federation (WIF)** | GitHub issues a short-lived signed token for each workflow run; GCP trusts tokens from **this repo's `main` branch only** and swaps them for temporary credentials. Nothing long-lived to leak. |
| **Service accounts (least privilege)** | `github-deployer` may only push images and deploy; `agentsville-run` (the app's identity) may only read the one secret. |
| **Reusable workflows** | `ci.yml` and `eval-gate.yml` gain a `workflow_call` trigger, so `deploy.yml` runs the exact same jobs as gates – one definition, no copies. |
| **Session affinity + WebSockets** | Streamlit keeps a WebSocket open per browser tab; Cloud Run must route a user back to the same instance, and allow the 1–2 minute agent run (request timeout). |

---

## Design

### 1. Container (`Dockerfile`, `.dockerignore`, `.streamlit/config.toml`)
- Base `python:3.11-slim`; install **`requirements.txt` only** (no pytest/ruff in production).
- Copy only what runs: `app.py`, `agentsville/`, `data/`, `prompts/`. No `.env`, tests, evals,
  cassettes, logs or plan docs (`.dockerignore` keeps the build context small and secret-free).
- Run as a non-root user; `CMD streamlit run app.py --server.port=$PORT --server.address=0.0.0.0`.
- `.streamlit/config.toml`: headless, no usage stats, theme defaults.
- Production env defaults in the image: `AGENTSVILLE_RUN_LOG=off` (Cloud Run's disk is temporary;
  Phase 14 sends runs to Cloud Logging), `AGENTSVILLE_FEEDBACK_LOG=stdout` (see §2).

### 2. Feedback on Cloud Run: `StdoutFeedbackSink`
Phase 12 promised the UI wouldn't change when feedback moves to the cloud. Cloud Run captures every
line a container prints into **Cloud Logging**, so a sink that prints the `feedback.v1` record as one
JSON line (with `"logName"`-friendly fields: `severity`, `event: "feedback"`) is enough until Phase
14 adds the BigQuery sink. `AGENTSVILLE_FEEDBACK_LOG=stdout` selects it. ~10 lines + tests.

### 3. Access control – passcode gate (Q3)
- If `APP_PASSCODE` is set, the app shows only a passcode box until the right code is entered
  (compared with `hmac.compare_digest`; remembered in `st.session_state` for that browser tab).
- Unset (local development, tests) → no gate.
- On Cloud Run the passcode comes from Secret Manager (`app-passcode`), like the API key.
- Plus hard limits on the service: `--max-instances=2`, so a flood of visitors can't fan out.
- Logic in `agentsville/ui/access.py` (pure, tested); `app.py` calls it first.

### 4. GCP one-time setup (you run the commands – `plan/13-cd/gcp-setup.md`)
Uses the existing project and region from `.env` (`GCP_PROJECT_ID`, `REGION`); nothing new is
created at project level.
1. Enable APIs: Cloud Run, Artifact Registry, Secret Manager, IAM Credentials, STS.
2. Artifact Registry Docker repo `agentsville` in `$REGION`.
3. Secrets `openai-api-key` and `app-passcode` (values typed by you, never echoed into files).
4. Service accounts `agentsville-run` (secretAccessor on the two secrets only) and
   `github-deployer` (`run.admin`, `artifactregistry.writer` on the repo, `iam.serviceAccountUser`
   on `agentsville-run` only).
5. WIF pool `github` + OIDC provider for `token.actions.githubusercontent.com`, with an
   **attribute condition** `assertion.repository == 'jansidv99-lab/trip_palnner_ReAct' &&
   assertion.ref == 'refs/heads/main'`; `github-deployer` can be impersonated only through it.
6. GitHub **repository variables** (not secrets – none of them is sensitive): `GCP_PROJECT_ID`,
   `GCP_REGION`, `WIF_PROVIDER`, `DEPLOYER_SA`, `RUNTIME_SA`, plus `OPENAI_BASE_URL`, `MODEL`.
7. GitHub **environment** `production` (optional required reviewer = you, Q5).

Every command is written with shell variables (`$PROJECT_ID`, `$REGION`…) so the doc itself
contains no project identifiers.

### 5. Deploy workflow (`.github/workflows/deploy.yml`)
```
on: push to main (+ manual "Run workflow")
jobs:
  ci     → uses ./.github/workflows/ci.yml          (lint + test)
  evals  → uses ./.github/workflows/eval-gate.yml   (replay + repeatability + judge calibration)
  deploy (needs: ci, evals; environment: production; permissions: id-token: write)
    1. auth to GCP via WIF            google-github-actions/auth@v2
    2. docker build, tag with git sha, push to Artifact Registry
    3. gcloud run deploy agentsville  --image …:<sha> --region $GCP_REGION
         --service-account agentsville-run  --allow-unauthenticated (passcode gate inside)
         --set-secrets OPENAI_API_KEY=openai-api-key:latest,APP_PASSCODE=app-passcode:latest
         --set-env-vars OPENAI_BASE_URL,MODEL,PROMPT_VERSION=v1
         --max-instances 2  --min-instances 0  --memory 1Gi  --cpu 1
         --timeout 900  --session-affinity  --concurrency 20
    4. smoke test: GET <url>/_stcore/health must return 200, else the job fails
```
- **Why reusable workflows (Q2):** `eval-gate.yml` has a path filter (it skips commits that touch
  only docs), so "wait for the Evals run on this commit" could wait forever. Calling it from
  `deploy.yml` runs the gate on every deploy, whatever changed. Cost: the gates run twice on a push
  to `main` (once from their own triggers, once inside deploy) – a few CI minutes, $0.
- **Thresholds stay informational** until B4 (Q4) – the replay itself (exit 2/3) blocks.
- `concurrency: deploy-production` without cancelling, so two merges deploy in order.

### 6. CI container check
A `container` job in `ci.yml`: `docker build`, run the image, poll `/_stcore/health` – catches a
broken Dockerfile on the PR, before it reaches `main`. No secrets needed (the app starts without
an API key and shows the setup message). Not a required check until you decide (Q6).

### 7. Rollback & runbook (`plan/13-cd/runbook.md`)
- See revisions: `gcloud run revisions list --service agentsville --region $REGION`.
- Roll back: `gcloud run services update-traffic agentsville --to-revisions <REV>=100`.
- Rotate the key / passcode: add a secret version; the next deploy (or a revision restart) picks
  it up.
- Pause public access (e.g. unexpected spend): change the passcode, or
  `gcloud run services update agentsville --no-allow-unauthenticated` (only IAM-authorized callers).

### Cost
- Cloud Run scales to zero: **≈ $0 when idle**; Artifact Registry storage a few cents/month
  (old images can be cleaned with a retention policy, Step 4).
- CI/CD minutes: free tier for this repo size.
- Each real agent run on the deployed app: 1–3 cents of OpenAI credit (that's why the gate exists).
- First deploy verification (Step 8): ≈ $0.10–0.30, incl. the postponed Phase 12 Step 7 checks.

---

## Steps

### Step 1 – Container image
**Purpose:** a production image of the app that runs the same everywhere.
**Output:** `Dockerfile`, `.dockerignore`, `.streamlit/config.toml`, LF endings in `.gitattributes`.
Verified by the CI `container` job (build, health check, import check) – not locally (owner
decision).
**Depends on:** Phase 12.

### Step 2 – Stdout feedback sink
**Purpose:** keep traveler feedback on Cloud Run (Cloud Logging) without changing the UI.
**Output:** `StdoutFeedbackSink` + `AGENTSVILLE_FEEDBACK_LOG=stdout` in `agentsville/ui/feedback.py`;
tests; spec line in `production-signal.md`.
**Depends on:** none.

### Step 3 – Passcode gate
**Purpose:** a public URL that only invited people can use.
**Output:** `agentsville/ui/access.py`, gate at the top of `app.py`, unit + `AppTest` tests.
**Depends on:** none.

### Step 4 – GCP setup guide (you run it)
**Purpose:** create the registry, secrets, service accounts and WIF trust – once, least privilege.
**Output:** `plan/13-cd/gcp-setup.md` with exact commands (variables only), a verification command
after each block, and an Artifact Registry cleanup policy (keep the last 10 images).
**Depends on:** none (can run in parallel with Steps 1–3).

### Step 5 – Reusable gates
**Purpose:** one definition of "safe to ship" used by PRs and deploys alike.
**Output:** `workflow_call` added to `ci.yml` and `eval-gate.yml`; their job names (and so the
required-check names on `main`) unchanged.
**Depends on:** none.

### Step 6 – Deploy workflow + CI container check
**Purpose:** merge to `main` → gated, keyless deploy with a smoke test.
**Output:** `.github/workflows/deploy.yml`; `container` job in `ci.yml`; `actionlint`-clean.
**Depends on:** Steps 1, 4, 5.

### Step 7 – Runbook and docs
**Purpose:** you (and future sessions) know how to deploy, roll back and rotate secrets.
**Output:** `plan/13-cd/runbook.md`; CLAUDE.md (container, deploy flow, env vars); README
(deployed app, how it's gated).
**Depends on:** Steps 1–6.

### Step 8 – First deploy and verification (after the merge; you push/merge)
**Purpose:** prove the pipeline end to end.
**Output:** the `Deploy` run is green; the URL asks for the passcode; one real run per case
(default, tight budget, rainy, invalid input) on the deployed app – this also covers the postponed
**Phase 12 Step 7**; a feedback event visible in Cloud Logging; a rollback rehearsed once.
**Depends on:** Steps 1–7 merged; GCP setup done.

| Area | Tests (Layer A, in CI, $0) |
|---|---|
| feedback | stdout sink prints one valid `feedback.v1` JSON line with `severity`/`event`; env selection |
| access | gate shown only when `APP_PASSCODE` is set; wrong code → error, no form; right code → form; constant-time compare |
| AppTest | passcode screen hides the form and never builds a backend; after unlocking the existing flows still pass |
| container | CI job builds the image and gets 200 from `/_stcore/health` |

---

## Verification (definition of done)

```bash
ruff check . && pytest
python scripts/run_experiment.py --check-expected --check-thresholds   # unchanged eval path
```
Plus: green PR checks (incl. `container`), then after merge a green `Deploy` run, a working URL
behind the passcode, and a rehearsed rollback.

---

## Questions for you

| # | Question | My recommendation |
|---|---|---|
| Q1 | Phase 12 isn't merged yet. Start Phase 13 on a new branch **stacked on `feature/phase-12-streamlit-ui`** (merge 12's PR first, then 13's), or add the Phase 13 commit **to the Phase 12 branch** (one PR, two commits)? | **Merge Phase 12 first**, then branch from `main` as usual (rule 9). If you'd rather not wait: stacked branch. |
| Q2 | Gate deploys by calling `ci.yml` + `eval-gate.yml` as reusable workflows from `deploy.yml` (gates always run, even for doc-only commits)? | **Yes** |
| Q3 | Access control: **public URL + passcode gate** (Secret Manager) + `max-instances 2`? Alternatives: private service reached with `gcloud run services proxy` (most secure, only you can use it), or fully public (anyone spends your credit). | **Passcode gate** – shareable with reviewers, cheap to build |
| Q4 | Threshold verdicts **do not block** deploys before B4 (cassette replay + calibration do)? | **Yes** – per Q9; B4 makes them blocking |
| Q5 | GitHub environment `production` with **you as required reviewer** (every deploy waits for your click)? | **No** for now – gates are automatic; add it if you want a manual brake |
| Q6 | New `container` CI job: make it a **required check** on `main`? | **Yes**, after its first green run |
| Q7 | Cloud Run sizing: 1 vCPU, 1 GiB, 0–2 instances, concurrency 20, timeout 900 s, session affinity? | **Yes** (≈ $0 idle) |
| Q8 | Feedback on Cloud Run via a **stdout sink** now (→ Cloud Logging), BigQuery in Phase 14? | **Yes** |
| Q9 | One commit for the whole phase (your instruction) – confirmed; Step 8 happens after merge, with any fixes in a follow-up `fix/…` branch? | **Yes** |
