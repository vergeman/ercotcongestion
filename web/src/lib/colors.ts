// =============================================================================
// Data palettes.
// =============================================================================
//
// Sign is carried by hue (blue↔red, emerald↔magenta); the endpoints stay legible
// on white and near-black alike. What DOES flip with the theme is the diverging
// *center* + endpoint depth: on the dark ground the near-white cream center glows,
// but on the white light-map ground that cream vanishes — the low/mid-congestion
// majority reads as nothing — so light gets a visible cool-grey center and
// deepened endpoints. The theme is read via currentTheme(); GridMap re-runs its
// node-color effect on a theme flip so the map repaints.
//
// Map *chrome* — labels, halos, node strokes, the state boundary — flips via the
// --map-* tokens in index.css.
//
// (The sequential binding-proximity ramp used to live here and could not survive
// a ground flip, since a sequential scale encodes magnitude as luminance. It was
// removed with the IBP pipeline; see plan/0097-compute-pipeline-remove-ibp.md.)

import { currentTheme, type Theme } from "./theme";

// Diverging endpoint/center triples. `_LIGHT` variants swap the pale cream for a
// cool grey that separates from the white map ground and deepen the hue ends.
const rgb = (c: readonly number[]) => `rgb(${c[0]},${c[1]},${c[2]})`;
function rgbMix(from: readonly number[], to: readonly number[], m: number): string {
  const k = Math.max(0, Math.min(1, m));
  return rgb([
    Math.round(from[0] + (to[0] - from[0]) * k),
    Math.round(from[1] + (to[1] - from[1]) * k),
    Math.round(from[2] + (to[2] - from[2]) * k),
  ]);
}
// Shared cool-grey neutral for every light-mode diverging center.
// The old neutral was dark enough that the many near-zero nodes became their
// own dense visual network on white. This quieter blue-grey preserves a visible
// midpoint without competing with meaningful forecast-error color.
const NEUTRAL_LIGHT = [216, 222, 230];

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
// blue (oversupply) ↔ neutral (nominal) ↔ orange (scarcity).
const LMP_BLUE = [59, 130, 246];
const LMP_CREAM = [226, 232, 200];
const LMP_ORANGE = [249, 115, 22];
const LMP_BLUE_LIGHT = [47, 111, 214];
const LMP_ORANGE_LIGHT = [217, 102, 15];

export function lmpColor(norm: number, theme: Theme = currentTheme()): string {
  const light = theme === "light";
  const cold = light ? LMP_BLUE_LIGHT : LMP_BLUE;
  const mid = light ? NEUTRAL_LIGHT : LMP_CREAM;
  const warm = light ? LMP_ORANGE_LIGHT : LMP_ORANGE;
  const t = Math.max(0, Math.min(1, norm));
  return t < 0.5 ? rgbMix(cold, mid, t * 2) : rgbMix(mid, warm, (t - 0.5) * 2);
}

// =============================================================================
// Congestion (diverging): signed Σ PTDF·μ per bus
// =============================================================================
//
// Diverging blue↔cream↔red centered at 0.
//   norm > 0  → import side, red
//   norm < 0  → export side, blue
//   norm ≈ 0  → cream (no signal)
//
// Window-percentile anchors (mirrors LmpStats): p_high = percentile(|mc|, 0.90);
// p_low = −p_high so the palette is symmetric around zero. γ damping flattens
// the cream band so noise near zero stays neutral. The normal scale retains its
// rational tail; exceptionally high positive congestion is marked separately
// with an alarm color so it cannot flatten the rest of the day.

// P90 (not P99) so the anchor is set by "typical binding hours," not by a
// single scarcity event. On a multi-day window one $400+ mc value at P99
// pushes normal-hour buses (|mc| = $30–$90) into the damped cream band.
// P90 leaves the tail's darkest pixels for the outlier hours (they still
// ride the rational tail past MC_CORE_END) while giving mid-range values
// visible saturation.
const MC_PCT_HIGH = 0.9;
// γ closer to 1 keeps the sensitivity roughly linear from floor to anchor.
// The old γ = 1.8 combined with a P99 anchor was doubly damping: it took
// both the anchor stretch and a strong power curve on top, so a $36 bus
// against a $400 P99 rendered near-cream.
const MC_GAMMA = 1.2;
// |mc| = p_high maps to |norm| = MC_CORE_END; the remaining band is the
// compressed normal tail for values above the core.
const MC_CORE_END = 0.9;
// Values with |mc| below this fraction of p_high read as cream (no signal).
// Small floor — a diverging signal at 2% of the window's top percentile is
// still meaningful; a heavier floor would wash out the map.
const MC_FLOOR_FRAC = 0.02;
// A discrete alarm bin reserves a categorical signal for rare scarcity nodes
// without changing the P90 scale that keeps ordinary values readable.
export const CONGESTION_ALARM_MULTIPLIER = 3;

export interface CongestionStats {
  p_high: number; // percentile(|mc|, MC_PCT_HIGH); positive
  p_low: number; // −p_high (symmetric)
  min: number; // observed negative daily extreme; 0 when no negative values
  max: number; // observed positive daily extreme; 0 when no positive values
  n: number;
}

export const CONGESTION_ANCHORS = {
  pct_high: MC_PCT_HIGH,
  gamma: MC_GAMMA,
  core_end: MC_CORE_END,
  floor_frac: MC_FLOOR_FRAC,
};

// Compute window-wide congestion stats. Pass a flat array of all observed
// congestion values across every (bus, snapshot) pair.
export function computeCongestionStats(
  values: Array<number | null | undefined>
): CongestionStats {
  const abs_xs: number[] = [];
  let min = 0;
  let max = 0;
  for (const v of values) {
    if (v == null || !isFinite(v)) continue;
    abs_xs.push(Math.abs(v));
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (abs_xs.length === 0) {
    return { p_high: 1, p_low: -1, min: 0, max: 0, n: 0 };
  }
  const sorted = [...abs_xs].sort((a, b) => a - b);
  const p_high = Math.max(percentile(sorted, MC_PCT_HIGH), 1e-9);
  return {
    p_high,
    p_low: -p_high,
    min,
    max,
    n: abs_xs.length,
  };
}

// Map a signed congestion value to [-1, 1] using window stats.
//   |v| ≤ floor           → 0 (cream)
//   floor < |v| ≤ p_high  → sign(v) · γ-damped(|v|) into [0, MC_CORE_END]
//   |v| > p_high          → sign(v) · rational tail into [MC_CORE_END, 1]
export function normalizeCongestion(
  value: number | null,
  stats: CongestionStats
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

export function congestionAlarmThreshold(stats: CongestionStats): number {
  return stats.p_high * CONGESTION_ALARM_MULTIPLIER;
}

// Scarcity is operationally asymmetric: a huge positive import-side price is
// the alarm condition. Negative congestion stays on its signed blue scale.
export function isCongestionAlarm(
  value: number | null,
  stats: CongestionStats
): boolean {
  return value != null && isFinite(value) && value >= congestionAlarmThreshold(stats);
}

// Diverging blue (−) → cream (0) → red (+). Endpoints match the LMP scale's
// blue (#3b82f6) for palette consistency; red end is the shared "critical"
// crimson (#ef4444) that also drives --mc-accent and --danger.
const MC_BLUE = [59, 130, 246];
const MC_CREAM = [232, 226, 215];
const MC_RED = [239, 68, 68];
const MC_BLUE_LIGHT = [47, 111, 214];
const MC_RED_LIGHT = [214, 59, 59];
// Electric yellow reads as a categorical "beyond red" alarm on both map
// grounds. It intentionally sits away from the red/blue signed metric axis.
const MC_ALARM = "#fef08a";
const MC_ALARM_LIGHT = "#ca8a04";

export function congestionAlarmColor(theme: Theme = currentTheme()): string {
  return theme === "light" ? MC_ALARM_LIGHT : MC_ALARM;
}

export function congestionColor(
  norm: number,
  theme: Theme = currentTheme()
): string {
  const light = theme === "light";
  const neg = light ? MC_BLUE_LIGHT : MC_BLUE;
  const mid = light ? NEUTRAL_LIGHT : MC_CREAM;
  const pos = light ? MC_RED_LIGHT : MC_RED;
  const t = Math.max(-1, Math.min(1, norm));
  return rgbMix(mid, t > 0 ? pos : neg, Math.abs(t));
}

// =============================================================================
// Shift-factor role palette
// =============================================================================
//
// Import/export is a structural role within one selected constraint, not a
// congestion, price, or forecast-error sign. Keep it off the metric blue↔red
// axis so exploring a constraint never reverses the apparent meaning of a map
// fill. Soft magenta marks the importing/expensive end (SF < 0); teal marks
// the exporting/trapped end (SF >= 0).
export const SF_IMPORT_COLOR = "#d382ae";
export const SF_EXPORT_COLOR = "#4aa892";

export function shiftFactorColor(sf: number): string {
  return sf < 0 ? SF_IMPORT_COLOR : SF_EXPORT_COLOR;
}

// =============================================================================
// Forecast error (diverging): P50 forecast − realized congestion
// =============================================================================
//
// Same diverging math as congestionColor, but a DIFFERENT hue axis on
// purpose. Forecast error is not a temperature or a source/sink quantity, so it
// must not borrow the blue↔red of congestion / LMP. Emerald ↔ cream ↔ magenta
// also sits clear of the quieter SF-overlay annotation family (lavender clouds,
// violet corridors, teal radials).
//   norm > 0 → over-forecast  (predicted > realized, magenta)
//   norm < 0 → under-forecast (predicted < realized, emerald)
//   norm ≈ 0 → cream (on target — shares the neutral with congestion)
// Reach/SF glow deliberately uses the separate shift-factor role palette: it
// must not imply a forecast-error or congestion sign.
const ERROR_EMERALD = [52, 211, 153]; // under-forecast (−) — brighter emerald-400
const ERROR_CREAM = MC_CREAM; // on target (0)
const ERROR_MAGENTA = [244, 114, 182]; // over-forecast (+) — brighter pink-400
const ERROR_EMERALD_LIGHT = [16, 185, 129]; // vivid emerald-500 on the white ground
const ERROR_MAGENTA_LIGHT = [236, 72, 153]; // vivid pink-500 on the white ground

// TRIAL (plan/0112): reuse the congestion blue↔red ramp for forecast error, so it
// reads on the same familiar axis (blue = under-forecast, red = over-forecast).
// Flip to false to use the distinct emerald↔magenta set (ERROR_* anchors) if
// this reads worse.
const ERROR_USE_CONGESTION: boolean = true;

function errorAnchors(theme: Theme) {
  const light = theme === "light";
  if (ERROR_USE_CONGESTION) {
    return {
      neg: light ? MC_BLUE_LIGHT : MC_BLUE, // under-forecast (−) → blue
      mid: light ? NEUTRAL_LIGHT : MC_CREAM,
      pos: light ? MC_RED_LIGHT : MC_RED, // over-forecast (+) → red
    };
  }
  return {
    neg: light ? ERROR_EMERALD_LIGHT : ERROR_EMERALD,
    mid: light ? NEUTRAL_LIGHT : ERROR_CREAM,
    pos: light ? ERROR_MAGENTA_LIGHT : ERROR_MAGENTA,
  };
}

export function forecastErrorColor(
  norm: number,
  theme: Theme = currentTheme()
): string {
  const { neg, mid, pos } = errorAnchors(theme);
  const t = Math.max(-1, Math.min(1, norm));
  return rgbMix(mid, t > 0 ? pos : neg, Math.abs(t));
}

// The forecast-error legend bar, kept in lockstep with forecastErrorColor's
// endpoints — theme-aware so the light bar matches the light map fills.
export function forecastErrorGradientCss(theme: Theme = currentTheme()): string {
  const { neg, mid, pos } = errorAnchors(theme);
  return `linear-gradient(to right, ${rgb(neg)}, ${rgb(mid)}, ${rgb(pos)})`;
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
