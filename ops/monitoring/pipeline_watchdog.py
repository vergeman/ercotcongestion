"""Twice-daily checks for the three production model schedules."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import argparse
import logging
import os

import pandas as pd
import requests

from ops.monitoring.email_helper import send_email
from ops.monitoring.preflight import expected_hours

SCHEDULES = {
    'ercot-forecast': (17, 0, 30, 1),
    'ercot-forecast-preview': (20, 15, 30, 2),
    'ercot-map-refresh': (18, 0, 60, None),
}


def expected_run(name, now):
    hour, minute, _, horizon = SCHEDULES[name]
    tick = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if tick > now:
        tick -= timedelta(days=1)
    if horizon is None:
        tick -= timedelta(days=(tick.weekday() - 6) % 7)
    return tick


def owned(resource, kind, name):
    return any(o.get('kind') == kind and o.get('name') == name
               for o in resource.get('metadata', {}).get('ownerReferences', []))


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def inspect_run(name, tick, now, jobs, pods, suspended):
    # Allow the scheduled run its full runtime before checking it.
    if now < tick + timedelta(minutes=SCHEDULES[name][2]):
        return [], None

    # Match the scheduled run by CronJob owner and scheduled time.
    matches = []
    for job in jobs:
        if not owned(job, 'CronJob', name):
            continue
        meta = job['metadata']
        scheduled = meta.get('annotations', {}).get('batch.kubernetes.io/cronjob-scheduled-timestamp')
        # Older Kubernetes versions omit the scheduled timestamp annotation.
        when = instant(scheduled or meta['creationTimestamp'])
        if when == tick or (not scheduled and tick <= when < tick + timedelta(minutes=5)):
            matches.append(job)
    if not matches:
        return ([] if suspended else ['missing scheduled run']), None

    # Read completion and failure conditions from the matching Job.
    job = max(matches, key=lambda j: j['metadata']['creationTimestamp'])
    status = job.get('status', {})
    problems = []
    complete = any(c['type'] == 'Complete' and c['status'] == 'True'
                   for c in status.get('conditions', []))
    for condition in status.get('conditions', []):
        if condition['type'] in ('Failed', 'FailureTarget') and condition['status'] == 'True':
            problems.append('failed Job: ' + condition.get('reason', 'unknown') + ' ' + condition.get('message', ''))

    # Include container OOMs, even when Kubernetes retried the container.
    for pod in pods:
        if not owned(pod, 'Job', job['metadata']['name']):
            continue
        for container in pod.get('status', {}).get('containerStatuses', []) + pod.get('status', {}).get('initContainerStatuses', []):
            for state in ('state', 'lastState'):
                terminated = container.get(state, {}).get('terminated', {})
                if terminated.get('reason') == 'OOMKilled':
                    problems.append('OOMKilled: ' + container['name'])

    # An unfinished run beyond its allowance is overdue.
    if not complete and not problems:
        problems.append('run past deadline')
    return problems, job if complete else None


def forecast_output(conn, tick, horizon, run_id):
    day = tick.astimezone(__import__('zoneinfo').ZoneInfo('America/Chicago')).date() + timedelta(days=horizon)
    with conn.cursor() as cur:
        cur.execute('SELECT DISTINCT ts FROM forecast_nodal WHERE run_id=%s AND delivery_date=%s AND horizon=%s',
                    (run_id, day, horizon))
        present = {pd.Timestamp(row[0]) for row in cur.fetchall()}
        missing = [h.isoformat() for h in expected_hours(day) if h not in present]
        cur.execute('SELECT 1 FROM forecast_sf_artifact WHERE run_id=%s AND delivery_date=%s AND horizon=%s',
                    (run_id, day, horizon))
        artifact = cur.fetchone()
    return ([f'forecast {day} missing hours: {", ".join(missing)}'] if missing else []) + ([] if artifact else [f'forecast {day} missing SF artifact'])


def sf_output(conn, tick):
    from compute.inputs.dam import panel_bounds
    from compute.sf_map.config import WINDOW_DAYS, REFIT_DAYS
    from compute.sf_map.storage.maps import MAP_RUN_ID
    # Mirror weekly_map's fixed grid, excluding its trailing partial week.
    start = pd.Timestamp('2024-12-25')
    end = pd.Timestamp(tick.date()) + pd.Timedelta(days=1)
    bounds = panel_bounds(conn, start - pd.Timedelta(days=WINDOW_DAYS), end)
    if bounds is None:
        return ['SF panel clock is empty']
    first, last = (pd.Timestamp(v).normalize() for v in bounds)
    grid = pd.date_range(first, last, freq=pd.Timedelta(days=REFIT_DAYS), inclusive='left')
    complete = [v + pd.Timedelta(days=REFIT_DAYS) for v in grid
                if v + pd.Timedelta(days=REFIT_DAYS) <= last + pd.Timedelta(days=1)
                and v + pd.Timedelta(days=REFIT_DAYS) > start.tz_localize(first.tz)]
    if not complete:
        return ['no complete SF window expected from panel clock']
    window_end = max(complete)
    window_start = window_end - pd.Timedelta(days=WINDOW_DAYS)
    with conn.cursor() as cur:
        cur.execute('SELECT 1 FROM sf_window_meta m JOIN sf_window_artifact a USING (run_id, window_start) '
                    'WHERE m.run_id=%s AND m.window_start=%s AND m.window_end=%s',
                    (MAP_RUN_ID, window_start, window_end))
        exists = cur.fetchone()
    return [] if exists else [f'missing SF metadata/artifact window {window_start} through {window_end}']


def kube_resources():
    root = Path('/var/run/secrets/kubernetes.io/serviceaccount')
    headers = {'Authorization': 'Bearer ' + (root / 'token').read_text().strip()}
    server = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT', '443')
    result = []
    for api, resource in [('apis/batch/v1', 'cronjobs'), ('apis/batch/v1', 'jobs'), ('api/v1', 'pods')]:
        response = requests.get(f'{server}/{api}/namespaces/ercotstress/{resource}',
                                headers=headers, verify=str(root / 'ca.crt'), timeout=30)
        response.raise_for_status()
        result.append(response.json()['items'])
    return result


def main():
    import psycopg
    from shared.settings import settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        # Load one Kubernetes snapshot for this scan.
        cronjobs, jobs, pods = kube_resources()
        now = datetime.now(timezone.utc)
        problems = []
        # Check each expected run, then its outputs if it completed.
        with psycopg.connect(settings.pg_dsn) as conn:
            for name, (_, _, _, horizon) in SCHEDULES.items():
                cron = next((c for c in cronjobs if c['metadata']['name'] == name), None)
                if cron is None:
                    problems.append(name + ': CronJob missing')
                    continue
                tick = expected_run(name, now)
                issues, completed = inspect_run(name, tick, now, jobs, pods, cron['spec'].get('suspend', False))
                if completed:
                    issues += forecast_output(conn, tick, horizon, 'mu-all-v1') if horizon else sf_output(conn, tick)
                problems.extend(f'{name} expected {tick.isoformat()}: {issue}' for issue in issues)
        # Send one summary for the scan; healthy scans stay quiet.
        if problems:
            body = 'ERCOT Congestion Explorer pipeline check:\n\n' + '\n'.join(problems)
            print(body)
            if not args.dry_run:
                send_email('ERCOT Congestion Explorer: pipeline problems', body)
        else:
            print('Pipeline check passed')
        return 1 if problems else 0
    except Exception as exc:
        logging.error('Pipeline monitoring dependency failed (%s)', type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
