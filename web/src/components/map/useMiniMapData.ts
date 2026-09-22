import { useEffect, useMemo, useState } from "react";
import {
  fetchErcotRange,
  fetchForecastRange,
  fetchTopology,
} from "../../api/client";
import type { ConstraintReach } from "../../api/types";
import {
  lmpColor,
  normalizeLmpFromStats,
  shiftFactorColor,
} from "../../lib/colors";
import { useTheme } from "../../lib/theme";
import {
  settlementPointsFromTopology,
  type SettlementPoint,
} from "../../lib/texasOutline";
import { REACH_K, useConstraintReach } from "../panels/constraintReachData";

// The data layer for MiniMap: given the mode, fetch and colour the marks to
// plot. It returns marks in lng/lat (the component owns the projection) plus
// the loading/failed flags each mode needs. Keeping every fetch here leaves the
// component purely presentational.

interface NodePoint {
  lng: number;
  lat: number;
}

// Chrome common to the two footprint modes.
export interface FootprintCommon {
  selectionKey: string;
  // Deep link to the full Map for this element (a control on the map itself).
  mapHref: string;
  // Intercept a plain left-click to navigate in-app (Matrix carries the shared
  // scrubber coordinate); modified/middle clicks fall through to the href.
  onNavigate?: (search: string) => void;
  // The "Grid footprint" heading — Brief keeps it, Matrix Read hides it.
  showTitle?: boolean;
  // Cursor instant whose CT delivery day the reach is served for.
  t?: Date;
}

export type MiniMapProps =
  | {
      // Decorative hero backdrop: every node coloured by the hour's LMP.
      mode: "lmp";
      cursor: { t: string; ws: string; we: string };
      // Which quantity has real dollars now: settled DAM LMP, else implied-λ.
      basis: "forecast" | "settled";
    }
  | (FootprintCommon & {
      // A constraint's SF-reach members, coloured by import/export pole.
      mode: "constraint";
      // Matrix passes its already-fetched reach; Brief omits it and this fetches.
      reach?: ConstraintReach | null;
      reachLoading?: boolean;
    })
  | (FootprintCommon & {
      // A single settlement point.
      mode: "node";
      // Matrix passes the coordinate it has; Brief looks it up from topology.
      nodeLocation?: NodePoint | null;
    });

// A mark in geographic coords with its resolved colour; the component projects
// it to screen space. `focus` gets the highlight ring (the single node).
export interface RawDot {
  id: string;
  lng: number;
  lat: number;
  color: string;
  focus: boolean;
}

export interface MiniMapData {
  dots: RawDot[];
  loading: boolean;
  // lmp only: the hour's nodal layer came back empty; the hero paints nothing.
  failed: boolean;
}

// Raw DAM SPP for the hour, keyed by settlement point.
async function loadSettledValues(
  t: Date,
  windowEnd: Date
): Promise<Map<string, number>> {
  const values = new Map<string, number>();
  const range = await fetchErcotRange(t, windowEnd);
  const entry =
    range?.entries.find(
      (e) => new Date(e.interval_ts).getTime() === t.getTime()
    ) ?? range?.entries[0];
  if (range && entry) {
    range.sp_ids.forEach((spId, i) => {
      const v = entry.spp[i];
      if (v != null) values.set(spId, v);
    });
  }
  return values;
}

// Deterministic forecast congestion + that hour's system-λ (the implied-LMP
// convention the Map's forecast pane renders; display, not a graded signal).
async function loadForecastValues(
  t: Date,
  windowEnd: Date
): Promise<Map<string, number>> {
  const values = new Map<string, number>();
  const range = await fetchForecastRange(t, windowEnd);
  const entry =
    range?.entries.find(
      (e) => new Date(e.interval_ts).getTime() === t.getTime()
    ) ?? range?.entries[0];
  if (range && entry?.system_lambda != null) {
    const lam = entry.system_lambda;
    range.sp_ids.forEach((spId, i) => {
      const congestion = entry.congestion[i];
      if (congestion != null) values.set(spId, congestion + lam);
    });
  }
  return values;
}

// `basis` picks the source with real dollars, but the per-node layer has its own
// gaps (e.g. the t+2 preview publishes no per-SP forecast), so fall back to the
// other source rather than showing an empty frame on a day that resolved fine.
async function loadHourValues(
  t: Date,
  basis: "forecast" | "settled"
): Promise<Map<string, number>> {
  const windowEnd = new Date(t.getTime() + 60 * 60 * 1000);
  const [primary, fallback] =
    basis === "settled"
      ? [loadSettledValues, loadForecastValues]
      : [loadForecastValues, loadSettledValues];
  const values = await primary(t, windowEnd);
  return values.size ? values : fallback(t, windowEnd);
}

export function useMiniMapData(props: MiniMapProps): MiniMapData {
  const theme = useTheme();

  // --- lmp mode: the hour's node scatter -----------------------------------
  const lmp = props.mode === "lmp" ? props : null;
  const lmpCursor = lmp?.cursor.t;
  const lmpBasis = lmp?.basis;
  const [lmpData, setLmpData] = useState<{
    points: SettlementPoint[];
    values: Map<string, number>;
  } | null>(null);
  const [lmpFailed, setLmpFailed] = useState(false);
  useEffect(() => {
    if (!lmpCursor || !lmpBasis) return;
    let live = true;
    queueMicrotask(() => {
      if (!live) return;
      setLmpData(null);
      setLmpFailed(false);
    });
    const t = new Date(lmpCursor);
    Promise.all([fetchTopology(), loadHourValues(t, lmpBasis)])
      .then(([topology, values]) => {
        if (!live) return;
        const points = settlementPointsFromTopology(topology);
        if (!points.length || !values.size) {
          setLmpFailed(true);
          return;
        }
        setLmpData({
          points,
          values,
        });
      })
      .catch(() => live && setLmpFailed(true));
    return () => {
      live = false;
    };
  }, [lmpCursor, lmpBasis]);

  // --- constraint mode: the SF reach ---------------------------------------
  const constraint = props.mode === "constraint" ? props : null;
  const providedReach = constraint?.reach;
  const hasProvidedReach = constraint != null && providedReach !== undefined;
  const { reach: fetchedReach, loading: fetchedReachLoading } =
    useConstraintReach(
      constraint && !hasProvidedReach ? constraint.selectionKey : null,
      REACH_K,
      constraint?.t
    );
  const reach = hasProvidedReach ? providedReach! : fetchedReach;
  const reachLoading = hasProvidedReach
    ? !!constraint?.reachLoading
    : fetchedReachLoading;

  // --- node mode: one located point ----------------------------------------
  const node = props.mode === "node" ? props : null;
  const nodeSelectionKey = node?.selectionKey;
  const nodeLocation = node?.nodeLocation;
  const [nodePoint, setNodePoint] = useState<NodePoint | null>(null);
  const [nodeResolved, setNodeResolved] = useState(props.mode !== "node");
  useEffect(() => {
    if (!nodeSelectionKey) {
      queueMicrotask(() => {
        setNodePoint(null);
        setNodeResolved(true);
      });
      return;
    }
    if (nodeLocation) {
      queueMicrotask(() => {
        setNodePoint(nodeLocation);
        setNodeResolved(true);
      });
      return;
    }
    let live = true;
    queueMicrotask(() => {
      if (!live) return;
      setNodeResolved(false);
      setNodePoint(null);
    });
    fetchTopology()
      .then((topology) => {
        if (!live) return;
        const match = settlementPointsFromTopology(topology).find(
          (p) => p.sp_id === nodeSelectionKey
        );
        if (match) setNodePoint({ lng: match.lng, lat: match.lat });
      })
      .catch(() => {})
      .finally(() => live && setNodeResolved(true));
    return () => {
      live = false;
    };
  }, [nodeSelectionKey, nodeLocation]);

  const dots = useMemo<RawDot[]>(() => {
    if (props.mode === "lmp") {
      if (!lmpData) return [];
      const { points, values } = lmpData;
      return points.flatMap((p) => {
        const v = values.get(p.sp_id);
        if (v == null) return [];
        return [
          {
            id: p.sp_id,
            lng: p.lng,
            lat: p.lat,
            color: lmpColor(normalizeLmpFromStats(v), theme),
            focus: false,
          },
        ];
      });
    }
    if (props.mode === "constraint") {
      return (reach?.sps ?? []).flatMap((s) => {
        if (s.lat == null || s.lon == null) return [];
        return [
          {
            id: s.settlement_point,
            lng: s.lon,
            lat: s.lat,
            color: shiftFactorColor(s.sf),
            focus: false,
          },
        ];
      });
    }
    if (nodePoint) {
      return [
        {
          id: props.selectionKey,
          lng: nodePoint.lng,
          lat: nodePoint.lat,
          color: "var(--accent)",
          focus: true,
        },
      ];
    }
    return [];
  }, [props, lmpData, theme, reach, nodePoint]);

  const loading =
    props.mode === "lmp"
      ? !lmpFailed && !lmpData
      : props.mode === "constraint"
      ? reachLoading
      : !nodeResolved;

  return { dots, loading, failed: props.mode === "lmp" && lmpFailed };
}
