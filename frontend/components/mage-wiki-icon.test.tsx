import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MageWikiIcon } from "./mage-wiki-icon";

describe("MageWikiIcon", () => {
  it("renders an svg with the given className", () => {
    const { container } = render(<MageWikiIcon className="size-4" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveClass("size-4");
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });

  it("renders without a className", () => {
    const { container } = render(<MageWikiIcon />);
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});
