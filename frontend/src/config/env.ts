/**
 * Env-based configuration. All values are read from Vite's `import.meta.env`
 * so the API base URL can be swapped per-environment without a rebuild of
 * application logic (only the `.env` file changes).
 */

export function readApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (!raw) {
    // Sensible local-dev default; production deployments MUST set this.
    return '/v1';
  }
  return raw.endsWith('/') ? raw.slice(0, -1) : raw;
}

/** Derives the `wss://<host>/v1/ws` (or `ws://` in local dev) base from the
 * REST `apiBaseUrl` — same host/path, scheme swapped for the WebSocket
 * upgrade — unless an explicit override is set. Exported (in addition to
 * the derived `env.wsBaseUrl`) so this branchy pure function gets direct
 * unit coverage (code review finding #5). */
export function deriveWsBaseUrl(apiBaseUrl: string): string {
  if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
    return `${apiBaseUrl.replace(/^http/, 'ws')}/ws`;
  }
  // Relative base (e.g. `/v1`) — resolve against the current page origin so
  // this also works when the frontend is served from the same host as the
  // API behind a reverse proxy.
  const isSecurePage = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const host = typeof window !== 'undefined' ? window.location.host : 'localhost';
  return `${isSecurePage ? 'wss' : 'ws'}://${host}${apiBaseUrl}/ws`;
}

export function readWsBaseUrl(apiBaseUrl: string): string {
  const raw = import.meta.env.VITE_WS_BASE_URL as string | undefined;
  if (!raw) {
    return deriveWsBaseUrl(apiBaseUrl);
  }
  return raw.endsWith('/') ? raw.slice(0, -1) : raw;
}

const apiBaseUrl = readApiBaseUrl();

export const env = {
  apiBaseUrl,
  /** `/v1/ws` endpoint base (no query string, no token) — the WS client
   * authenticates via the `Sec-WebSocket-Protocol: bearer, <jwt>`
   * sub-protocol at connect time, not a URL query param, so the access
   * token never lands in a URL that proxies/servers may log (T33, frozen
   * contract). */
  wsBaseUrl: readWsBaseUrl(apiBaseUrl),
  isDev: import.meta.env.DEV,
} as const;
