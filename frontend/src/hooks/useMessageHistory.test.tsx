import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/problem';
import type { ConversationTarget, Message } from '../api/types';

const { fetchMessageHistoryMock, sendMessageMock, editMessageMock, deleteMessageMock, generateClientIdMock } = vi.hoisted(
  () => ({
    fetchMessageHistoryMock: vi.fn(),
    sendMessageMock: vi.fn(),
    editMessageMock: vi.fn(),
    deleteMessageMock: vi.fn(),
    generateClientIdMock: vi.fn(),
  }),
);

vi.mock('../api/messagesApi', () => ({
  fetchMessageHistory: fetchMessageHistoryMock,
  sendMessage: sendMessageMock,
  editMessage: editMessageMock,
  deleteMessage: deleteMessageMock,
}));

vi.mock('../utils/id', () => ({
  generateClientId: generateClientIdMock,
}));

const { useMessageHistory } = await import('./useMessageHistory');

const CHANNEL_ID = '01J0CHANNEL0000000000000000';
const CHANNEL: ConversationTarget = { kind: 'channel', channel_id: CHANNEL_ID };
const CURRENT_USER_ID = '01J0ME000000000000000000000';

function msg(id: string, overrides: Partial<Message> = {}): Message {
  return {
    id,
    channel_id: CHANNEL_ID,
    recipient_id: null,
    sender_id: CURRENT_USER_ID,
    content: `content-${id}`,
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

describe('useMessageHistory', () => {
  let idCounter = 0;

  beforeEach(() => {
    idCounter = 0;
    generateClientIdMock.mockImplementation(() => `client-id-${(idCounter += 1)}`);
    fetchMessageHistoryMock.mockReset();
    sendMessageMock.mockReset();
    editMessageMock.mockReset();
    deleteMessageMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads the first page and exposes hasMoreOlder from next_cursor', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [msg('01J8BBBB'), msg('01J8AAAA')], next_cursor: 'cursor-1' });

    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));

    expect(result.current.isLoadingInitial).toBe(true);

    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    expect(result.current.messages.map((m) => m.id)).toEqual(['01J8AAAA', '01J8BBBB']);
    expect(result.current.hasMoreOlder).toBe(true);
    expect(fetchMessageHistoryMock).toHaveBeenCalledWith(CHANNEL, { limit: 50 });
  });

  it('loadOlder merges an older page using the prior next_cursor and updates it', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [msg('01J8BBBB')], next_cursor: 'cursor-1' });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [msg('01J8AAAA')], next_cursor: null });

    await act(async () => {
      await result.current.loadOlder();
    });

    expect(fetchMessageHistoryMock).toHaveBeenLastCalledWith(CHANNEL, { limit: 50, cursor: 'cursor-1' });
    expect(result.current.messages.map((m) => m.id)).toEqual(['01J8AAAA', '01J8BBBB']);
    expect(result.current.hasMoreOlder).toBe(false);
  });

  it('surfaces a validation error and does not call the API for empty content', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    await act(async () => {
      await result.current.sendMessage('   ');
    });

    expect(sendMessageMock).not.toHaveBeenCalled();
    expect(result.current.actionError).toBeInstanceOf(Error);
  });

  it('optimistically adds a pending send, then reconciles it with the server id on success', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    let resolveSend!: (value: { message: Message; created: boolean }) => void;
    sendMessageMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveSend = resolve;
      }),
    );

    let sendPromise!: Promise<void>;
    act(() => {
      sendPromise = result.current.sendMessage('hello world');
    });

    await waitFor(() => expect(result.current.pendingSends).toHaveLength(1));
    expect(result.current.pendingSends[0].status).toBe('sending');
    expect(result.current.pendingSends[0].content).toBe('hello world');

    await act(async () => {
      resolveSend({ message: msg('01J8SERVER00000000000000000', { content: 'hello world' }), created: true });
      await sendPromise;
    });

    expect(result.current.pendingSends).toHaveLength(0);
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].id).toBe('01J8SERVER00000000000000000');
    expect(sendMessageMock).toHaveBeenCalledWith(CHANNEL, { content: 'hello world' }, expect.any(String));
  });

  it('sends media_ids when provided (T35 attach-on-send) and omits the field otherwise', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    sendMessageMock.mockResolvedValueOnce({
      message: msg('01J8SERVER00000000000000001', { content: 'see attached' }),
      created: true,
    });

    await act(async () => {
      await result.current.sendMessage('see attached', ['01J8MEDIA00000000000000000']);
    });

    expect(sendMessageMock).toHaveBeenCalledWith(
      CHANNEL,
      { content: 'see attached', media_ids: ['01J8MEDIA00000000000000000'] },
      expect.any(String),
    );
  });

  it('retries a failed send carrying the same media_ids as the original attempt', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    sendMessageMock.mockRejectedValueOnce(new Error('network down'));
    await act(async () => {
      await result.current.sendMessage('retry with media', ['01J8MEDIA00000000000000000']);
    });
    const tempId = result.current.pendingSends[0].id;

    sendMessageMock.mockResolvedValueOnce({ message: msg('01J8SERVER00000000000000002'), created: true });
    await act(async () => {
      await result.current.retrySend(tempId);
    });

    expect(sendMessageMock).toHaveBeenLastCalledWith(
      CHANNEL,
      { content: 'retry with media', media_ids: ['01J8MEDIA00000000000000000'] },
      expect.any(String),
    );
  });

  it('marks a pending send as failed and allows retrying with the same idempotency key', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    sendMessageMock.mockRejectedValueOnce(new Error('network down'));

    await act(async () => {
      await result.current.sendMessage('retry me');
    });

    expect(result.current.pendingSends[0].status).toBe('failed');
    const tempId = result.current.pendingSends[0].id;
    const firstCallKey = sendMessageMock.mock.calls[0][2];

    sendMessageMock.mockResolvedValueOnce({ message: msg('01J8SERVER00000000000000000'), created: true });

    await act(async () => {
      await result.current.retrySend(tempId);
    });

    expect(sendMessageMock).toHaveBeenLastCalledWith(CHANNEL, { content: 'retry me' }, firstCallKey);
    expect(result.current.pendingSends).toHaveLength(0);
    expect(result.current.messages).toHaveLength(1);
  });

  it('captures retryAfterSeconds from a 429 ApiError on a failed send', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    sendMessageMock.mockRejectedValueOnce(
      new ApiError(
        {
          type: 'https://chatspace.example/problems/rate-limited',
          title: 'Rate limited',
          status: 429,
          detail: 'Too many messages.',
          instance: '/v1/channels/x/messages',
          correlation_id: '01J000',
        },
        7,
      ),
    );

    await act(async () => {
      await result.current.sendMessage('too fast');
    });

    expect(result.current.pendingSends[0].retryAfterSeconds).toBe(7);
  });

  it('discardFailedSend removes a failed pending row', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    sendMessageMock.mockRejectedValueOnce(new Error('nope'));
    await act(async () => {
      await result.current.sendMessage('will fail');
    });
    const tempId = result.current.pendingSends[0].id;

    act(() => {
      result.current.discardFailedSend(tempId);
    });

    expect(result.current.pendingSends).toHaveLength(0);
  });

  it('editMessage upserts the server-returned message in place', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [msg('01J8AAAA', { content: 'v1' })], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    editMessageMock.mockResolvedValueOnce(msg('01J8AAAA', { content: 'v2', edited_at: '2026-07-02T15:00:00.000Z' }));

    await act(async () => {
      await result.current.editMessage('01J8AAAA', 'v2');
    });

    expect(result.current.messages[0].content).toBe('v2');
    expect(result.current.messages[0].edited_at).toBe('2026-07-02T15:00:00.000Z');
  });

  it('deleteMessage marks the message deleted in place without a server body', async () => {
    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [msg('01J8AAAA')], next_cursor: null });
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));
    await waitFor(() => expect(result.current.isLoadingInitial).toBe(false));

    deleteMessageMock.mockResolvedValueOnce(undefined);

    await act(async () => {
      await result.current.deleteMessage('01J8AAAA');
    });

    expect(result.current.messages[0].deleted_at).not.toBeNull();
    expect(result.current.messages[0].content).toBe('');
  });

  it('surfaces a history load failure and recovers via retryInitialLoad', async () => {
    fetchMessageHistoryMock.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useMessageHistory(CHANNEL, CURRENT_USER_ID));

    await waitFor(() => expect(result.current.historyError).not.toBeNull());

    fetchMessageHistoryMock.mockResolvedValueOnce({ items: [msg('01J8AAAA')], next_cursor: null });
    act(() => {
      result.current.retryInitialLoad();
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.historyError).toBeNull();
  });
});
