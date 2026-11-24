import { describe, expect, it } from "vitest";
import { FALLBACK_CHECK_TYPES, KPI_TILES, prettifyCheckType } from "./kpi-tiles";

describe("prettifyCheckType", () => {
  it("replaces underscores with spaces and capitalizes the first word", () => {
    expect(prettifyCheckType("hardcoded_secret")).toBe("Hardcoded secret");
  });

  it("leaves a single-word check_type's capitalization alone beyond the first letter", () => {
    expect(prettifyCheckType("secret")).toBe("Secret");
  });
});

describe("KPI_TILES / FALLBACK_CHECK_TYPES", () => {
  it("has at least one tile", () => {
    expect(KPI_TILES.length).toBeGreaterThan(0);
  });

  it("claims every check_type it knows about -- no duplicate entries across tiles", () => {
    const seen = new Set<string>();
    for (const tile of KPI_TILES) {
      for (const checkType of tile.checkTypes) {
        expect(seen.has(checkType)).toBe(false);
        seen.add(checkType);
      }
    }
  });

  it("is a plain array of check_type strings", () => {
    expect(Array.isArray(FALLBACK_CHECK_TYPES)).toBe(true);
    for (const checkType of FALLBACK_CHECK_TYPES) {
      expect(typeof checkType).toBe("string");
    }
  });
});
