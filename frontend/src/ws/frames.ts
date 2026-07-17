import type { ConversationTarget, Message, MyChannelSummary } from '../api/types';

/**
 * `/v1/ws` frame shapes (T33, frozen contract). Kept separate from
 * `api/types.ts` since these are WS-only wire shapes, not REST resources.
 */

// --- Client -> server frames -------------------------------------------------

export interface JoinClientFrame {
  type: 'join';
  conversation: ConversationTarget;
}

export interface LeaveClientFrame {
  type: 'leave';
  conversation: ConversationTarget;
}

export interface PingClientFrame {
  type: 'ping';
}

/** `{ type: 'typing', conversation }` (T34, contract line 691). No explicit
 * stop frame exists — the receiving client alone owns the 5s auto-expire
 * since the last received `typing` frame (F56). */
export interface TypingClientFrame {
  type: 'typing';
  conversation: ConversationTarget;
}

export type ClientFrame = JoinClientFrame | LeaveClientFrame | PingClientFrame | TypingClientFrame;

export function buildJoinFrame(conversation: ConversationTarget): JoinClientFrame {
  return { type: 'join', conversation };
}

export function buildLeaveFrame(conversation: ConversationTarget): LeaveClientFrame {
  return { type: 'leave', conversation };
}

export function buildPingFrame(): PingClientFrame {
  return { type: 'ping' };
}

export function buildTypingFrame(conversation: ConversationTarget): TypingClientFrame {
  return { type: 'typing', conversation };
}

/** Canonical per-conversation key for local subscription bookkeeping
 * (join/leave/re-subscribe-on-reconnect) — not sent over the wire. */
export function conversationTopicKey(conversation: ConversationTarget): string {
  return conversation.kind === 'channel'
    ? `channel:${conversation.channel_id}`
    : `dm:${conversation.user_id}`;
}

// --- Server -> client frames --------------------------------------------------

export interface MessageCreatedFrame {
  type: 'message.created';
  conversation: ConversationTarget;
  data: Message;
}

export interface MessageEditedFrame {
  type: 'message.edited';
  conversation: ConversationTarget;
  data: Message;
}

export interface MessageDeletedPayload {
  id: string;
  conversation: ConversationTarget;
  deleted_at: string;
}

export interface MessageDeletedFrame {
  type: 'message.deleted';
  conversation: ConversationTarget;
  data: MessageDeletedPayload;
}

export interface ErrorServerFrame {
  type: 'error';
  data: { code: string; detail: string };
}

export interface PongServerFrame {
  type: 'pong';
}

/** `typing` event payload (contract line 719): `data = { user_id,
 * conversation }`. Relayed verbatim from the originating client's frame —
 * `conversation` here is never `null` (unlike `presence`'s). */
export interface TypingEventPayload {
  user_id: string;
  conversation: ConversationTarget;
}

/** `{ type: 'typing', conversation, data }` (T34, contract line 719). The
 * top-level `conversation` mirrors `data.conversation`, same envelope shape
 * as `message.*`. */
export interface TypingServerFrame {
  type: 'typing';
  conversation: ConversationTarget;
  data: TypingEventPayload;
}

/** `presence` event payload (contract line 720): `data = { user_id, state,
 * last_seen }`. `state` is an open enum (`online`/`offline` today) — clients
 * must tolerate unknown values. */
export interface PresenceEventPayload {
  user_id: string;
  state: string;
  last_seen: string | null;
}

/** `{ type: 'presence', conversation: null, data }` (T34, contract line
 * 720) — presence is user-scoped, not conversation-scoped, so `conversation`
 * is always `null` on this envelope (per `app/services/presence.py`). */
export interface PresenceServerFrame {
  type: 'presence';
  conversation: null;
  data: PresenceEventPayload;
}

/**
 * Channel summary embedded in `channel.member_added` (T51, ADR-0012) — the
 * same fields as `MyChannelSummary` minus `my_role` (the event's own `role`
 * field supplies that instead, since the summary is generic over any
 * member, not just the caller). Derived via `Omit` rather than
 * hand-duplicated so the two shapes can't silently drift apart if the REST
 * contract's fields change.
 */
export type MembershipChannelSummary = Omit<MyChannelSummary, 'my_role'>;

/** `channel.member_added` payload (F74, ADR-0012) — delivered only to the
 * added user's own connections via their `user:{user_id}` topic; carries
 * the full channel summary so the client can insert into its list
 * idempotently by id without a follow-up fetch. */
export interface ChannelMemberAddedPayload {
  channel: MembershipChannelSummary;
  user_id: string;
  role: string;
  joined_at: string;
}

export interface ChannelMemberAddedFrame {
  type: 'channel.member_added';
  conversation: ConversationTarget;
  data: ChannelMemberAddedPayload;
}

/** `channel.member_removed` payload (F75, ADR-0012) — no channel metadata,
 * only enough to drop the row and identify the affected user; delivered
 * only to the removed user's own connections. */
export interface ChannelMemberRemovedPayload {
  channel_id: string;
  user_id: string;
}

export interface ChannelMemberRemovedFrame {
  type: 'channel.member_removed';
  conversation: ConversationTarget;
  data: ChannelMemberRemovedPayload;
}

/**
 * Any other `type` — any future value. The contract's `type` enum is an
 * explicitly **open set**; the client MUST tolerate unknown values
 * gracefully rather than reject them.
 */
export interface UnknownServerFrame {
  type: string;
}

export type ServerFrame =
  | MessageCreatedFrame
  | MessageEditedFrame
  | MessageDeletedFrame
  | ChannelMemberAddedFrame
  | ChannelMemberRemovedFrame
  | ErrorServerFrame
  | PongServerFrame
  | TypingServerFrame
  | PresenceServerFrame
  | UnknownServerFrame;

/** Narrows a JSON-decoded WS payload to a `{ type: string }` shape without
 * asserting anything about the rest of it — full per-event-type validation
 * happens where each event is consumed (`useConversationSocket`). Anything
 * that isn't even an object with a string `type` is dropped as malformed
 * server traffic (defensive; the server is expected to always be
 * contract-conformant). */
export function parseServerFrame(raw: unknown): ServerFrame | null {
  if (typeof raw !== 'object' || raw === null) {
    return null;
  }
  const type = (raw as { type?: unknown }).type;
  if (typeof type !== 'string') {
    return null;
  }
  return raw as ServerFrame;
}
