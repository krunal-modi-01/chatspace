import type { Message } from '../api/types';
import type { MessageDeletedPayload } from './frames';

/** Dedup-by-id message store (F54). Represented as an immutable `Map` so
 * React state updates via `setState(prev => ...)` compare cheaply and
 * re-render only when content actually changes. */
export type MessageMap = ReadonlyMap<string, Message>;

export function emptyMessageMap(): MessageMap {
  return new Map();
}

/** Upserts one or more messages by id — used for both catch-up history
 * pages and live `message.created`/`message.edited` events. `edited`
 * reconciles idempotently by id (same shape, updated `content`/`edited_at`,
 * per the contract) via the same upsert path as `created`. */
export function upsertMessages(map: MessageMap, messages: readonly Message[]): MessageMap {
  if (messages.length === 0) {
    return map;
  }
  const next = new Map(map);
  for (const message of messages) {
    next.set(message.id, message);
  }
  return next;
}

/** Applies a `message.deleted` event: hides content in place by id (F53).
 * If the message was never seen locally (e.g. this client joined after it
 * was created), a minimal placeholder row is recorded so the deletion still
 * renders — deliberately empty `content`, matching the event payload never
 * carrying content for a deleted message. */
export function applyDeleted(map: MessageMap, payload: MessageDeletedPayload): MessageMap {
  const existing = map.get(payload.id);
  const next = new Map(map);
  next.set(payload.id, {
    id: payload.id,
    channel_id: existing?.channel_id ?? (payload.conversation.kind === 'channel' ? payload.conversation.channel_id : null),
    recipient_id: existing?.recipient_id ?? (payload.conversation.kind === 'dm' ? payload.conversation.user_id : null),
    sender_id: existing?.sender_id ?? '',
    content: '',
    media: [],
    created_at: existing?.created_at ?? payload.deleted_at,
    edited_at: existing?.edited_at ?? null,
    deleted_at: payload.deleted_at,
  });
  return next;
}

/** Messages ordered by the time-sortable id (ADR-0005) — the contract's
 * required ordering, not arrival order (fan-out is best-effort). */
export function sortedMessages(map: MessageMap): Message[] {
  return Array.from(map.values()).sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** The highest message id currently known — the client's "last received
 * message id" used to drive reconnect catch-up (F55). `null` when empty. */
export function latestMessageId(map: MessageMap): string | null {
  let latest: string | null = null;
  for (const id of map.keys()) {
    if (latest === null || id > latest) {
      latest = id;
    }
  }
  return latest;
}
