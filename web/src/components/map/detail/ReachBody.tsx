import type { ConstraintReach } from "../../../api/types";
import { fmtCong, fmtDollars } from "../../../lib/format";
import { shiftFactorColor } from "../../../lib/colors";
import { Row } from "./Row";
import { NodeChip, SfSign } from "./chips";

// Max constraint-reach rows the card lists; the rest are summarized as a count
// (the map still glows the full footprint). 0147.
const REACH_ROW_CAP = 20;

// Which nodes this constraint drives, split by SF sign.
export function ReachBody({
  reach,
  onHoverMember,
  onSelectMember,
  valueMode = "forecast",
}: {
  reach: ConstraintReach;
  onHoverMember?: (sp: string | null) => void;
  onSelectMember?: (sp: string) => void;
  valueMode?: "forecast" | "ercot";
}) {
  const negativeCount = reach.sps.filter((s) => s.sf < 0).length;
  const positiveCount = reach.sps.filter((s) => s.sf >= 0).length;
  const shadowPrice = valueMode === "ercot" ? reach.dam_mu : reach.shadow_price;
  const shadowPriceLabel =
    valueMode === "ercot" ? "ERCOT DAM Shadow Price" : "Forecast Shadow Price";
  return (
    <>
      {reach.basis === "nearest_past" && (
        <div className="dc-support label">
          SF as of {reach.window_start.slice(0, 10)} — no artifact for the
          selected day
        </div>
      )}
      <Row
        label="Binding hours"
        value={reach.binding_hours != null ? `${reach.binding_hours} h` : null}
      />
      <Row label={shadowPriceLabel} value={fmtCong(shadowPrice)} />
      <Row label="Negative SF nodes" value={negativeCount} />
      <Row label="Positive SF nodes" value={positiveCount} />
      <div
        className="dc-drivers dc-drivers--reach"
        onMouseLeave={() => onHoverMember?.(null)}
      >
        {/* The map glows the constraint's full driven footprint (0147); the card
            lists the strongest REACH_ROW_CAP and reports the rest as a count, so a
            broad constraint's hundreds of members stay scannable here. */}
        <div className="dc-driver dc-driver--head dc-driver--reach-row">
          <span aria-hidden="true" />
          <span className="dc-driver-col label">Settlement Point</span>
          <span className="dc-driver-col label">SF</span>
          <span
            className="dc-driver-col label"
            title={`Signed nodal congestion contribution: −SF × the constraint's ${valueMode === "ercot" ? "ERCOT DAM" : "forecast"} shadow price at the selected hour ($/MWh).`}
          >
            Contrib
          </span>
        </div>
        {reach.sps.slice(0, REACH_ROW_CAP).map((s) => (
          <button
            key={s.settlement_point}
            className="dc-driver dc-driver--reach-row"
            onClick={() => onSelectMember?.(s.settlement_point)}
            onMouseEnter={() => onHoverMember?.(s.settlement_point)}
          >
            <NodeChip />
            <span className="dc-driver-key mono">{s.settlement_point}</span>
            <SfSign sf={s.sf} />
            <span
              className="dc-driver-sup mono"
              style={{
                color:
                  shadowPrice == null
                    ? undefined
                    : shiftFactorColor(-s.sf * shadowPrice),
              }}
            >
              {shadowPrice == null
                ? "—"
                : fmtDollars(-s.sf * shadowPrice)}
            </span>
          </button>
        ))}
        {reach.sps.length > REACH_ROW_CAP && (
          <div className="dc-support label">
            + {reach.sps.length - REACH_ROW_CAP} more nodes
          </div>
        )}
      </div>
    </>
  );
}
