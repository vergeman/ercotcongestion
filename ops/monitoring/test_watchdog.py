from datetime import datetime, timedelta, timezone


from ops.monitoring.pipeline_watchdog import expected_run, inspect_run, forecast_output

TICK = datetime(2026, 11, 3, 17, tzinfo=timezone.utc)


def job(condition='Complete'):
    return {'metadata': {'name': 'test', 'creationTimestamp': TICK.isoformat(),
                         'ownerReferences': [{'kind': 'CronJob', 'name': 'ercot-forecast'}]},
            'status': {'conditions': [{'type': condition, 'status': 'True', 'reason': 'DeadlineExceeded'}]}}


def inspect(jobs, pods=None, suspended=False, minutes=60):
    return inspect_run('ercot-forecast', TICK, TICK + timedelta(minutes=minutes), jobs, pods or [], suspended)


def test_missing_suspended_and_grace():
    assert inspect([])[0] == ['missing scheduled run']
    assert inspect([], suspended=True)[0] == []
    assert inspect([], minutes=10)[0] == []


def test_failed_and_oom():
    pod = {'metadata': {'ownerReferences': [{'kind': 'Job', 'name': 'test'}]},
           'status': {'containerStatuses': [{'name': 'fit', 'state': {'terminated': {'reason': 'OOMKilled'}}}]}}
    problems, complete = inspect([job('Failed')], [pod])
    assert any('DeadlineExceeded' in p for p in problems)
    assert 'OOMKilled: fit' in problems
    assert complete is None


def test_overdue_and_complete():
    pending = job()
    pending['status'] = {}
    assert inspect([pending])[0] == ['run past deadline']
    assert inspect([job()])[0] == []
    assert inspect([job()])[1] is not None


def test_expected_schedules():
    assert expected_run('ercot-forecast-preview', TICK).day == 2
    assert expected_run('ercot-map-refresh', TICK).day == 1


def test_forecast_missing_output():
    from unittest.mock import MagicMock
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = []
    cur.fetchone.return_value = None
    assert len(forecast_output(conn, TICK, 1, 'mu-all-v1')) == 2


def test_repair_matches_delivery_date_and_requires_success():
    from ops.monitoring.pipeline_watchdog import repaired_run
    repair = job()
    repair['spec'] = {'template': {'spec': {'containers': [{
        'command': ['python', '-m', 'compute.jobs.daily_forecast', '--delivery-date',
                    '2026-11-04', '--horizon', '1', '--run-id', 'mu-all-v1', '--to-db']
    }]}}}
    cron = {'spec': {'jobTemplate': {'spec': repair['spec']}}}
    assert repaired_run('ercot-forecast', TICK, [repair], cron) is repair
    args = repair['spec']['template']['spec']['containers'][0]['command']
    args[args.index('2026-11-04')] = '2026-11-03'
    assert repaired_run('ercot-forecast', TICK, [repair], cron) is None
    args[args.index('2026-11-03')] = '2026-11-04'
    repair['status'] = {}
    assert repaired_run('ercot-forecast', TICK, [repair], cron) is None
