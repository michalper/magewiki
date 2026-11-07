import { act, renderHook } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { notifyQueryParamChange, useQueryParam } from "./use-query-param";

function setSearch(search: string) {
  const url = new URL(window.location.href);
  url.search = search;
  window.history.replaceState(null, "", url);
}

describe("useQueryParam", () => {
  afterEach(() => {
    setSearch("");
  });

  it("reads the current value from the URL", () => {
    setSearch("?tab=settings");
    const { result } = renderHook(() => useQueryParam("tab"));
    expect(result.current).toBe("settings");
  });

  it("returns null when the param is absent", () => {
    setSearch("");
    const { result } = renderHook(() => useQueryParam("tab"));
    expect(result.current).toBeNull();
  });

  it("re-reads after a popstate event (back/forward navigation)", () => {
    setSearch("?tab=a");
    const { result } = renderHook(() => useQueryParam("tab"));
    expect(result.current).toBe("a");

    act(() => {
      setSearch("?tab=b");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(result.current).toBe("b");
  });

  it("re-reads after notifyQueryParamChange (programmatic history.replaceState)", () => {
    setSearch("?tab=a");
    const { result } = renderHook(() => useQueryParam("tab"));
    expect(result.current).toBe("a");

    act(() => {
      setSearch("?tab=c");
      notifyQueryParamChange();
    });

    expect(result.current).toBe("c");
  });

  it("unsubscribes from popstate on unmount", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderHook(() => useQueryParam("tab"));

    unmount();

    expect(removeSpy).toHaveBeenCalledWith("popstate", expect.any(Function));
  });

  it("returns null server-side, never reading a URL that doesn't exist on the server", () => {
    function Probe() {
      const value = useQueryParam("tab");
      return value ?? "null";
    }
    expect(renderToString(<Probe />)).toBe("null");
  });
});
