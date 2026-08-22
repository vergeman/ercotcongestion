export interface CacheOptions {
  maxSize: number;
  ttlMs?: number;
}

interface CacheEntry<T> {
  value?: T;
  expiresAt?: number;
  promise?: Promise<T>;
  controller?: AbortController;
}

/** A bounded LRU cache that deduplicates loads and owns only its own aborts. */
export class QueryCache<T> {
  private readonly entries = new Map<string, CacheEntry<T>>();
  private readonly options: CacheOptions;

  constructor(options: CacheOptions) { this.options = options; }

  get(key: string): T | undefined {
    const entry = this.entries.get(key);
    if (!entry || entry.value === undefined || (entry.expiresAt != null && entry.expiresAt <= Date.now())) {
      if (entry?.expiresAt != null && entry.expiresAt <= Date.now()) this.entries.delete(key);
      return undefined;
    }
    this.touch(key, entry);
    return entry.value;
  }

  load(key: string, loader: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
    const cached = this.get(key);
    if (cached !== undefined) return Promise.resolve(cached);
    const existing = this.entries.get(key);
    if (existing?.promise) return existing.promise;

    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const entry: CacheEntry<T> = existing ?? {};
    const promise = loader(controller.signal).then(
      (value) => {
        entry.value = value;
        entry.expiresAt = this.options.ttlMs == null ? undefined : Date.now() + this.options.ttlMs;
        entry.promise = undefined;
        entry.controller = undefined;
        this.touch(key, entry);
        this.evict();
        return value;
      },
      (error) => {
        entry.promise = undefined;
        entry.controller = undefined;
        this.entries.delete(key);
        throw error;
      },
    ).finally(() => signal?.removeEventListener("abort", abort));
    entry.promise = promise;
    entry.controller = controller;
    this.entries.set(key, entry);
    this.evict();
    return promise;
  }

  invalidate(key?: string): void {
    if (key == null) {
      for (const entry of this.entries.values()) entry.controller?.abort();
      this.entries.clear();
      return;
    }
    const entry = this.entries.get(key);
    entry?.controller?.abort();
    this.entries.delete(key);
  }

  private touch(key: string, entry: CacheEntry<T>): void {
    this.entries.delete(key);
    this.entries.set(key, entry);
  }

  private evict(): void {
    while (this.entries.size > this.options.maxSize) {
      const oldest = this.entries.entries().next().value as [string, CacheEntry<T>] | undefined;
      if (!oldest) return;
      oldest[1].controller?.abort();
      this.entries.delete(oldest[0]);
    }
  }
}
