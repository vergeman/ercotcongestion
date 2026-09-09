import type { ReactNode } from "react";

interface Props {
  error: string | null;
  onRetry: () => void;
  children: ReactNode;
}

/** Keeps progressive evidence independent from the already-rendered hero shell. */
export default function BriefEvidence({ error, onRetry, children }: Props) {
  return (
    <>
      {error && (
        <div className="an-details-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={onRetry}>
            Retry details
          </button>
        </div>
      )}
      {children}
    </>
  );
}
