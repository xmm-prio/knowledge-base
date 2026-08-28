/**
 * Who is writing.
 *
 * The service has no authentication -- it is reachable only inside the network -- but every
 * write still has to be attributed, because git history is only useful if it says who
 * concluded what. So the browser remembers a name and sends it along.
 */

import { useCallback, useSyncExternalStore } from "react";

const KEY = "knowledge-base.author";
const DEFAULT_AUTHOR = "";

const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function read(): string {
  return window.localStorage.getItem(KEY) ?? DEFAULT_AUTHOR;
}

export function useAuthor(): [string, (name: string) => void] {
  const author = useSyncExternalStore(subscribe, read, () => DEFAULT_AUTHOR);
  const setAuthor = useCallback((name: string) => {
    window.localStorage.setItem(KEY, name);
    for (const listener of listeners) listener();
  }, []);
  return [author, setAuthor];
}
