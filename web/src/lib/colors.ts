// Fragility color scale

// Approach: log scale with γ damping in the core range, plus a soft rational
// tail above the red anchor so high-but-finite fragilities stay
// distinguishable without crushing the rest of the scale.
//
// Calibration history:
//   v1 (floor=1e-6, red=100, γ=1) — too sensitive at the low end, values
//   ~1e-3 read yellow despite being negligible; values ≥1 all crushed to red.
//   v2 (floor=0.05, red=10, γ=1.3, hard clamp) — fixed the low end, but
//   everything ≥9 looked identical (no tail handling).
//   v3 (floor=0.05, red=5, γ=1.3, soft log tail) — current. Below 0.05 = green.
//   ~0.6 enters yellow. 5 hits the "critical" red anchor (RED_CORE=0.85).
//   Values above 5 keep darkening via x/(1+x) decade tail, so 9 / 16 / 30 /
//   100 are visibly distinct shades of red without crushing the 0.5–5 ramp.

const FRAGILITY_FLOOR = 0.05; // below this → green (noise / no signal)
const FRAGILITY_RED = 5; // "this bus is critical" anchor
const FRAGILITY_GAMMA = 1.3; // damping in [floor, red]: >1 flattens low end
const FRAGILITY_RED_CORE = 0.85; // RED_ANCHOR maps to this on the color bar,
// reserving 0.15 of color space for the tail

export const FRAGILITY_ANCHORS = {
  floor: FRAGILITY_FLOOR,
  red: FRAGILITY_RED,
  gamma: FRAGILITY_GAMMA,
  red_core: FRAGILITY_RED_CORE,
  // Tick marks for legend. Leftmost label is "0" (cosmetic — the underlying
  // floor is 0.05, but 0 reads more naturally for the green end). Includes
  // the red anchor (5) and a tail value (50) so the user can see the tail
  // compression visually.
  ticks: [0, 0.5, 1, 5, 50],
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

// Map raw fragility values → [0, 1].
//   v ≤ FRAGILITY_FLOOR   → 0          (green)
//   FLOOR < v ≤ RED       → γ-damped log interp into [0, RED_CORE]
//   v > RED               → soft rational tail into [RED_CORE, 1]
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
      continue;
    }
    if (v <= FRAGILITY_RED) {
      const raw = (Math.log10(v) - logFloor) / logRange;
      const damped = Math.pow(Math.max(0, raw), FRAGILITY_GAMMA);
      map.set(
        b.bus_id,
        Math.min(FRAGILITY_RED_CORE, FRAGILITY_RED_CORE * damped)
      );
    } else {
      // Tail: x = decades above the red anchor.
      // x/(1+x) is 0 at the anchor, 0.5 at one decade out, ~0.91 at ten — slow
      // enough that 9 / 16 / 30 / 100 stay distinguishable.
      const x = Math.log10(v) - logRed;
      const tail = x / (1 + x);
      map.set(b.bus_id, FRAGILITY_RED_CORE + (1 - FRAGILITY_RED_CORE) * tail);
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

// =============================================================================
// Rank-delta view ("Δ Rank")
// =============================================================================
//
// For each snapshot, rank every bus by fragility (ascending) and by |basis|
// (ascending), normalize to [0, 1], and compute the signed difference:
//
//   delta = pct_fragility − pct_|basis|
//
//   delta > 0  → fragility rank higher than basis rank (model OVER-estimates)
//   delta < 0  → basis rank higher than fragility rank (model UNDER-estimates)
//   delta ≈ 0  → model and market agree on this bus
//
// Buses missing either fragility or basis are excluded from ranking and
// returned as null (rendered neutral on the map).
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

// Compute per-bus rank-delta for a single snapshot. Returns a Map keyed by
// bus_id; missing entries (excluded buses) map to null.
export function computeRankDelta(
  buses: Array<{
    bus_id: string;
    fragility: number | null;
    basis: number | null;
  }>
): Map<string, number | null> {
  const fragVals = buses.map((b) => b.fragility);
  const absBasisVals = buses.map((b) =>
    b.basis == null ? null : Math.abs(b.basis)
  );

  // Both must be present for a delta; otherwise null.
  const validMask = buses.map((b) => b.fragility != null && b.basis != null);
  const fragMasked: Array<number | null> = fragVals.map((v, i) =>
    validMask[i] ? v : null
  );
  const basisMasked: Array<number | null> = absBasisVals.map((v, i) =>
    validMask[i] ? v : null
  );

  const fragPct = percentileRank(fragMasked);
  const basisPct = percentileRank(basisMasked);

  const out = new Map<string, number | null>();
  for (let i = 0; i < buses.length; i++) {
    const f = fragPct[i];
    const b = basisPct[i];
    if (f == null || b == null) {
      out.set(buses[i].bus_id, null);
    } else {
      out.set(buses[i].bus_id, f - b); // ∈ [-1, 1]
    }
  }
  return out;
}

// Diverging color: purple (−1, model under) → cream (0) → teal (+1, model over).
// Anchors picked from the design palette (c-purple #7F77DD, c-teal #1D9E75)
// with a light cream center distinct from the LMP cream.
const DELTA_NEUTRAL_COLOR = "#1a4731"; // null/missing — same as fragility null
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
// Fragility z-score view
// =============================================================================
//
// Asks "is this bus unusually fragile *relative to its own history* in the
// loaded window?" rather than "is it absolutely high?" — useful for spotting
// anomalies that the absolute fragility view would hide because the bus has
// always been a low-fragility bus.
//
// Stats: per-bus mean + std across every snapshot in the loaded window.
// Computed once on window load, reused for every frame (stable coloring).
//
// Color scale is one-sided: gray for z ≤ 0 (this bus is at-or-below its
// typical) and red for z ≥ 3 (3+ std above typical = anomaly). Below-typical
// buses are dim because "fragility went down" is rarely the question.

export interface BusZStats {
  // Per-bus mean and std of fragility across the loaded window.
  // Buses with <3 observations or near-zero variance are excluded
  // (their map entries are missing).
  perBus: Map<string, { mean: number; std: number }>;
  // Total bus-snapshots that contributed.
  n: number;
}

const Z_MIN_OBS = 3;
const Z_STD_FLOOR = 1e-6;
const Z_SAT = 3; // saturate red at this many std above mean

// Compute per-bus mean+std of fragility from a list of snapshots in the
// loaded window. Each snapshot supplies an array of {bus_id, fragility}.
export function computeBusZStats(
  snapshots: Array<Array<{ bus_id: string; fragility: number | null }>>
): BusZStats {
  // Accumulate sums per bus.
  const acc = new Map<string, { sum: number; sumSq: number; n: number }>();
  let total = 0;

  for (const buses of snapshots) {
    for (const b of buses) {
      const v = b.fragility;
      if (v == null || !isFinite(v)) continue;
      let entry = acc.get(b.bus_id);
      if (!entry) {
        entry = { sum: 0, sumSq: 0, n: 0 };
        acc.set(b.bus_id, entry);
      }
      entry.sum += v;
      entry.sumSq += v * v;
      entry.n += 1;
      total += 1;
    }
  }

  const perBus = new Map<string, { mean: number; std: number }>();
  for (const [busId, e] of acc) {
    if (e.n < Z_MIN_OBS) continue;
    const mean = e.sum / e.n;
    const variance = Math.max(0, e.sumSq / e.n - mean * mean);
    const std = Math.sqrt(variance);
    if (std < Z_STD_FLOOR) continue; // bus is constant → z is undefined
    perBus.set(busId, { mean, std });
  }

  return { perBus, n: total };
}

// Compute z for one bus at the current snapshot.
export function fragilityZ(
  busId: string,
  fragility: number | null,
  stats: BusZStats
): number | null {
  if (fragility == null) return null;
  const s = stats.perBus.get(busId);
  if (!s) return null;
  return (fragility - s.mean) / s.std;
}

// Map z to [0, 1] for color lookup.
//   z ≤ 0   → 0 (gray)
//   z = Z_SAT → 1 (saturated red)
//   z > Z_SAT → 1 (clamp)
export function normalizeZ(z: number | null): number {
  if (z == null || !isFinite(z) || z <= 0) return 0;
  return Math.min(1, z / Z_SAT);
}

// One-sided: gray (#475569) → red (#ef4444). Linear interp in RGB.
const Z_GRAY = [71, 85, 105];
const Z_RED = [239, 68, 68];

export function fragilityZColor(norm: number): string {
  const t = Math.max(0, Math.min(1, norm));
  const r = Math.round(Z_GRAY[0] + (Z_RED[0] - Z_GRAY[0]) * t);
  const g = Math.round(Z_GRAY[1] + (Z_RED[1] - Z_GRAY[1]) * t);
  const b = Math.round(Z_GRAY[2] + (Z_RED[2] - Z_GRAY[2]) * t);
  return `rgb(${r},${g},${b})`;
}

export const Z_ANCHORS = {
  gray: `rgb(${Z_GRAY.join(",")})`,
  red: `rgb(${Z_RED.join(",")})`,
  saturate: Z_SAT,
};
