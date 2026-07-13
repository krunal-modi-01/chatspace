import { apiRequest } from './httpClient';
import type { ConversationTarget, CursorPage, ListMessagesParams, Message } from './types';

/** Builds the cursor-paginated history path for either conversation kind
 * (frozen contract: `GET /v1/channels/{channel_id}/messages` or
 * `GET /v1/dms/{user_id}/messages`). */
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
