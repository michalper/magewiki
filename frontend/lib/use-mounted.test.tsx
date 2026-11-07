import { renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { useMounted } from "./use-mounted";

describe("useMounted", () => {
  it("returns true once rendered on the client", () => {
    const { result } = renderHook(() => useMounted());
    expect(result.current).toBe(true);
  });

  it("returns false server-side, before hydration", () => {
    function Probe() {
      const mounted = useMounted();
      return mounted ? "mounted" : "not-mounted";
    }
    expect(renderToString(<Probe />)).toBe("not-mounted");
  });
});
