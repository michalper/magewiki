import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CHECK_TYPES, QualityBadges, sumFindingCounts } from "./quality-badges";

describe("sumFindingCounts", () => {
  it("sums every count", () => {
    expect(sumFindingCounts({ a: 2, b: 3 })).toBe(5);
  });

  it("is zero for an empty record", () => {
    expect(sumFindingCounts({})).toBe(0);
  });
});

describe("QualityBadges", () => {
  it('renders a single "clean" badge when every count is zero', () => {
    render(<QualityBadges findingCounts={{}} />);
    expect(screen.getByText("clean")).toBeInTheDocument();
  });

  it("renders one badge per non-zero check type, skipping zero counts", () => {
    render(<QualityBadges findingCounts={{ hardcoded_secret: 2, security_advisory: 0, phpstan_error: 5 }} />);

    expect(screen.getByText("2 secrets")).toBeInTheDocument();
    expect(screen.getByText("5 phpstan")).toBeInTheDocument();
    expect(screen.queryByText(/CVE/)).not.toBeInTheDocument();
  });

  it("pluralizes the secret count for exactly one", () => {
    render(<QualityBadges findingCounts={{ hardcoded_secret: 1 }} />);
    expect(screen.getByText("1 secret")).toBeInTheDocument();
  });

  it("covers every declared check type's label", () => {
    const allOnes = Object.fromEntries(CHECK_TYPES.map((c) => [c.key, 1]));
    render(<QualityBadges findingCounts={allOnes} />);
    for (const { label } of CHECK_TYPES) {
      expect(screen.getByText(label(1))).toBeInTheDocument();
    }
  });
});
