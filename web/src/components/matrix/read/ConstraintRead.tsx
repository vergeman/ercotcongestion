import { useMemo } from "react";
import type {
  AnalysisConstraintRow,
  ConstraintReach,
} from "../../../api/types";
import {
  Dipole,
} from "../../panels/ConstraintReach";
import {
  dipoleCounts,
  REACH_K,
  useFullConstraintReach,
} from "../../panels/constraintReachData";
import { REACH_THRESHOLD_OPTS } from "../../../api/client";
import MiniMap from "../../map/MiniMap";
import { mapLinkTo } from "../../../lib/mapLinks";
import { constraintName, marketValue, usd, zoneLabel } from "../../../lib/format";
import { Fact } from "../../detail/Fact";
import { DetailSummary } from "./DetailSummary";
import { MemberLobe } from "./MemberLobe";

// The reach the footprint map draws: members past the display threshold, capped
// at REACH_K.
function footprintReach(reach: ConstraintReach | null) {
  if (!reach) return reach;
  const floor = Math.max(
    (REACH_THRESHOLD_OPTS.minFrac ?? 0) * (reach.max_abs_sf ?? 0),
    REACH_THRESHOLD_OPTS.absFloor ?? 0
  );
  return {
    ...reach,
    sps: reach.sps.filter((sp) => Math.abs(sp.sf) >= floor).slice(0, REACH_K),
  };
}

export function ConstraintRead({
  selectionKey,
  row,
  timestamp,
  routeSearch,
  onNavigateToMap,
}: {
  selectionKey: string;
  row: AnalysisConstraintRow | null;
  timestamp: Date | null;
  routeSearch: string;
  onNavigateToMap: (search: string) => void;
}) {
  // The scrubbed interval selects the CT delivery day whose artifact backs the
  // reach (0144) — the same day the rest of the Read pane describes.
  const cursorTs = timestamp ?? undefined;
  const { reach, loading } = useFullConstraintReach(selectionKey, cursorTs);
  const { imp, exp } = dipoleCounts(reach);
  const name = constraintName(selectionKey);
  const contingency = selectionKey.includes("|")
    ? selectionKey.split("|")[1]
    : null;
  const mapHref = mapLinkTo(
    { kind: "constraint", value: selectionKey },
    routeSearch
  );

  const sps = reach?.sps ?? [];
  const mapReach = useMemo(() => footprintReach(reach), [reach]);
  const importLobe = [...sps]
    .filter((sp) => sp.sf < 0)
    .sort((a, b) => a.sf - b.sf);
  const exportLobe = [...sps]
    .filter((sp) => sp.sf >= 0)
    .sort((a, b) => b.sf - a.sf);

  return (
    <>
      <div className="mrd__main">
        <header className="mrd__head">
          <span className="mrd__eyebrow">Constraint</span>
          <h2 className="mrd__title">
            {name}
            {contingency && (
              <span className="mrd__contingency"> {contingency}</span>
            )}
          </h2>
        </header>
        <DetailSummary
          hourly={
            <>
              <Fact
                label="Forecast μ"
                value={marketValue(reach?.shadow_price)}
                numeric
              />
              <Fact label="DAM μ" value={marketValue(reach?.dam_mu)} numeric />
              <Fact
                label="Forecast Error"
                value={marketValue(reach?.forecast_error)}
                numeric
              />
            </>
          }
          structural={
            <>
              <Fact
                label="Forecast μ rank"
                value={reach?.daily_mu_rank ?? row?.daily_mu_rank ?? "—"}
                numeric
              />
              <Fact
                label="Daily Σμ"
                value={
                  reach?.daily_mu_sum == null
                    ? row
                      ? usd(row.daily_mu_sum, 2)
                      : "—"
                    : usd(reach.daily_mu_sum, 2)
                }
                numeric
              />
              <Fact
                label="Binding hours"
                value={reach?.binding_hours ?? row?.binding_hours ?? "—"}
                numeric
              />
              <Fact
                label="Peak |SF|"
                value={
                  reach?.max_abs_sf == null ? "—" : reach.max_abs_sf.toFixed(3)
                }
                numeric
              />
              <Fact
                label="Import / export"
                value={
                  reach
                    ? `${reach.import_members ?? imp} / ${
                        reach.export_members ?? exp
                      }`
                    : "—"
                }
                numeric
              />
              <Fact label="Zone" value={zoneLabel(row?.zone ?? null)} numeric />
              <Fact
                label="kV"
                value={row?.kv_max == null ? "—" : Math.round(row.kv_max)}
                numeric
              />
            </>
          }
        />

        <div className="mrd-reach">
          <span className="mrd-section-title">
            Grid reach · import ↔ export{" "}
            {reach && !loading && (
              <em>
                {reach.sps.length} located
                {reach.truncated ? " · truncated" : ""}
              </em>
            )}
          </span>
          <div className="mrd-reach__dipole">
            <Dipole imp={imp} exp={exp} />
          </div>
          {loading ? (
            <div className="cr-mem-msg">loading members…</div>
          ) : (
            <div className="mrd-lobes">
              <MemberLobe title="Import · SF < 0" members={importLobe} />
              <MemberLobe title="Export · SF ≥ 0" members={exportLobe} />
            </div>
          )}
        </div>
      </div>
      <div className="mrd__map">
        <MiniMap
          mode="constraint"
          selectionKey={selectionKey}
          mapHref={mapHref}
          onNavigate={onNavigateToMap}
          showTitle={false}
          t={cursorTs}
          reach={mapReach}
          reachLoading={loading}
        />
      </div>
    </>
  );
}
