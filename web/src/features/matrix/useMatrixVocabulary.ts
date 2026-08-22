/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useState } from "react";
import {
  fetchAnalysisConstraints,
  fetchAnalysisSettlementPoints,
} from "../../api/client";
import type {
  AnalysisConstraintsResponse,
  AnalysisSettlementPointsResponse,
  MatrixFrame,
} from "../../api/types";

export function useMatrixVocabulary(frame: MatrixFrame | null) {
  const [constraints, setConstraints] =
    useState<AnalysisConstraintsResponse | null>(null);
  const [settlementPoints, setSettlementPoints] =
    useState<AnalysisSettlementPointsResponse | null>(null);
  useEffect(() => {
    if (!frame?.available) {
      setConstraints(null);
      setSettlementPoints(null);
      return;
    }
    const controller = new AbortController();
    void fetchAnalysisConstraints(frame.delivery_date, {
      signal: controller.signal,
    })
      .then(setConstraints)
      .catch(() => {
        if (!controller.signal.aborted) setConstraints(null);
      });
    void fetchAnalysisSettlementPoints(frame.delivery_date, {
      signal: controller.signal,
    })
      .then(setSettlementPoints)
      .catch(() => {
        if (!controller.signal.aborted) setSettlementPoints(null);
      });
    return () => controller.abort();
  }, [frame?.available, frame?.delivery_date]);
  return { constraints, settlementPoints };
}
