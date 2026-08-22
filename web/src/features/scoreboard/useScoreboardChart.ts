import { useEffect, useRef, useState } from "react";

export function clampChartIndex(index: number, length: number): number | null {
  if (length <= 0) return null;
  return Math.max(0, Math.min(length - 1, Math.round(index)));
}

/** Owns chart measurement and pointer/keyboard hover coordinates. */
export function useScoreboardChart(length: number) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return {
    wrapRef,
    width,
    hover,
    clearHover: () => setHover(null),
    setHoverFromCoordinate: (coordinate: number, plotWidth: number) =>
      setHover(clampChartIndex((coordinate / plotWidth) * (length - 1), length)),
    moveHover: (delta: number) => setHover((current) =>
      clampChartIndex((current ?? (delta > 0 ? -1 : length)) + delta, length),
    ),
  };
}
