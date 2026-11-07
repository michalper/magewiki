import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TagBadge } from "./tag-badge";

describe("TagBadge", () => {
  it("renders the tag name", () => {
    render(<TagBadge tag="payments" />);
    expect(screen.getByText("payments")).toBeInTheDocument();
  });
});
