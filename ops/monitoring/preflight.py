"""Check recent DAM hours before fitting."""
from datetime import date, timedelta

import pandas as pd

from compute.time import ct_day_bounds
from ops.monitoring.email_helper import send_email


def expected_hours(day):
    start, end = ct_day_bounds(day)
    return pd.date_range(start, end, freq="h", inclusive="left")


def findings(conn, through):
    problems = []
    for offset in range(6, -1, -1):
        day = through - timedelta(days=offset)
        hours = expected_hours(day)
        for table, column in (("ercot_dam_spp", "dam_spp"),
                              ("dam_system_lambda", "system_lambda")):
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT DISTINCT interval_ts FROM {table} "
                    f"WHERE interval_ts >= %s AND interval_ts < %s AND {column} IS NOT NULL",
                    ct_day_bounds(day),
                )
                present = {pd.Timestamp(row[0]) for row in cur.fetchall()}
            missing = [hour.isoformat() for hour in hours if hour not in present]
            if missing:
                problems.append(f"{table} {day}: missing hours (UTC): {', '.join(missing)}")
    return problems


def check(conn, through, *, dry_run=False):
    problems = findings(conn, through)
    print("\n".join(problems) if problems else "DAM preflight passed")
    if problems and not dry_run:
        send_email("ERCOT Congestion Explorer: missing DAM inputs",
                   "ERCOT Congestion Explorer stopped before fitting.\n\n" + "\n".join(problems))
    return not problems


def main():
    import argparse
    import psycopg
    from shared.settings import settings
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", type=date.fromisoformat, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(settings.pg_dsn) as conn:
        return 0 if check(conn, args.through, dry_run=args.dry_run) else 1


if __name__ == "__main__":
    raise SystemExit(main())
