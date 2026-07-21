import { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteMessage as deleteMessageApi,
  editMessage as editMessageApi,
  fetchMessageHistory,
  sendMessage as sendMessageApi,
} from '../api/messagesApi';
import { ApiError } from '../api/problem';
import type { ConversationTarget, Message } from '../api/types';
import { MESSAGE_MAX_LENGTH } from '../constants';
import { generateClientId } from '../utils/id';
import { applyDeleted, emptyMessageMap, sortedMessages, upsertMessages, type MessageMap } from '../ws/messageStore';

const HISTORY_PAGE_LIMIT = 50;

export type PendingSendStatus = 'sending' | 'failed';

/** A not-yet-confirmed outgoing message. Kept out of the confirmed
 * `MessageMap` deliberately — its temporary id is a random client UUID, not
 * a UUIDv7, so it cannot be correctly interleaved by id-sort with confirmed
 * history; it is always rendered after the confirmed, sorted list instead
 * (correct because it is, by construction, the newest thing in the view). */
export interface PendingSend {
  id: string;
  content: string;
  /** `media_id`s attached at send time (T35) — carried through retry so a
   * retried send still attaches the same media. */
  mediaIds: string[];
  idempotencyKey: string;
  status: PendingSendStatus;
  createdAt: string;
  error: string | null;
  /** Seconds to wait before retrying, from the `429` response's
   * `Retry-After` header (send rate limit: 10/10s, burst 20). `undefined`
   * for any other failure. */
  retryAfterSeconds?: number;
}

export interface UseMessageHistoryResult {
  /** Confirmed history, id-ordered ascending (oldest first) — ordering is
   * derived from the UUIDv7 id, not page/array order, so it is correct
   * regardless of the history endpoint's page-internal ordering. */
  messages: Message[];
  /** Optimistic sends not yet reconciled with a server-confirmed message,
   * in submit order. */
  pendingSends: PendingSend[];
  isLoadingInitial: boolean;
  isLoadingOlder: boolean;
  /** True once the initial page has loaded and the server reported more
   * (non-null `next_cursor`) — drives the "load older" affordance. */
  hasMoreOlder: boolean;
  historyError: unknown;
  /** Surfaces validation/API failures from `sendMessage`/`editMessage`/
   * `deleteMessage` that aren't already carried on a `PendingSend` row
   * (e.g. a same-tick validation error before any optimistic row exists). */
  actionError: unknown;
  /** `mediaIds` (T35) defaults to none — omit entirely for a text-only send
   * so the request body matches the pre-T35 shape exactly (no empty
   * `media_ids: []` sent when there's nothing to attach). */
  sendMessage: (content: string, mediaIds?: string[]) => Promise<void>;
  retrySend: (tempId: string) => Promise<void>;
  discardFailedSend: (tempId: string) => void;
  loadOlder: () => Promise<void>;
  /** Re-runs the initial page load — the only recovery path for an initial
   * (first-page) load failure, since `loadOlder` is a no-op without a
   * `next_cursor` from a successful first page. */
  retryInitialLoad: () => void;
  editMessage: (messageId: string, content: string) => Promise<void>;
  deleteMessage: (messageId: string) => Promise<void>;
}

/** Mirrors the DB `CHECK` (R36): 1–4000 chars, non-whitespace. */
export function validateMessageContent(content: string): string | null {
  if (content.trim().length === 0) {
    return 'Message cannot be empty.';
  }
  if (content.length > MESSAGE_MAX_LENGTH) {
    return `Message is too long (max ${MESSAGE_MAX_LENGTH} characters).`;
  }
  return null;
}

function targetKeyOf(target: ConversationTarget | null): string | null {
  if (target === null) {
    return null;
  }
  return target.kind === 'channel' ? `channel:${target.channel_id}` : `dm:${target.user_id}`;
}

/**
 * REST-backed message list state for a single conversation: cursor-paginated
 * history with "load older", optimistic send (client-generated
 * `Idempotency-Key`, reconciled by the server-returned message `id`), and
 * author edit/delete. Deliberately REST-only — live WS delivery is T33's
 * scope, out of bounds here (T32 acceptance).
 */
export function useMessageHistory(
  target: ConversationTarget | null,
  currentUserId: string | null,
): UseMessageHistoryResult {
  const [messageMap, setMessageMap] = useState<MessageMap>(emptyMessageMap);
  const [pendingSends, setPendingSends] = useState<PendingSend[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasFetchedInitial, setHasFetchedInitial] = useState(false);
  const [isLoadingInitial, setIsLoadingInitial] = useState(false);
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const [historyError, setHistoryError] = useState<unknown>(null);
  const [actionError, setActionError] = useState<unknown>(null);

  const targetRef = useRef(target);
  targetRef.current = target;
  const nextCursorRef = useRef<string | null>(null);
  nextCursorRef.current = nextCursor;
  const isLoadingOlderRef = useRef(false);
  const [reloadToken, setReloadToken] = useState(0);

  const targetKey = targetKeyOf(target);

  useEffect(() => {
    setMessageMap(emptyMessageMap());
    setPendingSends([]);
    setNextCursor(null);
    setHasFetchedInitial(false);
    setHistoryError(null);
    setActionError(null);

    if (target === null) {
      setIsLoadingInitial(false);
      return;
    }

    let cancelled = false;
    setIsLoadingInitial(true);

    fetchMessageHistory(target, { limit: HISTORY_PAGE_LIMIT })
      .then((page) => {
        if (cancelled) {
          return;
        }
        setMessageMap(upsertMessages(emptyMessageMap(), page.items));
        setNextCursor(page.next_cursor);
        setHasFetchedInitial(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setHistoryError(err);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingInitial(false);
        }
      });

    return () => {
      cancelled = true;
    };
    // `targetKey` is the intentional identity dependency (stable per
    // conversation), matching `useConversationSocket`'s established pattern.
    // `reloadToken` deliberately re-runs this same effect for `retryInitialLoad`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey, reloadToken]);

  const retryInitialLoad = useCallback(() => {
    setReloadToken((prev) => prev + 1);
  }, []);

  const loadOlder = useCallback(async () => {
    const current = targetRef.current;
    if (current === null || nextCursorRef.current === null || isLoadingOlderRef.current) {
      return;
    }
    isLoadingOlderRef.current = true;
    setIsLoadingOlder(true);
    setHistoryError(null);
    try {
      const page = await fetchMessageHistory(current, { limit: HISTORY_PAGE_LIMIT, cursor: nextCursorRef.current });
      setMessageMap((prev) => upsertMessages(prev, page.items));
      setNextCursor(page.next_cursor);
    } catch (err) {
      setHistoryError(err);
    } finally {
      isLoadingOlderRef.current = false;
      setIsLoadingOlder(false);
    }
  }, []);

  const performSend = useCallback(
    async (tempId: string, content: string, mediaIds: string[], idempotencyKey: string) => {
      const current = targetRef.current;
      if (current === null) {
        return;
      }
      try {
        // Only include `media_ids` when non-empty so a text-only send's
        // request body is byte-for-byte identical to the pre-T35 shape.
        const request = mediaIds.length > 0 ? { content, media_ids: mediaIds } : { content };
        const { message } = await sendMessageApi(current, request, idempotencyKey);
        setPendingSends((prev) => prev.filter((pending) => pending.id !== tempId));
        setMessageMap((prev) => upsertMessages(prev, [message]));
      } catch (err) {
        const detail = err instanceof Error ? err.message : 'Failed to send message.';
        const retryAfterSeconds = err instanceof ApiError ? err.retryAfterSeconds : undefined;
        setPendingSends((prev) =>
          prev.map((pending) =>
            pending.id === tempId ? { ...pending, status: 'failed', error: detail, retryAfterSeconds } : pending,
          ),
        );
      }
    },
    [],
  );

  const sendMessage = useCallback(
    async (content: string, mediaIds: string[] = []) => {
      setActionError(null);
      const validationError = validateMessageContent(content);
      if (validationError !== null) {
        setActionError(new Error(validationError));
        return;
      }
      if (currentUserId === null || targetRef.current === null) {
        return;
      }

      const tempId = generateClientId();
      const idempotencyKey = generateClientId();
      const pending: PendingSend = {
        id: tempId,
        content,
        mediaIds,
        idempotencyKey,
        status: 'sending',
        createdAt: new Date().toISOString(),
        error: null,
      };
      setPendingSends((prev) => [...prev, pending]);
      await performSend(tempId, content, mediaIds, idempotencyKey);
    },
    [currentUserId, performSend],
  );

  const retrySend = useCallback(
    async (tempId: string) => {
      const pending = pendingSends.find((candidate) => candidate.id === tempId);
      if (!pending) {
        return;
      }
      setPendingSends((prev) =>
        prev.map((candidate) => (candidate.id === tempId ? { ...candidate, status: 'sending', error: null } : candidate)),
      );
      // Re-uses the same `idempotencyKey` from the original attempt — a
      // retry is the same logical send, and the contract guarantees a
      // replay of the same key is safe (no duplicate row) even if the
      // first attempt actually succeeded server-side but the response was
      // lost client-side.
      await performSend(tempId, pending.content, pending.mediaIds, pending.idempotencyKey);
    },
    [pendingSends, performSend],
  );

  const discardFailedSend = useCallback((tempId: string) => {
    setPendingSends((prev) => prev.filter((pending) => pending.id !== tempId));
  }, []);

  const editMessage = useCallback(async (messageId: string, content: string) => {
    setActionError(null);
    const validationError = validateMessageContent(content);
    if (validationError !== null) {
      const error = new Error(validationError);
      setActionError(error);
      throw error;
    }
    try {
      const updated = await editMessageApi(messageId, { content });
      setMessageMap((prev) => upsertMessages(prev, [updated]));
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }, []);

  const deleteMessage = useCallback(async (messageId: string) => {
    setActionError(null);
    try {
      await deleteMessageApi(messageId);
      const current = targetRef.current;
      if (current !== null) {
        setMessageMap((prev) => applyDeleted(prev, { id: messageId, conversation: current, deleted_at: new Date().toISOString() }));
      }
    } catch (err) {
      setActionError(err);
      throw err;
    }
  }, []);

  return {
    messages: sortedMessages(messageMap),
    pendingSends,
    isLoadingInitial,
    isLoadingOlder,
    hasMoreOlder: hasFetchedInitial && nextCursor !== null,
    historyError,
    actionError,
    sendMessage,
    retrySend,
    discardFailedSend,
    loadOlder,
    retryInitialLoad,
    editMessage,
    deleteMessage,
  };
}
