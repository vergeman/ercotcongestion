import { useRef, useState } from "react";
import { usePopoverDismiss } from "../../../hooks/usePopoverDismiss";
import type {
  AnalysisGrade,
  AnalysisGradeHalf,
  AnalysisGradeHistory,
  AnalysisGradeMetrics,
  AnalysisGradeSupport,
} from "../../../api/types";
import { beats, fmtScore, multiple, percent, usd } from "../../../lib/format";
import { LoadingState } from "./LoadingState";

function ScoreWhisker({
  model,
  persistence,
  history,
}: {
  model: number | null | undefined;
  persistence: number | null | undefined;
  history: number[];
}) {
  const values = history.filter((value): value is number =>
    Number.isFinite(value)
  );
  if (model == null || !values.length)
    return (
      <div className="an-grade-card__whisker an-grade-card__whisker--missing">
        Trailing grade history is not materialized yet.
      </div>
    );
  const low = Math.min(...values, model, persistence ?? model);
  const high = Math.max(...values, model, persistence ?? model);
  const span = Math.max(high - low, 0.01);
  const position = (value: number) => {
    const fraction = (value - low) / span;
    return `calc(${fraction * 100}% + ${12 - fraction * 24}px)`;
  };
  const trackWidth = (from: number, to: number) => {
    const fraction = (to - from) / span;
    return `calc(${fraction * 100}% - ${fraction * 24}px)`;
  };
  const p10 = values.slice().sort((a, b) => a - b)[
    Math.floor((values.length - 1) * 0.1)
  ];
  const p90 = values.slice().sort((a, b) => a - b)[
    Math.ceil((values.length - 1) * 0.9)
  ];
  const markers = [
    { value: p10, kind: "bound", priority: 0 },
    { value: p90, kind: "bound", priority: 0 },
    { value: model, kind: "model", priority: 2 },
    ...(persistence == null
      ? []
      : [{ value: persistence, kind: "persistence", priority: 1 }]),
  ].sort((a, b) => a.value - b.value);
  // A label needs roughly one eighth of this compact track. Keep every mark,
  // but collapse nearby labels to the most meaningful value (today, then
  // persistence, then the percentile) rather than printing unreadable stacks.
  const numberLabels = markers.reduce<typeof markers>((labels, marker) => {
    const previous = labels.at(-1);
    if (previous && (marker.value - previous.value) / span < 0.12) {
      if (marker.priority > previous.priority)
        labels[labels.length - 1] = marker;
    } else labels.push(marker);
    return labels;
  }, []);
  return (
    <div
      className="an-grade-card__whisker"
      aria-label={`Artifact profile forecast ${fmtScore(model)}; trailing ${
        values.length
      }-day p10 ${fmtScore(p10)}, p90 ${fmtScore(p90)}`}
    >
      <span className="an-grade-card__whisker-line" />
      <i
        className="an-grade-card__whisker-range"
        style={{ left: position(p10), width: trackWidth(p10, p90) }}
      />
      <i
        className="an-grade-card__whisker-bound"
        style={{ left: position(p10) }}
      />
      <i
        className="an-grade-card__whisker-bound"
        style={{ left: position(p90) }}
      />
      <i
        className="an-grade-card__whisker-model"
        style={{ left: position(model) }}
      />
      {persistence != null && (
        <i
          className="an-grade-card__whisker-persistence"
          style={{ left: position(persistence) }}
        />
      )}
      {numberLabels.map((marker) => (
        <span
          key={`${marker.kind}-${marker.value}`}
          className={`an-grade-card__whisker-number an-grade-card__whisker-number--${marker.kind}`}
          style={{ left: position(marker.value) }}
        >
          {fmtScore(marker.value)}
        </span>
      ))}
    </div>
  );
}

function GradeCard({
  kind,
  question,
  detail,
  model,
  modelHourly,
  persistence,
  support,
  entity,
  footer,
  formula,
  supportRows,
  history,
}: {
  kind: string;
  question: string;
  detail: string;
  model: number | null | undefined;
  modelHourly?: number | null | undefined;
  persistence: number | null | undefined;
  support: AnalysisGradeSupport | null | undefined;
  entity: string;
  footer: string;
  formula: string;
  supportRows: Array<{ value: string; label: string; win?: boolean }>;
  history: number[];
}) {
  const [formulaOpen, setFormulaOpen] = useState(false);
  const formulaRef = useRef<HTMLDivElement>(null);
  usePopoverDismiss(formulaOpen, formulaRef, () => setFormulaOpen(false));
  return (
    <article className={`an-grade-card an-grade-card--${kind.toLowerCase()}`}>
      <span className="an-grade-card__kind">{kind}</span>
      <h4>{question}</h4>
      <p className="an-grade-card__detail">{detail}</p>
      <div className="an-grade-card__value">
        <strong>{fmtScore(model)}</strong>
        {modelHourly !== undefined ? (
          <>
            <small>day</small>
            <span>→</span>
            <strong>{fmtScore(modelHourly)}</strong>
            <small>hourly</small>
          </>
        ) : (
          <small>model</small>
        )}
      </div>
      <ScoreWhisker model={model} persistence={persistence} history={history} />
      <div className="an-grade-card__support">
        {supportRows.map((row) => (
          <div
            key={row.label}
            className={
              row.win
                ? "an-grade-card__comparison an-grade-card__comparison--win"
                : "an-grade-card__comparison"
            }
          >
            <strong>{row.value}</strong>
            <span>{row.label}</span>
          </div>
        ))}
      </div>
      <p className="an-grade-card__evidence">{footer}</p>
      <p className="an-grade-card__footer">
        {support
          ? entity === "node"
            ? `${support.daily_bound_count.toLocaleString()} node-days above the numerical-noise floor · ${support.hourly_bound_count.toLocaleString()} node-hours above it`
            : `${support.daily_bound_count.toLocaleString()} constraint-days that bind · ${support.hourly_bound_count.toLocaleString()} constraint-hours that bind`
          : "Supporting population unavailable"}
      </p>
      <div ref={formulaRef} className="an-grade-card__formula">
        <button
          type="button"
          aria-expanded={formulaOpen}
          onClick={() => setFormulaOpen((open) => !open)}
        >
          How it is calculated
        </button>
        {formulaOpen && (
          <div className="an-grade-card__formula-popover" role="note">
            <pre>{formula}</pre>
          </div>
        )}
      </div>
    </article>
  );
}

const gradeMetric = (
  metrics: AnalysisGradeMetrics | null | undefined,
  key: keyof AnalysisGradeMetrics
) => metrics?.[key] ?? null;

const BRIEF_MODEL_SOURCE = "brief_model_artifact_profile";
const BRIEF_PERSISTENCE_SOURCE = "brief_persistence_prior_settled_profile";
const BRIEF_CLIMATOLOGY_SOURCE = "brief_climatology_trailing_settled_profile";

const gradeSource = (half: AnalysisGradeHalf | undefined, id: string) =>
  half?.source_metrics?.find((source) => source.id === id)?.metrics;

const gradeSourceLabel = (half: AnalysisGradeHalf | undefined, id: string) =>
  half?.sources?.find((source) => source.id === id)?.label ?? id;

function GradeHalf({
  label,
  half,
  history,
}: {
  label: string;
  half: AnalysisGradeHalf | undefined;
  history: AnalysisGradeHistory | null;
}) {
  if (!half?.graded) {
    return (
      <div className="an-grade__half an-grade__half--ungraded">
        <h3>{label}</h3>
        <p>
          Not graded
          {half?.unavailable_reason
            ? ` · ${half.unavailable_reason.replaceAll("_", " ")}`
            : ""}
        </p>
      </div>
    );
  }
  const nodes = label === "Nodes";
  const model = gradeSource(half, BRIEF_MODEL_SOURCE);
  const persistence = gradeSource(half, BRIEF_PERSISTENCE_SOURCE);
  const climatology = gradeSource(half, BRIEF_CLIMATOLOGY_SOURCE);
  const dailyRank = model?.detection_ap;
  const persistenceDailyRank = persistence?.detection_ap;
  const hourlyRank = model?.timing_hourly_skill;
  const subject = nodes ? "nodes" : "constraints";
  const historyFor = (key: keyof AnalysisGradeMetrics) =>
    (history?.days ?? [])
      .map((day) => gradeMetric(
        day[subject].source_metrics?.find((source) => source.id === BRIEF_MODEL_SOURCE)?.metrics,
        key
      ))
      .filter(
        (value): value is number => value != null && Number.isFinite(value)
      );
  return (
    <div className="an-grade__half">
      <h3>
        {label}
        {half.universe_size != null && <span>{half.universe_size} scored</span>}
      </h3>
      <div className="an-grade__cards">
        <GradeCard
          kind="Detection"
          question={
            nodes
              ? "Did we identify the nodes with the largest congestion?"
              : "Did we put the constraints with settled shadow prices near the top?"
          }
          detail={
            nodes
              ? "Ranks scored nodes by forecast total absolute congestion. The settled top 10% are the positive labels."
              : "Ranks constraints by forecast shadow price for the day, then checks whether constraints with settled shadow prices are near the top. Only the order matters."
          }
          model={dailyRank}
          persistence={persistenceDailyRank}
          support={half.support}
          entity={nodes ? "node" : "constraint"}
          supportRows={[
            {
              value: fmtScore(persistenceDailyRank),
              label: gradeSourceLabel(half, BRIEF_PERSISTENCE_SOURCE),
              win: beats(dailyRank, persistenceDailyRank),
            },
            {
              value: fmtScore(
                climatology?.detection_ap
              ),
              label: gradeSourceLabel(half, BRIEF_CLIMATOLOGY_SOURCE),
              win: beats(
                dailyRank,
                climatology?.detection_ap
              ),
            },
            {
              value: percent(half.support?.daily_bound_rate),
              label: "Random-ordering baseline",
            },
          ]}
          footer={
            half.support
              ? `${half.support.daily_bound_count.toLocaleString()} ${nodes ? "settled top-10% nodes by absolute congestion" : "constraints with settled shadow prices"} of ${half.universe_size?.toLocaleString() ?? "—"
              } scored · 1.00 means every positive label ranked ahead of every other subject.`
              : "Measures average precision."
          }
          formula={
            `AP  =  (1/B) · Σ  P(k)
               k ∈ positive labels

P(k) = positive labels within top k / k
B    = ${nodes ? "settled top 10% of scored nodes" : "constraints with settled shadow prices"}`
          }
          history={historyFor("detection_ap")}
        />
        <GradeCard
          kind="Magnitude"
          question={
            nodes
              ? "Did forecast and settled congestion agree in amount and place?"
              : "Did forecast and settled shadow prices agree in amount and place?"
          }
          detail={
            nodes
              ? "Matches forecast and settled absolute congestion by node. It credits only the amount they share; direction does not affect the score."
              : "Matches forecast and settled summed shadow prices by constraint. It credits only the amount they share."
          }
          model={model?.magnitude_overlap}
          persistence={persistence?.magnitude_overlap}
          support={half.support}
          entity={label === "Constraints" ? "constraint" : "node"}
          supportRows={[
            {
              value: multiple(half.support?.forecast_to_settled_ratio),
              label: "Forecast amount ÷ settled amount",
            },
            {
              value: fmtScore(half.support?.magnitude_ceiling),
              label: "Best possible score with this total",
            },
            {
              value: percent(half.support?.magnitude_of_ceiling),
              label: "Share of that best possible score",
            },
          ]}
          footer={
            half.support
              ? `${usd(half.support.forecast_total)} forecast · ${usd(
                half.support.settled_total
              )} settled.`
              : "Measures shared forecast and settled amount."
          }
          formula={`Σ min(forecastᵢ, settledᵢ)
────────────────────────────────
Σ (forecastᵢ  +  settledᵢ) / 2

= shared amount ÷ average forecast and settled amount`}
          history={historyFor("magnitude_overlap")}
        />
        <GradeCard
          kind="Timing"
          question={
            nodes
              ? "Did the detected nodes appear in the right hours?"
              : "Did the detected constraints appear in the right hours?"
          }
          detail={
            nodes
              ? "The day value is Detection rescaled so random ordering is 0. Each hour selects its settled top 10%, scores AP, then averages the hourly skills."
              : "The day value is Detection rescaled so random ordering is 0. The hourly value ranks every constraint-hour, testing whether forecast activity appeared in the right hour."
          }
          model={model?.timing_daily_skill}
          modelHourly={hourlyRank}
          persistence={persistence?.timing_daily_skill}
          support={half.support}
          entity={nodes ? "node" : "constraint"}
          supportRows={[
            {
              value: percent(half.support?.daily_bound_rate),
              label: nodes ? "Daily selected-node rate" : "Daily settled-event rate",
            },
            {
              value: percent(half.support?.hourly_bound_rate),
              label: nodes ? "Hourly selected-node rate" : "Hourly settled-event rate",
            },
          ]}
          footer={
            nodes
              ? "Day restates Detection on a chance-adjusted scale · hourly averages independently scored delivery hours. 0 = no better than random; negative = worse."
              : "Day restates Detection on a chance-adjusted scale · hourly tests timing. 0 = no better than random; negative = worse."
          }
          formula={
            `(AP − chance) ÷ (1 − chance)

AP = see Detection calculation

day: daily ${nodes ? "node" : "constraint"} ranking
hourly: ${nodes ? "AP and skill per hour, then average" : "pooled constraint-hour ranking"}

chance = ${nodes ? "selected-node rate" : "settled-event rate"}`
          }
          history={historyFor("timing_daily_skill")}
        />
      </div>
    </div>
  );
}

export default function ForecastGrade({
  grade,
  history,
  loading,
  settled,
}: {
  grade: AnalysisGrade | null;
  history: AnalysisGradeHistory | null;
  loading: boolean;
  settled: boolean;
}) {
  const persistenceLabel = grade?.constraints?.sources?.find(
    (source) => source.id === BRIEF_PERSISTENCE_SOURCE
  )?.label ?? "Prior-settled profile persistence";
  return (
    <section className="an-grade" aria-labelledby="forecast-grade-title">
      <h2 id="forecast-grade-title">Forecast Grade</h2>
      {settled && (
        <span className="an-grade-card__whisker-legend">
          <span className="an-grade-card__whisker-legend--bound">
            ● p10, p90
          </span>
          <span className="an-grade-card__whisker-legend--model">● Today</span>
          <span className="an-grade-card__whisker-legend--persistence">
            ● {persistenceLabel}
          </span>
        </span>
      )}
      {!settled && (
        <div className="an-grade__pending">
          <strong>Settlement pending</strong>
          <p>
            Forecast Grade appears after DAM settlement is available for this
            delivery day.
          </p>
        </div>
      )}
      {settled && loading && (
        <LoadingState>Loading forecast grade…</LoadingState>
      )}
      {settled && !loading && (!grade || !grade.available) && (
        <p>Forecast grade is unavailable for this delivery day.</p>
      )}
      {settled && !loading && grade?.available && (
        <div className="an-grade__halves">
          <GradeHalf
            label="Constraints"
            half={grade.constraints}
            history={history}
          />
          <GradeHalf label="Nodes" half={grade.nodes} history={history} />
        </div>
      )}
    </section>
  );
}
