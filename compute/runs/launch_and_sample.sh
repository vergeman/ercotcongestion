#!/usr/bin/env bash
# Run the ablation while a 100ms sampler records the peak RSS of the
# outage_ablate python process to /compute/runs/ablation_peak.txt. The sampler
# only matches the `python -m compute.mu.outage_ablate` process (not this wrapper
# or run.sh, whose cmdlines don't contain the dotted module path).
echo 0 > /compute/runs/ablation_peak.txt
(
  peak=0
  while true; do
    cur=0
    for f in /proc/[0-9]*/cmdline; do
      tr '\0' ' ' < "$f" 2>/dev/null | grep -q 'compute.mu.outage_ablate' || continue
      pid=$(basename "$(dirname "$f")")
      rss=$(awk '/VmRSS/{print int($2/1024)}' "/proc/$pid/status" 2>/dev/null)
      [ -n "$rss" ] && [ "$rss" -gt "$cur" ] && cur=$rss
    done
    [ "$cur" -gt "$peak" ] && { peak=$cur; echo "$peak" > /compute/runs/ablation_peak.txt; }
    sleep 0.1
  done
) &
sampler=$!
bash /compute/runs/run_outage_ablation.sh
kill "$sampler" 2>/dev/null
echo ">>> wrapper done. peak RSS: $(cat /compute/runs/ablation_peak.txt) MB"
