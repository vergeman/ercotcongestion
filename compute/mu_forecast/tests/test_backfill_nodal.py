"""Run-artifact path convention for backfill_nodal (plan/0113).

`--run-id` is the canonical namespace: offline μ predictions resolve under
`runs/<id>/mu/`, and the nodal point panel under `runs/<id>/forecast/`,
while explicit flags always win and the run-id-less mode keeps reading the legacy
`compute/mu` bundle with opt-in (None) outputs.
"""
from __future__ import annotations

from compute.jobs.backfill_nodal import nodal_path_for, preds_path_for, resolve_walk_paths


def test_run_id_derives_inputs_under_mu_and_outputs_under_forecast():
    preds, nodal_out = resolve_walk_paths("mu-all-v1", None, None)
    assert preds == preds_path_for("mu-all-v1")
    assert nodal_out == nodal_path_for("mu-all-v1")
    assert preds and nodal_out
    assert preds.endswith("runs/mu-all-v1/mu/mu_preds.npz")
    assert nodal_out.endswith("runs/mu-all-v1/forecast/mu_nodal.npz")


def test_explicit_paths_override_each_derived_path_independently():
    preds, nodal_out = resolve_walk_paths("mu-all-v1", "/p.npz", "/n.npz")
    assert (preds, nodal_out) == ("/p.npz", "/n.npz")

    # A single override leaves the rest derived.
    preds, nodal_out = resolve_walk_paths("mu-all-v1", None, None)
    assert preds == preds_path_for("mu-all-v1")
    assert nodal_out == nodal_path_for("mu-all-v1")


def test_run_id_less_reads_legacy_bundle_and_keeps_outputs_opt_in():
    preds, nodal_out = resolve_walk_paths(None, None, None)
    assert preds
    assert preds.endswith("compute/mu/mu_preds.npz")
    # ...but outputs stay opt-in (unchanged run-id-less behavior).
    assert nodal_out is None


def test_load_nodal_npz_mode_derives_nothing():
    """The standalone seed path runs no walk, so it must not manufacture output
    paths a later guard would then reject as 'makes no sense with --load-nodal-npz'.
    """
    assert resolve_walk_paths(
        "mu-all-v1", None, None, load_nodal_npz=True) == (None, None)
