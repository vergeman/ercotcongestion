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
// reused for every frame. Stable across playback (a bus that's at the median
// looks the same in every snapshot), and centered on the *median* rather than
// zero — most TX LMPs cluster at the gas-marginal-cost floor (~$28.55), so the
// median is the natural "neutral" point. Above-median = congestion premium
// (orange), below-median = oversupply / curtailment (blue).
//
// Spread is measured in MAD (median absolute deviation), not std, because
// LMP distributions are heavy-tailed (gas-marginal cluster + scarcity tail) —
// MAD is robust to those tail outliers.
export interface LmpStats {
  median: number;
  mad: number; // median absolute deviation, in $/MWh
  min: number; // observed window min (for legend labels)
  max: number; // observed window max (for legend labels)
  n: number; // number of LMP samples used
}

const MAD_SAT = 6; // saturate at ±6 MAD from median

function median(sorted: number[]): number {
  const n = sorted.length;
  if (n === 0) return 0;
  const mid = Math.floor(n / 2);
  return n % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
}

// Compute median + MAD across an entire window of bus LMPs (every bus, every
// snapshot). Pass a flat array of all observed LMP values.
export function computeLmpStats(
  values: Array<number | null | undefined>
): LmpStats {
  const xs: number[] = [];
  for (const v of values) {
    if (v == null || !isFinite(v)) continue;
    xs.push(v);
  }
  if (xs.length === 0) {
    return { median: 0, mad: 1, min: 0, max: 0, n: 0 };
  }
  const sorted = [...xs].sort((a, b) => a - b);
  const med = median(sorted);
  const absDev = xs.map((v) => Math.abs(v - med)).sort((a, b) => a - b);
  let mad = median(absDev);
  // Guard against degenerate window (all values equal → MAD=0).
  // Fall back to a tiny epsilon so the color function returns 0.5 (cream)
  // instead of dividing by zero.
  if (mad <= 0) mad = 1e-6;
  return {
    median: med,
    mad,
    min: sorted[0],
    max: sorted[sorted.length - 1],
    n: xs.length,
  };
}

// Map an LMP value to [0, 1] using window stats.
//   value === median       → 0.5  (cream)
//   value === median - 6*MAD → 0    (deepest blue)
//   value === median + 6*MAD → 1    (deepest orange)
export function normalizeLmpFromStats(
  value: number | null,
  stats: LmpStats
): number {
  if (value == null) return 0.5;
  const z = (value - stats.median) / stats.mad; // signed MAD-units
  const t = 0.5 + z / (2 * MAD_SAT); // map ±MAD_SAT → ±0.5
  return Math.max(0, Math.min(1, t));
}

export const LMP_MAD_SAT = MAD_SAT;

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
