import { AccessTokenRequiredError, getStoredAccessToken } from "@/lib/access-token";

export function parseSseBlock<T extends { event: string }>(block: string): T | null {
  const lines = block.split("\n");
  const eventLine = lines.find((l) => l.startsWith("event: "));
  // The SSE spec allows multiple "data: " lines per block, concatenated with "\n"
  // — this parser only ever took the first one. Not a live bug today (the only
  // producer, format_sse(), always emits exactly one data line per block), but an
  // implicit, undocumented assumption that would otherwise silently truncate data.
  const dataLines = lines.filter((l) => l.startsWith("data: "));
  if (!eventLine || dataLines.length === 0) return null;
  const event = eventLine.slice("event: ".length);
  const rawData = dataLines.map((l) => l.slice("data: ".length)).join("\n");
  try {
    const data = JSON.parse(rawData);
    return { event, ...data } as T;
  } catch {
    // A single malformed block must not take down the whole stream — the caller's
    // read loop would otherwise see this throw propagate out of a rejected
    // promise, killing an otherwise-healthy connection over one bad frame.
    return null;
  }
}

export async function streamSse<T extends { event: string }>(
  url: string,
  body: unknown,
  onEvent: (event: T) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const token = getStoredAccessToken();
  if (token) headers.set("X-Access-Token", token);

  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (res.status === 401) throw new AccessTokenRequiredError();
  if (!res.ok || !res.body) {
    throw new Error(`API responded with ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex: number;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);
      const event = parseSseBlock<T>(block);
      if (event) onEvent(event);
    }
  }

  // A leftover block with no trailing "\n\n" (the connection closed right after
  // flushing it, with no further separator ever arriving) was previously dropped
  // silently — best-effort parse it rather than discard real data at the end of
  // an otherwise-healthy stream.
  if (buffer.trim()) {
    const event = parseSseBlock<T>(buffer);
    if (event) onEvent(event);
  }
}
