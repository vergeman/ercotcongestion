// Data palettes for map values and annotations.

import { currentTheme, type Theme } from "./theme";

const rgb = (c: readonly number[]) => `rgb(${c[0]},${c[1]},${c[2]})`;
function rgbMix(from: readonly number[], to: readonly number[], m: number): string {
  const k = Math.max(0, Math.min(1, m));
  return rgb([
    Math.round(from[0] + (to[0] - from[0]) * k),
    Math.round(from[1] + (to[1] - from[1]) * k),
    Math.round(from[2] + (to[2] - from[2]) * k),
  ]);
}
// Light-map neutral that remains visible on a white background.
const NEUTRAL_LIGHT = [216, 222, 230];

// LMP colors: blue for low prices and orange for high prices.
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
  hasLocalExtreme: boolean;
}


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
  return n ? { min, max, n, hasLocalExtreme: false } : { min: 0, max: 0, n: 0, hasLocalExtreme: false };
}

export function normalizeLmpFromStats(value: number | null): number {
  return normalizeLmp(value);
}

export function localExtremeThreshold(
  values: Array<number | null | undefined>,
  positiveOnly = false
): number | null {
  const valid = values.filter(
    (value): value is number => value != null && isFinite(value) && (!positiveOnly || value > 0)
  ).sort((a, b) => b - a);
  if (!valid.length) return null;
  const threshold = valid[Math.max(0, Math.ceil(valid.length * 0.01) - 1)];
  return threshold >= EXTREME_PRICE_THRESHOLD ? threshold : null;
}

export function isLocalExtreme(value: number | null, threshold: number | null): boolean {
  return value != null && isFinite(value) && threshold != null && value >= threshold;
}

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

export interface CongestionStats {
  min: number;
  max: number;
  n: number;
  hasLocalExtreme: boolean;
}

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
  return { min, max, n, hasLocalExtreme: false };
}

export function normalizeCongestion(value: number | null): number {
  if (value == null || !isFinite(value)) return 0;
  const abs = Math.abs(value);
  return abs <= 10 ? 0 : Math.sign(value) * scalePosition(abs, CONGESTION_SCALE_CONTROLS);
}

// Congestion: blue for export-side and red for import-side values.
const MC_BLUE = [59, 130, 246];
const MC_CREAM = [232, 226, 215];
const MC_RED = [239, 68, 68];
const MC_BLUE_LIGHT = [47, 111, 214];
const MC_RED_LIGHT = [214, 59, 59];
export function congestionAlarmColor(theme: Theme = currentTheme()): string {
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

// Shift-factor signs use a separate negative/positive palette.
export const SF_NEGATIVE_COLOR = "#d382ae";
export const SF_POSITIVE_COLOR = "#4aa892";

export function shiftFactorColor(sf: number): string {
  return sf < 0 ? SF_NEGATIVE_COLOR : SF_POSITIVE_COLOR;
}

// Forecast error is forecast minus realized congestion.
const ERROR_EMERALD = [52, 211, 153]; // under-forecast
const ERROR_CREAM = MC_CREAM; // on target
const ERROR_MAGENTA = [244, 114, 182]; // over-forecast
const ERROR_EMERALD_LIGHT = [16, 185, 129];
const ERROR_MAGENTA_LIGHT = [236, 72, 153];

const ERROR_USE_CONGESTION: boolean = true;

function errorAnchors(theme: Theme) {
  const light = theme === "light";
  if (ERROR_USE_CONGESTION) {
    return {
      neg: light ? MC_BLUE_LIGHT : MC_BLUE,
      mid: light ? NEUTRAL_LIGHT : MC_CREAM,
      pos: light ? MC_RED_LIGHT : MC_RED,
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

export function forecastErrorGradientCss(theme: Theme = currentTheme()): string {
  const { neg, mid, pos } = errorAnchors(theme);
  return `linear-gradient(to right, ${rgb(neg)}, ${rgb(mid)}, ${rgb(pos)})`;
}

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
