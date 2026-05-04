// Fragility color scale

// TODO: revisit calibration once we have a wider data sample. Current
// thresholds are guesses from a slice of synthetic data — top observed value was
// ~30, noise floor ~1e-10.

// Approach: log scale, fixed absolute anchors. Stable across timesteps
// and queries — "red" means the same thing in March as it does in July.

const FRAGILITY_FLOOR = 1e-6; // below this → green (noise / no signal)
const FRAGILITY_RED = 100; // saturates at this value

export const FRAGILITY_ANCHORS = {
  floor: FRAGILITY_FLOOR,
  red: FRAGILITY_RED,
  // Decade tick marks for legend (log scale)
  ticks: [1e-6, 1e-4, 1e-2, 1, 100],
};

// Fragility: 0 → green, 0.5 → yellow, 1 → red
export function fragilityColor(norm: number): string {
  const t = Math.max(0, Math.min(1, norm));

  let r: number, g: number, b: number;
  if (t < 0.5) {
    const s = t * 2;
    r = Math.round(34 + (234 - 34) * s);
    g = Math.round(197 + (179 - 197) * s);
    b = Math.round(94 + (8 - 94) * s);
  } else {
    const s = (t - 0.5) * 2;
    r = Math.round(234 + (220 - 234) * s);
    g = Math.round(179 + (38 - 179) * s);
    b = Math.round(8 + (38 - 8) * s);
  }
  return `rgb(${r},${g},${b})`;
}

// Map raw fragility values → [0, 1] using a fixed log scale.
// Values below FRAGILITY_FLOOR clamp to 0 (green).
// Values above FRAGILITY_RED clamp to 1 (red).
export function normalizeFragility(
  buses: Array<{ bus_id: string; fragility: number | null }>
): Map<string, number> {
  const logFloor = Math.log10(FRAGILITY_FLOOR);
  const logRed = Math.log10(FRAGILITY_RED);
  const logRange = logRed - logFloor;

  const map = new Map<string, number>();
  for (const b of buses) {
    const v = b.fragility ?? 0;
    if (v <= FRAGILITY_FLOOR) {
      map.set(b.bus_id, 0);
    } else {
      const norm = (Math.log10(v) - logFloor) / logRange;
      map.set(b.bus_id, Math.min(1, Math.max(0, norm)));
    }
  }
  return map;
}

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
