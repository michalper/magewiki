import { useSyncExternalStore } from "react";

/** Reads a CSS media query client-side only (SSR snapshot is always false,
 * matching lib/use-query-param.ts's own "no URL on the server" convention). */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (callback) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", callback);
      return () => mql.removeEventListener("change", callback);
    },
    () => window.matchMedia(query).matches,
    () => false
  );
}
