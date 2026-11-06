import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/** True only after client-side hydration — avoids a server/client mismatch
 * for anything that depends on browser-only state (e.g. the resolved theme). */
export function useMounted(): boolean {
  return useSyncExternalStore(subscribe, () => true, () => false);
}
