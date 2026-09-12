// Vite replaces VITE_* variables when building the client bundle.
export const APP_TITLE =
  import.meta.env.VITE_APP_TITLE ?? "ERCOT Congestion Explorer";

export const APP_STORAGE_PREFIX =
  import.meta.env.VITE_APP_STORAGE_PREFIX ?? "ERCOTCongestion";
