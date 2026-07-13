import type { ConversationTarget, Message } from '../api/types';

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

export type ClientFrame = JoinClientFrame | LeaveClientFrame | PingClientFrame;

export function buildJoinFrame(conversation: ConversationTarget): JoinClientFrame {
  return { type: 'join', conversation };
}

export function buildLeaveFrame(conversation: ConversationTarget): LeaveClientFrame {
  return { type: 'leave', conversation };
}

export function buildPingFrame(): PingClientFrame {
  return { type: 'ping' };
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

/**
 * Any other `type` — including `typing`/`presence` (T34 scope, not T33) and
 * any future value. The contract's `type` enum is an explicitly **open
 * set**; the client MUST tolerate unknown values gracefully rather than
 * reject them.
 */
export interface UnknownServerFrame {
  type: string;
}

export type ServerFrame =
  | MessageCreatedFrame
  | MessageEditedFrame
  | MessageDeletedFrame
  | ErrorServerFrame
  | PongServerFrame
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
