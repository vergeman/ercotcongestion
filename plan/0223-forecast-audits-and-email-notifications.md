# 0223 - forecast-audits-and-email-notifications

Type: feat
Branch: feat/0223-forecast-audits-and-email-notifications

## Goal

* Test Cloudflare email delivery, then email when required input data is missing or a scheduled job fails.

* Cover final forecasts, preview forecasts, and the weekly SF refresh with basic preflight checks and one twice-daily monitoring CronJob.

## Context

* November 2 DAM prices were missing from ERCOT's APIs even though the website report existed. A successful HTTP response and ingest job did not mean the data was present.

* Forecast and SF jobs can be OOM-killed before they can report their own failure. A separate job must check their Kubernetes status.

* Keep this first version stateless. Repeated alerts are acceptable; no monitoring tables or alert history are needed.

## Approach

### Commit 1 — Test email delivery

* Put the email helper, manual test script, and instructions under `ops/monitoring/`. Use existing `requests` to POST sender, recipient, subject, and plain-text body directly to Cloudflare's email REST API.

* Configure the Cloudflare account ID, email API token, sender address, and verified Gmail recipient through a Kubernetes Secret. Use a request timeout, check the response for rejection or bounce, and keep credentials out of logs.

* Send one explicitly invoked test email from the cluster and confirm it arrives in Gmail before building the alerts. Verify account permissions and free-plan eligibility through this test; resolve any rejection before proceeding.

* Reference: [Cloudflare email REST API](https://developers.cloudflare.com/email-service/api/send-emails/rest-api/) and [verified recipients](https://developers.cloudflare.com/email-service/configuration/email-routing-addresses/).

### Commit 2 — Add a basic preflight check

* Put the check under `ops/monitoring/` and call it before the expensive fit in `compute/jobs/daily_forecast.py` and `compute/jobs/weekly_map.py`. Keep the existing application jobs in place.

* Check DAM settlement prices and DAM system lambda for the latest seven expected delivery days: through D−1 for forecasts, and through the current CT delivery day for the scheduled weekly SF refresh. Check each day's expected hour timestamps using existing CT/DST helpers. Report a missing day or an hour with no non-null prices or lambda.

* Keep the existing shadow-price publication gate and feature-input validation. Shadow prices are sparse, so do not require shadow rows for every hour. Do not add settlement-point count thresholds, historical baselines, or new validation of every training feature.

* If required data is missing, send one email naming the dataset and missing dates/hours, then exit nonzero before fitting. An email failure must not allow the fit to proceed. Support a dry run that prints findings without sending email or running a fit.

* This first version catches recent gaps such as November 2. It does not validate every settlement point or the entire training history.

### Commit 3 — Add one scheduled failure/output check

* Add `ops/monitoring/pipeline_watchdog.py` and its CronJob manifest under `ops/deploy/jobs/`. Run at 18:00 and 21:00 UTC (`0 18,21 * * *`), after the final and preview deadlines. The Sunday 21:00 scan also checks the weekly SF refresh. No five-minute polling.

* Read Kubernetes Jobs, Pods, and CronJobs in `ercotstress` using the service-account token and existing `requests`. Grant only the required namespace get/list permissions. Monitor `ercot-forecast`, `ercot-forecast-preview`, and `ercot-map-refresh`.

* Check the latest expected scheduled run for each job using the existing schedules: final daily at 17:00 UTC, preview daily at 20:15 UTC, and SF Sundays at 18:00 UTC. Match Jobs by their CronJob owner and scheduled time. Skip runs still within their allowed runtime; skip missing-run checks for currently suspended CronJobs. Keep this limited to these schedules rather than building a general scheduler.

* Report a missing run, failed Job, `OOMKilled` container, or run past its deadline. Use the existing 30-minute forecast and one-hour SF deadlines. Include the job name, expected run time, and Kubernetes failure reason when available.

* For a completed forecast, check that rows cover the expected delivery-day hours and a matching `forecast_sf_artifact` exists for its run/date/horizon. For a completed SF refresh, check that the latest expected complete SF window has metadata and an artifact, using the existing window calculation. Do not require a new insert when the incremental refresh legitimately reuses existing windows.

* Kubernetes failure remains an alert even if older output exists. A completed SF Job means its shell chain finished; do not add separate geography/evaluation receipts, artifact provenance tracking, or grade/snapshot audits.

* Send one summary email when a scan finds problems. Send nothing when healthy. Repeated alerts on later scans are fine. No deduplication or recovery emails. Use Kubernetes retention as the source of job status; document that retained failed Jobs may still be reported after a manual repair until the next scheduled success.

* If a monitoring dependency or email request fails, log the error and exit nonzero. A monitor inside k3s cannot notify while the entire cluster is down.

### Commit 4 — Wire deployment and verify

* Keep all new monitoring Python, helper scripts, tests, and the runbook under `ops/monitoring/`. Keep CronJob/RBAC manifests under `ops/deploy/`. Update the image only as needed to include/import the monitoring code.

* Add the watchdog to `ops/deploy/model_cronjobs.sh`, mount email configuration where needed, and retain failed jobs long enough for twice-daily scans. Preserve the existing forecast/SF schedules and resource limits.

* Run the preflight and watchdog in dry-run mode against production before enabling emails and blocking checks. Document how to run either check manually and inspect its findings.

## Scope control

* Use the smallest implementation satisfying the acceptance criteria; treat this as a first version.

* No database migrations, monitoring tables, persistent state files, alert-state annotations, automatic reruns/backfills, Worker endpoints, external heartbeat service, or SCED lambda changes.

* Before adding unplanned persistence, dependencies, or substantial verification work, explain the need and ask for a scope decision. Resolve routine implementation choices within this plan without further confirmation.

* Verification is limited to focused tests for email errors, missing input days/hours including DST, job failure/OOM/missing-run detection, and basic output presence; manifest/RBAC validation; the real email test; and production dry runs. Use fixture OOM statuses rather than killing a production job.

## Acceptance

* [x] A direct REST test email arrives in the verified Gmail inbox.

* [x] Missing recent DAM price/lambda hours stop a forecast or weekly SF fit and produce a useful email; valid DST days pass.

* [ ] The watchdog runs twice daily and reports failed, OOM-killed, overdue, or missing final/preview/SF jobs and missing basic outputs.

* [x] Healthy scans send no email; repeated problem emails are accepted. No monitoring state is stored.

* [x] Focused tests, manifest checks, and production dry runs pass, with limitations documented in `ops/monitoring/README.md`.

## Implementation and verification

* Email delivery confirmed in Gmail on November 3, 2026. Email copy uses
  ERCOT Congestion Explorer.
* Preflight and watchdog implementation complete. All 22 focused tests pass,
  including DST hours, missing inputs, email failures, missing runs, suspended
  schedules, overdue Jobs, failed Jobs, OOM statuses, and missing forecast outputs.
* Production dry runs passed final/preview input checks, forecast hours and
  artifacts, and the expected complete SF window metadata/artifact check.
* The watchdog dry run reported retained failed final/SF Jobs and a forecast OOM.
  Manual repairs do not clear retained scheduled Job failures.
* Kubernetes server-side dry-run validation passed for all updated manifests.
* The monitoring Secret and service account/RBAC exist in production. Temporary
  test pods were removed. Updated images and CronJobs await deployment; the
  twice-daily scheduling acceptance item remains open until deployment.
* Implementation commits: `8543f4c`, `29135d9`, `87057d1`, `610599c`,
  `d5bc573`, and `a3284e6`. Nothing pushed.
