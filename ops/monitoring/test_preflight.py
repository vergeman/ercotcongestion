from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from ops.monitoring.preflight import check, expected_hours, findings


@pytest.mark.parametrize('day,count', [('2026-03-08', 23), ('2026-11-01', 25), ('2026-11-02', 24)])
def test_dst(day, count):
    assert len(expected_hours(day)) == count


def connection(missing=False):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    def execute(sql, bounds):
        import pandas as pd
        hours = pd.date_range(*bounds, freq='h', inclusive='left')
        cur.fetchall.return_value = [(h,) for h in (hours[1:] if missing else hours)]
    cur.execute.side_effect = execute
    return conn


def test_healthy():
    assert findings(connection(), date(2026, 11, 3)) == []


def test_missing_hours_and_email():
    with patch('ops.monitoring.preflight.send_email') as send:
        assert not check(connection(True), date(2026, 11, 3))
        send.assert_called_once()
        assert 'ercot_dam_spp' in send.call_args.args[1]
        assert 'dam_system_lambda' in send.call_args.args[1]


def test_dry_run():
    with patch('ops.monitoring.preflight.send_email') as send:
        assert not check(connection(True), date(2026, 11, 3), dry_run=True)
        send.assert_not_called()


def test_email_failure_stops_fit():
    with patch('ops.monitoring.preflight.send_email', side_effect=RuntimeError('email failed')):
        with pytest.raises(RuntimeError):
            check(connection(True), date(2026, 11, 3))
