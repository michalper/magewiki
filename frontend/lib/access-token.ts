const STORAGE_KEY = "magewiki-access-token";

// Wrapped in try/catch: private browsing, blocked site data, or a disabled
// localStorage must not break the app -- the gate simply behaves as if no
// token were stored (same as a deployment that never set WRITE_ACCESS_TOKEN).
export function getStoredAccessToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredAccessToken(token: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Nothing to do -- the token just won't be remembered across reloads.
  }
}

// Thrown by apiFetch/streamSse on a 401 so callers can tell "this deployment
// has a write-access gate and no/the wrong token is stored" apart from every
// other failure, and show a prompt instead of a plain error message.
export class AccessTokenRequiredError extends Error {
  constructor() {
    super("This deployment requires an access token for this action.");
    this.name = "AccessTokenRequiredError";
  }
}

// Shared by apiFetch and streamSse — the stored token, if any, goes on every
// request the same way; harmless to send on the read-only endpoints that
// never check it (see apiFetch's own comment on why).
export function withAccessToken(headers: Headers): void {
  const token = getStoredAccessToken();
  if (token) headers.set("X-Access-Token", token);
}

// Shared by apiFetch and streamSse — a 401 always means the same thing here:
// the deployment has a write-access gate and no/the wrong token is stored.
export function throwIfAccessTokenRequired(res: Response): void {
  if (res.status === 401) throw new AccessTokenRequiredError();
}
