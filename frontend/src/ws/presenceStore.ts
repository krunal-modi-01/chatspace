/** Per-user presence state (T34, F49/F50), keyed by `user_id`.
 *
 * Populated from live `presence` WS events only — there is no REST
 * "fetch current presence for these users" endpoint in the frozen contract,
 * so a user with no entry here is simply *unknown* (never observed a
 * transition), not confidently "offline". Callers must render that
 * distinction (see `components/chat/PresenceIndicator.tsx`) rather than
 * defaulting an absent entry to "Offline".
 *
 * Known gap (flagged in `backend/app/services/presence.py`'s module
 * docstring, not invented here): the frozen contract does not specify which
 * connections should be subscribed to a given `presence:{user_id}` Redis
 * topic, so in the current backend wiring a client only ever receives a
 * `presence` event for a peer if some future fan-out-policy decision
 * delivers it to a conversation this client has joined. This store is
 * written to be correct regardless of how that gap is eventually resolved
 * (api-reviewer follow-up) — it just applies whatever `presence` events
 * actually arrive.
 */

export interface PresenceState {
  /** Open enum server-side (`online`/`offline` today) — render unknown
   * values the same as absent rather than crashing. */
  state: string;
  lastSeen: string | null;
}

export type PresenceMap = ReadonlyMap<string, PresenceState>;

export function emptyPresenceMap(): PresenceMap {
  return new Map();
}

export function applyPresenceEvent(
  map: PresenceMap,
  userId: string,
  state: string,
  lastSeen: string | null,
): PresenceMap {
  const next = new Map(map);
  next.set(userId, { state, lastSeen });
  return next;
}

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/** Minimal relative-time formatting for `last_seen` (F50) — deliberately
 * hand-rolled rather than pulling in a date library (CLAUDE.md: no new
 * dependency without the vetting checklist) for this single, narrow use.
 * Kept alongside the rest of the presence state (not in the component
 * file) so `components/chat/PresenceIndicator.tsx` stays component-only. */
export function formatLastSeen(lastSeen: string | null, now: number = Date.now()): string {
  if (lastSeen === null) {
    return 'Offline';
  }
  const then = new Date(lastSeen).getTime();
  if (Number.isNaN(then)) {
    return 'Offline';
  }
  const diffMs = Math.max(0, now - then);
  if (diffMs < MINUTE_MS) {
    return 'Last seen just now';
  }
  if (diffMs < HOUR_MS) {
    const minutes = Math.floor(diffMs / MINUTE_MS);
    return `Last seen ${minutes}m ago`;
  }
  if (diffMs < DAY_MS) {
    const hours = Math.floor(diffMs / HOUR_MS);
    return `Last seen ${hours}h ago`;
  }
  const days = Math.floor(diffMs / DAY_MS);
  return `Last seen ${days}d ago`;
}
