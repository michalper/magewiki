import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EnabledBadge } from "./enabled-badge";

describe("EnabledBadge", () => {
  it("renders the enabled label for true", () => {
    render(<EnabledBadge enabled={true} />);
    expect(screen.getByText("Enabled: yes")).toBeInTheDocument();
  });

  it("renders the disabled label for false", () => {
    render(<EnabledBadge enabled={false} />);
    expect(screen.getByText("Enabled: no")).toBeInTheDocument();
  });

  it("renders the unknown label for null", () => {
    render(<EnabledBadge enabled={null} />);
    expect(screen.getByText("Enabled: unknown")).toBeInTheDocument();
  });
});
