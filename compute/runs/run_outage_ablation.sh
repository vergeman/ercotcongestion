#!/usr/bin/env bash
# Run the 0089 outage ablation one arm per process to stay under this node's RAM.
#
# Why isolated processes: the heavy arms (all, all+out) peak ~11-12GiB in a single
# process because the panel (~4GB) is held while the 240-day train copy + sklearn's
# float32 matrix copy stack on top, plus any prior arm's preds still bound in the
# loop. Running each heavy arm in its own `python -m` invocation means only that
# arm's working set is ever live, and the process fully exits (releasing everything)
# before the next starts. The final pass rebuilds the panel once, reuses every npz
# (no walks), and writes the real table + CSV.
#
# Idempotent: an arm whose preds_<arm>.npz already exists on the PVC is skipped,
# so a rerun after an OOM resumes instead of recomputing. Safe to re-run anytime.
#
# Usage (inside the compute-shell pod):
#   bash /compute/runs/run_outage_ablation.sh
set -euo pipefail

SCORE_FROM="${SCORE_FROM:-2025-08-14}"
PREDS_DIR="${PREDS_DIR:-/compute/runs/outage_ablation}"
OUT="${OUT:-/compute/runs/outage_ablation.csv}"
SCRATCH="${SCRATCH:-/compute/runs/_ablation_scratch.csv}"

mkdir -p "$PREDS_DIR"

# Map an arm name to its cached npz filename (outage_ablate replaces '+' with '_').
npz_for() { echo "$PREDS_DIR/preds_${1//+/_}.npz"; }

run_isolated() {
  local arm="$1"
  local npz
  npz="$(npz_for "$arm")"
  if [[ -f "$npz" ]]; then
    echo ">>> arm '$arm': $npz already exists — skipping"
    return 0
  fi
  echo ">>> arm '$arm': running isolated process ($(date -u +%H:%M:%S)Z)"
  # Walk-only is the default: save the npz and stop, freeing M/C/regimes before the
  # fit so the heavy arms clear this node's RAM. Scoring is the --score pass below.
  python -m compute.mu.outage_ablate \
    --score-from "$SCORE_FROM" \
    --arms "$arm" \
    --preds-dir "$PREDS_DIR"
  echo ">>> arm '$arm': done, wrote $npz"
}

# Heavy arms first, each in its own process. 'out' is light but isolated too so the
# script has one uniform path. 'base' is expected to already be cached from earlier.
for arm in base all all+out out; do
  run_isolated "$arm"
done

# Final assembly: --score rebuilds the panel once, reuses all four npz (no walks),
# scores every arm through the harness, and writes the real CSV + verdict.
echo ">>> assembling all four arms into $OUT ($(date -u +%H:%M:%S)Z)"
python -m compute.mu.outage_ablate \
  --score-from "$SCORE_FROM" \
  --arms base,all,out,all+out \
  --preds-dir "$PREDS_DIR" \
  --score \
  --out "$OUT"

echo ">>> complete. Table + verdict written to $OUT"
