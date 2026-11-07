import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Providers } from "./providers";

describe("Providers", () => {
  it("renders children wrapped in the query/theme providers", () => {
    render(
      <Providers>
        <div>child content</div>
      </Providers>,
    );
    expect(screen.getByText("child content")).toBeInTheDocument();
  });
});
