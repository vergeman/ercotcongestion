// Small building blocks shared across the Brief page panels: the spinner shown
// while a panel loads, and the two-value stat box used in the hero evidence row.

export function LoadingState({ children }: { children: string }) {
  return (
    <p className="an-panel-state an-panel-state--loading">
      <span className="an-loading-indicator" aria-hidden="true" />
      {children}
    </p>
  );
}

export function DualStatBox({
  firstLabel,
  firstValue,
  secondLabel,
  secondValue,
}: {
  firstLabel: string;
  firstValue: string;
  secondLabel?: string;
  secondValue?: string;
}) {
  return (
    <div className="an-fact an-fact--dual-stat">
      <span className="an-fact__label">{firstLabel}</span>
      <strong className="an-fact__value an-fact__value--primary">
        {firstValue}
      </strong>
      {secondLabel != null && (
        <>
          <span className="an-fact__label an-fact__secondary">
            {secondLabel}
          </span>
          <strong className="an-fact__value">{secondValue ?? ""}</strong>
        </>
      )}
    </div>
  );
}
