const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type ApiErrorKind = "abort" | "transport" | "invalid-payload" | "http";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly cause?: unknown;

  constructor(
    message: string,
    kind: ApiErrorKind,
    status?: number,
    cause?: unknown,
  ) {
    super(message);
    this.name = kind === "abort" ? "AbortError" : "ApiError";
    this.kind = kind;
    this.status = status;
    this.cause = cause;
  }
}

export async function requestRequiredJson<T>(
  path: string,
  options: { query?: URLSearchParams; signal?: AbortSignal } = {},
): Promise<T> {
  const value = await requestJson<T>(path, { ...options, unavailable: [] });
  // An empty unavailable list means requestJson either resolves T or throws.
  return value as T;
}

export function apiUrl(path: string, query?: URLSearchParams): string {
  const suffix = query?.toString();
  return `${BASE}${path}${suffix ? `?${suffix}` : ""}`;
}

/**
 * The single JSON boundary for web API calls.  An unavailable artifact is a
 * normal, renderable state (`null`); all other failures retain a typed cause.
 */
export async function requestJson<T>(
  path: string,
  options: {
    query?: URLSearchParams;
    signal?: AbortSignal;
    unavailable?: readonly number[];
  } = {},
): Promise<T | null> {
  try {
    const response = await fetch(apiUrl(path, options.query), { signal: options.signal });
    if ((options.unavailable ?? [503]).includes(response.status)) return null;
    if (!response.ok) {
      throw new ApiError(`${path} ${response.status}`, "http", response.status);
    }
    try {
      return await response.json() as T;
    } catch (error) {
      throw new ApiError(`${path} returned invalid JSON`, "invalid-payload", response.status, error);
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(`${path} request aborted`, "abort", undefined, error);
    }
    throw new ApiError(`${path} request failed`, "transport", undefined, error);
  }
}
