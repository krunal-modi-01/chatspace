import { describe, expect, it } from 'vitest';
import type { Message } from '../api/types';
import { applyDeleted, emptyMessageMap, latestMessageId, sortedMessages, upsertMessages } from './messageStore';

function makeMessage(overrides: Partial<Message> & { id: string }): Message {
  return {
    channel_id: '01J0CHANNEL0000000000000000',
    recipient_id: null,
    sender_id: '01J0SENDER00000000000000000',
    content: 'hello',
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

describe('messageStore', () => {
  it('upserts and dedups by id (F54) — a duplicate delivery does not create a second entry', () => {
    const msg = makeMessage({ id: '01J8AAAA' });
    let map = emptyMessageMap();
    map = upsertMessages(map, [msg]);
    map = upsertMessages(map, [msg]); // duplicate at-least-once delivery

    expect(map.size).toBe(1);
    expect(sortedMessages(map)).toEqual([msg]);
  });

  it('orders messages ascending by the time-sortable id, not insertion order', () => {
    const early = makeMessage({ id: '01J8AAAA' });
    const late = makeMessage({ id: '01J8ZZZZ' });
    let map = emptyMessageMap();
    map = upsertMessages(map, [late, early]); // inserted out of order

    expect(sortedMessages(map).map((m) => m.id)).toEqual(['01J8AAAA', '01J8ZZZZ']);
  });

  it('message.edited reconciles idempotently by id — same id, updated content/edited_at, no new row', () => {
    const original = makeMessage({ id: '01J8AAAA', content: 'first draft' });
    const edited = makeMessage({ id: '01J8AAAA', content: 'fixed typo', edited_at: '2026-07-02T14:35:00.000Z' });

    let map = emptyMessageMap();
    map = upsertMessages(map, [original]);
    map = upsertMessages(map, [edited]);

    expect(map.size).toBe(1);
    const [only] = sortedMessages(map);
    expect(only.content).toBe('fixed typo');
    expect(only.edited_at).toBe('2026-07-02T14:35:00.000Z');
  });

  it('message.deleted hides content in place by id, preserving order/other fields', () => {
    const original = makeMessage({ id: '01J8AAAA', content: 'sensitive content' });
    let map = emptyMessageMap();
    map = upsertMessages(map, [original]);

    map = applyDeleted(map, {
      id: '01J8AAAA',
      conversation: { kind: 'channel', channel_id: '01J0CHANNEL0000000000000000' },
      deleted_at: '2026-07-02T14:40:00.000Z',
    });

    expect(map.size).toBe(1);
    const [only] = sortedMessages(map);
    expect(only.content).toBe('');
    expect(only.deleted_at).toBe('2026-07-02T14:40:00.000Z');
    expect(only.sender_id).toBe(original.sender_id);
  });

  it('message.deleted for a never-seen message records a minimal placeholder rather than dropping it', () => {
    let map = emptyMessageMap();
    map = applyDeleted(map, {
      id: '01J8NEVERSEEN',
      conversation: { kind: 'dm', user_id: '01J0USER000000000000000000' },
      deleted_at: '2026-07-02T14:40:00.000Z',
    });

    const [only] = sortedMessages(map);
    expect(only.id).toBe('01J8NEVERSEEN');
    expect(only.deleted_at).toBe('2026-07-02T14:40:00.000Z');
    expect(only.recipient_id).toBe('01J0USER000000000000000000');
    expect(only.content).toBe('');
  });

  it('latestMessageId returns null for an empty store and the max id otherwise', () => {
    expect(latestMessageId(emptyMessageMap())).toBeNull();

    let map = emptyMessageMap();
    map = upsertMessages(map, [makeMessage({ id: '01J8AAAA' }), makeMessage({ id: '01J8ZZZZ' })]);
    expect(latestMessageId(map)).toBe('01J8ZZZZ');
  });
});
