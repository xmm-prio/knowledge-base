/**
 * The one way a page talks to the API.
 *
 * There is no cache and no store: the knowledge base is small, every page is a handful of
 * requests, and a stale tree after someone else's write is worse than a re-fetch. What this
 * does own is the part every page would otherwise re-implement -- the three states, the
 * out-of-order guard, and a `reload` for after a mutation.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface Async<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** Run `task` whenever `deps` change. Pass `null` as the task to stand down. */
export function useAsync<T>(task: (() => Promise<T>) | null, deps: unknown[]): Async<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(task !== null);
  const [nonce, setNonce] = useState(0);
  const generation = useRef(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!task) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    const mine = ++generation.current;
    setLoading(true);
    setError(null);
    task().then(
      (value) => {
        if (generation.current !== mine) return;
        setData(value);
        setLoading(false);
      },
      (failure) => {
        if (generation.current !== mine) return;
        setData(null);
        setError(failure);
        setLoading(false);
      },
    );
    // The task closure is rebuilt every render; `deps` is what actually decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { data, error, loading, reload };
}

export interface Action<A extends unknown[], T> {
  run: (...args: A) => Promise<T | null>;
  running: boolean;
  error: unknown;
  result: T | null;
  reset: () => void;
}

/** A mutation: same three states, but fired by hand rather than by a dependency change. */
export function useAction<A extends unknown[], T>(
  task: (...args: A) => Promise<T>,
): Action<A, T> {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<T | null>(null);
  const latest = useRef(task);
  latest.current = task;

  const run = useCallback(async (...args: A) => {
    setRunning(true);
    setError(null);
    try {
      const value = await latest.current(...args);
      setResult(value);
      return value;
    } catch (failure) {
      setError(failure);
      return null;
    } finally {
      setRunning(false);
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setResult(null);
  }, []);

  return { run, running, error, result, reset };
}
