// Spinner shown while an evidence panel loads.

export function LoadingState({ children }: { children: string }) {
  return (
    <p className="an-panel-state an-panel-state--loading">
      <span className="an-loading-indicator" aria-hidden="true" />
      {children}
    </p>
  );
}
