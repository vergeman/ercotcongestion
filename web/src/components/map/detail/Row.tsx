// One label/value row in the detail card. Deemphasized dims the side of the
// decomposition this card is not scoped to.
export function Row({
  label,
  value,
  deemphasized = false,
}: {
  label: string;
  value: string | number | null;
  deemphasized?: boolean;
}) {
  return (
    <div className={`dc-row${deemphasized ? " dc-row--deemphasis" : ""}`}>
      <span className="label">{label}</span>
      <span className="dc-val mono">{value ?? "—"}</span>
    </div>
  );
}
