import { createContext, useContext } from "react";
import { useExplorerSession } from "./useExplorerSession";
import { useTimeCursor } from "./useTimeCursor";

export type Explorer = {
  session: ReturnType<typeof useExplorerSession>;
  cursor: ReturnType<typeof useTimeCursor>;
};

export const ExplorerContext = createContext<Explorer | null>(null);

export function useSharedExplorer(): Explorer {
  const context = useContext(ExplorerContext);
  if (!context) throw new Error("useSharedExplorer must be used within ExplorerProvider");
  return context;
}
