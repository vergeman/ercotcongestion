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
export const EXTREME_PRICE_THRESHOLD = 500;
type ScaleControl = readonly [value: number, position: number];
export const LMP_SCALE_CONTROLS: readonly ScaleControl[] = [
  [-50, 0], [-20, .14], [0, .3], [10, .4], [20, .46], [25, .5], [30, .54], [40, .6], [50, .65], [60, .69], [75, .74], [100, .8], [125, .84], [150, .87], [175, .895], [200, .915], [225, .93], [250, .945], [300, .965], [350, .978], [400, .987], [450, .994], [500, 1],
];
export const CONGESTION_SCALE_CONTROLS: readonly ScaleControl[] = [
  [10, 0], [25, .2], [50, .42], [75, .58], [100, .7], [125, .78], [150, .84], [175, .88], [200, .91], [225, .93], [250, .945], [300, .965], [350, .978], [400, .987], [450, .994], [500, 1],
];
function scalePosition(value: number, controls: readonly ScaleControl[]): number {
  if (value <= controls[0][0]) return controls[0][1];
  const last = controls[controls.length - 1];
  if (value >= last[0]) return last[1];
  for (let i = 1; i < controls.length; i += 1) {
    const [rightValue, rightPosition] = controls[i];
    if (value <= rightValue) {
      const [leftValue, leftPosition] = controls[i - 1];
      return leftPosition + (value - leftValue) / (rightValue - leftValue) * (rightPosition - leftPosition);
    }
  }
  return last[1];
}
export function normalizeLmp(value: number | null): number {
  return value == null || !isFinite(value) ? .5 : scalePosition(value, LMP_SCALE_CONTROLS);
}

export interface LmpStats {
  min: number;
  max: number;
  n: number;
}


// Compute window-wide LMP stats. Pass a flat array of all observed LMP
// values across every (bus, snapshot) pair in the window.
export function computeLmpStats(
  values: Array<number | null | undefined>
): LmpStats {
  let min = Infinity;
  let max = -Infinity;
  let n = 0;
  for (const v of values) {
    if (v == null || !isFinite(v)) continue;
    min = Math.min(min, v);
    max = Math.max(max, v);
    n += 1;
  }
  return n ? { min, max, n } : { min: 0, max: 0, n: 0 };
}

export function normalizeLmpFromStats(value: number | null): number {
  return normalizeLmp(value);
}

export function isLmpAlarm(value: number | null): boolean {
  return value != null && isFinite(value) && value >= EXTREME_PRICE_THRESHOLD;
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
export interface CongestionStats {
  min: number;
  max: number;
  n: number;
}

// Compute window-wide congestion stats. Pass a flat array of all observed
// congestion values across every (bus, snapshot) pair.
export function computeCongestionStats(
  values: Array<number | null | undefined>
): CongestionStats {
  let min = 0;
  let max = 0;
  let n = 0;
  for (const v of values) {
    if (v == null || !isFinite(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
    n += 1;
  }
  return { min, max, n };
}

export function normalizeCongestion(value: number | null): number {
  if (value == null || !isFinite(value)) return 0;
  const abs = Math.abs(value);
  return abs <= 10 ? 0 : Math.sign(value) * scalePosition(abs, CONGESTION_SCALE_CONTROLS);
}

// Scarcity is operationally asymmetric: a huge positive import-side price is
// the alarm condition. Negative congestion stays on its signed blue scale.
export function isCongestionAlarm(value: number | null): boolean {
  return value != null && isFinite(value) && value >= EXTREME_PRICE_THRESHOLD;
}

// Diverging blue (−) → cream (0) → red (+). Endpoints match the LMP scale's
// blue (#3b82f6) for palette consistency; red end is the shared "critical"
// crimson (#ef4444) that also drives --mc-accent and --danger.
const MC_BLUE = [59, 130, 246];
const MC_CREAM = [232, 226, 215];
const MC_RED = [239, 68, 68];
const MC_BLUE_LIGHT = [47, 111, 214];
const MC_RED_LIGHT = [214, 59, 59];
export function congestionAlarmColor(theme: Theme = currentTheme()): string {
  // The map keeps the normal signed red scale; the animated legend swatch
  // supplies the categorical extreme-price cue without competing with the
  // constraint overlay's gold GTC marks.
  return congestionColor(1, theme);
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
// Forecast error (diverging): forecast − realized congestion
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
