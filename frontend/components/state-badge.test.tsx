import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StateBadge } from "./state-badge";

describe("StateBadge", () => {
  it.each(["up_to_date", "pending", "scanning", "analyzing", "embedding", "failed", "paused_budget"])(
    "renders a known state label: %s",
    (state) => {
      render(<StateBadge state={state} />);
      expect(screen.getByText(`State: ${state}`)).toBeInTheDocument();
    },
  );

  it("falls back to a generic description for an unknown state", () => {
    render(<StateBadge state="some_future_state" />);
    expect(screen.getByText("State: some_future_state")).toBeInTheDocument();
  });
});
