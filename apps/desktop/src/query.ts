// SPDX-License-Identifier: AGPL-3.0-or-later
// A small query cache: one shared result per key, refetched on invalidation (job
// events, worker restarts). Enough for this app without a query library.
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { type ApiError, toApiError } from "./api";

interface Entry {
  data?: unknown;
  error?: ApiError;
  loading: boolean;
  version: number;
}

const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
const fetchers = new Map<string, () => Promise<unknown>>();
const inflight = new Map<string, Promise<void>>();

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function load(key: string): Promise<void> {
  const fetcher = fetchers.get(key);
  if (!fetcher) return Promise.resolve();
  const running = inflight.get(key);
  if (running) return running;
  const previous = entries.get(key);
  entries.set(key, { ...previous, loading: true, version: (previous?.version ?? 0) + 1 });
  emit();
  const promise = fetcher()
    .then(
      (data) => entries.set(key, { data, loading: false, version: entries.get(key)?.version ?? 0 }),
      (error: unknown) =>
        entries.set(key, {
          ...entries.get(key),
          error: toApiError(error),
          loading: false,
          version: entries.get(key)?.version ?? 0,
        }),
    )
    .then(() => {
      inflight.delete(key);
      emit();
    });
  inflight.set(key, promise);
  return promise;
}

/** Refetch every cached query whose key starts with one of the prefixes (all if none). */
export function invalidate(...prefixes: string[]): void {
  for (const key of fetchers.keys()) {
    if (prefixes.length === 0 || prefixes.some((p) => key.startsWith(p))) void load(key);
  }
}

/** For tests: forget everything. */
export function resetQueries(): void {
  entries.clear();
  fetchers.clear();
  inflight.clear();
}

export interface QueryResult<T> {
  data: T | undefined;
  error: ApiError | undefined;
  loading: boolean;
  refetch: () => void;
}

export function useQuery<T>(key: string | null, fetcher: () => Promise<T>): QueryResult<T> {
  const entry = useSyncExternalStore(subscribe, () => (key ? entries.get(key) : undefined));
  useEffect(() => {
    if (!key) return;
    const known = fetchers.has(key);
    fetchers.set(key, fetcher);
    if (!known || !entries.has(key)) void load(key);
    // The fetcher is captured per key; a changed closure for the same key is ignored.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const refetch = useCallback(() => {
    if (key) void load(key);
  }, [key]);
  return {
    data: entry?.data as T | undefined,
    error: entry?.error,
    loading: key !== null && (entry?.loading ?? true),
    refetch,
  };
}

/** Run an action and remember its error for display. */
export function useAction<A extends unknown[]>(
  action: (...args: A) => Promise<unknown>,
): { run: (...args: A) => Promise<boolean>; busy: boolean; error: ApiError | undefined } {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>();
  const run = useCallback(
    async (...args: A) => {
      setBusy(true);
      setError(undefined);
      try {
        await action(...args);
        return true;
      } catch (e) {
        setError(toApiError(e));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [action],
  );
  return { run, busy, error };
}
