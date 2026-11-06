export const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Shared by every page's plain JSON fetch (GET or PATCH) — was independently
// re-typed in 8 files. Surfaces the backend's own error `detail` when present
// (previously only the settings PATCH call did this; every other call site
// just said "API responded with 404" even when the backend sent something
// more specific) instead of dropping it on the floor.
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiUrl()}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `API responded with ${res.status}`);
  }
  return res.json();
}
