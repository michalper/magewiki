import { afterEach, describe, expect, it } from "vitest";
import { AccessTokenRequiredError, getStoredAccessToken, setStoredAccessToken } from "./access-token";

describe("access-token", () => {
  afterEach(() => {
    localStorage.clear();
  });

  it("returns null when nothing is stored", () => {
    expect(getStoredAccessToken()).toBeNull();
  });

  it("round-trips a stored token", () => {
    setStoredAccessToken("abc123");
    expect(getStoredAccessToken()).toBe("abc123");
  });
});

describe("AccessTokenRequiredError", () => {
  it("is an Error with a distinguishable name", () => {
    const err = new AccessTokenRequiredError();
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("AccessTokenRequiredError");
  });
});
