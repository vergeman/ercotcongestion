/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useRef, useState } from "react";
import { getMatrixFrame } from "../../api/matrixFrames";
import type { MatrixFrame } from "../../api/types";
import type { MatrixRouteState } from "./routeState";

let rememberedFrame: MatrixFrame | null = null;

export function useMatrixFrame(
  timestamp: Date | null,
  state: MatrixRouteState,
  seeded: boolean,
  onSeed?: (frame: MatrixFrame) => void
) {
  const [frame, setFrame] = useState<MatrixFrame | null>(() =>
    rememberedFrame?.interval_ts === timestamp?.toISOString()
      ? rememberedFrame
      : null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const requestId = useRef(0);
  const previewConstraint =
    state.selection?.kind === "constraint" ? state.selection.key : null;
  const previewNode =
    state.selection?.kind === "node" ? state.selection.point : null;
  const peekConstraint =
    previewConstraint && !state.pinnedConstraints.includes(previewConstraint)
      ? previewConstraint
      : null;
  const peekSettlementPoint =
    previewNode && !state.pinnedSettlementPoints.includes(previewNode)
      ? previewNode
      : null;
  useEffect(() => {
    if (!timestamp) return;
    const id = ++requestId.current;
    const workingSetEmpty =
      !state.pinnedConstraints.length && !state.pinnedSettlementPoints.length;
    const seeding = !seeded && workingSetEmpty;
    setLoading(true);
    setError(null);
    const request = seeding
      ? {
          rowPreset: "top30" as const,
          rowLimit: 8,
          columnLimit: 30,
          columnSet: "default_anchors" as const,
          rowOrder: "anchor_contribution" as const,
        }
      : {
          rowPreset: "pinned" as const,
          columnSet: "pinned" as const,
          rowLimit: 8,
          columnLimit: 30,
          pinnedConstraints: state.pinnedConstraints,
          pinnedSettlementPoints: state.pinnedSettlementPoints,
          peekConstraint,
          peekSettlementPoint,
        };
    void getMatrixFrame(timestamp, request)
      .then((next) => {
        if (id !== requestId.current) return;
        rememberedFrame = next;
        setFrame(next);
        if (
          seeding &&
          next.available &&
          (next.rows.length || next.columns.length)
        )
          onSeed?.(next);
      })
      .catch((requestError: unknown) => {
        if (
          !(
            requestError instanceof Error && requestError.name === "AbortError"
          ) &&
          id === requestId.current
        )
          setError(
            "The Matrix frame could not be loaded. Check the connection and retry."
          );
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false);
      });
    // onSeed is an event callback; re-subscribing the request for its identity would abort an active request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    seeded,
    state.pinnedConstraints,
    state.pinnedSettlementPoints,
    peekConstraint,
    peekSettlementPoint,
    retryVersion,
    timestamp,
  ]);
  return {
    frame,
    loading,
    error,
    retry: () => setRetryVersion((value) => value + 1),
  };
}
