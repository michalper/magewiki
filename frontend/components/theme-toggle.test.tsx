import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "./theme-toggle";

const setThemeMock = vi.fn();
let resolvedTheme = "light";

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme, setTheme: setThemeMock }),
}));

describe("ThemeToggle", () => {
  it("toggles from light to dark", async () => {
    resolvedTheme = "light";
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: "Toggle theme" }));

    expect(setThemeMock).toHaveBeenCalledWith("dark");
  });

  it("toggles from dark to light", async () => {
    resolvedTheme = "dark";
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(screen.getByRole("button", { name: "Toggle theme" }));

    expect(setThemeMock).toHaveBeenCalledWith("light");
  });
});
