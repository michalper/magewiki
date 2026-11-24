import { describe, expect, it } from "vitest";
import { buildHealthReportMarkdown } from "./health-report";
import type { components } from "@/lib/api-types";

type ModuleSummary = components["schemas"]["ModuleSummary"];

function module(overrides: Partial<ModuleSummary> = {}): ModuleSummary {
  return {
    id: 1,
    name: "Vendor_Module",
    composer_name: "vendor/module",
    source_type: "app_code",
    path: "app/code/Vendor/Module",
    repo_root: "/sites/store-a",
    enabled: true,
    state: "up_to_date",
    setup_version: "1.0.0",
    class_count: 0,
    plugin_count: 0,
    observer_count: 0,
    last_scanned_at: "2026-01-01T00:00:00Z",
    tags: [],
    has_readme: true,
    has_tests: true,
    has_module_doc: true,
    phpunit_tests_run: null,
    phpunit_tests_failed: null,
    phpunit_coverage_percent: null,
    finding_counts: {},
    ...overrides,
  };
}

const GENERATED_AT = new Date("2026-02-01T12:00:00Z");
const ORIGIN = "https://magewiki.example";

describe("buildHealthReportMarkdown", () => {
  it("reports no modules scanned when the repo is empty", () => {
    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules: [],
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    expect(report).toContain("No modules scanned under this repo yet.");
    expect(report).not.toContain("## Overview");
  });

  it("reports a clean fleet with no findings", () => {
    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules: [module({ id: 1 }), module({ id: 2, enabled: false, has_readme: false })],
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    expect(report).toContain("- 2 modules");
    expect(report).toContain("- 50% enabled");
    expect(report).toContain("- 50% with a README");
    expect(report).toContain("No quality findings — clean fleet.");
    expect(report).toContain("No modules have any findings.");
  });

  it("singularizes the module count for exactly one module", () => {
    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules: [module()],
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    expect(report).toContain("- 1 module\n");
  });

  it("groups findings under Critical/Warning headings by KPI tile accent", () => {
    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules: [module({ finding_counts: { hardcoded_secret: 2, deprecated_annotation: 1 } })],
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    const criticalIndex = report.indexOf("### Critical");
    const warningIndex = report.indexOf("### Warning");
    expect(criticalIndex).toBeGreaterThan(-1);
    expect(warningIndex).toBeGreaterThan(criticalIndex);
    expect(report).toContain("- **Hardcoded secrets**: 2");
    expect(report).toContain("- **Deprecated usages**: 1");
  });

  it("lists the top 5 riskiest modules by total finding count, descending, dropping the rest", () => {
    const modules = Array.from({ length: 7 }, (_, i) =>
      module({ id: i + 1, name: `Vendor_Module${i + 1}`, finding_counts: { hardcoded_secret: i + 1 } }),
    );

    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules,
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    const riskiestSection = report.slice(report.indexOf("## Riskiest modules"));
    expect(riskiestSection).toContain("[Vendor_Module7](https://magewiki.example/modules/7) — 7 findings");
    expect(riskiestSection).toContain("[Vendor_Module3](https://magewiki.example/modules/3) — 3 findings");
    expect(riskiestSection).not.toContain("Vendor_Module2");
    expect(riskiestSection).not.toContain("Vendor_Module1 ");
    // Vendor_Module7 (7 findings) must come before Vendor_Module3 (3 findings).
    expect(riskiestSection.indexOf("Vendor_Module7")).toBeLessThan(riskiestSection.indexOf("Vendor_Module3"));
  });

  it("singularizes a single finding on the riskiest-modules line", () => {
    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules: [module({ id: 9, name: "Vendor_One", finding_counts: { license_risk: 1 } })],
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    expect(report).toContain("[Vendor_One](https://magewiki.example/modules/9) — 1 finding\n");
  });

  it("reports the latest last_scanned_at across every module", () => {
    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules: [
        module({ id: 1, last_scanned_at: "2026-01-01T00:00:00Z" }),
        module({ id: 2, last_scanned_at: "2026-03-15T00:00:00Z" }),
      ],
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    expect(report).toContain("**Last scanned:** 2026-03-15T00:00:00.000Z");
  });

  it("renders a real 0% rather than treating it as missing data", () => {
    const report = buildHealthReportMarkdown({
      repoRoot: "/sites/store-a",
      modules: [module({ enabled: false, has_readme: false, has_tests: false, has_module_doc: false })],
      generatedAt: GENERATED_AT,
      origin: ORIGIN,
    });

    expect(report).toContain("- 0% enabled");
  });
});
