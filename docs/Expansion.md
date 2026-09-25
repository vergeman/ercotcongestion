# Expansion priorities

The next improvements should emphasize interpretation, robustness, and clear
market context—not another shift-factor (SF) estimator.

## Priority: constraint dossier and attribution robustness

Build a compact dossier for each `constraint_name | contingency_name` pair that
links the market result to the protected condition:

- monitored element, contingency, limit, modeled value, headroom/violation,
  shadow price, market, and timestamp;
- implied SF, predicted `μ`, predicted contribution (`-SF × μ`), and the
  strongest negative/positive SF settlement points; and
- a plain-language statement that SCED/DAM enforces a post-contingency flow
  inequality through changes in injections, rather than treating the constraint
  as a controllable line setting.

Pair this with per-constraint attribution-robustness measures across refits:
SF-row and lobe similarity, reach and peak-SF changes, binding count,
co-binding/collinearity groups, and leave-one-constraint-out sensitivity.
Describe these as confidence in the named attribution, not proof of physical
topology or an exact ERCOT PTDF.

Label markets and timestamps rigorously: DAM shadow prices feed the SF
regression; RTM/SCED data can provide operational context but must not be shown
as the DAM `μ` used in the fit.

## Reliability and change detection

Extend nodal uncertainty beyond `μ` forecast bands by fitting several qualified
rolling or resampled SF maps and projecting the same `μ` scenarios through each.
Report the additional variation from the implied SF map, especially where large
opposing contributions cancel.

Use rolling artifacts and published constraint fields for a daily “what changed?”
review layer. Flag new top contributors, materially changed SF lobes or reach,
renamed/split constraint-contingency keys, sharp limit changes, unusual high `μ`,
and new contingency pairings. Treat flags as regime or data-quality signals—not
claims about a specific physical switching or failure event.

## Later work

- **Historical coverage:** measure missing `forecast_sf_artifact` days; if
  playback warrants it, plan an idempotent backfill with resource and causal-input
  checks. Never substitute a latest fit for historical data.
- **Stability analytics:** validate settlement-point, constraint-lobe, and path
  differential-vector stability, plus contribution concentration and gross-versus-
  net cancellation. Define matching rules for churn and collinearity first.
- **CRR paths:** after the Matrix is trusted, support source/sink selection with
  `ΔSF[c] = SF[c, source] - SF[c, sink]`, expected contribution, residual
  exposure, and scenario risk. Do not imply a physical route or trade advice.
- **Daily congestion brief:** only if usage supports it, save a concise view of
  Matrix outputs—dominant constraints, exposed regions, cancellations, and
  post-DAM comparison—without creating a separate model pipeline.

## Out of scope

New `μ` or SF methods, official SF ingestion, CRR optimization, alerts or
notifications, generated market commentary, node/path-specific UI scores, an
unbounded constraint-by-point table, broad mobile parity, and redesign of the
existing map Constraints tab.
