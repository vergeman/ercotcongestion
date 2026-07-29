import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { AnalysisBrief } from "../api/types";
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
// This commit lands the scaffold — routing, nav, client, day-nav header, and the
// loading / unavailable / soft-fail states. The "what matters" story (F5b/F5a),
// the after-action (F6), and the F1–F4 disclosure families arrive in the
// following commits; the main body here is an intentional placeholder.

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

          {/* The brief for the selected day. The full story lands in the next
              commits; this is the scaffold placeholder. */}
          {!loading && env?.available && env.brief && (
            <div className="an-placeholder">
              <div className="an-section-h label">Insight Brief</div>
              <p className="an-note">
                {env.brief.provenance.n_hours} hours ·{" "}
                {env.brief.provenance.n_constraints} constraints ·{" "}
                {env.brief.provenance.n_settlement_points} settlement points.
              </p>
              <p className="an-note an-note--muted">
                The separation story, after-action, and supporting families
                render here.
              </p>
            </div>
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
        .an-empty { padding: 40px 16px; text-align: center; }
        .an-section-h {
          padding: 14px 16px 6px;
          display: block;
        }
        .an-placeholder { padding: 4px 0; }
        .an-note { padding: 0 16px; margin: 4px 0; font-size: 13.5px; color: var(--text-secondary); }
        .an-note--muted { color: var(--text-muted); }

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
