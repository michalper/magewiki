import { useEffect, useState } from "react";

/** Delays reacting to a fast-changing value (e.g. a search input) until it's
 * stopped changing for `delayMs` — so a filter/sort over a large list
 * re-runs once per pause in typing instead of on every keystroke. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
