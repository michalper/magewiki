import { AccessTokenRequiredError, getStoredAccessToken } from "@/lib/access-token";

export const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Shared by every page's plain JSON fetch (GET or PATCH) — was independently
// re-typed in 8 files. Surfaces the backend's own error `detail` when present
// (previously only the settings PATCH call did this; every other call site
// just said "API responded with 404" even when the backend sent something
// more specific) instead of dropping it on the floor.
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  // Harmless to send on the read-only endpoints that never check it — only
  // the handful of write/cost-incurring routes actually enforce this header,
  // and only when the deployment set WRITE_ACCESS_TOKEN (see CLAUDE.md's
  // Phase 24 decision note).
  const token = getStoredAccessToken();
  if (token) headers.set("X-Access-Token", token);

  const res = await fetch(`${apiUrl()}${path}`, { ...init, headers });
  if (res.status === 401) throw new AccessTokenRequiredError();
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `API responded with ${res.status}`);
  }
  return res.json();
}
