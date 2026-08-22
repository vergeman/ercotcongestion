import { useCallback, useEffect, useRef } from "react";
import type maplibregl from "maplibre-gl";

/** Keeps the two compare panes aligned without leaking MapLibre listeners into product state. */
export function useSynchronizedMaps() {
  const mainMapRef = useRef<maplibregl.Map | null>(null);
  const rightMapRef = useRef<maplibregl.Map | null>(null);
  const syncingSide = useRef<"main" | "right" | null>(null);
  const teardownRef = useRef<(() => void) | null>(null);

  const rearm = useCallback(() => {
    teardownRef.current?.();
    const main = mainMapRef.current;
    const right = rightMapRef.current;
    if (!main || !right) return;
    const drive = (from: maplibregl.Map, to: maplibregl.Map, side: "main" | "right") => () => {
      if (syncingSide.current && syncingSide.current !== side) return;
      syncingSide.current = side;
      to.jumpTo({ center: from.getCenter(), zoom: from.getZoom(), bearing: from.getBearing(), pitch: from.getPitch() });
      syncingSide.current = null;
    };
    const mainToRight = drive(main, right, "main");
    const rightToMain = drive(right, main, "right");
    main.on("move", mainToRight);
    right.on("move", rightToMain);
    mainToRight();
    teardownRef.current = () => {
      main.off("move", mainToRight);
      right.off("move", rightToMain);
    };
  }, []);

  useEffect(() => () => teardownRef.current?.(), []);

  const onMainReady = useCallback((map: maplibregl.Map) => {
    mainMapRef.current = map;
    rearm();
  }, [rearm]);
  const onRightReady = useCallback((map: maplibregl.Map) => {
    rightMapRef.current = map;
    rearm();
  }, [rearm]);

  return { onMainReady, onRightReady };
}
