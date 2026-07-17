import { describe, expect, it } from 'vitest';
import { applyPresenceEvent, emptyPresenceMap, formatLastSeen } from './presenceStore';

describe('presenceStore', () => {
  it('starts empty', () => {
    expect(emptyPresenceMap().size).toBe(0);
  });

  it('records an online transition', () => {
    const map = applyPresenceEvent(emptyPresenceMap(), 'user-1', 'online', null);
    expect(map.get('user-1')).toEqual({ state: 'online', lastSeen: null });
  });

  it('records an offline transition with a last_seen timestamp', () => {
    const map = applyPresenceEvent(emptyPresenceMap(), 'user-1', 'offline', '2026-07-08T00:00:00.000Z');
    expect(map.get('user-1')).toEqual({ state: 'offline', lastSeen: '2026-07-08T00:00:00.000Z' });
  });

  it('overwrites the previous entry for the same user on a new event', () => {
    let map = applyPresenceEvent(emptyPresenceMap(), 'user-1', 'online', null);
    map = applyPresenceEvent(map, 'user-1', 'offline', '2026-07-08T00:00:00.000Z');
    expect(map.get('user-1')).toEqual({ state: 'offline', lastSeen: '2026-07-08T00:00:00.000Z' });
    expect(map.size).toBe(1);
  });

  it('leaves other users untouched', () => {
    let map = applyPresenceEvent(emptyPresenceMap(), 'user-1', 'online', null);
    map = applyPresenceEvent(map, 'user-2', 'online', null);
    expect(map.size).toBe(2);
  });
});

describe('formatLastSeen', () => {
  const now = new Date('2026-07-08T12:00:00.000Z').getTime();

  it('reports "Offline" for a null last_seen', () => {
    expect(formatLastSeen(null, now)).toBe('Offline');
  });

  it('reports "just now" under a minute', () => {
    expect(formatLastSeen(new Date(now - 30_000).toISOString(), now)).toBe('Last seen just now');
  });

  it('reports minutes under an hour', () => {
    expect(formatLastSeen(new Date(now - 5 * 60_000).toISOString(), now)).toBe('Last seen 5m ago');
  });

  it('reports hours under a day', () => {
    expect(formatLastSeen(new Date(now - 3 * 60 * 60_000).toISOString(), now)).toBe('Last seen 3h ago');
  });

  it('reports days beyond a day', () => {
    expect(formatLastSeen(new Date(now - 2 * 24 * 60 * 60_000).toISOString(), now)).toBe('Last seen 2d ago');
  });

  it('reports "Offline" for an unparseable timestamp', () => {
    expect(formatLastSeen('not-a-date', now)).toBe('Offline');
  });
});
