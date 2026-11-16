# Phase 13 – Step 7: runbook – deploy, verify, roll back, rotate

> For the deployed AgentsVille app on Cloud Run. Commands assume the variables from
> [`gcp-setup.md` §0](gcp-setup.md#0-variables-this-shell-only--nothing-is-written-to-files).
> Phase plan: [`plan.md`](plan.md)

## How a deploy happens

```
merge to main ─▶ Deploy workflow
                  ├─ ci     (lint, test, container)      ┐ both must pass
                  ├─ evals  (replay + calibration)       ┘
                  └─ deploy: build → push app:<sha> → gcloud run deploy → health check
```
- Every revision runs the image tagged with its commit SHA (label `commit-sha`).
- Redeploy without a code change (e.g. after rotating a secret): GitHub → Actions → Deploy →
  *Run workflow* on `main`, or `gh workflow run deploy.yml --ref main`.

## Is it healthy?

```bash
gcloud run services describe agentsville --region "$REGION" \
  --format 'value(status.url,status.latestReadyRevisionName)'
curl -fsS "$(gcloud run services describe agentsville --region "$REGION" --format 'value(status.url)')/_stcore/health"
gcloud run services logs read agentsville --region "$REGION" --limit 50
```
Feedback events (Phase 13 – Step 2) in Cloud Logging:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND jsonPayload.event="feedback"' --limit 20
```

## Roll back

```bash
# list revisions, newest first (the commit-sha label tells you which commit each one runs)
gcloud run revisions list --service agentsville --region "$REGION" \
  --format 'table(metadata.name,metadata.labels.commit-sha,status.conditions[0].status,metadata.creationTimestamp)'

# send all traffic to a known-good revision
gcloud run services update-traffic agentsville --region "$REGION" --to-revisions <REVISION>=100
```
A rollback sticks until the next deploy, which sends traffic to the new revision again. Fix forward
with a `fix/…` branch, or revert the bad commit on `main`.

## Rotate a secret

```bash
read -rsp "New value: " VALUE; echo
printf '%s' "$VALUE" | gcloud secrets versions add openai-api-key --data-file=-   # or app-passcode
unset VALUE
gh workflow run deploy.yml --ref main   # new revision reads :latest at start-up
```
Old versions can be disabled with `gcloud secrets versions disable <N> --secret openai-api-key`.

## Unexpected spend or abuse

1. Change the passcode (above) – everyone has to enter the new one.
2. Or make the service private (only IAM-authorized callers):
   `gcloud run services update agentsville --region "$REGION" --no-allow-unauthenticated`
   and open it yourself with `gcloud run services proxy agentsville --region "$REGION"`.
3. The next deploy re-applies `--allow-unauthenticated`; remove that flag from `deploy.yml` if the
   service should stay private.
