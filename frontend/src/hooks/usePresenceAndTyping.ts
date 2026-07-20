import { useCallback, useEffect, useRef, useState } from 'react';
import { refreshAccessToken } from '../api/httpClient';
import type { ConversationTarget } from '../api/types';
import { env } from '../config/env';
import { authStoreApi, useAuthStore } from '../store/authStore';
import { conversationTopicKey, type PresenceServerFrame, type ServerFrame, type TypingServerFrame } from '../ws/frames';
import { applyPresenceEvent, emptyPresenceMap, type PresenceMap } from '../ws/presenceStore';
import { ReconnectingSocket, type WsStatus } from '../ws/socketClient';
import {
  activeTypingUserIds,
  emptyTypingMap,
  pruneExpired,
  upsertTyping,
  type TypingMap,
} from '../ws/typingStore';

/** Auto-expire a typing indicator exactly 5s after the last received frame
 * for that user (F56) — the contract has no explicit stop frame. */
const TYPING_EXPIRY_MS = 5_000;

function buildWsUrl(): string {
  // Same rationale as `useConversationSocket.buildWsUrl` — no token in the
  // URL; the access token travels via the `Sec-WebSocket-Protocol: bearer,
  // <jwt>` sub-protocol instead (see `ReconnectingSocket`).
  return env.wsBaseUrl;
}

function isTypingPayload(data: unknown): data is TypingServerFrame['data'] {
  return typeof data === 'object' && data !== null && typeof (data as { user_id?: unknown }).user_id === 'string';
}

function isPresencePayload(data: unknown): data is PresenceServerFrame['data'] {
  if (typeof data !== 'object' || data === null) {
    return false;
  }
  const candidate = data as { user_id?: unknown; state?: unknown; last_seen?: unknown };
  return (
    typeof candidate.user_id === 'string' &&
    typeof candidate.state === 'string' &&
    (candidate.last_seen === null || typeof candidate.last_seen === 'string')
  );
}

export interface PresenceAndTypingState {
  /** Raw transport status — drives a `ReconnectingBanner` the same way
   * `useConversationSocket`'s does. */
  status: WsStatus;
  /** User ids currently within the 5s window since their last `typing`
   * frame for this conversation (F56). Never includes the caller's own id
   * — the server already excludes the typer's own connections from the
   * relay (`app/ws/typing_events.py`), so nothing received here can be a
   * self-echo. */
  typingUserIds: string[];
  /** Live presence-by-user-id, populated only from observed `presence`
   * events (see `ws/presenceStore.ts` for why an absent entry means
   * "unknown", not "offline"). */
  presenceByUserId: PresenceMap;
  /** Sends a `typing` frame for the joined conversation — a no-op while
   * disconnected (fire-and-forget, matches `leave`'s posture). Callers
   * (the composer) are responsible for throttling their own call rate. */
  sendTyping: () => void;
  fatalError: 'revoked' | 'deactivated' | 'auth-failed' | null;
}

/**
 * Presence + typing UI (T34): connects to `/v1/ws`, joins `conversation`,
 * and renders live `typing`/`presence` events with the contract's 5s
 * client-side typing auto-expire (F56) and ref-counted presence rendering
 * (F49/F50). Heartbeat `ping`s are sent automatically by the underlying
 * `ReconnectingSocket` (T33) while the connection is open.
 *
 * Deliberately independent of `useConversationSocket` (T33): that hook
 * already ignores `typing`/`presence` frames by design and additionally
 * owns REST catch-up + live message state that this hook has no need to
 * duplicate. `ChannelPage` now calls both hooks side by side (T51
 * integration, so `MessageList` actually receives live message events) —
 * that means two live connections per open channel view today, which the
 * technical spec's "1 WebSocket per tab" design does not intend long-term.
 * Consolidating the two into a single connection is a known, tracked
 * follow-up, not done here to keep that change scoped and separately
 * reviewable from the message-delivery fix.
 *
 * Pass `null` to stay disconnected (e.g. viewer isn't an authorized
 * participant of `conversation` yet).
 *
 * KNOWN INTEGRATION GAP (not introduced by this hook, do not "fix" it here):
 * the frozen contract has no client frame that subscribes a connection to a
 * peer's `presence:{user_id}` Redis topic — only `join` for a conversation
 * exists. Until a fan-out-policy decision ships on the backend (flagged as
 * an open api-reviewer question in `backend/app/services/presence.py`'s
 * module docstring, e.g. auto-subscribing a joining connection to every
 * channel member's presence topic), `presenceByUserId` returned here will
 * stay empty in production even though this hook/its rendering
 * (`PresenceIndicator`) is fully correct for whatever `presence` frames it
 * is actually given. Treat T34 as frontend-complete/integration-incomplete
 * until that backend follow-up ships — do not read the green test suite
 * here as proof presence is observable end-to-end yet.
 */
export function usePresenceAndTyping(conversation: ConversationTarget | null): PresenceAndTypingState {
  // Same rationale as `useConversationSocket`: a derived boolean, not the
  // raw token, so a silent mid-session refresh never tears down an
  // otherwise-healthy connection.
  const hasSession = useAuthStore((state) => state.accessToken !== null);
  const clearSession = useAuthStore((state) => state.clearSession);

  const [status, setStatus] = useState<WsStatus>('closed');
  const [fatalError, setFatalError] = useState<PresenceAndTypingState['fatalError']>(null);
  const [typingMap, setTypingMap] = useState<TypingMap>(emptyTypingMap);
  const [presenceMap, setPresenceMap] = useState<PresenceMap>(emptyPresenceMap);

  const socketRef = useRef<ReconnectingSocket | null>(null);
  const conversationRef = useRef(conversation);
  conversationRef.current = conversation;
  const expiryTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const conversationKey =
    conversation === null
      ? null
      : conversation.kind === 'channel'
        ? `channel:${conversation.channel_id}`
        : `dm:${conversation.user_id}`;

  useEffect(() => {
    // Captured once per effect run (not re-read as `expiryTimersRef.current`
    // at each use site) — the ref's own object identity never changes
    // across the hook's lifetime (`useRef(new Map())`, set once), so this
    // is exactly the same Map the cleanup below clears, just satisfying the
    // linter's general "don't re-read `.current` late" caution.
    const timers = expiryTimersRef.current;

    setTypingMap(emptyTypingMap());
    setPresenceMap(emptyPresenceMap());
    setFatalError(null);
    setStatus('closed');
    for (const timer of timers.values()) {
      clearTimeout(timer);
    }
    timers.clear();

    if (conversation === null || !hasSession) {
      return;
    }

    let cancelled = false;

    function scheduleExpiry(userId: string): void {
      const existing = timers.get(userId);
      if (existing !== undefined) {
        clearTimeout(existing);
      }
      const timer = setTimeout(() => {
        timers.delete(userId);
        if (cancelled) {
          return;
        }
        setTypingMap((prev) => pruneExpired(prev, Date.now()));
      }, TYPING_EXPIRY_MS);
      timers.set(userId, timer);
    }

    function applyFrame(frame: ServerFrame): void {
      if (frame.type === 'typing') {
        const typingFrame = frame as TypingServerFrame;
        const data = typingFrame.data;
        if (!isTypingPayload(data)) {
          return; // malformed/under-specified frame — drop, don't crash
        }
        // Guard against a `typing` frame for a *different* conversation
        // than the one this hook instance joined. Harmless today (one
        // conversation per hook instance, one `join` per mount) but this
        // stops a stray/late frame from a just-left conversation (e.g. a
        // race on rapid conversation switching before `leave` lands) from
        // populating `typingUserIds` for the wrong conversation if this
        // hook is ever reused to track multiple conversations at once
        // (code-review finding, T34).
        if (conversationTopicKey(typingFrame.conversation) !== conversationKey) {
          return;
        }
        setTypingMap((prev) => upsertTyping(prev, data.user_id, Date.now() + TYPING_EXPIRY_MS));
        scheduleExpiry(data.user_id);
        return;
      }
      if (frame.type === 'presence') {
        const data = (frame as PresenceServerFrame).data;
        if (!isPresencePayload(data)) {
          return; // malformed/under-specified frame — drop, don't crash
        }
        // No conversation filter here by design: `presence` is user-scoped
        // (`conversation: null`, contract line 720), not conversation-scoped
        // like `typing` — a peer's online/offline transition is relevant
        // regardless of which conversation is currently joined.
        setPresenceMap((prev) => applyPresenceEvent(prev, data.user_id, data.state, data.last_seen));
        return;
      }
      // `message.*`/`pong`/`error`/any other type are not this hook's
      // concern (T33's scope, or non-fatal transport noise).
    }

    const socket = new ReconnectingSocket({
      buildUrl: buildWsUrl,
      getAccessToken: () => authStoreApi.getState().accessToken,
      refreshAccessToken,
      onStatusChange: (next) => {
        if (!cancelled) {
          setStatus(next);
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
          clearSession();
        }
      },
    });

    socketRef.current = socket;
    socket.connect();
    socket.join(conversation);

    return () => {
      cancelled = true;
      for (const timer of timers.values()) {
        clearTimeout(timer);
      }
      timers.clear();
      socketRef.current = null;
      socket.destroy();
    };
    // `conversationKey` is the intentional identity dependency (stable per
    // conversation), matching `useConversationSocket`'s established
    // pattern; `hasSession` (not `accessToken`) for the same reason too.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationKey, hasSession, clearSession]);

  const sendTyping = useCallback(() => {
    const current = conversationRef.current;
    if (current === null) {
      return;
    }
    socketRef.current?.sendTyping(current);
  }, []);

  return {
    status,
    typingUserIds: activeTypingUserIds(typingMap),
    presenceByUserId: presenceMap,
    sendTyping,
    fatalError,
  };
}
