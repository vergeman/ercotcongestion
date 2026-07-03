// LMP color anchors ($/MWh) — fixed-scale fallback
//   - negative: oversupply (rare but informative; renewables curtailment)
//   - mid: nominal market clearing
//   - high: scarcity / congestion
const LMP_LOW = -50; // deeply negative → blue
const LMP_MID = 30; // normal market → neutral/cream
const LMP_HIGH = 500; // scarcity territory → orange/red

export function normalizeLmp(value: number | null): number {
  if (value == null) return 0.5;
  if (value <= LMP_MID) {
    // LOW → MID maps to 0 → 0.5
    const t = (value - LMP_LOW) / (LMP_MID - LMP_LOW);
    return Math.max(0, Math.min(0.5, t * 0.5));
  } else {
    // MID → HIGH maps to 0.5 → 1.0, log-scaled for the long tail
    const logMid = Math.log10(LMP_MID);
    const logHi = Math.log10(LMP_HIGH);
    const logV = Math.log10(Math.min(LMP_HIGH, value));
    return 0.5 + ((logV - logMid) / (logHi - logMid)) * 0.5;
  }
}

// Window-wide LMP scaling. Computed once when a playback window loads, then
// reused for every frame so the same dollar value renders as the same color
// across the entire playback session.
//
// Three anchors derived from percentiles of every (bus, snapshot) LMP in the
// window:
//   p_low  (P5)   → deepest blue
//   median        → cream
//   p_high (P95)  → deepest orange
//
// Percentiles (not std/MAD) because the distribution is heavy-tailed and
// degenerate-clustered at the gas-marginal floor (~$28.55) — spread-based
// stats collapse there. Percentiles describe the actual observed range.
// Asymmetric blue / orange halves let the gradient stretch independently
// in each direction, since curtailment range and scarcity range differ.
export interface LmpStats {
  median: number;
  p_low: number; // low percentile anchor (P5 by default)
  p_high: number; // high percentile anchor (P95 by default)
  min: number; // observed window min (for legend display only)
  max: number; // observed window max (for legend display only)
  n: number; // number of LMP samples used
}

// Trim percentiles. Values inside [p_low, p_high] occupy the main color
// gradient (with γ damping near the median). Values outside fall into a
// log-extended tail that keeps deepening — so a single $1500 outlier doesn't
// crush the scale, but $40 / $65 / $90 still register as visibly distinct
// shades of orange.
export const LMP_PCT_LOW = 0.01;
export const LMP_PCT_HIGH = 0.99;

// Response-curve exponent. Linear interpolation (γ=1) puts maximum color
// sensitivity right at the median, which is where the gas-marginal cluster
// sits — small ($0.50) noise reads as visibly orange. Pushing γ > 1 flattens
// the curve near the median and steepens it toward the percentile anchors,
// so noise stays cream and only meaningful moves toward p_low / p_high
// register as color.
export const LMP_GAMMA = 1.8;

// Linear-interpolated percentile of a sorted array.
function percentile(sorted: number[], p: number): number {
  const n = sorted.length;
  if (n === 0) return 0;
  if (n === 1) return sorted[0];
  const idx = p * (n - 1);
  const lo = Math.floor(idx);
  const hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (idx - lo);
}

// Compute window-wide LMP stats. Pass a flat array of all observed LMP
// values across every (bus, snapshot) pair in the window.
export function computeLmpStats(
  values: Array<number | null | undefined>
): LmpStats {
  const xs: number[] = [];
  for (const v of values) {
    if (v == null || !isFinite(v)) continue;
    xs.push(v);
  }
  if (xs.length === 0) {
    return { median: 0, p_low: 0, p_high: 1, min: 0, max: 0, n: 0 };
  }
  const sorted = [...xs].sort((a, b) => a - b);
  return {
    median: percentile(sorted, 0.5),
    p_low: percentile(sorted, LMP_PCT_LOW),
    p_high: percentile(sorted, LMP_PCT_HIGH),
    min: sorted[0],
    max: sorted[sorted.length - 1],
    n: xs.length,
  };
}

// Map an LMP value to [0, 1] using window stats.
//
// In-bounds  (p_low ≤ value ≤ p_high):
//   value === median → 0.5  (cream)
//   value === p_low  → BLUE_CORE_END   (mid-deep blue, not deepest)
//   value === p_high → ORANGE_CORE_END (mid-deep orange, not deepest)
//   γ-damped so values close to the median stay cream regardless of small noise.
//
// Out-of-bounds: log-compressed extension into the reserved [0, BLUE_CORE_END]
// or [ORANGE_CORE_END, 1] range. Keeps darkening so $40 / $65 / $90 are
// distinguishable, but a $1500 outlier asymptotes rather than crushing
// the rest of the scale.
const BLUE_CORE_END = 0.1; // p_low maps here
const ORANGE_CORE_END = 0.9; // p_high maps here

export function normalizeLmpFromStats(
  value: number | null,
  stats: LmpStats
): number {
  if (value == null) return 0.5;
  const { median, p_low, p_high } = stats;

  if (value <= median) {
    const span = median - p_low;
    if (span <= 0) return 0.5;

    if (value >= p_low) {
      // In-bounds: γ-damped, p_low → BLUE_CORE_END, median → 0.5
      const d = (median - value) / span; // 0 at median, 1 at p_low
      const damped = Math.pow(d, LMP_GAMMA);
      return 0.5 - (0.5 - BLUE_CORE_END) * damped;
    } else {
      // Out-of-bounds (below p_low): rational tail into [0, BLUE_CORE_END].
      // x is "p_low-spans below p_low" — 1 means another full span out.
      // x/(1+x) is 0 at the boundary, 0.5 at one span, 0.91 at ten — slow
      // enough that $40/$65/$90 in the high tail stay distinguishable.
      const x = (p_low - value) / span;
      const tail = x / (1 + x);
      return BLUE_CORE_END * (1 - tail);
    }
  } else {
    const span = p_high - median;
    if (span <= 0) return 0.5;

    if (value <= p_high) {
      // In-bounds: γ-damped, median → 0.5, p_high → ORANGE_CORE_END
      const d = (value - median) / span;
      const damped = Math.pow(d, LMP_GAMMA);
      return 0.5 + (ORANGE_CORE_END - 0.5) * damped;
    } else {
      // Out-of-bounds (above p_high): rational tail into [ORANGE_CORE_END, 1].
      const x = (value - p_high) / span;
      const tail = x / (1 + x);
      return ORANGE_CORE_END + (1 - ORANGE_CORE_END) * tail;
    }
  }
}

// LMP: blue (low) → white → orange (high), per-snapshot normalized
export function lmpColor(norm: number): string {
  const t = Math.max(0, Math.min(1, norm));
  if (t < 0.5) {
    const s = t * 2;
    const r = Math.round(59 + (226 - 59) * s);
    const g = Math.round(130 + (232 - 130) * s);
    const b = Math.round(246 + (200 - 246) * s);
    return `rgb(${r},${g},${b})`;
  } else {
    const s = (t - 0.5) * 2;
    const r = Math.round(226 + (249 - 226) * s);
    const g = Math.round(232 + (115 - 232) * s);
    const b = Math.round(200 + (22 - 200) * s);
    return `rgb(${r},${g},${b})`;
  }
}

// =============================================================================
// Congestion-vs-basis rank view ("Δ Rank")
// =============================================================================
//
// For each snapshot, rank every bus by signed modeled_congestion (ascending)
// and by signed basis (ascending), normalize to [0, 1], and compute the
// signed difference:
//
//   delta = pct_modeled_congestion − pct_basis
//
//   delta > 0  → model ranks this bus MORE congested than the market does
//   delta < 0  → market ranks this bus MORE congested than the model does
//   delta ≈ 0  → model and market agree on this bus's rank
//
// Both inputs signed (no abs) — an "export-side" bus in the model should
// pair with a negative basis in the market; ranking them signed preserves
// that agreement in the low-percentile band as well as the high.
//
// Buses missing either input are excluded from ranking and returned as null
// (rendered neutral on the map).
//
// Per-snapshot, not window-wide — we want "where in *this* picture do model
// and market disagree most," not a stable cross-frame anchor.

// Convert an array of values into per-element percentile rank in [0, 1].
// Ties get the average rank. Nulls are preserved as null in the output.
function percentileRank(values: Array<number | null>): Array<number | null> {
  const n = values.length;
  // Collect (originalIndex, value) for non-null entries.
  const indexed: Array<{ i: number; v: number }> = [];
  for (let i = 0; i < n; i++) {
    const v = values[i];
    if (v != null && isFinite(v)) indexed.push({ i, v });
  }
  if (indexed.length === 0) return values.map(() => null);
  if (indexed.length === 1) {
    const out: Array<number | null> = values.map(() => null);
    out[indexed[0].i] = 0.5;
    return out;
  }

  // Sort by value ascending.
  indexed.sort((a, b) => a.v - b.v);

  // Assign average rank for ties.
  const ranks = new Array<number>(indexed.length);
  let i = 0;
  while (i < indexed.length) {
    let j = i;
    while (j + 1 < indexed.length && indexed[j + 1].v === indexed[i].v) j++;
    const avgRank = (i + j) / 2; // 0-based, average of run
    for (let k = i; k <= j; k++) ranks[k] = avgRank;
    i = j + 1;
  }

  // Normalize ranks to [0, 1] and place back into original positions.
  const out: Array<number | null> = values.map(() => null);
  const denom = indexed.length - 1;
  for (let k = 0; k < indexed.length; k++) {
    out[indexed[k].i] = ranks[k] / denom;
  }
  return out;
}

// Compute per-bus congestion-vs-basis rank delta for a single snapshot.
// Returns a Map keyed by bus_id; missing entries (excluded buses) map to null.
export function computeCongestionVsBasisRank(
  buses: Array<{
    bus_id: string;
    modeled_congestion: number | null;
    basis: number | null;
  }>
): Map<string, number | null> {
  // Both signed — no abs(). See section header for the rationale.
  const validMask = buses.map(
    (b) => b.modeled_congestion != null && b.basis != null
  );
  const mcMasked: Array<number | null> = buses.map((b, i) =>
    validMask[i] ? b.modeled_congestion : null
  );
  const basisMasked: Array<number | null> = buses.map((b, i) =>
    validMask[i] ? b.basis : null
  );

  const mcPct = percentileRank(mcMasked);
  const basisPct = percentileRank(basisMasked);

  const out = new Map<string, number | null>();
  for (let i = 0; i < buses.length; i++) {
    const m = mcPct[i];
    const b = basisPct[i];
    if (m == null || b == null) {
      out.set(buses[i].bus_id, null);
    } else {
      out.set(buses[i].bus_id, m - b); // ∈ [-1, 1]
    }
  }
  return out;
}

// Diverging color: purple (−1, model under) → cream (0) → teal (+1, model over).
// Anchors picked from the design palette (c-purple #7F77DD, c-teal #1D9E75)
// with a light cream center distinct from the LMP cream.
const DELTA_NEUTRAL_COLOR = "#1a4731"; // null/missing — dim green, no-signal read
const DELTA_PURPLE = [127, 119, 221]; // −1
const DELTA_CREAM = [232, 226, 215]; //  0
const DELTA_TEAL = [29, 158, 117]; // +1

// γ damping flattens the cream band so small disagreements stay neutral and
// only meaningful rank gaps register as color.
const DELTA_GAMMA = 1.6;

// Map a rank delta in [−1, 1] to RGB.
export function rankDeltaColor(delta: number | null): string {
  if (delta == null) return DELTA_NEUTRAL_COLOR;
  const sign = Math.sign(delta);
  const mag = Math.min(1, Math.pow(Math.abs(delta), DELTA_GAMMA));
  const target = sign < 0 ? DELTA_PURPLE : DELTA_TEAL;
  const r = Math.round(DELTA_CREAM[0] + (target[0] - DELTA_CREAM[0]) * mag);
  const g = Math.round(DELTA_CREAM[1] + (target[1] - DELTA_CREAM[1]) * mag);
  const b = Math.round(DELTA_CREAM[2] + (target[2] - DELTA_CREAM[2]) * mag);
  return `rgb(${r},${g},${b})`;
}

// Anchors exposed for the legend.
export const DELTA_ANCHORS = {
  purple: `rgb(${DELTA_PURPLE.join(",")})`,
  cream: `rgb(${DELTA_CREAM.join(",")})`,
  teal: `rgb(${DELTA_TEAL.join(",")})`,
  gamma: DELTA_GAMMA,
};

// =============================================================================
// Modeled congestion (diverging): signed Σ PTDF·μ per bus
// =============================================================================
//
// Diverging blue↔cream↔red centered at 0.
//   norm > 0  → import side, red
//   norm < 0  → export side, blue
//   norm ≈ 0  → cream (no signal)
//
// Window-percentile anchors (mirrors LmpStats): p_high = percentile(|mc|, 0.99);
// p_low = −p_high so the palette is symmetric around zero. γ damping flattens
// the cream band so noise near zero stays neutral. Rational tail beyond p_high
// keeps outlier snapshots darkening without crushing the mid range.

const MC_PCT_HIGH = 0.99;
// γ > 1 flattens near zero; matches LMP_GAMMA for consistent visual weight.
const MC_GAMMA = 1.8;
// |mc| = p_high maps to |norm| = MC_CORE_END; the remaining [MC_CORE_END, 1]
// band is the log-compressed tail for outliers.
const MC_CORE_END = 0.9;
// Values with |mc| below this fraction of p_high read as cream (no signal).
// Small floor — a diverging signal at 2% of the window's top percentile is
// still meaningful; a heavier floor would wash out the map.
const MC_FLOOR_FRAC = 0.02;

export interface ModeledCongestionStats {
  p_high: number; // percentile(|mc|, MC_PCT_HIGH); positive
  p_low: number; // −p_high (symmetric)
  max_abs: number; // observed window max |mc| — legend only
  n: number;
}

export const MODELED_CONGESTION_ANCHORS = {
  pct_high: MC_PCT_HIGH,
  gamma: MC_GAMMA,
  core_end: MC_CORE_END,
  floor_frac: MC_FLOOR_FRAC,
};

// Compute window-wide modeled-congestion stats. Pass a flat array of all
// observed modeled_congestion values across every (bus, snapshot) pair.
export function computeModeledCongestionStats(
  values: Array<number | null | undefined>
): ModeledCongestionStats {
  const abs_xs: number[] = [];
  for (const v of values) {
    if (v == null || !isFinite(v)) continue;
    abs_xs.push(Math.abs(v));
  }
  if (abs_xs.length === 0) {
    return { p_high: 1, p_low: -1, max_abs: 0, n: 0 };
  }
  const sorted = [...abs_xs].sort((a, b) => a - b);
  const p_high = Math.max(percentile(sorted, MC_PCT_HIGH), 1e-9);
  return {
    p_high,
    p_low: -p_high,
    max_abs: sorted[sorted.length - 1],
    n: abs_xs.length,
  };
}

// Map a signed modeled_congestion value to [-1, 1] using window stats.
//   |v| ≤ floor           → 0 (cream)
//   floor < |v| ≤ p_high  → sign(v) · γ-damped(|v|) into [0, MC_CORE_END]
//   |v| > p_high          → sign(v) · rational tail into [MC_CORE_END, 1]
export function normalizeModeledCongestion(
  value: number | null,
  stats: ModeledCongestionStats
): number {
  if (value == null || !isFinite(value)) return 0;
  const p = stats.p_high;
  if (p <= 0) return 0;
  const floor = p * MC_FLOOR_FRAC;
  const abs = Math.abs(value);
  if (abs <= floor) return 0;
  const sign = Math.sign(value);
  if (abs <= p) {
    const d = (abs - floor) / (p - floor); // 0 at floor, 1 at anchor
    const damped = Math.pow(d, MC_GAMMA);
    return sign * MC_CORE_END * damped;
  }
  // Rational tail: 0 at anchor, 0.5 at 2× anchor, ~0.91 at 11× anchor.
  const x = (abs - p) / p;
  const tail = x / (1 + x);
  return sign * (MC_CORE_END + (1 - MC_CORE_END) * tail);
}

// Diverging blue (−) → cream (0) → red (+). Endpoints match the LMP scale's
// blue (#3b82f6) for palette consistency; red end is the shared "critical"
// crimson (#ef4444) that also drives --mc-accent and --danger.
const MC_BLUE = [59, 130, 246];
const MC_CREAM = [232, 226, 215];
const MC_RED = [239, 68, 68];

export function modeledCongestionColor(norm: number): string {
  const t = Math.max(-1, Math.min(1, norm));
  if (t === 0) return `rgb(${MC_CREAM.join(",")})`;
  const target = t > 0 ? MC_RED : MC_BLUE;
  const mag = Math.abs(t);
  const r = Math.round(MC_CREAM[0] + (target[0] - MC_CREAM[0]) * mag);
  const g = Math.round(MC_CREAM[1] + (target[1] - MC_CREAM[1]) * mag);
  const b = Math.round(MC_CREAM[2] + (target[2] - MC_CREAM[2]) * mag);
  return `rgb(${r},${g},${b})`;
}

// =============================================================================
// Binding proximity (sequential): |flow| / (s_nom · s_max_pu) per bus
// =============================================================================
//
// Sequential [0, 1] — 0 slack, 1 binding. Fixed anchors; no window stats
// because proximity is already bounded and dimensionless. γ > 1 darkens the
// mid range so only 0.9+ ("on the cusp") reads bright.

const PROX_GAMMA = 1.5;

export const BINDING_PROXIMITY_ANCHORS = {
  low: 0,
  high: 1.0,
  ticks: [0, 0.5, 0.9, 1.0] as const,
  gamma: PROX_GAMMA,
};

export function normalizeProximity(v: number | null): number {
  if (v == null || !isFinite(v)) return 0;
  const clamped = Math.max(0, Math.min(1, v));
  return Math.pow(clamped, PROX_GAMMA);
}

// Sequential palette: dim slate → amber → red. Colorblind-safe (avoids the
// pure green→red diverge; monotonic in luminance from dim to bright).
const PROX_LOW = [30, 41, 59]; // slate — slack
const PROX_MID = [234, 179, 8]; // amber — approaching
const PROX_HIGH = [239, 68, 68]; // red — binding

export function bindingProximityColor(norm: number): string {
  const t = Math.max(0, Math.min(1, norm));
  let r: number, g: number, b: number;
  if (t < 0.5) {
    const s = t * 2;
    r = Math.round(PROX_LOW[0] + (PROX_MID[0] - PROX_LOW[0]) * s);
    g = Math.round(PROX_LOW[1] + (PROX_MID[1] - PROX_LOW[1]) * s);
    b = Math.round(PROX_LOW[2] + (PROX_MID[2] - PROX_LOW[2]) * s);
  } else {
    const s = (t - 0.5) * 2;
    r = Math.round(PROX_MID[0] + (PROX_HIGH[0] - PROX_MID[0]) * s);
    g = Math.round(PROX_MID[1] + (PROX_HIGH[1] - PROX_MID[1]) * s);
    b = Math.round(PROX_MID[2] + (PROX_HIGH[2] - PROX_MID[2]) * s);
  }
  return `rgb(${r},${g},${b})`;
}

// =============================================================================
// Cluster tag palette
// =============================================================================
//
// Distinct hues for the 5–7 "tight" anchor clusters surfaced by the scorecard.
// The residual/background cluster (any id not in the tight set) collapses to
// `CLUSTER_GRAY` so it visually recedes.

export const CLUSTER_GRAY = "#3a4451";

const CLUSTER_PALETTE = [
  "#38bdf8", // sky
  "#f97316", // orange
  "#a78bfa", // violet
  "#34d399", // emerald
  "#f472b6", // pink
  "#facc15", // yellow
  "#22d3ee", // cyan
];

// Order tight ids ascending so cluster 1 always claims palette[0].
export function clusterColor(
  clusterId: number | null | undefined,
  tightSet: Set<number>
): string {
  if (clusterId == null || !tightSet.has(clusterId)) return CLUSTER_GRAY;
  const ordered = Array.from(tightSet).sort((a, b) => a - b);
  const idx = ordered.indexOf(clusterId);
  return CLUSTER_PALETTE[
    (idx < 0 ? 0 : idx) % CLUSTER_PALETTE.length
  ];
}
