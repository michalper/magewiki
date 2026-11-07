import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useChartPalette } from "./chart-palette";

let resolvedTheme = "light";
vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme }),
}));

describe("useChartPalette", () => {
  it("returns the light palette by default", () => {
    resolvedTheme = "light";
    const { result } = renderHook(() => useChartPalette());
    expect(result.current.ink.primary).toBe("#0b0b0b");
    expect(result.current.track).toBe("#f0efec");
  });

  it("returns the dark palette once mounted with resolvedTheme dark", () => {
    resolvedTheme = "dark";
    const { result } = renderHook(() => useChartPalette());
    expect(result.current.ink.primary).toBe("#f0efec");
    expect(result.current.track).toBe("#383835");
    expect(result.current.sequential).toBe("#3987e5");
  });

  it("always uses the same status colors regardless of theme", () => {
    resolvedTheme = "dark";
    const { result } = renderHook(() => useChartPalette());
    expect(result.current.status.critical).toBe("#d03b3b");
  });
});
