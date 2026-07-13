/**
 * `/v1/ws` close-code catalogue mirrored from the frozen API contract
 * (backend: `app/ws/close_codes.py`). Enum-typed close codes are an **open
 * set** — the client MUST tolerate an undocumented code gracefully (treat
 * as transient) rather than crash or hang.
 */
export const WsCloseCode = {
  NORMAL_CLOSURE: 1000,
  GOING_AWAY: 1001,
  AUTH_FAILED: 4401,
  TOKEN_EXPIRED: 4402,
  TOKEN_REVOKED: 4403,
  USER_DEACTIVATED: 4404,
  HEARTBEAT_TIMEOUT: 4408,
  RATE_LIMITED: 4429,
} as const;

export type WsCloseAction =
  | { kind: 'refresh-and-reconnect' }
  | { kind: 'reconnect' }
  | { kind: 'stop'; reason: 'revoked' | 'deactivated' | 'auth-failed' | 'client-initiated' };

/**
 * Classifies a close code into the reconnect strategy this client uses:
 *
 * - `4402` (token-expired mid-connection): refresh the access token, then
 *   reconnect — this is the contract's explicit guidance for this code.
 * - `4401` (auth-failed at connect): the token was already stale/invalid
 *   before the socket even opened (e.g. a long-backgrounded tab) — one
 *   refresh-then-retry is a reasonable recovery; if the refresh itself
 *   fails the caller treats it as `auth-failed` fatal (session is gone).
 * - `4403`/`4404` (revoked / deactivated): terminal — reconnecting would
 *   just reproduce the same rejection, and these mean the session is
 *   genuinely gone (logout elsewhere, password change, admin deactivation).
 * - `1001`/`4408`/`4429` and any undocumented/future code: transient —
 *   reconnect with backoff. A `1000` is only terminal when *this* client
 *   initiated the close (`disconnect()`); a server-sent `1000` (unusual,
 *   but the contract doesn't forbid it) is still treated as transient.
 */
export function classifyCloseCode(
  code: number,
  { clientInitiated }: { clientInitiated: boolean },
): WsCloseAction {
  if (clientInitiated && code === WsCloseCode.NORMAL_CLOSURE) {
    return { kind: 'stop', reason: 'client-initiated' };
  }

  switch (code) {
    case WsCloseCode.TOKEN_EXPIRED:
    case WsCloseCode.AUTH_FAILED:
      return { kind: 'refresh-and-reconnect' };
    case WsCloseCode.TOKEN_REVOKED:
      return { kind: 'stop', reason: 'revoked' };
    case WsCloseCode.USER_DEACTIVATED:
      return { kind: 'stop', reason: 'deactivated' };
    default:
      // Includes NORMAL_CLOSURE (server-initiated), GOING_AWAY,
      // HEARTBEAT_TIMEOUT, RATE_LIMITED, and any unknown code.
      return { kind: 'reconnect' };
  }
}
