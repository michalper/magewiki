import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";

// @testing-library/react's auto-cleanup only self-registers for Jest; vitest
// needs this explicitly, or each test's rendered DOM leaks into the next.
afterEach(() => {
  cleanup();
});

// jsdom doesn't implement matchMedia at all -- next-themes (ThemeProvider,
// used by every page via app/providers.tsx) reads it to resolve the "system"
// theme.
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    // Both deprecated, but still part of MediaQueryList's own type -- this
    // mock must implement the full interface shape to type-check as one.
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    addListener: () => {},
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

// jsdom doesn't implement Element.scrollTo -- the Modules page's scan-log
// auto-scroll effect calls it directly on a real DOM node ref.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}
