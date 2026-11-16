import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccessTokenPrompt } from "./access-token-gate";

describe("AccessTokenPrompt", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores the trimmed token and unlocks on submit", async () => {
    const onUnlock = vi.fn();
    const user = userEvent.setup();
    render(<AccessTokenPrompt onUnlock={onUnlock} />);

    await user.type(screen.getByLabelText("Access token"), "  secret-token  ");
    await user.click(screen.getByRole("button", { name: "Unlock" }));

    expect(localStorage.getItem("magewiki-access-token")).toBe("secret-token");
    expect(onUnlock).toHaveBeenCalledOnce();
  });

  it("does nothing on a blank/whitespace-only submit", () => {
    // The Unlock button is already disabled for a blank input -- this covers
    // the form's own early-return guard against a submit bypassing that (e.g.
    // a programmatic submit), not a click a real user could make.
    const onUnlock = vi.fn();
    render(<AccessTokenPrompt onUnlock={onUnlock} />);

    fireEvent.submit(screen.getByLabelText("Access token").closest("form")!);

    expect(localStorage.getItem("magewiki-access-token")).toBeNull();
    expect(onUnlock).not.toHaveBeenCalled();
  });
});
