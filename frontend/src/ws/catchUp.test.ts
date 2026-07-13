import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ConversationTarget, CursorPage, Message } from '../api/types';
import { fetchMissedMessages } from './catchUp';

const { fetchMessageHistoryMock } = vi.hoisted(() => ({ fetchMessageHistoryMock: vi.fn() }));

vi.mock('../api/messagesApi', () => ({
  fetchMessageHistory: fetchMessageHistoryMock,
}));

const TARGET: ConversationTarget = { kind: 'channel', channel_id: '01J0CHANNEL0000000000000000' };

function msg(id: string): Message {
  return {
    id,
    channel_id: TARGET.kind === 'channel' ? TARGET.channel_id : null,
    recipient_id: null,
    sender_id: '01J0SENDER00000000000000000',
    content: `content-${id}`,
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
  };
}

function page(items: Message[], nextCursor: string | null): CursorPage<Message> {
  return { items, next_cursor: nextCursor };
}

describe('fetchMissedMessages', () => {
  afterEach(() => {
    fetchMessageHistoryMock.mockReset();
  });

  it('first load (sinceMessageId null) takes only the first page', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce(page([msg('01J8CCCC'), msg('01J8BBBB')], 'opaque-cursor-1'));

    const result = await fetchMissedMessages(TARGET, null);

    expect(fetchMessageHistoryMock).toHaveBeenCalledTimes(1);
    expect(fetchMessageHistoryMock).toHaveBeenCalledWith(TARGET, { limit: 50, cursor: null });
    expect(result.messages.map((m) => m.id)).toEqual(['01J8CCCC', '01J8BBBB']);
    expect(result.truncated).toBe(false);
  });

  it('collects only messages newer than sinceMessageId from the first page and stops', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce(
      page([msg('01J8EEEE'), msg('01J8DDDD'), msg('01J8CCCC')], 'opaque-cursor-1'),
    );

    const result = await fetchMissedMessages(TARGET, '01J8CCCC');

    expect(fetchMessageHistoryMock).toHaveBeenCalledTimes(1);
    expect(result.messages.map((m) => m.id).sort()).toEqual(['01J8DDDD', '01J8EEEE']);
    expect(result.truncated).toBe(false);
  });

  it('walks multiple pages via next_cursor (never constructing a cursor itself) until it reaches sinceMessageId', async () => {
    fetchMessageHistoryMock
      .mockResolvedValueOnce(page([msg('01J8FFFF'), msg('01J8EEEE')], 'opaque-cursor-1'))
      .mockResolvedValueOnce(page([msg('01J8DDDD'), msg('01J8CCCC')], 'opaque-cursor-2'));

    const result = await fetchMissedMessages(TARGET, '01J8CCCC');

    expect(fetchMessageHistoryMock).toHaveBeenCalledTimes(2);
    expect(fetchMessageHistoryMock).toHaveBeenNthCalledWith(1, TARGET, { limit: 50, cursor: null });
    expect(fetchMessageHistoryMock).toHaveBeenNthCalledWith(2, TARGET, { limit: 50, cursor: 'opaque-cursor-1' });
    expect(result.messages.map((m) => m.id).sort()).toEqual(['01J8DDDD', '01J8EEEE', '01J8FFFF']);
    expect(result.truncated).toBe(false);
  });

  it('stops when next_cursor is null (reached the beginning of history)', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce(page([msg('01J8FFFF')], null));

    const result = await fetchMissedMessages(TARGET, '01J8CCCC');

    expect(fetchMessageHistoryMock).toHaveBeenCalledTimes(1);
    expect(result.messages.map((m) => m.id)).toEqual(['01J8FFFF']);
    expect(result.truncated).toBe(false);
  });

  it('respects maxPages as a safety cap on a very large gap, and reports the walk as truncated', async () => {
    fetchMessageHistoryMock.mockImplementation(() =>
      Promise.resolve(page([msg('01J8FFFF')], 'always-more')),
    );

    const result = await fetchMissedMessages(TARGET, '01J8AAAA', { maxPages: 3 });

    expect(fetchMessageHistoryMock).toHaveBeenCalledTimes(3);
    expect(result.messages).toHaveLength(3);
    expect(result.truncated).toBe(true);
  });
});
