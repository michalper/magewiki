import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AccessTokenRequiredError, setStoredAccessToken } from "./access-token";
import { parseSseBlock, streamSse } from "./sse";

type Ev = { event: string; [key: string]: unknown };

describe("parseSseBlock", () => {
  it("parses a well-formed single-line event", () => {
    const block = 'event: token\ndata: {"text":"hi"}';
    expect(parseSseBlock<Ev>(block)).toEqual({ event: "token", text: "hi" });
  });

  it("returns null when there is no data line", () => {
    expect(parseSseBlock<Ev>("event: token")).toBeNull();
  });

  it("returns null when there is no event line", () => {
    expect(parseSseBlock<Ev>('data: {"text":"hi"}')).toBeNull();
  });

  it("concatenates multiple data lines per the SSE spec instead of taking only the first", () => {
    const block = 'event: token\ndata: {"text":\ndata: "hi"}';
    expect(parseSseBlock<Ev>(block)).toEqual({ event: "token", text: "hi" });
  });

  it("returns null (not throw) on malformed JSON, so one bad block can't kill the stream", () => {
    const block = "event: token\ndata: {not valid json";
    expect(parseSseBlock<Ev>(block)).toBeNull();
  });
});

describe("streamSse", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  function fakeResponse(chunks: string[], { ok = true, status = 200 } = {}) {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
    return { ok, status, body: stream } as unknown as Response;
  }

  it("delivers events split arbitrarily across chunk boundaries", async () => {
    const events: Ev[] = [];
    const raw = 'event: token\ndata: {"text":"hello"}\n\nevent: done\ndata: {}\n\n';
    // Split mid-block, not on a convenient boundary.
    const chunks = [raw.slice(0, 10), raw.slice(10, 25), raw.slice(25)];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse(chunks)));

    await streamSse<Ev>("/x", {}, (e) => events.push(e));

    expect(events).toEqual([{ event: "token", text: "hello" }, { event: "done" }]);
  });

  it("skips a malformed event but keeps delivering the rest of the stream", async () => {
    const events: Ev[] = [];
    const raw = "event: token\ndata: {broken\n\n" + 'event: done\ndata: {}\n\n';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse([raw])));

    await streamSse<Ev>("/x", {}, (e) => events.push(e));

    expect(events).toEqual([{ event: "done" }]);
  });

  it("silently drops a malformed trailing block with no closing blank line", async () => {
    const events: Ev[] = [];
    const raw = 'event: token\ndata: {"text":"a"}\n\nevent: done\ndata: {broken';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse([raw])));

    await streamSse<Ev>("/x", {}, (e) => events.push(e));

    expect(events).toEqual([{ event: "token", text: "a" }]);
  });

  it("best-effort parses a trailing block with no closing blank line", async () => {
    const events: Ev[] = [];
    const raw = 'event: token\ndata: {"text":"a"}\n\nevent: done\ndata: {}';
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse([raw])));

    await streamSse<Ev>("/x", {}, (e) => events.push(e));

    expect(events).toEqual([{ event: "token", text: "a" }, { event: "done" }]);
  });

  it("throws when the response is not ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse([], { ok: false, status: 500 })));

    await expect(streamSse<Ev>("/x", {}, () => {})).rejects.toThrow("500");
  });

  it("throws AccessTokenRequiredError on a 401 instead of a generic error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(fakeResponse([], { ok: false, status: 401 })));

    await expect(streamSse<Ev>("/x", {}, () => {})).rejects.toBeInstanceOf(AccessTokenRequiredError);
  });

  it("sends the stored access token as a header when one is set", async () => {
    setStoredAccessToken("my-token");
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse(['event: done\ndata: {}\n\n']));
    vi.stubGlobal("fetch", fetchMock);

    await streamSse<Ev>("/x", {}, () => {});

    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get("X-Access-Token")).toBe("my-token");
  });
});
