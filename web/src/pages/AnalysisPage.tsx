import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type {
  AnalysisBrief,
  Brief,
  BriefBestPair,
  BriefDriver,
  BriefHour,
  BriefHubDipole,
} from "../api/types";
import { fetchAnalysisBrief, fetchAnalysisBriefLatest } from "../api/client";
import HeaderNav from "../components/layout/HeaderNav";
import Tooltip from "../components/ui/Tooltip";

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

// $/MWh formatters. `usd` is a bare magnitude; `usdSigned` keeps the driver
// sign (unicode minus, to match the app's numeric styling).
const usd = (v: number): string => `$${v.toFixed(2)}`;
const usdSigned = (v: number): string =>
  `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const pct = (v: number): string => `${(v * 100).toFixed(0)}%`;

// An ISO hour key (UTC) → the ERCOT "hour ending" label in Central time. HE N is
// the hour spanning [N−1:00, N:00) CT, so the delivery hour starting at CT hour h
// is HE (h+1). Returns e.g. { he: 17, clock: "4 PM", label: "HE17 · 4 PM CT" }.
function ctHourEnding(iso: string): { he: number; clock: string; label: string } {
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    hourCycle: "h23",
    timeZone: "America/Chicago",
  }).formatToParts(d);
  const startHour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const he = startHour + 1; // 00:00 CT → HE01, 23:00 CT → HE24
  const clock = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    timeZone: "America/Chicago",
  }).format(d);
  return { he, clock, label: `HE${he} · ${clock} CT` };
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

// ── the day navigator (Previous / Latest / Next), driven by available_dates ──
function DayNav({
  dates,
  current,
  latest,
  onGo,
}: {
  dates: string[];
  current: string;
  latest: string | null;
  onGo: (date: string | null) => void;
}) {
  const idx = dates.indexOf(current);
  const prev = idx > 0 ? dates[idx - 1] : null;
  const next = idx >= 0 && idx < dates.length - 1 ? dates[idx + 1] : null;
  const atLatest = current === latest;
  return (
    <div className="an-daynav">
      <button
        className="an-daynav__btn"
        onClick={() => onGo(prev)}
        disabled={!prev}
        aria-label="Previous day"
      >
        ← Previous
      </button>
      <span className="an-daynav__cur">{fmtDay(current)}</span>
      <button
        className="an-daynav__btn"
        onClick={() => onGo(next)}
        disabled={!next}
        aria-label="Next day"
      >
        Next →
      </button>
      <button
        className="an-daynav__latest"
        onClick={() => onGo(null)}
        disabled={atLatest}
      >
        Latest
      </button>
    </div>
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

      <div className="an-pair">
        <div className="an-pair__end">
          <div className="an-pair__sp">{bp.sink.settlement_point}</div>
          <div className="an-pair__meta label">
            sink · {usd(bp.sink.cong)}
            {bp.sink.sp_type ? ` · ${bp.sink.sp_type}` : ""}
          </div>
        </div>
        <div className="an-pair__arrow">↔</div>
        <div className="an-pair__end an-pair__end--right">
          <div className="an-pair__sp">{bp.source.settlement_point}</div>
          <div className="an-pair__meta label">
            source · {usd(bp.source.cong)}
            {bp.source.sp_type ? ` · ${bp.source.sp_type}` : ""}
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
      <HubDipoleLine dipole={hour.hub_dipole} />
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
function BriefView({ brief }: { brief: Brief }) {
  const hourKeys = useMemo(() => Object.keys(brief.hours).sort(), [brief]);
  const peakKey = brief.day.peak_hours.by_hour_score;

  const [mode, setMode] = useState<"hour" | "day">("hour");
  const [hourKey, setHourKey] = useState<string | null>(null);
  // Keep the selection valid across day navigation: an hour key from the prior
  // day (different date) falls back to this day's peak.
  const selectedHour =
    hourKey && hourKeys.includes(hourKey) ? hourKey : peakKey;
  const hourIdx = hourKeys.indexOf(selectedHour);

  const pickHour = (iso: string) => {
    setHourKey(iso);
    setMode("hour");
  };
  const stepHour = (delta: number) => {
    const next = hourKeys[hourIdx + delta];
    if (next) setHourKey(next);
  };

  const hour = brief.hours[selectedHour];
  const hourLabel = ctHourEnding(selectedHour).label;

  return (
    <div className="an-brief">
      <div className="an-modebar">
        <div className="an-seg">
          <button
            className={mode === "hour" ? "active" : ""}
            onClick={() => setMode("hour")}
          >
            This hour
          </button>
          <button
            className={mode === "day" ? "active" : ""}
            onClick={() => setMode("day")}
          >
            Whole day
          </button>
        </div>

        {mode === "hour" && (
          <div className="an-hoursel">
            <button
              className="an-hoursel__step"
              onClick={() => stepHour(-1)}
              disabled={hourIdx <= 0}
              aria-label="Earlier hour"
            >
              ◀
            </button>
            <select
              className="an-hoursel__select"
              value={selectedHour}
              onChange={(e) => setHourKey(e.target.value)}
              aria-label="Delivery hour"
            >
              {hourKeys.map((k) => (
                <option key={k} value={k}>
                  {ctHourEnding(k).label}
                  {k === peakKey ? "  — peak" : ""}
                </option>
              ))}
            </select>
            <button
              className="an-hoursel__step"
              onClick={() => stepHour(1)}
              disabled={hourIdx < 0 || hourIdx >= hourKeys.length - 1}
              aria-label="Later hour"
            >
              ▶
            </button>
          </div>
        )}
      </div>

      {mode === "hour" ? (
        <HourStory hour={hour} hourLabel={hourLabel} />
      ) : (
        <DaySummary brief={brief} onPickHour={pickHour} />
      )}
    </div>
  );
}

export default function AnalysisPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlDate = searchParams.get("date");

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

  // The day actually shown: the URL date when it's a real day in the index,
  // otherwise the latest. Null until the index resolves (we wait, not fetch).
  const selectedDate =
    urlDate && availableDates.includes(urlDate) ? urlDate : latestDate;

  // The selected day's brief. Reuse the latest envelope when the selection is
  // the latest day, so the landing view never double-fetches.
  const [dayEnv, setDayEnv] = useState<AnalysisBrief | null>(null);
  const [dayLoading, setDayLoading] = useState(false);
  useEffect(() => {
    if (!selectedDate) return;
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

  // Navigate to a date; null → the latest (drop the query param).
  const goTo = (date: string | null) => {
    if (date == null || date === latestDate) {
      setSearchParams({}, { replace: false });
    } else {
      setSearchParams({ date }, { replace: false });
    }
  };

  const loading = !indexLoaded || (selectedDate != null && dayLoading);
  const env = dayEnv;

  return (
    <div className="an-page">
      <header className="an-topbar">
        <HeaderNav active="analysis" />
        {env?.available && selectedDate && (
          <>
            <div className="an-daynav-wrap">
              <DayNav
                dates={availableDates}
                current={selectedDate}
                latest={latestDate}
                onGo={goTo}
              />
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

          {/* Run is published but this day has no brief (available:false). */}
          {!loading && latest && env && !env.available && (
            <div className="an-empty label">
              no Insight Brief for{" "}
              {selectedDate ? fmtDay(selectedDate) : "this day"}.
            </div>
          )}

          {/* The brief for the selected day: the "what matters" story. */}
          {!loading && env?.available && env.brief && (
            <BriefView brief={env.brief} />
          )}
        </main>

        {/* Right rail — the glossary lands in a later commit. */}
        <aside className="an-guide" />
      </div>

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
