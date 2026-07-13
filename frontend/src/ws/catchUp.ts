import { fetchMessageHistory } from '../api/messagesApi';
import type { ConversationTarget, Message } from '../api/types';

export interface CatchUpOptions {
  /** Page size for each history request (contract default 50, max 100). */
  pageLimit?: number;
  /** Safety cap on pages walked in one catch-up run, so a very large gap
   * (or a bug) can't spin the client into fetching the entire history. */
  maxPages?: number;
}

const DEFAULT_PAGE_LIMIT = 50;
const DEFAULT_MAX_PAGES = 20;

export interface CatchUpResult {
  messages: Message[];
  /** True if the walk hit the `maxPages` safety cap before reaching
   * `sinceMessageId` or the start of history — some messages older than
   * the last page fetched may still be missing from `messages`. Callers
   * should treat this as a signal to log/telemetry a partial catch-up; no
   * UI treatment of it is in scope for T33 (code review finding #3). */
  truncated: boolean;
}

/**
 * Fetches "history since the last received message id" (F55, Flow K) by
 * walking the cursor-paginated history endpoint and collecting every
 * message newer than `sinceMessageId`, without ever constructing a cursor
 * client-side — the cursor stays fully opaque, exactly as the contract
 * requires; catch-up here means *paginating with the endpoint's own
 * `next_cursor` and filtering by id*, not deriving a cursor from the id.
 *
 * `sinceMessageId === null` means "no local history yet" (first load) and
 * short-circuits to just the first page — reconnect catch-up proper always
 * passes the last known id.
 *
 * Ordering within/between pages is not assumed here (the contract text and
 * the DB design's DESC keyset index are in tension on this point) — every
 * item is compared individually against `sinceMessageId`, so the result is
 * correct regardless of page ordering direction.
 */
export async function fetchMissedMessages(
  target: ConversationTarget,
  sinceMessageId: string | null,
  { pageLimit = DEFAULT_PAGE_LIMIT, maxPages = DEFAULT_MAX_PAGES }: CatchUpOptions = {},
): Promise<CatchUpResult> {
  const collected: Message[] = [];
  let cursor: string | null = null;
  let truncated = false;

  for (let page = 0; page < maxPages; page += 1) {
    const result = await fetchMessageHistory(target, { limit: pageLimit, cursor });

    let reachedKnown = false;
    for (const message of result.items) {
      if (sinceMessageId !== null && message.id <= sinceMessageId) {
        reachedKnown = true;
        continue;
      }
      collected.push(message);
    }

    if (sinceMessageId === null || reachedKnown || result.next_cursor === null) {
      break;
    }
    cursor = result.next_cursor;

    if (page === maxPages - 1) {
      // Hit the safety cap without ever reaching `sinceMessageId` or the
      // start of history — some older missed messages may still be absent
      // from `collected`.
      truncated = true;
    }
  }

  return { messages: collected, truncated };
}
