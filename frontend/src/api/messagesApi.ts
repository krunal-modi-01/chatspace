import { apiRequest, apiRequestWithStatus } from './httpClient';
import type {
  ConversationTarget,
  CursorPage,
  EditMessageRequest,
  ListMessagesParams,
  Message,
  SendMessageRequest,
} from './types';

/** Builds the cursor-paginated history path for either conversation kind
 * (frozen contract: `GET /v1/channels/{channel_id}/messages` or
 * `GET /v1/dms/{user_id}/messages`). Also the send path for the same
 * conversation (`POST` to the same URL). */
function historyPath(target: ConversationTarget): string {
  return target.kind === 'channel'
    ? `/channels/${encodeURIComponent(target.channel_id)}/messages`
    : `/dms/${encodeURIComponent(target.user_id)}/messages`;
}

function toQueryString(params: ListMessagesParams): string {
  const search = new URLSearchParams();
  if (params.limit !== undefined) {
    search.set('limit', String(params.limit));
  }
  // The cursor is an opaque token from a prior `next_cursor` — never
  // constructed client-side (frozen contract). `null`/`undefined` both mean
  // "first page" and are omitted rather than sent as the literal string.
  if (params.cursor) {
    search.set('cursor', params.cursor);
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

/** Protected — cursor-paginated channel or DM history, reverse-chronological
 * (newest first), soft-deleted excluded. Also serves reconnect catch-up
 * (F55) via `cursor`; see `../ws/catchUp.ts` for the catch-up merge strategy. */
export function fetchMessageHistory(
  target: ConversationTarget,
  params: ListMessagesParams = {},
): Promise<CursorPage<Message>> {
  return apiRequest<CursorPage<Message>>(`${historyPath(target)}${toQueryString(params)}`, {
    method: 'GET',
  });
}

/** Result of a send: `created` distinguishes a genuinely new row (`201`)
 * from an idempotent replay of the same `Idempotency-Key` (`200`, no new
 * row) — both return the canonical `message`, which callers reconcile their
 * optimistic row against by `id` regardless of which case fired. */
export interface SendMessageResult {
  message: Message;
  created: boolean;
}

/** Protected — sends a channel or DM message. `idempotencyKey` MUST be a
 * client-generated UUID and is required by the frozen contract (missing/
 * malformed → `400`); the same key resent (e.g. a client-side retry after a
 * dropped response) safely replays rather than duplicating the message. */
export async function sendMessage(
  target: ConversationTarget,
  request: SendMessageRequest,
  idempotencyKey: string,
): Promise<SendMessageResult> {
  const { data, status } = await apiRequestWithStatus<Message>(historyPath(target), {
    method: 'POST',
    body: request,
    headers: { 'Idempotency-Key': idempotencyKey },
  });
  return { message: data, created: status === 201 };
}

/** Protected, author-only — edits a message's `content`; sets `edited_at`,
 * `id`/order unchanged. `409` if the message is already soft-deleted. */
export function editMessage(messageId: string, request: EditMessageRequest): Promise<Message> {
  return apiRequest<Message>(`/messages/${encodeURIComponent(messageId)}`, {
    method: 'PATCH',
    body: request,
  });
}

/** Protected, author-only — soft-deletes a message (sets `deleted_at`,
 * content excluded from future history reads). Idempotent: already-deleted
 * → `204`. */
export function deleteMessage(messageId: string): Promise<void> {
  return apiRequest<void>(`/messages/${encodeURIComponent(messageId)}`, {
    method: 'DELETE',
  });
}
