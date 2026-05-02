import { useEffect, useMemo, useState } from "react";
import type { ValidationResponse, ScatterPoint } from "../../api/types";
import { fetchValidation } from "../../api/client";

interface Props {
  start: Date | null;
  end: Date | null;
}

type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: ValidationResponse }
  | { status: "error"; message: string };

/** Fixed log10 axis bounds — fragility and |basis| both span several orders
 *  of magnitude. These are wide enough to cover anything observed; outliers
 *  clip to the edge rather than skewing the layout. */
const X_LOG_MIN = -4; // 1e-4
const X_LOG_MAX = 2; // 1e2
const Y_LOG_MIN = -2; // $0.01/MWh
const Y_LOG_MAX = 3; // $1000/MWh

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
          Correlation: fragility vs |basis|
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
            accent="var(--frag-high)"
          />
          <RhoTile
            label="Quiet"
            result={data.quiet}
            accent="var(--text-secondary)"
          />
        </div>
        <div className="vp-threshold label">
          congested ≡ n_binding ≥ {data.congested_threshold_n_binding}
        </div>
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
              style={{ background: "var(--frag-high)" }}
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

function ScatterPlot({
  points,
  showCongested,
  showQuiet,
}: {
  points: ScatterPoint[];
  showCongested: boolean;
  showQuiet: boolean;
}) {
  // Project log-space coords to pixel-space. We clip rather than drop so
  // outliers are still represented at the edge of the plot.
  const projected = useMemo(() => {
    const w = PLOT_W - PAD_L - PAD_R;
    const h = PLOT_H - PAD_T - PAD_B;
    return points
      .filter((p) => p.fragility > 0 && p.abs_basis > 0)
      .filter((p) => (p.congested ? showCongested : showQuiet))
      .map((p) => {
        const lx = clamp(Math.log10(p.fragility), X_LOG_MIN, X_LOG_MAX);
        const ly = clamp(Math.log10(p.abs_basis), Y_LOG_MIN, Y_LOG_MAX);
        const x = PAD_L + ((lx - X_LOG_MIN) / (X_LOG_MAX - X_LOG_MIN)) * w;
        const y = PAD_T + h - ((ly - Y_LOG_MIN) / (Y_LOG_MAX - Y_LOG_MIN)) * h;
        return { x, y, congested: p.congested };
      });
  }, [points, showCongested, showQuiet]);

  if (points.length === 0) {
    return <div className="panel-empty label">no observations</div>;
  }

  const xTicks = tickSequence(X_LOG_MIN, X_LOG_MAX);
  const yTicks = tickSequence(Y_LOG_MIN, Y_LOG_MAX);

  return (
    <svg
      width={PLOT_W}
      height={PLOT_H}
      viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
      className="vp-scatter"
    >
      {/* Grid */}
      {xTicks.map((t) => {
        const w = PLOT_W - PAD_L - PAD_R;
        const x = PAD_L + ((t - X_LOG_MIN) / (X_LOG_MAX - X_LOG_MIN)) * w;
        return (
          <line
            key={`xg${t}`}
            x1={x}
            x2={x}
            y1={PAD_T}
            y2={PLOT_H - PAD_B}
            stroke="var(--border)"
            strokeWidth={0.5}
          />
        );
      })}
      {yTicks.map((t) => {
        const h = PLOT_H - PAD_T - PAD_B;
        const y = PAD_T + h - ((t - Y_LOG_MIN) / (Y_LOG_MAX - Y_LOG_MIN)) * h;
        return (
          <line
            key={`yg${t}`}
            x1={PAD_L}
            x2={PLOT_W - PAD_R}
            y1={y}
            y2={y}
            stroke="var(--border)"
            strokeWidth={0.5}
          />
        );
      })}

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
            fill="var(--frag-high)"
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
      {xTicks.map((t) => {
        const w = PLOT_W - PAD_L - PAD_R;
        const x = PAD_L + ((t - X_LOG_MIN) / (X_LOG_MAX - X_LOG_MIN)) * w;
        return (
          <text
            key={`xt${t}`}
            x={x}
            y={PLOT_H - PAD_B + 12}
            fontSize={9}
            fill="var(--text-muted)"
            textAnchor="middle"
            fontFamily="Space Mono"
          >
            1e{t}
          </text>
        );
      })}
      {yTicks.map((t) => {
        const h = PLOT_H - PAD_T - PAD_B;
        const y = PAD_T + h - ((t - Y_LOG_MIN) / (Y_LOG_MAX - Y_LOG_MIN)) * h;
        return (
          <text
            key={`yt${t}`}
            x={PAD_L - 4}
            y={y + 3}
            fontSize={9}
            fill="var(--text-muted)"
            textAnchor="end"
            fontFamily="Space Mono"
          >
            1e{t}
          </text>
        );
      })}

      {/* Axis labels */}
      <text
        x={(PLOT_W + PAD_L - PAD_R) / 2}
        y={PLOT_H - 4}
        fontSize={9}
        fill="var(--text-secondary)"
        textAnchor="middle"
        style={{ letterSpacing: "0.08em", textTransform: "uppercase" }}
      >
        fragility
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
        |basis| $/MWh
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

  if (overall.rho != null) {
    lines.push(
      `Across ${fmtInt(
        overall.n
      )} bus-snapshots, fragility correlates with |basis| at ` +
        `ρ = ${overall.rho.toFixed(3)} (${rhoStrength(overall.rho)}).`
    );
  }

  if (congested.rho != null && quiet.rho != null) {
    const lift = congested.rho - quiet.rho;
    if (lift > 0.05) {
      lines.push(
        `The model performs notably better under congestion (ρ = ${congested.rho.toFixed(
          3
        )}) ` +
          `than during quiet periods (ρ = ${quiet.rho.toFixed(
            3
          )}). The +${lift.toFixed(3)} lift ` +
          `is the signal: fragility carries explanatory power exactly when grid stress is real.`
      );
    } else if (lift < -0.05) {
      lines.push(
        `Surprisingly, correlation is weaker under congestion (ρ = ${congested.rho.toFixed(
          3
        )}) ` +
          `than during quiet periods (ρ = ${quiet.rho.toFixed(
            3
          )}). Either the synthetic topology ` +
          `mismatches real binding constraints, or the congested sample is dominated by atypical events.`
      );
    } else {
      lines.push(
        `Congested and quiet regimes show similar correlation ` +
          `(${congested.rho.toFixed(3)} vs ${quiet.rho.toFixed(
            3
          )}), suggesting fragility tracks ` +
          `|basis| about equally well regardless of binding-constraint count.`
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

function fmtInt(n: number): string {
  return n.toLocaleString("en-US");
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
.vp-threshold {
    color: var(--text-muted);
    font-size: 9px;
    text-align: center;
    margin-top: 2px;
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
