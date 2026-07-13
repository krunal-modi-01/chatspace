import { useEffect, useMemo, useRef, useState } from 'react';
import { refreshAccessToken } from '../api/httpClient';
import type { ConversationTarget, Message } from '../api/types';
import { env } from '../config/env';
import { authStoreApi, useAuthStore } from '../store/authStore';
import { fetchMissedMessages } from '../ws/catchUp';
import type {
  MessageCreatedFrame,
  MessageDeletedFrame,
  MessageDeletedPayload,
  MessageEditedFrame,
  ServerFrame,
} from '../ws/frames';
import {
  applyDeleted,
  emptyMessageMap,
  latestMessageId,
  sortedMessages,
  upsertMessages,
  type MessageMap,
} from '../ws/messageStore';
import { ReconnectingSocket, type WsStatus } from '../ws/socketClient';

export interface ConversationSocketState {
  /** Raw transport status — `useAuth`-style consumers generally want
   * `isReconnecting` instead; exposed for callers that need the full
   * lifecycle (e.g. a debug panel). */
  status: WsStatus;
  /** Dedup'd, id-ordered messages for the joined conversation (F54),
   * merged from catch-up history + live `message.created/edited/deleted`
   * events. */
  messages: Message[];
  /** True once a previously-open connection has dropped and a
   * reconnect/backoff attempt (or a 4402 refresh-then-reconnect) is under
   * way — drives the reconnecting banner (Flow K step 1). */
  isReconnecting: boolean;
  /** Set on a terminal close (`revoked`/`deactivated`/`auth-failed`) — no
   * further reconnect attempts follow. `revoked`/`deactivated` also clear
   * the local session so route guards redirect to `/login`. */
  fatalError: 'revoked' | 'deactivated' | 'auth-failed' | null;
  /** Non-fatal — a catch-up history fetch failed; the live socket keeps
   * running, but some missed messages may be absent until the next
   * successful catch-up (next reconnect, or a future manual retry). */
  catchUpError: string | null;
}

function buildWsUrl(): string {
  // No token in the URL — the access token is sent via the
  // `Sec-WebSocket-Protocol: bearer, <jwt>` sub-protocol (see
  // `ReconnectingSocket`), matching the backend's purpose-built mitigation
  // for tokens otherwise landing in a URL that proxies/servers may log.
  return env.wsBaseUrl;
}

/** Narrows an unknown `frame.data` payload to the minimal `Message` shape
 * this hook relies on, before ever touching it inside a `setState`
 * updater. A malformed/under-specified live frame (missing `data`, missing
 * `id`, etc.) is dropped and tolerated — same defensive posture as the
 * JSON-parse-failure path in `ReconnectingSocket` — rather than throwing
 * inside React state (code review finding #2). */
function isMessagePayload(data: unknown): data is Message {
  return typeof data === 'object' && data !== null && typeof (data as { id?: unknown }).id === 'string';
}

/** Same defensive narrowing as `isMessagePayload`, for `message.deleted`'s
 * distinct payload shape. */
function isDeletedPayload(data: unknown): data is MessageDeletedPayload {
  if (typeof data !== 'object' || data === null) {
    return false;
  }
  const candidate = data as { id?: unknown; deleted_at?: unknown; conversation?: unknown };
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.deleted_at === 'string' &&
    typeof candidate.conversation === 'object' &&
    candidate.conversation !== null
  );
}

/**
 * Connects to `/v1/ws`, joins the given conversation, and renders live
 * `message.created`/`message.edited`/`message.deleted` events merged with
 * REST catch-up history (F51–F55). Pass `null` to stay disconnected (e.g.
 * no conversation selected yet).
 *
 * Presence/typing are explicitly out of scope here (T34) — `typing`/
 * `presence`/`error`/`pong` server frames, and any unrecognized `type`, are
 * intentionally no-ops in this hook.
 */
export function useConversationSocket(conversation: ConversationTarget | null): ConversationSocketState {
  // Deliberately a derived boolean, not the raw `accessToken` value: this
  // only flips on genuine login/logout. `getAccessToken` below always reads
  // the live token fresh at (re)connect time, so a silent mid-session token
  // refresh (e.g. from an unrelated REST 401 retry, or this socket's own
  // 4402 handling) must not tear down and rebuild an otherwise-healthy
  // connection (code review finding #3).
  const hasSession = useAuthStore((state) => state.accessToken !== null);
  const clearSession = useAuthStore((state) => state.clearSession);

  const [status, setStatus] = useState<WsStatus>('closed');
  const [fatalError, setFatalError] = useState<ConversationSocketState['fatalError']>(null);
  const [catchUpError, setCatchUpError] = useState<string | null>(null);
  const [messageMap, setMessageMap] = useState<MessageMap>(emptyMessageMap);

  const lastMessageIdRef = useRef<string | null>(null);

  const conversationKey =
    conversation === null
      ? null
      : conversation.kind === 'channel'
        ? `channel:${conversation.channel_id}`
        : `dm:${conversation.user_id}`;

  useEffect(() => {
    lastMessageIdRef.current = null;
    setMessageMap(emptyMessageMap());
    setFatalError(null);
    setCatchUpError(null);
    setStatus('closed');

    if (conversation === null || !hasSession) {
      return;
    }

    let cancelled = false;

    function applyFrame(frame: ServerFrame): void {
      if (frame.type === 'message.created' || frame.type === 'message.edited') {
        // `ServerFrame`'s `UnknownServerFrame` arm intentionally types
        // `type` as a bare `string` (open enum, T34 frame types included),
        // so the `frame.type === '...'` checks above don't fully exclude
        // it for TS's structural narrowing — a `data`-shaped cast is still
        // required, but scoped to the exact two frame types already
        // established by the check above, rather than an untyped `{ data?:
        // unknown }` shape (code review finding #4). `isMessagePayload`
        // still runs as runtime validation of untrusted server input.
        const data = (frame as MessageCreatedFrame | MessageEditedFrame).data;
        if (!isMessagePayload(data)) {
          return; // malformed/under-specified frame — drop, don't crash
        }
        setMessageMap((prev) => upsertMessages(prev, [data]));
        if (lastMessageIdRef.current === null || data.id > lastMessageIdRef.current) {
          lastMessageIdRef.current = data.id;
        }
        return;
      }
      if (frame.type === 'message.deleted') {
        const data = (frame as MessageDeletedFrame).data;
        if (!isDeletedPayload(data)) {
          return; // malformed/under-specified frame — drop, don't crash
        }
        setMessageMap((prev) => applyDeleted(prev, data));
        return;
      }
      // `error` (non-fatal per-frame), `pong`, `typing`, `presence`, and any
      // unrecognized `type` are intentionally no-ops (open enum, F51-F55
      // scope boundary with T34).
    }

    async function runCatchUp(): Promise<void> {
      if (conversation === null) {
        return;
      }
      try {
        const { messages: missed, truncated } = await fetchMissedMessages(conversation, lastMessageIdRef.current);
        if (cancelled) {
          return;
        }
        if (truncated) {
          // Telemetry-only signal — no UI treatment in scope for T33 (code
          // review finding #3). Never log message content, only the fact
          // that the walk was capped.
          console.warn('[useConversationSocket] catch-up truncated before reaching the last known message id');
        }
        if (missed.length === 0) {
          return;
        }
        setMessageMap((prev) => {
          const next = upsertMessages(prev, missed);
          const latest = latestMessageId(next);
          if (latest !== null) {
            lastMessageIdRef.current = latest;
          }
          return next;
        });
        setCatchUpError(null);
      } catch (err) {
        if (!cancelled) {
          setCatchUpError(err instanceof Error ? err.message : 'Failed to load missed messages.');
        }
      }
    }

    const socket = new ReconnectingSocket({
      buildUrl: buildWsUrl,
      getAccessToken: () => authStoreApi.getState().accessToken,
      refreshAccessToken,
      onStatusChange: (next) => {
        if (cancelled) {
          return;
        }
        setStatus(next);
        if (next === 'open') {
          void runCatchUp();
        }
      },
      onFrame: (frame) => {
        if (!cancelled) {
          applyFrame(frame);
        }
      },
      onFatal: (reason) => {
        if (cancelled) {
          return;
        }
        setFatalError(reason);
        if (reason === 'revoked' || reason === 'deactivated') {
          // Session is genuinely gone server-side — clear it locally too so
          // route guards redirect to /login rather than leaving a socket-
          // less, silently-stale authenticated view up.
          clearSession();
        }
      },
    });

    socket.connect();
    socket.join(conversation);

    return () => {
      cancelled = true;
      socket.destroy();
    };
    // `conversationKey` is the intentional identity dependency (stable
    // per-conversation), not the `conversation` object reference itself.
    // `hasSession` (not `accessToken`) is deliberate — see its declaration
    // above (code review finding #3).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationKey, hasSession, clearSession]);

  const messages = useMemo(() => sortedMessages(messageMap), [messageMap]);
  const isReconnecting = status === 'reconnecting';

  return { status, messages, isReconnecting, fatalError, catchUpError };
}
