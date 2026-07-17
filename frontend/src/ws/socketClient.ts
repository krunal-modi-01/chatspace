import { ApiError } from '../api/problem';
import type { ConversationTarget } from '../api/types';
import { classifyCloseCode } from './closeCodes';
import {
  buildJoinFrame,
  buildLeaveFrame,
  buildPingFrame,
  buildTypingFrame,
  conversationTopicKey,
  parseServerFrame,
} from './frames';
import type { ServerFrame } from './frames';

/** `WebSocket.readyState` values, hand-rolled (not read off the global
 * `WebSocket` constructor) so this module works identically whether the
 * runtime's global `WebSocket` exists, and so tests can inject a minimal
 * fake without implementing static constants. */
const READY_STATE_OPEN = 1;

export type WsStatus = 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface BackoffOptions {
  initialMs: number;
  maxMs: number;
  factor: number;
}

const DEFAULT_BACKOFF: BackoffOptions = { initialMs: 500, maxMs: 15_000, factor: 2 };
const DEFAULT_HEARTBEAT_INTERVAL_MS = 20_000;
/** How long a connection must stay open before a prior refresh-and-reconnect
 * cycle is considered "resolved" and the consecutive-cycle counter resets
 * (code review finding #1). */
const DEFAULT_MIN_STABLE_CONNECTION_MS = 10_000;
/** Cap on consecutive refresh-then-immediate-reclose cycles (e.g. a
 * refreshed token being rejected again right away) before giving up and
 * escalating to a fatal state instead of hammering `/auth/refresh` and
 * `/v1/ws` in a tight loop forever (code review finding #1). */
const DEFAULT_MAX_CONSECUTIVE_REFRESH_CYCLES = 3;

/** Minimal shape this client needs from a WebSocket — satisfied by the real
 * global `WebSocket` and by test doubles alike. */
export interface WebSocketLike {
  readyState: number;
  onopen: (() => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onerror: (() => void) | null;
  send(data: string): void;
  close(code?: number): void;
}

export interface SocketClientOptions {
  /** Builds the connect URL — no token embedded. The access token is sent
   * via the `Sec-WebSocket-Protocol: bearer, <jwt>` sub-protocol instead of
   * a `?access_token=` query param, so it never lands in a URL that
   * proxies/servers may write to access logs (matches the backend's
   * purpose-built `bearer` sub-protocol fallback, `app/ws/auth.py`). */
  buildUrl: () => string;
  getAccessToken: () => string | null;
  /** Forces a token refresh (reuses the REST client's single-flight
   * refresh guard); resolves with the new access token or throws. */
  refreshAccessToken: () => Promise<string>;
  onStatusChange?: (status: WsStatus) => void;
  onFrame?: (frame: ServerFrame) => void;
  /** Invoked once for a terminal close — session is gone (`revoked`,
   * `deactivated`) or unrecoverable (`auth-failed`, i.e. refresh itself
   * failed with a definitive 401/403). No further reconnect attempts follow. */
  onFatal?: (reason: 'revoked' | 'deactivated' | 'auth-failed') => void;
  /** Injectable for tests; defaults to the global `WebSocket`. `protocols`
   * carries the `['bearer', <jwt>]` sub-protocol offer. */
  webSocketFactory?: (url: string, protocols?: string[]) => WebSocketLike;
  heartbeatIntervalMs?: number;
  backoff?: BackoffOptions;
  /** How long a connection must stay open before a refresh-and-reconnect
   * cycle counts as "resolved" (see `DEFAULT_MIN_STABLE_CONNECTION_MS`). */
  minStableConnectionMs?: number;
  /** Cap on consecutive refresh-then-immediate-reclose cycles before this
   * client gives up and reports `onFatal('auth-failed')` instead of
   * retrying forever (see `DEFAULT_MAX_CONSECUTIVE_REFRESH_CYCLES`). */
  maxConsecutiveRefreshCycles?: number;
}

/** A refresh failure is only proof the session is actually gone when the
 * refresh endpoint itself definitively rejected it (401/403). Anything else
 * — a thrown network error, a 5xx, the refresh endpoint being briefly
 * unreachable — is transient and must not permanently stop reconnection
 * (see code review finding #1). */
function isFatalAuthError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 401 || err.status === 403);
}

/**
 * Reconnecting `/v1/ws` client (T33): connects with the access token,
 * tracks joined conversations and re-subscribes on every (re)connect, sends
 * periodic heartbeat `ping` frames while open, and classifies every close
 * code into refresh-and-reconnect / backoff-reconnect / terminal-stop per
 * `classifyCloseCode`. Message dedup/ordering and REST catch-up are the
 * caller's concern (`useConversationSocket`) — this class only owns the
 * transport.
 */
export class ReconnectingSocket {
  private socket: WebSocketLike | null = null;
  private status: WsStatus = 'closed';
  private manuallyClosed = false;
  private destroyed = false;
  /** True once the current connection attempt has reached `open` at least
   * once — reset to `false` at the start of every `open()` call. Used to
   * detect a pre-accept close (see `handleClose`). */
  private openedThisAttempt = false;
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  /** Number of refresh-and-reconnect cycles completed since the connection
   * last stayed open for `minStableConnectionMs` (or since construction).
   * Reset by `stableTimer` firing; incremented on every successful refresh
   * that leads to a reopen (code review finding #1). */
  private refreshCycleCount = 0;
  private stableTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly joined = new Map<string, ConversationTarget>();
  private readonly backoff: BackoffOptions;
  private readonly minStableConnectionMs: number;
  private readonly maxConsecutiveRefreshCycles: number;
  private readonly options: SocketClientOptions;

  constructor(options: SocketClientOptions) {
    this.options = options;
    this.backoff = options.backoff ?? DEFAULT_BACKOFF;
    this.minStableConnectionMs = options.minStableConnectionMs ?? DEFAULT_MIN_STABLE_CONNECTION_MS;
    this.maxConsecutiveRefreshCycles =
      options.maxConsecutiveRefreshCycles ?? DEFAULT_MAX_CONSECUTIVE_REFRESH_CYCLES;
  }

  getStatus(): WsStatus {
    return this.status;
  }

  /** Opens the connection. Safe to call once per client instance lifetime;
   * reconnects after a drop are scheduled internally. */
  connect(): void {
    this.manuallyClosed = false;
    this.destroyed = false;
    this.open();
  }

  /** Marks a conversation as joined (re-sent on every reconnect) and sends
   * the `join` frame immediately if the socket is currently open. */
  join(conversation: ConversationTarget): void {
    this.joined.set(conversationTopicKey(conversation), conversation);
    this.send(buildJoinFrame(conversation));
  }

  leave(conversation: ConversationTarget): void {
    this.joined.delete(conversationTopicKey(conversation));
    this.send(buildLeaveFrame(conversation));
  }

  /** Sends a `typing` frame for `conversation` (T34, F56) — fire-and-forget,
   * like `leave`: if the socket isn't currently open the frame is simply
   * dropped (no send queue), which is correct here since typing is
   * explicitly ephemeral/relay-only with no durable history to catch up on
   * (unlike `join`, there is nothing to re-send on the next reconnect). */
  sendTyping(conversation: ConversationTarget): void {
    this.send(buildTypingFrame(conversation));
  }

  /** Client-initiated clean close (e.g. navigating away) — no reconnect. */
  disconnect(): void {
    this.manuallyClosed = true;
    this.clearTimers();
    this.socket?.close(1000);
  }

  /** Permanently tears the client down (component unmount) — same as
   * `disconnect()` plus suppresses any reconnect already in flight. */
  destroy(): void {
    this.destroyed = true;
    this.disconnect();
  }

  private open(): void {
    const token = this.options.getAccessToken();
    if (!token) {
      // Nothing to connect with (e.g. logged out) — caller decides whether
      // to retry once a token appears; this class does not poll for one.
      this.setStatus('closed');
      return;
    }

    this.setStatus(this.reconnectAttempt > 0 ? 'reconnecting' : 'connecting');
    this.openedThisAttempt = false;
    const url = this.options.buildUrl();
    const factory = this.options.webSocketFactory ?? defaultWebSocketFactory;
    const socket = factory(url, ['bearer', token]);
    this.socket = socket;
    socket.onopen = this.handleOpen;
    socket.onmessage = this.handleMessage;
    socket.onclose = this.handleClose;
    socket.onerror = () => {
      // A WebSocket `error` event is always followed by a `close` event per
      // spec — all reconnect/fatal handling lives in `handleClose`.
    };
  }

  private send(frame: unknown): void {
    if (this.socket && this.socket.readyState === READY_STATE_OPEN) {
      this.socket.send(JSON.stringify(frame));
    }
    // If not open yet: `join` is safely re-sent by `handleOpen` for every
    // currently-tracked conversation on (re)connect, so no send queue is
    // needed; a `leave` sent while not connected has nothing server-side to
    // undo.
  }

  private handleOpen = (): void => {
    this.reconnectAttempt = 0;
    this.openedThisAttempt = true;
    this.setStatus('open');
    for (const conversation of this.joined.values()) {
      this.send(buildJoinFrame(conversation));
    }
    this.startHeartbeat();
    // If this connection survives `minStableConnectionMs`, treat any prior
    // refresh-and-reconnect cycles as resolved rather than letting them
    // count toward the consecutive-cycle cap forever (code review finding
    // #1). Cleared by `clearTimers()` on the next close, so a connection
    // that drops before stabilizing does not reset the counter.
    this.stableTimer = setTimeout(() => {
      this.refreshCycleCount = 0;
    }, this.minStableConnectionMs);
  };

  private handleMessage = (event: { data: unknown }): void => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(String(event.data));
    } catch {
      return; // malformed server frame — nothing to recover, not our contract to enforce
    }
    const frame = parseServerFrame(parsed);
    if (frame) {
      this.options.onFrame?.(frame);
    }
  };

  private handleClose = (event: { code: number }): void => {
    this.clearTimers();
    const wasManual = this.manuallyClosed;
    const openedBeforeThisClose = this.openedThisAttempt;

    if (this.destroyed) {
      this.setStatus('closed');
      return;
    }

    let action = classifyCloseCode(event.code, { clientInitiated: wasManual });

    // Workaround for a known backend gap (`app/ws/router.py`
    // `_authenticate_and_accept` calls `websocket.close(4401)` *before*
    // `websocket.accept()`): per the WebSocket spec/browser behavior, a
    // close sent before the handshake completes never reaches the client
    // as a real close frame/code — it surfaces as a plain abnormal closure
    // (code 1006) instead. A connection that never reached `open` in this
    // attempt therefore can't be trusted to have reported its true close
    // code, so treat it as ambiguous-auth and eagerly refresh rather than
    // retrying forever with the same stale token (code review finding #4).
    if (!wasManual && !openedBeforeThisClose && action.kind === 'reconnect') {
      action = { kind: 'refresh-and-reconnect' };
    }

    if (action.kind === 'stop') {
      this.setStatus('closed');
      if (action.reason !== 'client-initiated') {
        this.options.onFatal?.(action.reason);
      }
      return;
    }

    if (action.kind === 'refresh-and-reconnect') {
      this.setStatus('reconnecting');
      void this.refreshAndReconnect();
      return;
    }

    this.scheduleReconnect();
  };

  private async refreshAndReconnect(): Promise<void> {
    try {
      await this.options.refreshAccessToken();
    } catch (err) {
      if (this.destroyed) {
        return;
      }
      if (isFatalAuthError(err)) {
        this.setStatus('closed');
        this.options.onFatal?.('auth-failed');
        return;
      }
      // Transient failure (network error, refresh endpoint 5xx/unreachable)
      // — not proof the session is actually gone. Keep retrying with
      // backoff instead of permanently stopping.
      this.scheduleReconnect();
      return;
    }
    if (this.destroyed || this.manuallyClosed) {
      return;
    }

    this.refreshCycleCount += 1;
    if (this.refreshCycleCount > this.maxConsecutiveRefreshCycles) {
      // The refresh itself keeps succeeding, but the connection never
      // stays open long enough to reset the counter — the freshly-issued
      // token is being rejected again right away every time (clock skew,
      // a backend TTL bug, etc). Escalate to fatal instead of spinning
      // `/auth/refresh` + `/v1/ws` in a tight loop forever (code review
      // finding #1).
      this.clearTimers();
      this.setStatus('closed');
      this.options.onFatal?.('auth-failed');
      return;
    }

    this.reconnectAttempt = 0;
    if (this.refreshCycleCount === 1) {
      // First cycle since the last stable connection (or since start) —
      // 4402/4401 handling is meant to recover fast, so reconnect
      // immediately.
      this.open();
      return;
    }
    // A repeat cycle without ever stabilizing — back off before retrying
    // rather than reconnecting instantly again, escalating the delay with
    // each additional cycle.
    const delay = Math.min(
      this.backoff.initialMs * this.backoff.factor ** (this.refreshCycleCount - 2),
      this.backoff.maxMs,
    );
    this.reconnectTimer = setTimeout(() => {
      this.open();
    }, delay);
  }

  private scheduleReconnect(): void {
    this.setStatus('reconnecting');
    const delay = Math.min(
      this.backoff.initialMs * this.backoff.factor ** this.reconnectAttempt,
      this.backoff.maxMs,
    );
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.open();
    }, delay);
  }

  private startHeartbeat(): void {
    const interval = this.options.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_INTERVAL_MS;
    this.heartbeatTimer = setInterval(() => {
      this.send(buildPingFrame());
    }, interval);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.stableTimer) {
      clearTimeout(this.stableTimer);
      this.stableTimer = null;
    }
  }

  private setStatus(status: WsStatus): void {
    if (this.status === status) {
      return;
    }
    this.status = status;
    this.options.onStatusChange?.(status);
  }
}

function defaultWebSocketFactory(url: string, protocols?: string[]): WebSocketLike {
  return new WebSocket(url, protocols) as unknown as WebSocketLike;
}
