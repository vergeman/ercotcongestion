"""Put the ercot_ingest package root on sys.path for the test session.

`loaders` imports its siblings by bare name (`from outage_parse import ...`), the
docker layout that mounts this tree at `/ercot_ingest`. Mirror `api/tests`, which
inserts `/api` the same way, so the tests import the loaders exactly as the
container runs them.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
