// Two-value stat box used in the hero evidence row.

export default function DualStatBox({
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
