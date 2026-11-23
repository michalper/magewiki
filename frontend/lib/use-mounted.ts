import { useSyncExternalStore } from "react";

// useSyncExternalStore's own contract requires subscribe to return an
// unsubscribe function -- this store's snapshot (true/false, below) never
// actually changes after mount, so there's nothing to ever unsubscribe from.
// eslint-disable-next-line @typescript-eslint/no-empty-function
const subscribe = () => () => {};

/** True only after client-side hydration — avoids a server/client mismatch
 * for anything that depends on browser-only state (e.g. the resolved theme). */
export function useMounted(): boolean {
  return useSyncExternalStore(subscribe, () => true, () => false);
}
