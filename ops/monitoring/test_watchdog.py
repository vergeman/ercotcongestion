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


def test_outputs_decide_whether_failed_jobs_alert():
    from unittest.mock import patch
    from ops.monitoring.pipeline_watchdog import output_issues
    now = TICK + timedelta(hours=1)
    for name, reader in [('ercot-forecast', 'forecast_output'), ('ercot-map-refresh', 'sf_output')]:
        with patch('ops.monitoring.pipeline_watchdog.' + reader, return_value=[]):
            assert output_issues(None, name, TICK, now, [job('Failed')], []) == []
        with patch('ops.monitoring.pipeline_watchdog.' + reader, return_value=['missing output']):
            issues = output_issues(None, name, TICK, now, [job('Failed')], [])
            assert issues[0] == 'missing output'
            assert len(issues) > 1
