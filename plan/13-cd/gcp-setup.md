# Phase 13 – Step 4: one-time GCP + GitHub setup for CD

> You run these commands (Git Bash, from the repo root, logged in with `gcloud auth login`).
> They use the **existing** project and region from your `.env`; nothing is created at
> organization or billing level. Each block ends with a check command.
> Master plan: [`../00-master/master-plan.md`](../00-master/master-plan.md) · Phase plan: [`plan.md`](plan.md)

What gets created (least privilege). Every name starts with `trip-planner-react`: the project
already hosts other apps, including a separate AgentsVille service that owns `agentsville*`
resources and an `openai-api-key` secret. Sharing them would hand that app our key, or let our
registry cleanup policy delete its images.

| Resource | Name | Why |
|---|---|---|
| Cloud Run service | `trip-planner-react` | the app (created by the first deploy) |
| Artifact Registry repo | `trip-planner-react` (Docker, in `$REGION`) | stores one image per commit |
| Secrets | `trip-planner-react-openai-key`, `trip-planner-react-passcode` | read by the app at start-up only |
| Service account | `trip-planner-react-run` | the app's identity: may read the two secrets, nothing else |
| Service account | `trip-planner-react-deployer` | CD's identity: push images, deploy Cloud Run, act as `trip-planner-react-run` |
| WIF provider | `github-trip-planner-react` in the existing pool `github-pool` | trusts GitHub tokens from this repo's `main` branch only |

> Status (2026-11-16): all of this exists – steps 1–5 were run once. Keep this file as the record
> and for rebuilding the setup.

---

## 0. Variables (this shell only – nothing is written to files)

```bash
# Copy the three values from your .env (GCP_PROJECT_ID, GCP_PROJECT_NUMBER, REGION)
export PROJECT_ID="<GCP_PROJECT_ID>"
export PROJECT_NUMBER="<GCP_PROJECT_NUMBER>"
export REGION="<REGION>"

export GITHUB_REPO="jansidv99-lab/trip_palnner_ReAct"
export APP="trip-planner-react"
export AR_REPO="$APP"
export OPENAI_SECRET="${APP}-openai-key"
export PASSCODE_SECRET="${APP}-passcode"
export RUNTIME_SA="${APP}-run@${PROJECT_ID}.iam.gserviceaccount.com"
export DEPLOYER_SA="${APP}-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
export WIF_POOL="github-pool"                 # existing pool, one provider per repo
export WIF_PROVIDER_ID="github-${APP}"
export WIF_PROVIDER="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER_ID}"

gcloud config set project "$PROJECT_ID"
```
Check: `gcloud config get-value project` prints your project ID.

## 1. Enable the APIs

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com
```
Check: `gcloud services list --enabled | grep -E "run|artifactregistry|secretmanager|iamcredentials|sts"`

## 2. Artifact Registry (image store) + cleanup policy

```bash
gcloud artifacts repositories create "$AR_REPO" \
  --repository-format=docker --location="$REGION" \
  --description="AgentsVille Streamlit app images (one per commit)"

# keep the 10 newest images, delete anything else older than 30 days
gcloud artifacts repositories set-cleanup-policies "$AR_REPO" \
  --location="$REGION" --policy=plan/13-cd/ar-cleanup-policy.json --no-dry-run
```
Check: `gcloud artifacts repositories describe "$AR_REPO" --location="$REGION"`

## 3. Secrets (typed in silently – never echoed, never saved in a file)

```bash
read -rsp "OpenAI API key: " VALUE; echo
printf '%s' "$VALUE" | gcloud secrets create "$OPENAI_SECRET" --replication-policy=automatic --data-file=-
unset VALUE

read -rsp "App passcode to share with testers: " VALUE; echo
printf '%s' "$VALUE" | gcloud secrets create "$PASSCODE_SECRET" --replication-policy=automatic --data-file=-
unset VALUE
```
Check: `gcloud secrets list --filter="name~${APP}"` shows both (values are never printed).
Rotate later: see [`runbook.md`](runbook.md#rotate-a-secret).

## 4. Service accounts and their permissions

```bash
gcloud iam service-accounts create "${APP}-run" --display-name="${APP} Cloud Run runtime"
gcloud iam service-accounts create "${APP}-deployer" --display-name="${APP} GitHub deployer"

# the app may read exactly these two secrets
for SECRET in "$OPENAI_SECRET" "$PASSCODE_SECRET"; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${RUNTIME_SA}" --role=roles/secretmanager.secretAccessor
done

# the deployer may deploy Cloud Run services ...
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${DEPLOYER_SA}" --role=roles/run.admin
# ... push images to this one repository ...
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --location="$REGION" \
  --member="serviceAccount:${DEPLOYER_SA}" --role=roles/artifactregistry.writer
# ... and start the service as the runtime account (only this account)
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:${DEPLOYER_SA}" --role=roles/iam.serviceAccountUser
```
Check: `gcloud iam service-accounts list | grep "$APP"`

## 5. Workload Identity Federation (GitHub → GCP without keys)

The pool `github-pool` already exists (your other repos have one provider each in it), so this
repo only adds its own provider. On a fresh project, create the pool first:
`gcloud iam workload-identity-pools create "$WIF_POOL" --location=global --display-name="GitHub Actions"`.

```bash
gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER_ID" \
  --location=global --workload-identity-pool="$WIF_POOL" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository == '${GITHUB_REPO}' && assertion.ref == 'refs/heads/main'"

# only workflow runs from this repository may act as the deployer
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/attribute.repository/${GITHUB_REPO}"
```
Check: `gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER_ID" --location=global --workload-identity-pool="$WIF_POOL" --format="value(state,attributeCondition)"` → `ACTIVE` and the condition.

## 6. GitHub repository variables (not secrets – none of these is sensitive)

```bash
gh variable set GCP_PROJECT_ID --body "$PROJECT_ID"
gh variable set GCP_REGION     --body "$REGION"
gh variable set WIF_PROVIDER   --body "$WIF_PROVIDER"
gh variable set DEPLOYER_SA    --body "$DEPLOYER_SA"
gh variable set RUNTIME_SA     --body "$RUNTIME_SA"
# from .env – the OpenAI-compatible endpoint and the default model
gh variable set OPENAI_BASE_URL --body "<OPENAI_BASE_URL from .env>"
gh variable set MODEL           --body "gpt-4o-mini"
```
Check: `gh variable list`

The `production` environment is created automatically by the first deploy run (no required
reviewer – plan Q5). To add a manual brake later: GitHub → Settings → Environments → production →
Required reviewers.

---

## Troubleshooting

| Symptom in the Deploy run | Likely cause | Fix |
|---|---|---|
| `auth` step: *must specify exactly one of "workload_identity_provider" or "credentials_json"* | the repo variables aren't set (step 6) – `vars.*` are blank | run step 6, then re-run the workflow |
| `auth` step: *unable to generate access token* / *permission denied on iam.serviceAccounts.getAccessToken* | step 5 binding missing, or the run isn't from `main` | re-run step 5's last command; deploys only work from `main` by design |
| `docker push`: *denied: Permission "artifactregistry.repositories.uploadArtifacts"* | step 4 repo binding missing | re-run the `artifactregistry.writer` binding |
| `gcloud run deploy`: *Permission 'iam.serviceaccounts.actAs' denied* | `serviceAccountUser` binding missing | re-run the last binding in step 4 |
| deploy: *Secret … not found or permission denied* | secret name typo or runtime binding missing | re-run step 3 / the loop in step 4 |
| deploy: *Setting IAM policy failed … allUsers* (`--allow-unauthenticated`) | an organization policy forbids public services | keep it private: remove `--allow-unauthenticated` in `deploy.yml` and open the app with `gcloud run services proxy trip-planner-react --region "$REGION"` |
| smoke test fails, logs show *ModuleNotFoundError* | a needed folder is missing from the image | add it to both `Dockerfile` and `.dockerignore` |
