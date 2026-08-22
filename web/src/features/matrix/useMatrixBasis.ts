import { useEffect, useRef, useState } from "react";
import { getAnalysisNode } from "../../api/analysisNode";
import type { AnalysisBasis, MatrixFrame } from "../../api/types";
import { basisFromNodes, type BasisResult } from "../../lib/basis";

export function useMatrixBasis(show: boolean, a: string | null, b: string | null, timestamp: Date | null, frame: MatrixFrame | null, basis: AnalysisBasis) {
  const [primary, setPrimary] = useState<BasisResult | null>(null);
  const [realizedTotal, setRealizedTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const requestId = useRef(0);
  useEffect(() => {
    if (!show || !a || !b || !timestamp || !frame?.delivery_date) { setPrimary(null); setRealizedTotal(null); setLoading(false); return; }
    const controller = new AbortController(); const id = ++requestId.current; setLoading(true);
    const fetchPair = (nextBasis: AnalysisBasis) => Promise.all([getAnalysisNode(a, frame.delivery_date, timestamp.toISOString(), nextBasis, controller.signal), getAnalysisNode(b, frame.delivery_date, timestamp.toISOString(), nextBasis, controller.signal)]);
    void fetchPair(basis).then(async ([first, second]) => {
      if (id !== requestId.current) return;
      const nextPrimary = basisFromNodes(first, second);
      let nextRealized: number | null = null;
      if (basis === "predicted" && frame.dam_status === "available") {
        try { nextRealized = basisFromNodes(...await fetchPair("realized")).total; } catch { /* Optional comparison. */ }
      }
      if (id === requestId.current) { setPrimary(nextPrimary); setRealizedTotal(nextRealized); }
    }).catch((error: unknown) => {
      if (!(error instanceof Error && error.name === "AbortError") && id === requestId.current) { setPrimary(null); setRealizedTotal(null); }
    }).finally(() => { if (id === requestId.current) setLoading(false); });
    return () => controller.abort();
  }, [show, a, b, timestamp, frame?.delivery_date, frame?.run_id, frame?.dam_status, basis]);
  return { primary, realizedTotal, loading };
}
