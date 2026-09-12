import { compactMoney } from "../../../lib/format";
import { HistoryWhisker } from "../HistoryGlyphs";
import { SignedBars } from "./SignedBars";

// The trailing-30-day block (whisker + per-day bars) shared by every kind, with
// the mark placed on the settled total once settled, else the forecast total.
// The panel has room, so both glyphs are full-width and carry real numbers: the
// whisker prints p10 / today / p90 under their marks, the bars a left y-axis.
export function HistoryBlock({
  low,
  q25,
  median,
  q75,
  high,
  mark,
  values,
  unit,
}: {
  low: number | null;
  q25: number | null;
  median: number | null;
  q75: number | null;
  high: number | null;
  mark: number | null;
  values: number[];
  unit: string;
}) {
  // Today's mark drives the whisker; the p10–p90 band is optional (an element
  // with no settled history still shows today). The label math mirrors
  // HistoryWhisker so each label sits over its true point.
  const hasBand = low != null && high != null;
  const scale =
    mark != null
      ? (() => {
          const min = Math.min(hasBand ? low : mark, mark, 0);
          const max = Math.max(hasBand ? high : mark, mark, 0);
          const span = Math.max(max - min, 1);
          const pos = (v: number) =>
            Math.min(100, Math.max(0, ((v - min) / span) * 100));
          return {
            p10: hasBand ? pos(low) : null,
            p90: hasBand ? pos(high) : null,
            mark: pos(mark),
          };
        })()
      : null;
  // Near the ends, shift the label to the point's inner side instead of moving
  // the anchor: keeps it over the point without clipping the panel edge.
  const tickShift = (p: number) => (p <= 6 ? "0" : p >= 94 ? "-100%" : "-50%");
  return (
    <div className="bdp-history">
      <span className="bdp-section-title">30-day history</span>
      <div className="bdp-history__row">
        <span className="bdp-history__cap">{unit} vs its own 30 days</span>
        <div className="bdp-whisker">
          {/* p10 / p90 sit ABOVE the number line, today BELOW it, so a value
              landing near p90 no longer prints on top of it. p10/p90 appear only
              when the element has a settled band. */}
          {scale && scale.p10 != null && scale.p90 != null && (
            <div className="bdp-whisker__top">
              <span
                className="bdp-whisker__tick"
                style={{ left: `${scale.p10}%`, transform: `translateX(${tickShift(scale.p10)})` }}
              >
                <em>p10</em>
                {compactMoney(low!)}
              </span>
              <span
                className="bdp-whisker__tick"
                style={{ left: `${scale.p90}%`, transform: `translateX(${tickShift(scale.p90)})` }}
              >
                <em>p90</em>
                {compactMoney(high!)}
              </span>
            </div>
          )}
          <HistoryWhisker
            low={low}
            q25={q25}
            median={median}
            q75={q75}
            high={high}
            mark={mark}
          />
          {scale && (
            <div className="bdp-whisker__bottom">
              <span
                className="bdp-whisker__tick bdp-whisker__tick--mark"
                style={{ left: `${scale.mark}%`, transform: `translateX(${tickShift(scale.mark)})` }}
              >
                {compactMoney(mark!)}
                <em>today</em>
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="bdp-history__row">
        <span className="bdp-history__cap">
          {unit} each of the last 30 days, then today
          {!values.length && (
            <em className="bdp-history__none"> — no prior settled days</em>
          )}
        </span>
        <SignedBars values={values} today={mark} fmt={compactMoney} />
      </div>
    </div>
  );
}
