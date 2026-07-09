"""Regime-conditioned scorecard diagnostic.

CLI driver at :mod:`compute.experiments.regime_scorecard.run`. Reads the
existing matrix + partition artifacts, buckets hours by a regime scheme
(``congestion_magnitude:q4``, ``net_load:q4``, ``binding_active``), and
reports per-bucket + pooled scorecard metrics.

See ``README.md`` in this directory for what ``q4`` means and how to
read the output.
"""
