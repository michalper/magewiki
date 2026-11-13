import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccessTokenRequiredError, setStoredAccessToken } from "./access-token";
import { apiFetch, apiUrl } from "./api";

describe("apiUrl", () => {
  it("defaults to localhost:8000", () => {
    expect(apiUrl()).toBe("http://localhost:8000");
  });
});

describe("apiFetch", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("throws AccessTokenRequiredError on a 401 instead of a generic error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: "missing token" }) }),
    );

    await expect(apiFetch("/scan")).rejects.toBeInstanceOf(AccessTokenRequiredError);
  });

  it("sends the stored access token as a header when one is set", async () => {
    setStoredAccessToken("my-token");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/modules");

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get("X-Access-Token")).toBe("my-token");
  });

  it("omits the access-token header when none is stored", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    await apiFetch("/modules");

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.has("X-Access-Token")).toBe(false);
  });

  it("returns the parsed JSON body on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ hello: "world" }),
      }),
    );

    const result = await apiFetch<{ hello: string }>("/modules");
    expect(result).toEqual({ hello: "world" });
  });

  it("surfaces the backend's own error detail when present", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: "module not found" }),
      }),
    );

    await expect(apiFetch("/modules/999")).rejects.toThrow("module not found");
  });

  it("falls back to a generic message when the body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error("not json");
        },
      }),
    );

    await expect(apiFetch("/modules")).rejects.toThrow("API responded with 500");
  });
});
