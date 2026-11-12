import { renderToString } from "react-dom/server";
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useMediaQuery } from "./use-media-query";

function mockMatchMedia(matches: boolean) {
  const addEventListener = vi.fn();
  const removeEventListener = vi.fn();
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({ matches, addEventListener, removeEventListener }),
  );
  return { addEventListener, removeEventListener };
}

describe("useMediaQuery", () => {
  beforeEach(() => {
    mockMatchMedia(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the real matchMedia result client-side", () => {
    mockMatchMedia(true);
    const { result } = renderHook(() => useMediaQuery("(min-width: 768px)"));
    expect(result.current).toBe(true);
  });

  it("subscribes to and unsubscribes from the change event", () => {
    const { addEventListener, removeEventListener } = mockMatchMedia(false);
    const { unmount } = renderHook(() => useMediaQuery("(min-width: 768px)"));

    expect(addEventListener).toHaveBeenCalledWith("change", expect.any(Function));
    unmount();
    expect(removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  });

  it("returns false server-side, never reading a media query that doesn't exist on the server", () => {
    function Probe() {
      const matches = useMediaQuery("(min-width: 768px)");
      return matches ? "true" : "false";
    }
    expect(renderToString(<Probe />)).toBe("false");
  });
});
