import type { ExposuresResponse } from "../../../api/types";
import { formatCT } from "../../../lib/time";
import { fmtDollars } from "../../../lib/format";
import { shiftFactorColor } from "../../../lib/colors";
import { TypeChip } from "./chips";

// The constraints that drove this node at the cursor's hour, ranked by
// contribution (−SF × μ). Constraints that did not bind are omitted — the
// matrix is the place to see the full unfiltered ranking.
export function ExposuresBody({
  exposures,
  loading,
  cursorTs,
  onSelectConstraint,
  onHoverConstraint,
}: {
  exposures: ExposuresResponse | null;
  loading?: boolean;
  cursorTs?: Date;
  onSelectConstraint?: (c: string) => void;
  onHoverConstraint?: (c: string | null) => void;
}) {
  // Same format as the scrubber and the matrix, so the card is visibly pinned
  // to the same instant the rest of the workspace is showing.
  const hour = cursorTs ? `${formatCT(cursorTs, "MMM d, HH:mm")} CT` : null;
  const header = (
    <div className="dc-drivers-head">
      <span className="dc-drivers-basis label">
        {hour ? `Drove ${hour}` : "Drove this hour"}
      </span>
    </div>
  );

  if (!exposures) {
    return (
      <>
        {header}
        <div className="dc-drivers-empty label">
          {loading ? "loading drivers…" : "—"}
        </div>
      </>
    );
  }
  return (
    <>
      {header}
      {exposures.exposures.length === 0 && (
        <div className="dc-drivers-empty label">Nothing bound this hour</div>
      )}
      <div
        className="dc-drivers"
        onMouseLeave={() => onHoverConstraint?.(null)}
      >
        {/* Keep headers inside the scroll area so columns stay aligned. */}
        {exposures.exposures.length > 0 && (
          <div className="dc-driver dc-driver--head">
            <span aria-hidden="true" />
            <span className="dc-driver-col label">
              Constraint | Contingency
            </span>
            <span className="dc-driver-col label">$/MWh</span>
          </div>
        )}
        {exposures.exposures.map((e) => (
          <button
            key={e.constraint_key}
            className="dc-driver"
            onClick={() => onSelectConstraint?.(e.constraint_key)}
            onMouseEnter={() => onHoverConstraint?.(e.constraint_key)}
            title={
              e.sf_clipped
                ? `SF is pinned at the fit's ±1 clip — a bound on a poorly-conditioned column, not a measured 1:1 response.`
                : undefined
            }
          >
            <TypeChip ctype={e.ctype} />
            <span className="dc-driver-key mono">
              {e.constraint_key}
              {e.sf_clipped && <span className="dc-driver-clip">*</span>}
            </span>
            <span
              className="dc-driver-sf mono"
              style={{
                color:
                  e.contribution != null
                    ? shiftFactorColor(-e.contribution)
                    : undefined,
              }}
            >
              {e.contribution != null ? fmtDollars(e.contribution) : "—"}
            </span>
          </button>
        ))}
      </div>
      {exposures.exposures.some((e) => e.sf_clipped) && (
        <div className="dc-drivers-note label">
          * SF pinned at the fit's ±1 clip — a bound, not a measurement
        </div>
      )}
    </>
  );
}
