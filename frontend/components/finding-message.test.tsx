import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FindingMessage } from "./finding-message";

describe("FindingMessage", () => {
  it("renders plain text unchanged when there is no trailing URL citation", () => {
    render(<FindingMessage message="Composer package is missing a license field." />);
    expect(screen.getByText("Composer package is missing a license field.")).toBeInTheDocument();
  });

  it("renders a trailing (https://...) citation as a real link", () => {
    render(
      <FindingMessage message="CVE-2024-12345 — some vulnerability (https://example.com/advisories/GHSA-xxxx)" />,
    );
    const link = screen.getByRole("link", { name: "https://example.com/advisories/GHSA-xxxx" });
    expect(link).toHaveAttribute("href", "https://example.com/advisories/GHSA-xxxx");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("does not linkify a non-http(s) scheme", () => {
    render(<FindingMessage message="see the docs (javascript:alert(1))" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
