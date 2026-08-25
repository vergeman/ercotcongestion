#!/usr/bin/env bash
# Run the ablation while a 100ms sampler records peak RSS for the canonical
# experiment module. Keep this output beside the experiment's cached artifacts.
OUTAGE_RUN_DIR="${OUTAGE_RUN_DIR:-/compute/runs/experiments/mu}"
PEAK_FILE="${PEAK_FILE:-$OUTAGE_RUN_DIR/outage_ablation.peak_rss_mb.txt}"
mkdir -p "$OUTAGE_RUN_DIR"
echo 0 > "$PEAK_FILE"
(
  peak=0
  while true; do
    cur=0
    for f in /proc/[0-9]*/cmdline; do
      tr '\0' ' ' < "$f" 2>/dev/null | grep -q 'compute.experiments.mu.outage_ablation' || continue
      pid=$(basename "$(dirname "$f")")
      rss=$(awk '/VmRSS/{print int($2/1024)}' "/proc/$pid/status" 2>/dev/null)
      [ -n "$rss" ] && [ "$rss" -gt "$cur" ] && cur=$rss
    done
    [ "$cur" -gt "$peak" ] && { peak=$cur; echo "$peak" > "$PEAK_FILE"; }
    sleep 0.1
  done
) &
sampler=$!
bash /compute/runs/run_outage_ablation.sh
kill "$sampler" 2>/dev/null
echo ">>> wrapper done. peak RSS: $(cat "$PEAK_FILE") MB"
