import { useEffect, useMemo, useState } from "react";
import type { ValidationResponse, ScatterPoint } from "../../api/types";
import { fetchValidation } from "../../api/client";

interface Props {
  /** Start/end of the currently-loaded playback window. Drives the fetch. */
  start: Date | null;
  end: Date | null;
}

type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: ValidationResponse }
  | { status: "error"; message: string };

/** Symlog on both axes: sign(v) * log10(1 + |v|). Zero lines + 45°/135°
 *  perfect-agreement guides. Bounds cover the observed range on both sides;
 *  outliers clip to the edge rather than skewing the layout. */
const AXIS_MIN = -3; // symlog units (~ -$1000/MWh)
const AXIS_MAX = 3;

const SYMLOG_C = 1; // $/MWh — knee of the symlog transform

const PLOT_W = 280;
const PLOT_H = 220;
const PAD_L = 36;
const PAD_R = 8;
const PAD_T = 8;
const PAD_B = 28;

export default function ValidationPanel({ start, end }: Props) {
  const [state, setState] = useState<FetchState>({ status: "idle" });
  const [showCongested, setShowCongested] = useState(true);
  const [showQuiet, setShowQuiet] = useState(true);

  useEffect(() => {
    if (!start || !end) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    fetchValidation(start, end)
      .then((data) => {
        if (!cancelled) setState({ status: "ok", data });
      })
      .catch((err) => {
        if (!cancelled) setState({ status: "error", message: String(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [start, end]);

  if (state.status === "idle") {
    return (
      <Shell>
        <div className="panel-empty label">load a window to validate</div>
      </Shell>
    );
  }
  if (state.status === "loading") {
    return (
      <Shell>
        <div className="panel-empty label">computing correlation…</div>
      </Shell>
    );
  }
  if (state.status === "error") {
    return (
      <Shell>
        <div className="panel-empty label" style={{ color: "var(--danger)" }}>
          {state.message}
        </div>
      </Shell>
    );
  }

  const { data } = state;

  return (
    <Shell>
      <div className="panel-section">
        <div className="panel-section__header label">Window</div>
        <div className="vp-window mono">
          {fmtDate(data.start)} → {fmtDate(data.end)}
        </div>
        <div className="vp-counts label">
          {data.n_snapshots} snapshots · {fmtInt(data.n_observations)}{" "}
          observations
        </div>
      </div>

      {data.warnings.length > 0 && (
        <div className="panel-section vp-warnings">
          {data.warnings.map((w, i) => (
            <div key={i} className="vp-warning">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      <div className="panel-section">
        <div className="panel-section__header label">
          Correlation: modeled congestion vs basis (signed)
        </div>
        <div className="vp-rho-grid">
          <RhoTile
            label="Overall"
            result={data.overall}
            accent="var(--accent)"
          />
          <RhoTile
            label="Congested"
            result={data.congested}
            accent="var(--mc-accent)"
          />
          <RhoTile
            label="Quiet"
            result={data.quiet}
            accent="var(--text-secondary)"
          />
        </div>
        <div className="vp-sign-agreement mono">
          sign-agreement: {fmtSignAgreement(data.sign_agreement_overall)} overall
          · {fmtSignAgreement(data.sign_agreement_congested)} congested
        </div>
        <div className="vp-threshold label">
          congested ≡ n_binding ≥ {data.congested_threshold_n_binding}
        </div>
      </div>

      <div className="panel-section">
        <div className="panel-section__header label">By load zone</div>
        <ZoneBreakdown byZone={data.by_zone} />
      </div>

      <div className="panel-section">
        <div className="panel-section__header label">Scatter (log–log)</div>
        <ScatterPlot
          points={data.scatter}
          showCongested={showCongested}
          showQuiet={showQuiet}
        />
        <div className="vp-legend">
          <button
            className={`vp-chip ${showCongested ? "on" : ""}`}
            onClick={() => setShowCongested((v) => !v)}
          >
            <span
              className="vp-dot"
              style={{ background: "var(--mc-accent)" }}
            />
            congested
          </button>
          <button
            className={`vp-chip ${showQuiet ? "on" : ""}`}
            onClick={() => setShowQuiet((v) => !v)}
          >
            <span
              className="vp-dot"
              style={{ background: "var(--text-secondary)" }}
            />
            quiet
          </button>
        </div>
      </div>

      <div className="panel-section">
        <div className="panel-section__header label">Interpretation</div>
        <Interpretation data={data} />
      </div>

      <style>{styles}</style>
    </Shell>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="validation-panel">{children}</div>;
}

function RhoTile({
  label,
  result,
  accent,
}: {
  label: string;
  result: { n: number; rho: number | null };
  accent: string;
}) {
  const rhoStr = result.rho == null ? "—" : result.rho.toFixed(3);
  const strength = rhoStrength(result.rho);
  return (
    <div className="vp-tile">
      <div className="label vp-tile-label">{label}</div>
      <div className="mono vp-tile-rho" style={{ color: accent }}>
        ρ = {rhoStr}
      </div>
      <div className="label vp-tile-meta">
        n={fmtInt(result.n)} · {strength}
      </div>
    </div>
  );
}

// Stable display order — falls back to alphabetical for any zone we don't
// know about (future-proof if a fifth load zone shows up).
const ZONE_ORDER = ["north", "houston", "south", "west"];

function ZoneBreakdown({
  byZone,
}: {
  byZone: Record<string, { n: number; rho: number | null }>;
}) {
  const zones = Object.keys(byZone).sort((a, b) => {
    const ai = ZONE_ORDER.indexOf(a);
    const bi = ZONE_ORDER.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  if (zones.length === 0) {
    return <div className="panel-empty label">no zone data</div>;
  }

  return (
    <div className="vp-zones">
      {zones.map((z) => {
        const r = byZone[z];
        const rho = r.rho;
        // Bar width tracks |ρ|; sign drives color so a negative
        // correlation visually distinguishes itself from a strong one.
        const widthPct = rho == null ? 0 : Math.abs(rho) * 100;
        const color =
          rho == null
            ? "var(--text-muted)"
            : rho >= 0
            ? "var(--accent)"
            : "var(--basis-neg)";
        return (
          <div key={z} className="vp-zone-row">
            <span className="label vp-zone-name">{z}</span>
            <div className="vp-zone-bar-wrap">
              <div
                className="vp-zone-bar"
                style={{ width: `${widthPct}%`, background: color }}
              />
            </div>
            <span className="mono vp-zone-rho" style={{ color }}>
              {rho == null ? "—" : rho.toFixed(3)}
            </span>
            <span className="label vp-zone-n">n={fmtIntCompact(r.n)}</span>
          </div>
        );
      })}
    </div>
  );
}

function ScatterPlot({
  points,
  showCongested,
  showQuiet,
}: {
  points: ScatterPoint[];
  showCongested: boolean;
  showQuiet: boolean;
}) {
  // Project symlog-space coords to pixel-space. We clip rather than drop so
  // outliers are still represented at the edge of the plot.
  const projected = useMemo(() => {
    const w = PLOT_W - PAD_L - PAD_R;
    const h = PLOT_H - PAD_T - PAD_B;
    return points
      .filter((p) => p.modeled_congestion !== 0 && p.basis !== 0)
      .filter((p) => (p.congested ? showCongested : showQuiet))
      .map((p) => {
        const sx = clamp(symlog(p.modeled_congestion), AXIS_MIN, AXIS_MAX);
        const sy = clamp(symlog(p.basis), AXIS_MIN, AXIS_MAX);
        const x = PAD_L + ((sx - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * w;
        const y = PAD_T + h - ((sy - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * h;
        return { x, y, congested: p.congested };
      });
  }, [points, showCongested, showQuiet]);

  if (points.length === 0) {
    return <div className="panel-empty label">no observations</div>;
  }

  const w = PLOT_W - PAD_L - PAD_R;
  const h = PLOT_H - PAD_T - PAD_B;
  const axisToX = (v: number) =>
    PAD_L + ((v - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * w;
  const axisToY = (v: number) =>
    PAD_T + h - ((v - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * h;

  const xTicks = tickSequence(AXIS_MIN, AXIS_MAX);
  const yTicks = tickSequence(AXIS_MIN, AXIS_MAX);

  return (
    <svg
      width={PLOT_W}
      height={PLOT_H}
      viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
      className="vp-scatter"
    >
      {/* Grid */}
      {xTicks.map((t) => (
        <line
          key={`xg${t}`}
          x1={axisToX(t)}
          x2={axisToX(t)}
          y1={PAD_T}
          y2={PLOT_H - PAD_B}
          stroke="var(--border)"
          strokeWidth={0.5}
        />
      ))}
      {yTicks.map((t) => (
        <line
          key={`yg${t}`}
          x1={PAD_L}
          x2={PLOT_W - PAD_R}
          y1={axisToY(t)}
          y2={axisToY(t)}
          stroke="var(--border)"
          strokeWidth={0.5}
        />
      ))}

      {/* Reference lines: axis zeros + y=x (agreement) + y=-x (anti). */}
      <line
        x1={axisToX(0)}
        x2={axisToX(0)}
        y1={PAD_T}
        y2={PLOT_H - PAD_B}
        stroke="var(--border-bright)"
        strokeWidth={0.75}
      />
      <line
        x1={PAD_L}
        x2={PLOT_W - PAD_R}
        y1={axisToY(0)}
        y2={axisToY(0)}
        stroke="var(--border-bright)"
        strokeWidth={0.75}
      />
      <line
        x1={axisToX(AXIS_MIN)}
        y1={axisToY(AXIS_MIN)}
        x2={axisToX(AXIS_MAX)}
        y2={axisToY(AXIS_MAX)}
        stroke="var(--text-muted)"
        strokeWidth={0.5}
        strokeDasharray="2 2"
      />
      <line
        x1={axisToX(AXIS_MIN)}
        y1={axisToY(-AXIS_MIN)}
        x2={axisToX(AXIS_MAX)}
        y2={axisToY(-AXIS_MAX)}
        stroke="var(--text-muted)"
        strokeWidth={0.5}
        strokeDasharray="2 2"
      />

      {/* Points — quiet first so congested draws on top. */}
      {projected
        .filter((p) => !p.congested)
        .map((p, i) => (
          <circle
            key={`q${i}`}
            cx={p.x}
            cy={p.y}
            r={1.4}
            fill="var(--text-secondary)"
            fillOpacity={0.35}
          />
        ))}
      {projected
        .filter((p) => p.congested)
        .map((p, i) => (
          <circle
            key={`c${i}`}
            cx={p.x}
            cy={p.y}
            r={1.6}
            fill="var(--mc-accent)"
            fillOpacity={0.55}
          />
        ))}

      {/* Axes */}
      <line
        x1={PAD_L}
        y1={PLOT_H - PAD_B}
        x2={PLOT_W - PAD_R}
        y2={PLOT_H - PAD_B}
        stroke="var(--border-bright)"
        strokeWidth={1}
      />
      <line
        x1={PAD_L}
        y1={PAD_T}
        x2={PAD_L}
        y2={PLOT_H - PAD_B}
        stroke="var(--border-bright)"
        strokeWidth={1}
      />

      {/* Tick labels */}
      {xTicks.map((t) => (
        <text
          key={`xt${t}`}
          x={axisToX(t)}
          y={PLOT_H - PAD_B + 12}
          fontSize={9}
          fill="var(--text-muted)"
          textAnchor="middle"
          fontFamily="Space Mono"
        >
          {tickLabel(t)}
        </text>
      ))}
      {yTicks.map((t) => (
        <text
          key={`yt${t}`}
          x={PAD_L - 4}
          y={axisToY(t) + 3}
          fontSize={9}
          fill="var(--text-muted)"
          textAnchor="end"
          fontFamily="Space Mono"
        >
          {tickLabel(t)}
        </text>
      ))}

      {/* Axis labels */}
      <text
        x={(PLOT_W + PAD_L - PAD_R) / 2}
        y={PLOT_H - 4}
        fontSize={9}
        fill="var(--text-secondary)"
        textAnchor="middle"
        style={{ letterSpacing: "0.08em", textTransform: "uppercase" }}
      >
        modeled congestion $/MWh (symlog)
      </text>
      <text
        x={-PLOT_H / 2}
        y={10}
        fontSize={9}
        fill="var(--text-secondary)"
        textAnchor="middle"
        transform="rotate(-90)"
        style={{ letterSpacing: "0.08em", textTransform: "uppercase" }}
      >
        basis $/MWh (symlog)
      </text>
    </svg>
  );
}

function Interpretation({ data }: { data: ValidationResponse }) {
  if (data.n_observations === 0) {
    return (
      <p className="vp-prose">No data in this window — load a wider range.</p>
    );
  }

  const { overall, congested, quiet } = data;
  const lines: string[] = [];

  lines.push(
    "Modeled congestion is the OPF's own congestion component — the signed " +
      "Σ PTDF·μ at each bus. When the model says a bus is on the import side " +
      "of a binding constraint (positive), the market's basis at that bus " +
      "should also be positive (LMP above the zone reference). ρ answers " +
      "'does the model agree with the market, in sign and magnitude, when " +
      "the grid is actually stressed?'"
  );

  if (overall.rho != null) {
    lines.push(
      `Across ${fmtInt(
        overall.n
      )} bus-snapshots, signed modeled congestion tracks signed basis at ` +
        `ρ = ${overall.rho.toFixed(3)} (${rhoStrength(overall.rho)}). ` +
        `Direction is the first-order read; magnitude is a screening signal, ` +
        `not a P&L predictor.`
    );
  }

  if (congested.rho != null && quiet.rho != null) {
    const lift = congested.rho - quiet.rho;
    if (lift > 0.05) {
      lines.push(
        `The model sharpens under congestion (ρ = ${congested.rho.toFixed(3)}) ` +
          `vs quiet periods (ρ = ${quiet.rho.toFixed(3)}). ` +
          `The +${lift.toFixed(3)} lift is the signal: modeled congestion ` +
          `agrees with the market exactly when the grid is actually stressed.`
      );
    } else if (lift < -0.05) {
      lines.push(
        `Surprisingly, correlation is weaker under congestion ` +
          `(ρ = ${congested.rho.toFixed(3)}) than during quiet periods ` +
          `(ρ = ${quiet.rho.toFixed(3)}). Either the synthetic topology ` +
          `mismatches real binding constraints, or the congested sample is ` +
          `dominated by atypical events.`
      );
    } else {
      lines.push(
        `Congested and quiet regimes agree about equally ` +
          `(${congested.rho.toFixed(3)} vs ${quiet.rho.toFixed(3)}), ` +
          `suggesting modeled congestion tracks basis independent of ` +
          `binding-constraint count.`
      );
    }
  } else if (congested.rho != null) {
    lines.push(
      `Quiet regime had insufficient data; only congested ρ = ${congested.rho.toFixed(
        3
      )} is reliable.`
    );
  } else if (quiet.rho != null) {
    lines.push(
      `No congested snapshots in window; only quiet ρ = ${quiet.rho.toFixed(
        3
      )} is reliable.`
    );
  }

  return (
    <div className="vp-prose">
      {lines.map((line, i) => (
        <p key={i}>{line}</p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}

/** sign(v) * log10(1 + |v| / c). Preserves sign; compresses tails. */
function symlog(v: number, c: number = SYMLOG_C): number {
  return Math.sign(v) * Math.log10(1 + Math.abs(v) / c);
}

function tickLabel(t: number): string {
  if (t === 0) return "0";
  const mag = Math.pow(10, Math.abs(t)) - 1;
  const sign = t < 0 ? "-" : "";
  if (mag >= 1) return `${sign}${Math.round(mag)}`;
  return `${sign}${mag.toFixed(1)}`;
}

function tickSequence(min: number, max: number): number[] {
  const ticks: number[] = [];
  for (let t = min; t <= max; t++) ticks.push(t);
  return ticks;
}

function rhoStrength(rho: number | null): string {
  if (rho == null) return "n/a";
  const a = Math.abs(rho);
  if (a < 0.1) return "negligible";
  if (a < 0.3) return "weak";
  if (a < 0.5) return "moderate";
  if (a < 0.7) return "strong";
  return "very strong";
}

function fmtSignAgreement(x: number | null): string {
  if (x == null) return "—";
  return `${(x * 100).toFixed(1)}%`;
}

function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
}

function fmtIntCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// ---------------------------------------------------------------------------
// Styles — scoped via className prefix to avoid clash with StatsPanel
// ---------------------------------------------------------------------------

const styles = `
.validation-panel {
    width: var(--panel-w);
    height: 100%;
    overflow-y: auto;
    background: var(--bg-panel);
    border-left: 1px solid var(--border);
    display: flex;
    flex-direction: column;
}
.vp-window {
    font-size: 11px;
    color: var(--text-primary);
    margin-bottom: 2px;
}
.vp-counts {
    color: var(--text-muted);
}
.vp-warnings { background: rgba(245, 158, 11, 0.05); }
.vp-warning {
    color: var(--warn);
    font-size: 11px;
    line-height: 1.4;
    margin: 2px 0;
}
.vp-rho-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 6px;
    margin-bottom: 6px;
}
.vp-tile {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 6px 4px;
    text-align: center;
}
.vp-tile-label { color: var(--text-secondary); margin-bottom: 3px; }
.vp-tile-rho { font-size: 13px; font-weight: 700; line-height: 1.1; }
.vp-tile-meta { color: var(--text-muted); margin-top: 3px; font-size: 9px; }
.vp-sign-agreement {
    color: var(--text-secondary);
    font-size: 10px;
    text-align: center;
    margin-top: 4px;
}
.vp-threshold {
    color: var(--text-muted);
    font-size: 9px;
    text-align: center;
    margin-top: 2px;
}
.vp-zones {
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.vp-zone-row {
    display: grid;
    grid-template-columns: 56px 1fr 48px 36px;
    align-items: center;
    gap: 6px;
}
.vp-zone-name {
    color: var(--text-secondary);
    text-transform: capitalize;
    letter-spacing: 0.06em;
}
.vp-zone-bar-wrap {
    height: 6px;
    background: var(--bg-surface);
    border-radius: 3px;
    overflow: hidden;
}
.vp-zone-bar {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s;
}
.vp-zone-rho {
    font-size: 11px;
    font-weight: 700;
    text-align: right;
}
.vp-zone-n {
    color: var(--text-muted);
    text-align: right;
    font-size: 9px;
}
.vp-scatter {
    display: block;
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: 3px;
    margin: 0 auto;
}
.vp-legend {
    display: flex;
    justify-content: center;
    gap: 8px;
    margin-top: 6px;
}
.vp-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10px;
    padding: 3px 8px;
    opacity: 0.5;
}
.vp-chip.on { opacity: 1; }
.vp-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    display: inline-block;
}
.vp-prose p {
    font-size: 11px;
    line-height: 1.5;
    color: var(--text-primary);
    margin-bottom: 6px;
}
.vp-prose p:last-child { margin-bottom: 0; }
`;
