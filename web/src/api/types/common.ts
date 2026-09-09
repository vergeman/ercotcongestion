// =============================================================================
// Shared primitives used across more than one domain.
// =============================================================================

// Explicitly describes a bootstrap section's soft-fail state and, where the
// resource has one, the source artifact identity behind its payload.
export interface BootstrapSectionStatus {
  available: boolean;
  unavailable_reason: string | null;
  run_id: string | null;
  delivery_date: string | null;
  horizon: number | null;
}

export interface SourceDescriptor {
  id: string;
  series_id?: string | null;
  label: string;
  definition: string;
}
