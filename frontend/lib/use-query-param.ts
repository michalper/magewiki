import { useSyncExternalStore } from "react";

const listeners = new Set<() => void>();

function subscribe(callback: () => void): () => void {
  listeners.add(callback);
  window.addEventListener("popstate", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("popstate", callback);
  };
}

/** Call after mutating the URL via history.replaceState/pushState, since
 * those don't fire a "popstate" event the way back/forward navigation does. */
export function notifyQueryParamChange(): void {
  for (const callback of listeners) callback();
}

/** Reads a URL query param client-side only — never during SSR/static
 * render, since the server has no URL to read. */
export function useQueryParam(name: string): string | null {
  return useSyncExternalStore(
    subscribe,
    () => new URLSearchParams(window.location.search).get(name),
    () => null
  );
}
