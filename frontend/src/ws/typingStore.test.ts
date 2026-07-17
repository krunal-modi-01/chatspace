import { describe, expect, it } from 'vitest';
import { activeTypingUserIds, emptyTypingMap, pruneExpired, upsertTyping } from './typingStore';

describe('typingStore', () => {
  it('starts empty', () => {
    expect(activeTypingUserIds(emptyTypingMap())).toEqual([]);
  });

  it('records a typing user with their expiry timestamp', () => {
    const map = upsertTyping(emptyTypingMap(), 'user-1', 5_000);
    expect(activeTypingUserIds(map)).toEqual(['user-1']);
  });

  it('refreshes an existing typing user rather than duplicating them', () => {
    let map = upsertTyping(emptyTypingMap(), 'user-1', 1_000);
    map = upsertTyping(map, 'user-1', 6_000);
    expect(activeTypingUserIds(map)).toEqual(['user-1']);
  });

  it('prunes only entries whose expiry has passed', () => {
    let map = upsertTyping(emptyTypingMap(), 'user-1', 1_000);
    map = upsertTyping(map, 'user-2', 10_000);

    const pruned = pruneExpired(map, 5_000);

    expect(activeTypingUserIds(pruned)).toEqual(['user-2']);
  });

  it('returns the same map reference when nothing is expired (no-op prune)', () => {
    const map = upsertTyping(emptyTypingMap(), 'user-1', 10_000);
    const pruned = pruneExpired(map, 5_000);
    expect(pruned).toBe(map);
  });

  it('treats an expiry exactly at "now" as expired', () => {
    const map = upsertTyping(emptyTypingMap(), 'user-1', 5_000);
    const pruned = pruneExpired(map, 5_000);
    expect(activeTypingUserIds(pruned)).toEqual([]);
  });
});
