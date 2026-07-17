/** Per-conversation typing indicator state (T34, F56).
 *
 * The contract's `typing` frame has no explicit stop — the client alone
 * decides an indicator has gone stale by auto-expiring it exactly 5s after
 * the last received frame for that user. This module holds the pure,
 * testable state transitions; the actual 5s timers live in
 * `usePresenceAndTyping` (a `setTimeout` per user, scheduled/rescheduled on
 * every frame) since they need to drive a React re-render on expiry, which
 * a pure data structure can't do on its own.
 */

/** userId -> the epoch-ms timestamp at which their indicator should expire. */
export type TypingMap = ReadonlyMap<string, number>;

export function emptyTypingMap(): TypingMap {
  return new Map();
}

/** Records (or refreshes) `userId` as currently typing, expiring at `expiresAt`. */
export function upsertTyping(map: TypingMap, userId: string, expiresAt: number): TypingMap {
  const next = new Map(map);
  next.set(userId, expiresAt);
  return next;
}

/** Drops every entry whose expiry is at or before `now`. Returns the same
 * `map` reference (not a copy) when nothing changed, so callers can skip a
 * state update / re-render when a scheduled prune turns out to be a no-op
 * (e.g. a fresher frame already rescheduled the same user past `now`). */
export function pruneExpired(map: TypingMap, now: number): TypingMap {
  let changed = false;
  const next = new Map(map);
  for (const [userId, expiresAt] of map) {
    if (expiresAt <= now) {
      next.delete(userId);
      changed = true;
    }
  }
  return changed ? next : map;
}

/** Currently-typing user ids, in no particular order (rendering order is
 * the caller's concern). */
export function activeTypingUserIds(map: TypingMap): string[] {
  return Array.from(map.keys());
}
