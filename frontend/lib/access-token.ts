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
