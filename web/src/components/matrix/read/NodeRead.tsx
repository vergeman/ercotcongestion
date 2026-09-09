/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useRef, useState } from "react";
import type {
  AnalysisBasis,
  AnalysisNodeResponse,
  MatrixDamStatus,
} from "../../../api/types";
import { getAnalysisNode } from "../../../api/analysisNode";
import MiniMap from "../../map/MiniMap";
import { mapLinkTo } from "../../../lib/mapLinks";
import { marketValue, percent, zoneLabel } from "../../../lib/format";
import type { MatrixValTab } from "../../../lib/matrix";
import { Fact } from "./Fact";
import { DetailSummary } from "./DetailSummary";
import { DriverTable } from "./DriverTable";
import type { NodeSort, NodeSortKey } from "./sort";

export function NodeRead({
  point,
  meta,
  timestamp,
  val,
  deliveryDate,
  damStatus,
  sort,
  onToggleSort,
  onNavigateToMap,
}: {
  point: string;
  meta: {
    type: string | null;
    zone: string | null;
    lat: number | null;
    lon: number | null;
  } | null;
  timestamp: Date | null;
  val: MatrixValTab;
  deliveryDate: string | null;
  damStatus: MatrixDamStatus | null;
  sort: NodeSort;
  onToggleSort: (key: NodeSortKey) => void;
  onNavigateToMap: (search: string) => void;
}) {
  const basis: AnalysisBasis = val === "dmu" ? "realized" : "predicted";
  const [node, setNode] = useState<AnalysisNodeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const requestId = useRef(0);

  useEffect(() => {
    if (!timestamp || !deliveryDate) {
      setNode(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const id = ++requestId.current;
    setNode(null);
    setLoading(true);
    getAnalysisNode(
      point,
      deliveryDate,
      timestamp.toISOString(),
      basis,
      controller.signal,
      true
    )
      .then((response) => {
        if (id === requestId.current) setNode(response);
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        if (id === requestId.current) setNode(null);
      })
      .finally(() => {
        if (id === requestId.current) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [point, deliveryDate, timestamp, basis]);

  const mapHref = mapLinkTo({ kind: "sp", value: point });
  const terms = node?.available ? node.terms ?? [] : [];
  const structuralTerms = node?.available ? node.structural_terms ?? [] : [];
  // One table over the full nonzero-SF set when we have it (it is the superset
  // that includes the drivers), else the drivers alone.
  const tableTerms = structuralTerms.length > 0 ? structuralTerms : terms;
  const market = node?.available ? node.market_state : null;

  return (
    <>
      <div className="mrd__main">
        <header className="mrd__head">
          <span className="mrd__eyebrow">Settlement point</span>
          <h2 className="mrd__title">{point}</h2>
        </header>
        {node?.available && (
          <DetailSummary
            hourly={
              <>
                <Fact
                  label="Forecast Congestion"
                  value={marketValue(market?.forecast_congestion)}
                  numeric
                />
                <Fact
                  label="Realized Congestion"
                  value={marketValue(market?.realized_congestion)}
                  numeric
                />
                <Fact
                  label="Forecast Error"
                  value={marketValue(market?.forecast_error)}
                  numeric
                />
                <Fact
                  label="Forecast LMP"
                  value={marketValue(market?.forecast_lmp)}
                  numeric
                />
                <Fact
                  label="DAM LMP"
                  value={marketValue(market?.dam_lmp)}
                  numeric
                />
                <Fact
                  label={
                    basis === "realized"
                      ? "DAM μ attribution"
                      : "Forecast μ attribution"
                  }
                  value={marketValue(node.total)}
                  tone={(node.total ?? 0) >= 0 ? "pos" : "neg"}
                  numeric
                />
              </>
            }
            structural={
              <>
                <Fact
                  label="Zone"
                  value={zoneLabel(meta?.zone ?? null)}
                  numeric
                />
                <Fact label="Type" value={meta?.type ?? "—"} numeric />
                <Fact
                  label="ESSP members"
                  value={
                    node.essp_member_count != null && node.essp_member_count > 1
                      ? `≈${node.essp_member_count}`
                      : "—"
                  }
                  numeric
                />
                <Fact
                  label="SF coverage"
                  value={node.coverage == null ? "—" : percent(node.coverage)}
                  numeric
                />
                <Fact
                  label="Current drivers"
                  value={`${node.n_terms ?? terms.length}`}
                  numeric
                />
              </>
            }
          />
        )}

        {basis === "realized" && node?.available && market?.dam_lmp == null && (
          <div className="mrd-notice">
            ERCOT DAM LMP has not been published for this settlement point and
            hour — unavailable, not zero.
          </div>
        )}
        {basis === "realized" && damStatus === "partial" && (
          <div className="mrd-notice">
            ERCOT DAM μ is only partially published for this day; unmatched
            constraints read as zero here.
          </div>
        )}
        {loading && !node && (
          <div className="mrd-loading">Loading node column…</div>
        )}
        {!loading && node && !node.available && (
          <div className="mrd-notice">
            No forecast artifact for this node on this delivery day.
          </div>
        )}
        {node?.available && tableTerms.length > 0 && (
          <div className="mrd-drivers">
            <span className="mrd-section-title">
              Drivers &amp; exposure{" "}
              <em>
                {`${node.structural_n_terms ?? tableTerms.length} constraints · −SF·μ · sort any column`}
              </em>
            </span>
            <DriverTable terms={tableTerms} sort={sort} onToggleSort={onToggleSort} />
          </div>
        )}
      </div>
      <div className="mrd__map">
        <MiniMap
          mode="node"
          selectionKey={point}
          mapHref={mapHref}
          onNavigate={onNavigateToMap}
          showTitle={false}
          nodeLocation={
            meta?.lat != null && meta.lon != null
              ? { lat: meta.lat, lng: meta.lon }
              : null
          }
        />
      </div>
    </>
  );
}
