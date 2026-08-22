import type {
  AnalysisConstraintsResponse,
  AnalysisSettlementPointsResponse,
} from "../../api/types";
import type { MatrixSidebarItem } from "../../components/matrix/MatrixSidebar";
import type { MatrixRouteState } from "./routeState";

const moneyLabel = (value: number) => `$${Math.round(value).toLocaleString()}`;

export function matrixVocabulary(
  constraints: AnalysisConstraintsResponse | null,
  points: AnalysisSettlementPointsResponse | null,
  state: MatrixRouteState
) {
  const nodeMeta = new Map(
    (points?.available ? points.metadata ?? [] : []).map((item) => [
      item.settlement_point,
      {
        type: item.settlement_point_type,
        zone: item.load_zone,
        lat: item.lat,
        lon: item.lon,
      },
    ])
  );
  const constraintItems: MatrixSidebarItem[] = [
    ...(constraints?.available ? constraints.rows ?? [] : []),
  ]
    .sort((a, b) => a.daily_mu_rank - b.daily_mu_rank)
    .map((row) => ({
      id: row.constraint_key,
      label: row.name,
      sub: row.contingency,
      type: row.ctype,
      zone: row.zone,
      sizeLabel: moneyLabel(row.daily_mu_sum),
      pinned: state.pinnedConstraints.includes(row.constraint_key),
    }));
  const nodeItems: MatrixSidebarItem[] = [
    ...(points?.available ? points.settlement_points ?? [] : []),
  ]
    .sort((a, b) => a.localeCompare(b))
    .map((point) => {
      const meta = nodeMeta.get(point);
      return {
        id: point,
        label: point,
        sub: null,
        type: meta?.type ?? null,
        zone: meta?.zone ?? null,
        sizeLabel: null,
        pinned: state.pinnedSettlementPoints.includes(point),
      };
    });
  const fullItems = state.tab === "constraints" ? constraintItems : nodeItems;
  const filteredItems = fullItems.filter((item) => {
    if (
      (state.fType && item.type !== state.fType) ||
      (state.fZone && item.zone !== state.fZone)
    )
      return false;
    return (
      !state.query.trim() ||
      `${item.id} ${item.label} ${item.sub ?? ""}`
        .toLowerCase()
        .includes(state.query.trim().toLowerCase())
    );
  });
  return {
    constraintItems,
    nodeMeta,
    fullItems,
    filteredItems,
    typeOptions: [
      ...new Set(
        fullItems
          .map((item) => item.type)
          .filter((item): item is string => Boolean(item))
      ),
    ].sort(),
    zoneOptions: [
      ...new Set(
        fullItems
          .map((item) => item.zone)
          .filter((item): item is string => Boolean(item))
      ),
    ].sort(),
  };
}
