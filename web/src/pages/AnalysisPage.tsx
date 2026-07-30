import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type {
  AnalysisBrief,
  Brief,
  BriefAfterAction,
  BriefBestPair,
  BriefCommonNode,
  BriefConstraint,
  BriefConstraintStats,
  BriefDriver,
  BriefHotspot,
  BriefHour,
  BriefHubDipole,
  BriefHubTriple,
  BriefNode,
  BriefScorecard,
  BriefSpreadDecomposition,
} from "../api/types";
import { fetchAnalysisBrief, fetchAnalysisBriefLatest } from "../api/client";
import HeaderNav from "../components/layout/HeaderNav";
import Tooltip from "../components/ui/Tooltip";
import { mapSettlementPointLink } from "../lib/mapLinks";
import ExplorerScrubber from "../components/playback/ExplorerScrubber";
import { useSharedExplorer } from "../hooks/useSharedExplorer";
import { snapToFrames } from "../hooks/useTimeCursor";
import { formatCT } from "../lib/time";

// The Analysis page (plan/0125): a single-delivery-day Insight Brief rendering
// the 0124 F1–F6 findings for one day, defaulting to the latest. The landing
// call is /analysis/brief/latest — one day's full brief plus `available_dates`,
// the run's day index. "Previous day" / forward step to the neighbor date in
// that index (gaps skipped); "Latest" resets. The selected day lives in the URL
// (?date=YYYY-MM-DD). Every day step past the first fetches the frozen per-day
// endpoint. Reuses ScoreboardPage's shell: HeaderNav topbar carrying provenance,
// a two-pane body, hand-rolled markup, CSS vars, tabular-nums, and the soft-fail
// contract (a day with no brief renders an empty state, never a thrown error).
//
// The body leads with the "what matters" story: an hour selector walking the
// day's 24 hours (default: the day's peak), the F5b best-pair separation with its
// driver waterfall summing to the spread, and the one-line F5a hub-dipole market
// read. A "whole day" mode reads the roll-up. The F6 after-action and the F1–F4
// disclosure families layer on in the following commits. Nothing is re-ranked or
// recomputed here — server values render verbatim.

const fmtDay = (d: string): string =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

const fmtComputed = (iso: string): string =>
  new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });

// The served horizon → a badge. The endpoint coalesces final (t+1) over preview
// (t+2), so the page shows whichever it served for the day.
const HORIZON = {
  1: { label: "Final · t+1", tip: "Served from the final (t+1) artifact — the run's day-ahead horizon." },
  2: { label: "Preview · t+2", tip: "Served from the preview (t+2) artifact — no final horizon exists for this day yet." },
} as const;

// $/MWh formatters. `usd` keeps a leading unicode minus for negatives (no plus
// for positives); `usdSigned` always shows the sign — for deltas/driver
// contributions where the direction is the point.
const usd = (v: number): string => `${v < 0 ? "−" : ""}$${Math.abs(v).toFixed(2)}`;
const usdSigned = (v: number): string =>
  `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const pct = (v: number): string => `${(v * 100).toFixed(0)}%`;

// Split a "NAME|CONTINGENCY" constraint key for the rows that carry only the
// key (the F6 scorecard), mirroring families.py:split_constraint_key.
function splitKey(key: string): { name: string; contingency: string | null } {
  const i = key.indexOf("|");
  return i < 0
    ? { name: key, contingency: null }
    : { name: key.slice(0, i), contingency: key.slice(i + 1) };
}

// An ISO hour key (UTC) → the ERCOT "hour ending" label in Central time. ERCOT
// settles day-ahead by *hour ending*: HE N is the delivery hour spanning
// [N−1:00, N:00) CT, so the hour starting at CT hour h is HE (h+1). To keep the
// HE number from reading as a mismatch against the clock (HE20 is 7–8 PM, not
// 8 PM), the label carries the full clock span: e.g. "HE20 · 7–8 PM CT".
function ctHourEnding(iso: string): { he: number; label: string } {
  const start = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    hourCycle: "h23",
    timeZone: "America/Chicago",
  }).formatToParts(start);
  const startHour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const he = startHour + 1; // 00:00 CT → HE01, 23:00 CT → HE24
  const end = new Date(start.getTime() + 3_600_000);
  const clock = (d: Date) =>
    new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      timeZone: "America/Chicago",
    }).format(d); // e.g. "7 PM"
  const [sNum, sMer] = clock(start).split(" ");
  const [eNum, eMer] = clock(end).split(" ");
  // Collapse a shared meridiem ("7–8 PM"); keep both when it flips ("11 PM–12 AM").
  const span = sMer === eMer ? `${sNum}–${eNum} ${eMer}` : `${sNum} ${sMer}–${eNum} ${eMer}`;
  return { he, label: `HE${he} · ${span} CT` };
}

// A constraint key "NAME|CONTINGENCY" split for display. The brief already
// carries `constraint_name`/`contingency_name`, but drivers/ranks share the
// same {name, contingency} shape, so one renderer suffices.
function ConstraintLabel({
  name,
  contingency,
}: {
  name: string;
  contingency: string | null;
}) {
  return (
    <span className="an-ckey">
      <span className="an-ckey__name">{name}</span>
      {contingency && <span className="an-ckey__cont"> | {contingency}</span>}
    </span>
  );
}

// ── the provenance meta cluster in the topbar ───────────────────────────────
function Provenance({ env }: { env: AnalysisBrief }) {
  const prov = env.brief?.provenance;
  const horizon = env.horizon != null ? HORIZON[env.horizon as 1 | 2] : undefined;
  const coverage = prov?.dam_match_coverage;
  return (
    <>
      <div className="an-meta">
        <span className="an-meta__label label">Run</span>
        <span className="an-meta__val">{env.run_id}</span>
      </div>
      {horizon && (
        <span className="an-meta an-meta--sub">
          <Tooltip className="an-badge" tip={horizon.tip}>
            {horizon.label}
          </Tooltip>
        </span>
      )}
      {coverage != null && (
        <span className="an-meta an-meta--sub">
          <span className="an-meta__label label">
            <Tooltip
              className="an-help"
              tip="Share of the forecast's |μ̂| mass on constraints the DAM feed carries — how much of the day the after-action can actually grade."
            >
              DAM coverage
            </Tooltip>
          </span>
          <span className="an-meta__val">{(coverage * 100).toFixed(0)}%</span>
        </span>
      )}
      {env.computed_at && (
        <span className="an-meta an-meta--sub">
          <span className="an-meta__label label">Computed</span>
          <span className="an-meta__val">{fmtComputed(env.computed_at)}</span>
        </span>
      )}
    </>
  );
}

// ── the driver waterfall (F5b / F5a) ────────────────────────────────────────
// A DOM bar chart of the per-constraint contributions to a spread. The server
// returns the top-K drivers; the remainder is folded into one "Other net
// contribution" row so the bars visibly sum to the spread total. Positive
// drivers push toward the sink (accent), negative ones pull back (danger).
function Waterfall({
  drivers,
  spread,
  totalLabel,
}: {
  drivers: BriefDriver[];
  spread: number;
  totalLabel: string;
}) {
  const shownSum = drivers.reduce((s, d) => s + d.contribution, 0);
  const other = spread - shownSum;
  const rows = [
    ...drivers.map((d) => ({
      key: d.constraint_key,
      name: d.constraint_name,
      contingency: d.contingency_name,
      value: d.contribution,
      other: false,
    })),
    {
      key: "__other__",
      name: "Other net contribution",
      contingency: null,
      value: other,
      other: true,
    },
  ];
  const maxAbs = Math.max(
    ...rows.map((r) => Math.abs(r.value)),
    Math.abs(spread),
    1e-9
  );
  return (
    <div className="an-wf">
      {rows.map((r) => (
        <div key={r.key} className="an-wf__row">
          <span className="an-wf__label">
            {r.other ? (
              <span className="an-wf__other">{r.name}</span>
            ) : (
              <ConstraintLabel name={r.name} contingency={r.contingency} />
            )}
          </span>
          <span className="an-wf__bar-cell">
            <span
              className="an-wf__bar"
              data-sign={r.value >= 0 ? "pos" : "neg"}
              style={{ width: `${(Math.abs(r.value) / maxAbs) * 100}%` }}
            />
          </span>
          <span className="an-wf__val" data-sign={r.value >= 0 ? "pos" : "neg"}>
            {usdSigned(r.value)}
          </span>
        </div>
      ))}
      <div className="an-wf__row an-wf__row--total">
        <span className="an-wf__label an-wf__label--total">{totalLabel}</span>
        <span className="an-wf__bar-cell" />
        <span className="an-wf__val an-wf__val--total">{usdSigned(spread)}</span>
      </div>
    </div>
  );
}

// ── the F5b headline: the best-pair separation story ────────────────────────
function BestPairCard({ bp, hourLabel }: { bp: BriefBestPair; hourLabel: string }) {
  const [showDrivers, setShowDrivers] = useState(true);
  const lead = bp.drivers[0];
  return (
    <section className="an-card">
      <div className="an-card__kicker label">
        What matters — {hourLabel}
      </div>
      <div className="an-card__title label">
        <Tooltip
          className="an-help"
          tip="The largest quality-gated forecast congestion gap between two settlement points this hour — sink (highest) minus source (lowest). Endpoints are DAM-covered and de-duplicated by location; the F5a hub dipole is suppressed so this never re-tells it."
        >
          Largest modeled separation
        </Tooltip>
      </div>

      {/* Read source → sink: congestion rises from the low (source) endpoint to
          the high (sink) one across the spread. Each node links into the map. */}
      <div className="an-pair">
        <div className="an-pair__end">
          <Link className="an-pair__sp an-pair__link" to={mapSettlementPointLink(bp.source.settlement_point)}>
            {bp.source.settlement_point}
          </Link>
          <div className="an-pair__meta label">
            source · {usd(bp.source.cong)}
            {bp.source.sp_type ? ` · ${bp.source.sp_type}` : ""}
          </div>
        </div>
        <div className="an-pair__arrow">→</div>
        <div className="an-pair__end an-pair__end--right">
          <Link className="an-pair__sp an-pair__link" to={mapSettlementPointLink(bp.sink.settlement_point)}>
            {bp.sink.settlement_point}
          </Link>
          <div className="an-pair__meta label">
            sink · {usd(bp.sink.cong)}
            {bp.sink.sp_type ? ` · ${bp.sink.sp_type}` : ""}
          </div>
        </div>
      </div>

      <div className="an-spread">
        <span className="an-spread__num">{usd(bp.spread)}</span>
        <span className="an-spread__unit label">/MWh forecast spread</span>
      </div>
      {lead && (
        <div className="an-dom">
          Top driver{" "}
          <ConstraintLabel name={lead.constraint_name} contingency={lead.contingency_name} />{" "}
          explains {pct(bp.dominance_share)} of it.
        </div>
      )}

      <button
        className="an-disclose"
        onClick={() => setShowDrivers((v) => !v)}
        aria-expanded={showDrivers}
      >
        {showDrivers ? "▾ Drivers" : "▸ Show drivers"}
      </button>
      {showDrivers && (
        <Waterfall
          drivers={bp.drivers}
          spread={bp.spread}
          totalLabel="Forecast spread"
        />
      )}
    </section>
  );
}

// ── the one-line F5a hub-dipole market read ─────────────────────────────────
function HubDipoleLine({ dipole }: { dipole: BriefHubDipole }) {
  if (!dipole.min || !dipole.max) return null;
  const lead = dipole.drivers[0];
  return (
    <div className="an-dipole">
      <span className="label an-dipole__h">
        <Tooltip
          className="an-help"
          tip="Forecast congestion projected onto ERCOT's liquid hubs and load zones — the market-wide north/south read, independent of the localized best pair above."
        >
          Hub spread
        </Tooltip>
      </span>{" "}
      <b>{dipole.max.settlement_point}</b> {usd(dipole.max.cong)} vs{" "}
      <b>{dipole.min.settlement_point}</b> {usd(dipole.min.cong)} ={" "}
      <b>{usd(dipole.spread)}</b>
      {lead && (
        <>
          {" · top driver "}
          <ConstraintLabel name={lead.constraint_name} contingency={lead.contingency_name} />{" "}
          {usdSigned(lead.contribution)}
        </>
      )}
    </div>
  );
}

// ── F6 — the spread decomposition (severity vs reconstruction) ───────────────
// forecast → +Δμ (realized DAM μ through the same S) → +spatial residual → actual
// DAM SPP spread. The two intermediate totals (reconstruction, actual) are the
// milestones; the deltas between them isolate severity error from the spatial
// operator's residual. `actual`/`residual` are null until DAM SPP covers both
// endpoints — then the flow stops at the reconstruction with a pending note.
function SpreadDecomp({ d }: { d: BriefSpreadDecomposition }) {
  const hasActual = d.actual_spread != null && d.spatial_residual != null;
  const row = (
    label: React.ReactNode,
    value: number,
    kind: "total" | "delta"
  ) => (
    <div className={`an-df__row an-df__row--${kind}`}>
      <span className="an-df__label">{label}</span>
      <span className="an-df__val" data-sign={value >= 0 ? "pos" : "neg"}>
        {kind === "delta" ? usdSigned(value) : usd(value)}
      </span>
    </div>
  );
  return (
    <div className="an-df">
      {/* Same source → sink reading as the headline: b (low) → a (high). */}
      <div className="an-df__pair label">
        {d.b} <span className="an-df__sep">→</span> {d.a}
      </div>
      {row("Forecast spread", d.forecast_spread, "total")}
      {row(
        <Tooltip
          className="an-help"
          tip="How much the realized DAM shadow prices differ from the forecast μ̂, pushed through the SAME recovered shift-factor operator — the severity (μ) error, isolated from any spatial error."
        >
          + Δμ (severity)
        </Tooltip>,
        d.delta_mu,
        "delta"
      )}
      {row("Reconstructed (DAM μ)", d.recon_spread, "total")}
      {hasActual ? (
        <>
          {row(
            <Tooltip
              className="an-help"
              tip="What the recovered operator couldn't reconstruct: the gap between the DAM-μ reconstruction and the actual DAM SPP spread — the spatial (SF) residual."
            >
              + spatial residual
            </Tooltip>,
            d.spatial_residual as number,
            "delta"
          )}
          {row("Actual DAM spread", d.actual_spread as number, "total")}
        </>
      ) : (
        <div className="an-df__pending label">
          Actual DAM SPP spread pending for these endpoints.
        </div>
      )}
    </div>
  );
}

// ── F6 — the ranking scorecard (predicted vs realized top-K) ─────────────────
// recall/exact hits + the two error exemplars, then the predicted top-K with its
// realized rank. The hour scorecard carries μ̂/μ_DAM per row; the day roll-up's
// does not, so the μ columns are shown only when present.
function Scorecard({ card }: { card: BriefScorecard }) {
  const hasMu = card.predicted.some(
    (r) => r.mu_forecast != null || r.mu_dam != null
  );
  const miss = splitKey(card.biggest_severity_miss.constraint_key);
  const alarm = splitKey(card.biggest_false_alarm.constraint_key);
  return (
    <div className="an-sc">
      <div className="an-sc__tiles">
        <div className="an-sc__tile">
          <span className="label an-sc__k">
            <Tooltip
              className="an-help"
              tip="Of the predicted top-K constraints, the fraction that were also in the realized top-K — constraint-selection accuracy, independent of rank order."
            >
              Recall@{card.top_k}
            </Tooltip>
          </span>
          <span className="an-sc__v">{pct(card.recall_at_k)}</span>
        </div>
        <div className="an-sc__tile">
          <span className="label an-sc__k">Exact hits</span>
          <span className="an-sc__v">
            {card.exact_hits}/{card.top_k}
          </span>
        </div>
      </div>
      <div className="an-sc__errs">
        <div className="an-sc__err">
          <span className="label an-sc__errk">Biggest severity miss</span>
          <ConstraintLabel name={miss.name} contingency={miss.contingency} />
          <span className="an-sc__rank label">
            pred #{card.biggest_severity_miss.predicted_rank} → real #
            {card.biggest_severity_miss.realized_rank}
          </span>
        </div>
        <div className="an-sc__err">
          <span className="label an-sc__errk">Biggest false alarm</span>
          <ConstraintLabel name={alarm.name} contingency={alarm.contingency} />
          <span className="an-sc__rank label">
            pred #{card.biggest_false_alarm.predicted_rank} → real #
            {card.biggest_false_alarm.realized_rank}
          </span>
        </div>
      </div>
      <div className={`an-sctab${hasMu ? " an-sctab--mu" : ""}`} role="table">
        <div className="an-sctab__head" role="row">
          <span role="columnheader">Constraint</span>
          <span role="columnheader" className="an-sctab__num">Pred</span>
          <span role="columnheader" className="an-sctab__num">Real</span>
          {hasMu && (
            <>
              <span role="columnheader" className="an-sctab__num">μ̂</span>
              <span role="columnheader" className="an-sctab__num">μ DAM</span>
            </>
          )}
        </div>
        {card.predicted.map((r) => {
          const k = splitKey(r.constraint_key);
          return (
            <div key={r.constraint_key} className="an-sctab__row" role="row">
              <span role="cell">
                <ConstraintLabel name={k.name} contingency={k.contingency} />
              </span>
              <span role="cell" className="an-sctab__num">#{r.predicted_rank}</span>
              <span role="cell" className="an-sctab__num">#{r.realized_rank}</span>
              {hasMu && (
                <>
                  <span role="cell" className="an-sctab__num">
                    {r.mu_forecast == null ? "—" : usd(r.mu_forecast)}
                  </span>
                  <span role="cell" className="an-sctab__num">
                    {r.mu_dam == null ? "—" : usd(r.mu_dam)}
                  </span>
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── F6 — the hub triple: forecast / reconstruction / realized + band check ───
function HubTriple({ triples }: { triples: BriefHubTriple[] }) {
  const num = (v: number | null) => (v == null ? "—" : usd(v));
  return (
    <div className="an-htab" role="table">
      <div className="an-htab__head" role="row">
        <span role="columnheader">Hub</span>
        <span role="columnheader" className="an-htab__num">Forecast</span>
        <span role="columnheader" className="an-htab__num">Recon</span>
        <span role="columnheader" className="an-htab__num">Realized</span>
        <span role="columnheader" className="an-htab__num">P10–P90</span>
        <span role="columnheader" className="an-htab__band">Band</span>
      </div>
      {triples.map((t) => (
        <div key={t.settlement_point} className="an-htab__row" role="row">
          <span role="cell" className="an-htab__sp">{t.settlement_point}</span>
          <span role="cell" className="an-htab__num">{num(t.forecast)}</span>
          <span role="cell" className="an-htab__num">{num(t.reconstruction)}</span>
          <span role="cell" className="an-htab__num">{num(t.realized)}</span>
          <span role="cell" className="an-htab__num an-htab__band-range">
            {t.p10 == null || t.p90 == null
              ? "—"
              : `${usd(t.p10)} … ${usd(t.p90)}`}
          </span>
          <span
            role="cell"
            className="an-htab__band"
            data-band={t.in_band == null ? "na" : t.in_band ? "in" : "out"}
          >
            {t.in_band == null ? "—" : t.in_band ? "✓" : "✗"}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── F6 — the after-action section for one hour ───────────────────────────────
function AfterAction({ after }: { after: BriefAfterAction | null }) {
  if (!after) {
    return (
      <section className="an-aa an-aa--pending">
        <div className="an-aa__h label">After DAM · pending</div>
        <p className="an-aa__pend">
          DAM shadow prices for this hour haven't published yet — the forecast is
          graded here once they land.
        </p>
      </section>
    );
  }
  const decomp = after.best_pair_decomposition ?? after.hub_dipole_decomposition;
  const inBand = after.hub_triple.filter((t) => t.in_band === true).length;
  const graded = after.hub_triple.filter((t) => t.in_band != null).length;
  return (
    <section className="an-aa">
      <div className="an-aa__head">
        <div className="an-aa__h label">After DAM · how the forecast graded</div>
        <span className="an-aa__cov label">
          DAM coverage {pct(after.dam_match_coverage)}
        </span>
      </div>
      {decomp && <SpreadDecomp d={decomp} />}
      <Scorecard card={after.scorecard} />
      <details className="an-htab-wrap">
        <summary className="an-htab-sum">
          Hub band check — {inBand}/{graded} hubs inside P10–P90
        </summary>
        <HubTriple triples={after.hub_triple} />
      </details>
    </section>
  );
}

// ── F3 — archetype label derived at render (never a stored fact) ─────────────
// The quantitative stats are the primary evidence (last_mile.md); this label is
// a legible convenience read off them: a large one-sided footprint is broad /
// systemic, a small footprint is a localized pocket, and a footprint with
// meaningful mass on BOTH sides is a strong separator.
function archetype(s: BriefConstraintStats): { label: string; tip: string } {
  const total = s.import_count + s.export_count;
  const minSide = Math.min(s.import_count, s.export_count);
  const balance = total ? minSide / total : 0; // 0 = one-sided, 0.5 = even
  if (s.reach <= 30) {
    return {
      label: "Localized pocket",
      tip: "Small footprint (few meaningful members) — its influence is concentrated on one location, not the system.",
    };
  }
  if (balance >= 0.2) {
    return {
      label: "Strong separator",
      tip: "Meaningful shift-factor mass on both the import and export sides — it pushes some nodes up while pulling others down.",
    };
  }
  return {
    label: "Broad / systemic",
    tip: "Large footprint moving mostly one direction — importance comes from breadth, not a single sharp pocket.",
  };
}

// ── F2 — a constraint's import- or export-side node extrema ──────────────────
function NodeList({ nodes, side }: { nodes: BriefNode[]; side: "import" | "export" }) {
  return (
    <div className="an-nodes">
      <div className="an-nodes__h label">
        {side} · SF {side === "import" ? "< 0" : "> 0"}
      </div>
      {nodes.length === 0 && <div className="an-nodes__none label">none</div>}
      {nodes.map((n) => (
        <div key={n.settlement_point} className="an-nodes__row">
          <span className="an-nodes__sp">{n.settlement_point}</span>
          <span className="an-nodes__sf">{n.sf.toFixed(3)}</span>
          <span className="an-nodes__contrib">{usdSigned(n.contribution)}</span>
        </div>
      ))}
    </div>
  );
}

// ── F1 — one ranked constraint (expands to F2 nodes + F3 stats) ──────────────
function ConstraintRow({ c }: { c: BriefConstraint }) {
  const arch = archetype(c.stats);
  return (
    <details className="an-crow">
      <summary className="an-crow__sum">
        <span className="an-crow__rank">
          <span className="an-crow__rk">h#{c.hour_rank}</span>
          <span className="an-crow__rk an-crow__rk--day">d#{c.daily_rank}</span>
        </span>
        <span className="an-crow__key">
          <ConstraintLabel name={c.constraint_name} contingency={c.contingency_name} />
        </span>
        <span className="an-crow__mu">{usd(c.mu)}</span>
        <span className="an-crow__reach label">reach {c.stats.reach}</span>
        <Tooltip className="an-arch" tip={arch.tip}>
          {arch.label}
        </Tooltip>
      </summary>
      <div className="an-crow__body">
        <div className="an-stats">
          <span><b>{c.stats.import_count}</b> import · <b>{c.stats.export_count}</b> export members</span>
          <span>top-5 share <b>{pct(c.stats.top5_share)}</b></span>
          <span>peak |SF| <b>{c.stats.peak_abs_sf.toFixed(3)}</b></span>
          <span>
            max contrast <b>{usd(c.stats.max_contrast.value)}</b>{" "}
            <span className="label">
              ({c.stats.max_contrast.export_sp} ↔ {c.stats.max_contrast.import_sp})
            </span>
          </span>
        </div>
        <div className="an-nodes__grid">
          <NodeList nodes={c.nodes.import} side="import" />
          <NodeList nodes={c.nodes.export} side="export" />
        </div>
      </div>
    </details>
  );
}

// ── F4 — nodal hotspots (reinforcement vs cancellation) ──────────────────────
function Hotspots({ hotspots }: { hotspots: BriefHotspot[] }) {
  return (
    <div className="an-hot">
      {hotspots.map((h) => {
        const cancel = h.net_gross_ratio < 0.6;
        return (
          <div key={h.settlement_point} className="an-hot__row">
            <span className="an-hot__sp">{h.settlement_point}</span>
            <span className="an-hot__cong">{usd(h.cong)}</span>
            <span className="an-hot__ng">
              <span className="an-hot__meter" aria-hidden="true">
                <span
                  className="an-hot__meter-fill"
                  style={{ width: `${h.net_gross_ratio * 100}%` }}
                />
              </span>
              <Tooltip
                className="an-hot__ratio"
                tip="net ÷ gross: near 1 the constraints all push this node the same way (reinforcement); near 0 they fight over it (cancellation) — a big gross with a small net is itself a finding."
              >
                {h.net_gross_ratio.toFixed(2)} {cancel ? "cancellation" : "reinforcement"}
              </Tooltip>
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── F4 — confluence nodes (in ≥2 constraints' extrema) ───────────────────────
function CommonNodes({ nodes }: { nodes: BriefCommonNode[] }) {
  return (
    <div className="an-cn">
      {nodes.map((n) => (
        <div key={n.settlement_point} className="an-cn__row">
          <span className="an-cn__sp">{n.settlement_point}</span>
          <span className="an-cn__count label">{n.count} constraints</span>
          <span className="an-cn__keys label">{n.constraints.join(", ")}</span>
        </div>
      ))}
    </div>
  );
}

// ── F1–F4 supporting families, behind progressive disclosure ─────────────────
function SupportingDetail({ hour }: { hour: BriefHour }) {
  return (
    <section className="an-support">
      <div className="an-section-h label">Supporting detail</div>

      <details className="an-fam">
        <summary className="an-fam__sum">
          Ranked constraints — this hour ({hour.constraints.length})
        </summary>
        <div className="an-fam__body">
          <div className="an-crow__legend label">
            <Tooltip
              className="an-help"
              tip="Two independent ranks: h# is this hour's footprint (|μ̂|·reach); d# is the whole day's mass. A constraint can lead the hour yet rank differently across the day — the two are never conflated."
            >
              h# hour rank · d# daily rank
            </Tooltip>
            <span> · expand a row for its node extrema and shape stats</span>
          </div>
          {hour.constraints.map((c) => (
            <ConstraintRow key={c.constraint_key} c={c} />
          ))}
        </div>
      </details>

      <details className="an-fam">
        <summary className="an-fam__sum">
          Nodal hotspots ({hour.hotspots.length})
        </summary>
        <div className="an-fam__body">
          <Hotspots hotspots={hour.hotspots} />
        </div>
      </details>

      {hour.common_nodes.length > 0 && (
        <details className="an-fam">
          <summary className="an-fam__sum">
            Confluence nodes ({hour.common_nodes.length})
          </summary>
          <div className="an-fam__body">
            <CommonNodes nodes={hour.common_nodes} />
          </div>
        </details>
      )}
    </section>
  );
}

// ── one hour's story ────────────────────────────────────────────────────────
function HourStory({ hour, hourLabel }: { hour: BriefHour; hourLabel: string }) {
  return (
    <div className="an-story">
      {hour.best_pair ? (
        <BestPairCard bp={hour.best_pair} hourLabel={hourLabel} />
      ) : (
        <div className="an-empty label">
          No gated separation this hour — fewer than two eligible endpoints
          survived the quality gates.
        </div>
      )}
      <AfterAction after={hour.after_action} />
      <HubDipoleLine dipole={hour.hub_dipole} />
      <SupportingDetail hour={hour} />
    </div>
  );
}

// ── the whole-day roll-up ────────────────────────────────────────────────────
function DaySummary({
  brief,
  onPickHour,
}: {
  brief: Brief;
  onPickHour: (isoHour: string) => void;
}) {
  const { day } = brief;
  const peakScore = day.peak_hours.by_hour_score;
  const peakDipole = day.peak_hours.by_dipole_spread;
  return (
    <div className="an-day">
      <section className="an-day__peaks">
        <div className="an-section-h label">Peak hours</div>
        <div className="an-peakrow">
          <button className="an-peak" onClick={() => onPickHour(peakScore)}>
            <span className="label an-peak__k">Biggest footprint</span>
            <span className="an-peak__v">{ctHourEnding(peakScore).label}</span>
          </button>
          <button className="an-peak" onClick={() => onPickHour(peakDipole)}>
            <span className="label an-peak__k">Widest hub spread</span>
            <span className="an-peak__v">{ctHourEnding(peakDipole).label}</span>
          </button>
        </div>
      </section>

      {day.after_action && (
        <section className="an-aa">
          <div className="an-aa__head">
            <div className="an-aa__h label">Day scorecard · after DAM</div>
            {day.after_action.dam_match_coverage != null && (
              <span className="an-aa__cov label">
                DAM coverage {pct(day.after_action.dam_match_coverage)}
              </span>
            )}
          </div>
          <Scorecard card={day.after_action.scorecard} />
        </section>
      )}

      <section>
        <div className="an-section-h label">Daily footprint ranks</div>
        <div className="an-ranks">
          {day.daily_ranks.map((r) => (
            <div key={r.constraint_key} className="an-ranks__row">
              <span className="an-ranks__rank">{r.daily_rank}</span>
              <span className="an-ranks__ckey">
                <ConstraintLabel name={r.constraint_name} contingency={r.contingency_name} />
              </span>
              <span className="an-ranks__score">{r.daily_score.toFixed(1)}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="an-watch">
        <div className="an-section-h label">
          <Tooltip
            className="an-help"
            tip="Constraints and nodes that recur across many hours of the day — the day's persistent structure, not a single-hour spike."
          >
            Watchlist
          </Tooltip>
        </div>
        <div className="an-watch__grid">
          <div>
            <div className="an-watch__h label">Constraints</div>
            {day.watchlist.constraints.length === 0 && (
              <div className="an-watch__none label">none recurred</div>
            )}
            {day.watchlist.constraints.map((c) => (
              <div key={c.constraint_key} className="an-watch__row">
                <span className="an-watch__key">{c.constraint_key}</span>
                <span className="an-watch__hrs label">{c.hours}h</span>
              </div>
            ))}
          </div>
          <div>
            <div className="an-watch__h label">Nodes</div>
            {day.watchlist.nodes.length === 0 && (
              <div className="an-watch__none label">none recurred</div>
            )}
            {day.watchlist.nodes.map((n) => (
              <div key={n.settlement_point} className="an-watch__row">
                <span className="an-watch__key">{n.settlement_point}</span>
                <span className="an-watch__hrs label">{n.hours}h</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

// ── the brief body: mode toggle + hour selector + the story ─────────────────
function BriefView({
  brief,
  selectedHour,
  wholeDay,
  onPickHour,
}: {
  brief: Brief;
  selectedHour: string | null;
  wholeDay: boolean;
  onPickHour: (iso: string) => void;
}) {
  // Controlled by the shared URL time cursor (useTimeCursor): the selected hour
  // and the whole-day flag now live in the URL, driven by the bottom
  // TimeTransport — so Analysis reads "when" exactly the way Map and Matrix do.
  // This component just renders the selected slice.
  const hour = selectedHour ? brief.hours[selectedHour] : null;
  const hourLabel = selectedHour ? ctHourEnding(selectedHour).label : "";
  return (
    <div className="an-brief">
      {wholeDay ? (
        <DaySummary brief={brief} onPickHour={onPickHour} />
      ) : hour ? (
        <HourStory hour={hour} hourLabel={hourLabel} />
      ) : (
        <div className="an-empty label">no hour available for this day.</div>
      )}
    </div>
  );
}

// Inline defined term — the dotted-underline word whose definition rides the
// shared Tooltip, matching ScoreboardPage's `Term`.
function Term({ children, def }: { children: React.ReactNode; def: React.ReactNode }) {
  return (
    <Tooltip as="span" className="an-term" placement="bottom" tip={def}>
      {children}
    </Tooltip>
  );
}

// ── right-rail glossary: plain-language read of the brief's vocabulary ───────
function Glossary() {
  return (
    <aside className="an-guide">
      <div className="an-guide__block">
        <div className="an-guide__h">What this page is</div>
        <p className="an-guide__p">
          One delivery day's <b>Insight Brief</b> — a server-computed reading of
          the forecast that leads with the single most consequential spatial{" "}
          <Term def="Two settlement points whose forecast congestion prices pull hardest apart this hour — the sink (highest) and the source (lowest). The gap between them is the spread.">
            separation
          </Term>
          , explains which constraints drive it, and — once the day-ahead market
          publishes — grades what actually happened. Nothing here is re-ranked in
          your browser; every figure is served.
        </p>
      </div>

      <div className="an-guide__block">
        <div className="an-guide__h">The separation story</div>
        <dl className="an-guide__dl">
          <dt>Spread</dt>
          <dd>
            The forecast congestion gap between the sink and source, in $/MWh —
            the largest quality-gated one this hour.
          </dd>
          <dt>
            <Term def="A binding transmission constraint whose shadow price moves these two nodes apart. Each driver's contribution is −(SF_sink − SF_source)·μ.">
              Driver
            </Term>
          </dt>
          <dd>
            A constraint pushing the two endpoints apart. The{" "}
            <b>waterfall</b> lists each driver's contribution; they sum exactly to
            the spread (the un-listed remainder is folded into "Other").
          </dd>
          <dt>Dominance</dt>
          <dd>The leading driver's share of the whole spread.</dd>
          <dt>
            <Term def="Congestion projected onto ERCOT's liquid hubs and load zones — the market-wide read, independent of the localized best pair.">
              Hub spread
            </Term>
          </dt>
          <dd>
            The north/south market read across the canonical hubs — separate from
            the localized best pair above.
          </dd>
        </dl>
      </div>

      <div className="an-guide__block">
        <div className="an-guide__h">After DAM (the grade)</div>
        <p className="an-guide__p">
          Once day-ahead shadow prices land, the realized μ is pushed through the{" "}
          <b>same</b> recovered shift-factor operator, so error splits cleanly:
        </p>
        <dl className="an-guide__dl">
          <dt>Δμ (severity)</dt>
          <dd>
            How far the realized shadow prices moved the spread — the μ error,
            with the spatial operator held fixed.
          </dd>
          <dt>Spatial residual</dt>
          <dd>
            What the recovered operator couldn't reconstruct — the gap left to the
            actual DAM SPP spread.
          </dd>
          <dt>
            <Term def="Of the predicted top-K constraints, the fraction that landed in the realized top-K. Selection accuracy, independent of order.">
              Recall@K
            </Term>
          </dt>
          <dd>Did the forecast flag the constraints that mattered?</dd>
          <dt>Band check</dt>
          <dd>
            Whether each hub's realized congestion fell inside the forecast
            P10–P90 — the calibration test.
          </dd>
        </dl>
      </div>

      <div className="an-guide__block">
        <div className="an-guide__h">Supporting detail</div>
        <dl className="an-guide__dl">
          <dt>Hour rank vs daily rank</dt>
          <dd>
            A constraint's footprint this exact hour vs its whole-day mass — kept
            as distinct columns because "rank 1 this hour" and "rank 2 all day"
            are different statements.
          </dd>
          <dt>Archetype</dt>
          <dd>
            A convenience label read off the shape stats — <i>broad / systemic</i>{" "}
            (large one-sided footprint), <i>strong separator</i> (mass on both
            sides), <i>localized pocket</i> (small footprint). The stats are the
            real evidence; the label is derived, not stored.
          </dd>
          <dt>
            <Term def="net ÷ gross for a node: near 1, every constraint pushes it the same way (reinforcement); near 0, they cancel — a large gross with a small net is itself a finding.">
              net / gross
            </Term>
          </dt>
          <dd>
            Whether the constraints stacking on a hotspot reinforce or cancel each
            other.
          </dd>
        </dl>
      </div>
    </aside>
  );
}

export default function AnalysisPage() {
  const [searchParams] = useSearchParams();
  const urlDate = searchParams.get("date");
  // Shared explorer: the live session drives the scrubber and the URL time
  // coordinate; `cursor` is that coordinate. On Analysis the cursor also selects
  // the day — the shown day is the cursor hour's Central-time date (empty when
  // that day has no brief).
  const { session, cursor } = useSharedExplorer();

  // The landing call: latest day's brief + the run's day index. Fetched once;
  // null on 503 (no forecast run published — soft-fail).
  const [latest, setLatest] = useState<AnalysisBrief | null>(null);
  const [indexLoaded, setIndexLoaded] = useState(false);
  useEffect(() => {
    let live = true;
    fetchAnalysisBriefLatest().then((res) => {
      if (!live) return;
      setLatest(res);
      setIndexLoaded(true);
    });
    return () => {
      live = false;
    };
  }, []);

  const availableDates = useMemo(
    () => latest?.available_dates ?? [],
    [latest]
  );
  const latestDate = latest?.delivery_date ?? null;

  // What day the coordinate asks for, and whether a brief exists for it. A
  // cursor hour from another day (e.g. arriving from the Map) resolves to ITS
  // day — if that day has no brief we show an explicit empty state rather than
  // silently falling back to the latest. With no coordinate at all we land on
  // the latest available day. `selectedDate` is null (→ nothing fetched) when
  // the requested day is unavailable.
  const cursorDay = cursor.t ? formatCT(cursor.t, "yyyy-MM-dd") : null;
  const requestedDay = cursorDay ?? urlDate ?? latestDate;
  const dayAvailable =
    requestedDay != null && availableDates.includes(requestedDay);
  const selectedDate = dayAvailable ? requestedDay : null;

  // The selected day's brief. Reuse the latest envelope when the selection is
  // the latest day, so the landing view never double-fetches.
  const [dayEnv, setDayEnv] = useState<AnalysisBrief | null>(null);
  const [dayLoading, setDayLoading] = useState(false);
  useEffect(() => {
    if (!selectedDate) {
      // Requested day has no brief — clear any stale envelope so the empty state
      // shows instead of the previously-loaded day.
      setDayEnv(null);
      setDayLoading(false);
      return;
    }
    if (latest && selectedDate === latestDate) {
      setDayEnv(latest);
      setDayLoading(false);
      return;
    }
    let live = true;
    setDayLoading(true);
    fetchAnalysisBrief(selectedDate).then((res) => {
      if (!live) return;
      setDayEnv(res);
      setDayLoading(false);
    });
    return () => {
      live = false;
    };
  }, [selectedDate, latest, latestDate]);

  const loading = !indexLoaded || (selectedDate != null && dayLoading);
  const env = dayEnv;

  // The shown day's brief (null when unavailable). The hour view renders the
  // brief hour nearest the cursor — cursor.t is within this day, so that is just
  // its hour; before the session has set a cursor, default to the day's peak.
  const brief = env?.available ? env.brief ?? null : null;
  const hourKeys = useMemo(
    () => (brief ? Object.keys(brief.hours).sort() : []),
    [brief]
  );
  const frames = useMemo(() => hourKeys.map((k) => new Date(k)), [hourKeys]);
  const peakKey = brief?.day.peak_hours.by_hour_score ?? null;
  const snapped = snapToFrames(cursor.t, frames);
  const hourIdx =
    cursor.t && snapped >= 0
      ? snapped
      : peakKey
        ? Math.max(0, hourKeys.indexOf(peakKey))
        : 0;
  const selectedHour = hourKeys[hourIdx] ?? null;

  return (
    <div className="an-page">
      <header className="an-topbar">
        <HeaderNav active="analysis" />
        {env?.available && selectedDate && (
          <>
            <div className="an-daynav-wrap">
              <span className="an-daylabel">{fmtDay(selectedDate)}</span>
            </div>
            <Provenance env={env} />
          </>
        )}
      </header>

      <div className="an-body">
        <main className="an-main">
          {loading && <div className="an-empty label">loading…</div>}

          {/* 503 soft-fail: no forecast run published at all. */}
          {!loading && indexLoaded && !latest && (
            <div className="an-empty label">no forecast run is published yet.</div>
          )}

          {/* The coordinate points to a day with no brief in this run — say so,
              rather than silently showing a different day. */}
          {!loading && latest && !dayAvailable && (
            <div className="an-empty label">
              No Insight Brief for{" "}
              {requestedDay ? fmtDay(requestedDay) : "this day"} — this run has no
              analysis for that day.
            </div>
          )}

          {/* Day is in the index but the fetch came back unavailable. */}
          {!loading && latest && dayAvailable && env && !env.available && (
            <div className="an-empty label">
              no Insight Brief for{" "}
              {selectedDate ? fmtDay(selectedDate) : "this day"}.
            </div>
          )}

          {/* The brief for the selected day: the "what matters" story. */}
          {!loading && brief && (
            <BriefView
              brief={brief}
              selectedHour={selectedHour}
              wholeDay={cursor.wholeDay}
              onPickHour={(iso) => {
                cursor.setWholeDay(false);
                cursor.setT(new Date(iso));
              }}
            />
          )}
        </main>

        {/* Right rail — plain-language glossary for the brief's vocabulary. */}
        <Glossary />
      </div>

      {/* The shared explorer scrubber — the same control (Load Window + play +
          step + spark) as Map and Matrix — always present, even with no brief so
          you can keep scrolling to a day that has one; the whole-day toggle rides
          in its right slot. */}
      <ExplorerScrubber
        session={session}
        rightSlot={
          <button
            className="an-wholeday"
            aria-pressed={cursor.wholeDay}
            onClick={() => cursor.setWholeDay(!cursor.wholeDay)}
          >
            {cursor.wholeDay ? "● Whole day" : "○ Whole day"}
          </button>
        }
      />

      <style>{`
        .an-page {
          height: 100%;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: var(--bg-base);
          color: var(--text-primary);
          font-variant-numeric: tabular-nums;
        }
        .an-topbar {
          display: flex; align-items: center; gap: 14px;
          height: var(--header-h);
          padding: 0 16px;
          background: var(--bg-panel);
          border-bottom: 1px solid var(--border);
          position: sticky; top: 0; z-index: 2;
          flex-wrap: nowrap;
        }
        .an-daynav-wrap { margin-left: auto; }
        .an-daylabel {
          font-size: 13px; color: var(--text-primary);
          font-family: var(--font-label); letter-spacing: var(--track-label);
        }
        .an-daynav { display: flex; align-items: center; gap: 8px; }
        .an-daynav__btn, .an-daynav__latest {
          background: var(--bg-surface); color: var(--text-primary);
          border: 1px solid var(--border); border-radius: 3px;
          padding: 4px 10px; font-size: 12px; font-family: var(--font-label);
          letter-spacing: var(--track-label); cursor: pointer;
        }
        .an-daynav__btn:hover:not(:disabled),
        .an-daynav__latest:hover:not(:disabled) {
          background: var(--bg-hover); border-color: var(--border-bright);
        }
        .an-daynav__btn:disabled, .an-daynav__latest:disabled {
          opacity: 0.4; cursor: default;
        }
        .an-daynav__cur {
          font-size: 13px; color: var(--text-primary);
          min-width: 128px; text-align: center;
        }
        .an-daynav__latest { color: var(--text-secondary); }

        .an-meta { display: flex; align-items: baseline; gap: 6px; }
        .an-meta--sub { align-items: center; }
        .an-meta__label { color: var(--text-muted); }
        .an-meta__val {
          font-family: var(--font-mono);
          font-size: 12px; color: var(--text-secondary);
        }
        .an-help { color: var(--text-muted); cursor: help; text-decoration: underline dotted; text-underline-offset: 2px; }
        .an-badge {
          font-family: var(--font-label); font-size: 11px;
          letter-spacing: var(--track-label);
          color: var(--accent);
          border: 1px solid var(--border-bright); border-radius: 3px;
          padding: 2px 7px; cursor: help;
        }

        .an-body { flex: 1; min-height: 0; display: flex; align-items: stretch; }
        .an-main { flex: 5 1 0; min-width: 0; overflow-y: auto; padding-bottom: 40px; }
        .an-guide {
          flex: 2 1 0; min-width: var(--panel-w);
          overflow-y: auto;
          border-left: 1px solid var(--border);
        }
        .an-empty { padding: 40px 16px; text-align: center; color: var(--text-secondary); }
        .an-wholeday {
          background: var(--bg-surface); color: var(--text-secondary);
          border: 1px solid var(--border); border-radius: 4px;
          padding: 6px 12px; font-size: 12px; cursor: pointer;
          font-family: var(--font-label); letter-spacing: var(--track-label);
          white-space: nowrap;
        }
        .an-wholeday[aria-pressed="true"] { color: var(--accent); border-color: var(--border-bright); }
        .an-section-h {
          padding: 14px 16px 6px;
          display: block;
        }

        /* shared: a constraint key rendered as name | contingency */
        .an-ckey { white-space: nowrap; }
        .an-ckey__name { color: var(--text-primary); font-family: var(--font-mono); }
        .an-ckey__cont { color: var(--text-muted); font-family: var(--font-mono); }

        /* mode toggle + hour selector */
        .an-modebar {
          display: flex; align-items: center; gap: 14px;
          padding: 12px 16px 4px; flex-wrap: wrap;
        }
        .an-seg { display: inline-flex; border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
        .an-seg button {
          background: var(--bg-surface); color: var(--text-secondary);
          border: none; padding: 5px 12px; font-size: 12px;
          font-family: var(--font-label); letter-spacing: var(--track-label);
          cursor: pointer;
        }
        .an-seg button + button { border-left: 1px solid var(--border); }
        .an-seg button.active { background: var(--bg-hover); color: var(--accent); }
        .an-hoursel { display: inline-flex; align-items: center; gap: 6px; }
        .an-hoursel__step {
          background: var(--bg-surface); color: var(--text-primary);
          border: 1px solid var(--border); border-radius: 3px;
          padding: 3px 8px; font-size: 11px; cursor: pointer;
        }
        .an-hoursel__step:disabled { opacity: 0.4; cursor: default; }
        .an-hoursel__select {
          background: var(--bg-surface); color: var(--text-primary);
          border: 1px solid var(--border); border-radius: 3px;
          padding: 4px 8px; font-size: 13px; font-family: inherit;
        }

        /* the F5b headline card */
        .an-story { padding: 4px 0; }
        .an-card {
          margin: 8px 16px; padding: 16px 18px;
          background: var(--bg-panel); border: 1px solid var(--border);
          border-radius: 6px;
        }
        .an-card__kicker { color: var(--text-muted); display: block; }
        .an-card__title {
          display: block; margin-top: 2px;
          font-size: 15px; color: var(--text-secondary);
          letter-spacing: normal; text-transform: none;
        }
        .an-card__title .an-help { color: var(--text-secondary); }
        .an-pair {
          display: flex; align-items: center; gap: 14px;
          margin: 12px 0 4px; flex-wrap: wrap;
        }
        .an-pair__end { min-width: 0; }
        .an-pair__end--right { text-align: right; }
        .an-pair__sp { font-size: 20px; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono); }
        .an-pair__link { text-decoration: none; cursor: pointer; }
        .an-pair__link:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 3px; }
        .an-pair__meta { color: var(--text-muted); margin-top: 2px; }
        .an-pair__arrow { font-size: 22px; color: var(--text-secondary); }

        .an-spread { margin-top: 10px; display: flex; align-items: baseline; gap: 8px; }
        .an-spread__num { font-size: 34px; font-weight: 700; line-height: 1; color: var(--text-primary); }
        .an-spread__unit { color: var(--text-secondary); }
        .an-dom { margin-top: 6px; font-size: 13.5px; color: var(--text-secondary); }

        .an-disclose {
          margin-top: 12px; background: none; border: none;
          color: var(--accent); font-size: 12px; font-family: var(--font-label);
          letter-spacing: var(--track-label); cursor: pointer; padding: 0;
        }

        /* the driver waterfall */
        .an-wf { margin-top: 10px; display: grid; grid-template-columns: minmax(140px, 220px) 1fr minmax(64px, auto); column-gap: 12px; row-gap: 5px; align-items: center; }
        .an-wf__row { display: contents; }
        .an-wf__label { font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; }
        .an-wf__other { color: var(--text-muted); font-style: italic; }
        .an-wf__bar-cell { position: relative; height: 12px; background: var(--bg-surface); border-radius: 2px; }
        .an-wf__bar { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 2px; min-width: 1px; }
        .an-wf__bar[data-sign="pos"] { background: var(--accent); }
        .an-wf__bar[data-sign="neg"] { background: var(--danger); }
        .an-wf__val { text-align: right; font-size: 12.5px; font-family: var(--font-mono); }
        .an-wf__val[data-sign="pos"] { color: var(--text-primary); }
        .an-wf__val[data-sign="neg"] { color: var(--danger); }
        .an-wf__row--total { margin-top: 4px; }
        .an-wf__label--total, .an-wf__val--total {
          font-weight: 700; color: var(--text-primary);
          border-top: 1px solid var(--border-bright); padding-top: 5px;
        }
        .an-wf__val--total { font-family: var(--font-mono); }

        /* the F5a one-liner */
        .an-dipole {
          margin: 10px 16px 4px; padding: 10px 14px;
          font-size: 13px; line-height: 1.5; color: var(--text-secondary);
          background: var(--bg-surface); border-radius: 4px;
          border-left: 2px solid var(--border-bright);
        }
        .an-dipole__h { color: var(--text-muted); }
        .an-dipole b { color: var(--text-primary); font-family: var(--font-mono); font-weight: 600; }

        /* day summary */
        .an-day { padding: 4px 0 8px; }
        .an-peakrow { display: flex; gap: 12px; padding: 0 16px; flex-wrap: wrap; }
        .an-peak {
          flex: 1; min-width: 160px; text-align: left;
          background: var(--bg-panel); border: 1px solid var(--border);
          border-radius: 4px; padding: 8px 12px; cursor: pointer;
        }
        .an-peak:hover { border-color: var(--border-bright); background: var(--bg-hover); }
        .an-peak__k { display: block; color: var(--text-muted); }
        .an-peak__v { display: block; margin-top: 3px; font-size: 15px; color: var(--text-primary); }

        .an-ranks { padding: 0 16px; }
        .an-ranks__row {
          display: grid; grid-template-columns: 28px 1fr auto;
          column-gap: 12px; align-items: baseline;
          padding: 4px 0; border-bottom: 1px solid var(--border);
        }
        .an-ranks__rank { color: var(--text-muted); font-size: 12px; text-align: right; }
        .an-ranks__score { font-family: var(--font-mono); font-size: 13px; color: var(--text-secondary); }

        .an-watch { }
        .an-watch__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; padding: 0 16px; }
        .an-watch__h { display: block; color: var(--text-muted); margin-bottom: 4px; }
        .an-watch__row { display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; }
        .an-watch__key { font-family: var(--font-mono); font-size: 12.5px; color: var(--text-primary); }
        .an-watch__hrs { color: var(--text-muted); }
        .an-watch__none { color: var(--text-muted); }

        /* F6 — the after-action section */
        .an-aa {
          margin: 8px 16px; padding: 14px 16px;
          background: var(--bg-panel); border: 1px solid var(--border);
          border-radius: 6px;
        }
        .an-aa__head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
        .an-aa__h { color: var(--text-secondary); }
        .an-aa__cov { margin-left: auto; color: var(--text-muted); }
        .an-aa--pending { border-style: dashed; }
        .an-aa__pend { margin: 6px 0 0; font-size: 13px; color: var(--text-muted); line-height: 1.5; }

        /* spread-decomposition flow */
        .an-df {
          margin-top: 12px; padding: 10px 12px;
          background: var(--bg-surface); border-radius: 4px;
          max-width: 460px;
        }
        .an-df__pair { color: var(--text-muted); margin-bottom: 6px; font-family: var(--font-mono); letter-spacing: normal; }
        .an-df__sep { color: var(--text-secondary); }
        .an-df__row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; padding: 3px 0; }
        .an-df__row--total { font-weight: 700; }
        .an-df__row--total + .an-df__row--delta { border-top: none; }
        .an-df__row--total .an-df__label, .an-df__row--total .an-df__val { color: var(--text-primary); }
        .an-df__row--delta { padding-left: 12px; }
        .an-df__label { font-size: 13px; color: var(--text-secondary); }
        .an-df__val { font-family: var(--font-mono); font-size: 13px; }
        .an-df__row--delta .an-df__val[data-sign="pos"] { color: var(--ok); }
        .an-df__row--delta .an-df__val[data-sign="neg"] { color: var(--danger); }
        .an-df__pending { padding: 4px 0 0; color: var(--text-muted); font-style: italic; }

        /* ranking scorecard */
        .an-sc { margin-top: 14px; }
        .an-sc__tiles { display: flex; gap: 12px; flex-wrap: wrap; }
        .an-sc__tile {
          background: var(--bg-surface); border: 1px solid var(--border);
          border-radius: 4px; padding: 6px 14px; min-width: 96px;
        }
        .an-sc__k { display: block; color: var(--text-muted); }
        .an-sc__v { font-size: 22px; font-weight: 700; color: var(--text-primary); }
        .an-sc__errs { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; }
        .an-sc__err { font-size: 13px; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
        .an-sc__errk { color: var(--text-muted); min-width: 150px; }
        .an-sc__rank { color: var(--text-secondary); }

        .an-sctab { margin-top: 12px; display: grid; row-gap: 2px; }
        /* 3-column default (day roll-up: no μ); the μ variant adds two columns
           for the hour scorecard's μ̂ / μ_DAM. */
        .an-sctab__head, .an-sctab__row {
          display: grid;
          grid-template-columns: minmax(150px, 1fr) 52px 52px;
          column-gap: 10px; align-items: baseline;
        }
        .an-sctab--mu .an-sctab__head, .an-sctab--mu .an-sctab__row {
          grid-template-columns: minmax(150px, 1fr) 52px 52px 78px 78px;
        }
        .an-sctab__head { padding-bottom: 4px; border-bottom: 1px solid var(--border); }
        .an-sctab__head span { font-family: var(--font-label); font-size: 11px; letter-spacing: var(--track-label); color: var(--text-muted); }
        .an-sctab__row { padding: 3px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
        .an-sctab__num { text-align: right; font-family: var(--font-mono); color: var(--text-secondary); }

        /* hub-triple band table (behind a disclosure) */
        .an-htab-wrap { margin-top: 12px; }
        .an-htab-sum { cursor: pointer; font-size: 12px; color: var(--accent); font-family: var(--font-label); letter-spacing: var(--track-label); }
        .an-htab { margin-top: 8px; display: grid; row-gap: 2px; overflow-x: auto; }
        .an-htab__head, .an-htab__row {
          display: grid;
          grid-template-columns: minmax(96px, 1fr) 74px 74px 74px 132px 44px;
          column-gap: 10px; align-items: baseline;
        }
        .an-htab__head { padding-bottom: 4px; border-bottom: 1px solid var(--border); }
        .an-htab__head span { font-family: var(--font-label); font-size: 11px; letter-spacing: var(--track-label); color: var(--text-muted); }
        .an-htab__row { padding: 3px 0; border-bottom: 1px solid var(--border); font-size: 12.5px; }
        .an-htab__sp { font-family: var(--font-mono); color: var(--text-primary); }
        .an-htab__num { text-align: right; font-family: var(--font-mono); color: var(--text-secondary); }
        .an-htab__band-range { color: var(--text-muted); }
        .an-htab__band { text-align: center; }
        .an-htab__band[data-band="in"] { color: var(--ok); }
        .an-htab__band[data-band="out"] { color: var(--danger); }
        .an-htab__band[data-band="na"] { color: var(--text-muted); }

        /* F1–F4 supporting families (behind disclosure) */
        .an-support { margin-top: 6px; }
        .an-fam { margin: 0 16px 6px; border: 1px solid var(--border); border-radius: 5px; background: var(--bg-panel); }
        .an-fam__sum {
          cursor: pointer; padding: 9px 12px; font-size: 13px;
          font-family: var(--font-label); letter-spacing: var(--track-label);
          color: var(--text-secondary); list-style: none;
        }
        .an-fam__sum::-webkit-details-marker { display: none; }
        .an-fam__sum::before { content: "▸ "; color: var(--text-muted); }
        .an-fam[open] > .an-fam__sum::before { content: "▾ "; }
        .an-fam[open] > .an-fam__sum { border-bottom: 1px solid var(--border); color: var(--text-primary); }
        .an-fam__body { padding: 10px 12px; }

        .an-crow__legend { color: var(--text-muted); margin-bottom: 8px; display: block; }
        .an-crow { border-bottom: 1px solid var(--border); }
        .an-crow__sum {
          cursor: pointer; list-style: none; padding: 6px 0;
          display: grid; grid-template-columns: 70px minmax(140px, 1fr) 68px auto auto;
          column-gap: 10px; align-items: baseline;
        }
        .an-crow__sum::-webkit-details-marker { display: none; }
        .an-crow__rank { display: flex; gap: 5px; }
        .an-crow__rk { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary); }
        .an-crow__rk--day { color: var(--text-muted); }
        .an-crow__mu { text-align: right; font-family: var(--font-mono); font-size: 13px; color: var(--text-secondary); }
        .an-crow__reach { color: var(--text-muted); text-align: right; }
        .an-arch {
          font-family: var(--font-label); font-size: 10.5px;
          letter-spacing: var(--track-label); color: var(--text-secondary);
          border: 1px solid var(--border); border-radius: 3px;
          padding: 1px 6px; cursor: help; white-space: nowrap;
        }
        .an-crow__body { padding: 6px 0 10px; }
        .an-stats {
          display: flex; flex-wrap: wrap; gap: 6px 18px;
          font-size: 12.5px; color: var(--text-secondary); margin-bottom: 10px;
        }
        .an-stats b { color: var(--text-primary); font-family: var(--font-mono); font-weight: 600; }

        .an-nodes__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .an-nodes__h { display: block; color: var(--text-muted); margin-bottom: 4px; text-transform: capitalize; }
        .an-nodes__none { color: var(--text-muted); }
        .an-nodes__row { display: grid; grid-template-columns: 1fr 56px 64px; column-gap: 8px; padding: 2px 0; font-size: 12px; }
        .an-nodes__sp { font-family: var(--font-mono); color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; }
        .an-nodes__sf { text-align: right; font-family: var(--font-mono); color: var(--text-muted); }
        .an-nodes__contrib { text-align: right; font-family: var(--font-mono); color: var(--text-secondary); }

        /* F4 hotspots */
        .an-hot__row { display: grid; grid-template-columns: minmax(110px, 1fr) 74px minmax(150px, 220px); column-gap: 12px; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--border); font-size: 12.5px; }
        .an-hot__sp { font-family: var(--font-mono); color: var(--text-primary); }
        .an-hot__cong { text-align: right; font-family: var(--font-mono); color: var(--text-secondary); }
        .an-hot__ng { display: flex; align-items: center; gap: 8px; }
        .an-hot__meter { position: relative; flex: 1; height: 6px; background: var(--danger); opacity: 0.9; border-radius: 3px; overflow: hidden; }
        .an-hot__meter-fill { position: absolute; left: 0; top: 0; bottom: 0; background: var(--ok); }
        .an-hot__ratio { font-size: 11px; color: var(--text-secondary); cursor: help; white-space: nowrap; }

        /* F4 confluence nodes */
        .an-cn__row { display: grid; grid-template-columns: minmax(110px, auto) 110px 1fr; column-gap: 12px; align-items: baseline; padding: 3px 0; border-bottom: 1px solid var(--border); font-size: 12.5px; }
        .an-cn__sp { font-family: var(--font-mono); color: var(--text-primary); }
        .an-cn__count { color: var(--text-secondary); }
        .an-cn__keys { color: var(--text-muted); font-family: var(--font-mono); font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        /* right-rail glossary (mirrors ScoreboardPage's sb-guide) */
        .an-guide__block + .an-guide__block { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--border); }
        .an-guide__block:first-child { padding-top: 4px; }
        .an-guide__h { display: block; margin: 0 0 10px; font-size: 16px; font-weight: 600; line-height: 1.25; color: var(--text-primary); }
        .an-guide__p { font-size: 13.5px; line-height: 1.5; color: var(--text-secondary); margin: 0; }
        .an-guide__p b { color: var(--text-primary); }
        .an-guide__dl { margin: 0; }
        .an-guide__dl dt { font-size: 13.5px; font-weight: 700; color: var(--text-primary); margin-top: 8px; }
        .an-guide__dl dt:first-child { margin-top: 0; }
        .an-guide__dl dd { margin: 1px 0 0; font-size: 13.5px; line-height: 1.5; color: var(--text-secondary); }
        .an-guide__dl dd b { color: var(--text-primary); }
        .an-term { text-decoration: underline dotted; text-underline-offset: 2px; cursor: help; outline: none; }
        .an-guide { padding: 14px 16px 24px; }

        @media (max-width: 900px) {
          .an-page { overflow-y: auto; }
          .an-body { flex-direction: column; min-height: 0; }
          .an-main { overflow: visible; padding-bottom: 0; }
          .an-guide {
            flex-basis: auto; width: 100%; min-width: 0; overflow: visible;
            border-left: none; border-top: 1px solid var(--border);
          }
        }
        @media (max-width: 767px) {
          .an-topbar { flex-wrap: wrap; height: auto; padding: 8px 16px; gap: 8px; }
          .an-daynav-wrap { margin-left: 0; }
        }
      `}</style>
    </div>
  );
}
