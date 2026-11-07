import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";

// @testing-library/react's auto-cleanup only self-registers for Jest; vitest
// needs this explicitly, or each test's rendered DOM leaks into the next.
afterEach(() => {
  cleanup();
});
