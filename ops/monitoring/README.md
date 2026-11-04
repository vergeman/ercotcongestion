# Pipeline monitoring

The preflight checks seven delivery days of DAM settlement prices and system
lambda for missing hours. Forecast and weekly SF jobs run it before fitting.
Missing inputs stop the fit and send an email.

The watchdog runs at 18:00 and 21:00 UTC. It checks final, preview, and weekly SF
outputs after their allowed runtime. Missing forecast hours/artifacts or SF window
metadata/artifacts send one summary email, with Job failure details when available.
Complete outputs send nothing, including after a manual repair.


## Configuration

Copy `.env.email.stub` to `.env.email` and fill in the values. Create the Secret:

```sh
kubectl -n ercotstress create secret generic monitoring-email \
  --from-env-file=.env.email
```

Build and deploy an image containing the monitoring code, then apply the CronJobs:

```sh
ops/deploy/model_cronjobs.sh all
```

## Manual checks

Run inside a compute pod with database configuration. For preflight, use D−1 for
forecasts or the current CT date for weekly SF:

```sh
python -m ops.monitoring.preflight --through 2026-11-03 --dry-run
```

Run the watchdog inside a pod using the `pipeline-watchdog` service account:

```sh
python -m ops.monitoring.pipeline_watchdog --dry-run
```

Dry runs print findings without sending email. Remove `--dry-run` to enable email.
Both commands exit 1 for problems or dependency errors. The model entry points
also accept `--preflight-dry-run` to check inputs and exit before fitting.
