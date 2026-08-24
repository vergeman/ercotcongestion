"""Compatibility launcher for :mod:`compute.mu.outage.crosswalk`."""

from compute.mu.outage.crosswalk import *  # noqa: F403
from compute.probes.outage_crosswalk import main


if __name__ == "__main__":
    raise SystemExit(main())  # noqa: F405
