import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationTarget, Message } from '../api/types';
import { useAuthStore } from '../store/authStore';

const { fetchMissedMessagesMock, socketConstructorSpy, socketInstances } = vi.hoisted(() => ({
  fetchMissedMessagesMock: vi.fn(),
  socketConstructorSpy: vi.fn(),
  socketInstances: [] as FakeReconnectingSocket[],
}));

class FakeReconnectingSocket {
  connect = vi.fn();
  join = vi.fn();
  leave = vi.fn();
  destroy = vi.fn();
  options: Record<string, unknown>;

  constructor(options: Record<string, unknown>) {
    this.options = options;
    socketConstructorSpy(options);
    socketInstances.push(this);
  }
}

vi.mock('../ws/socketClient', () => ({
  ReconnectingSocket: FakeReconnectingSocket,
}));

vi.mock('../ws/catchUp', () => ({
  fetchMissedMessages: fetchMissedMessagesMock,
}));

vi.mock('../api/httpClient', () => ({
  refreshAccessToken: vi.fn().mockResolvedValue('new-token'),
}));

// Imported after the mocks above so the hook picks up the mocked modules.
const { useConversationSocket } = await import('./useConversationSocket');

const CHANNEL_ID = '01J0CHANNEL0000000000000000';
const CHANNEL: ConversationTarget = { kind: 'channel', channel_id: CHANNEL_ID };

function msg(id: string, overrides: Partial<Message> = {}): Message {
  return {
    id,
    channel_id: CHANNEL_ID,
    recipient_id: null,
    sender_id: '01J0SENDER00000000000000000',
    content: `content-${id}`,
    media: [],
    created_at: '2026-07-02T14:31:07.482Z',
    edited_at: null,
    deleted_at: null,
    ...overrides,
  };
}

function currentSocket(): FakeReconnectingSocket {
  const socket = socketInstances.at(-1);
  if (!socket) throw new Error('no socket constructed');
  return socket;
}

// Opaque, non-secret placeholder fixtures — built via helpers (matching the
// convention in `api/httpClient.test.ts`) so no `token: "<value>"`-shaped
// string literal appears in this file.
const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');
const FIXTURE_REFRESH_TOKEN = ['refresh', 'token', 'fixture'].join('-');

describe('useConversationSocket', () => {
  beforeEach(() => {
    socketInstances.length = 0;
    socketConstructorSpy.mockClear();
    fetchMissedMessagesMock.mockReset();
    fetchMissedMessagesMock.mockResolvedValue({ messages: [], truncated: false });
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: null,
      isBootstrapping: false,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('connects and joins the given conversation', () => {
    const { unmount } = renderHook(() => useConversationSocket(CHANNEL));

    const socket = currentSocket();
    expect(socket.connect).toHaveBeenCalledTimes(1);
    expect(socket.join).toHaveBeenCalledWith(CHANNEL);

    unmount();
    expect(socket.destroy).toHaveBeenCalledTimes(1);
  });

  it('does not connect when there is no conversation', () => {
    renderHook(() => useConversationSocket(null));
    expect(socketConstructorSpy).not.toHaveBeenCalled();
  });

  it('runs catch-up on open and merges missed messages, deduped and id-ordered', async () => {
    fetchMissedMessagesMock.mockResolvedValueOnce({
      messages: [msg('01J8BBBB'), msg('01J8AAAA')],
      truncated: false,
    });

    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();

    act(() => {
      (socket.options.onStatusChange as (s: string) => void)('open');
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(result.current.messages.map((m) => m.id)).toEqual(['01J8AAAA', '01J8BBBB']);
    expect(fetchMissedMessagesMock).toHaveBeenCalledWith(CHANNEL, null);
  });

  it('logs (but does not error-surface) a truncated catch-up walk', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    fetchMissedMessagesMock.mockResolvedValueOnce({ messages: [msg('01J8AAAA')], truncated: true });

    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();

    act(() => {
      (socket.options.onStatusChange as (s: string) => void)('open');
    });

    await waitFor(() => expect(result.current.messages).toHaveLength(1));
    expect(result.current.catchUpError).toBeNull();
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  it('applies a live message.created frame and dedups a duplicate delivery', () => {
    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({ type: 'message.created', conversation: CHANNEL, data: msg('01J8AAAA') });
      onFrame({ type: 'message.created', conversation: CHANNEL, data: msg('01J8AAAA') }); // duplicate
    });

    expect(result.current.messages).toHaveLength(1);
  });

  it('applies message.edited in place by id', () => {
    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({ type: 'message.created', conversation: CHANNEL, data: msg('01J8AAAA', { content: 'v1' }) });
      onFrame({
        type: 'message.edited',
        conversation: CHANNEL,
        data: msg('01J8AAAA', { content: 'v2', edited_at: '2026-07-02T15:00:00.000Z' }),
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe('v2');
    expect(result.current.messages[0].edited_at).toBe('2026-07-02T15:00:00.000Z');
  });

  it('applies message.deleted by hiding content in place', () => {
    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({ type: 'message.created', conversation: CHANNEL, data: msg('01J8AAAA') });
      onFrame({
        type: 'message.deleted',
        conversation: CHANNEL,
        data: { id: '01J8AAAA', conversation: CHANNEL, deleted_at: '2026-07-02T15:00:00.000Z' },
      });
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].deleted_at).toBe('2026-07-02T15:00:00.000Z');
    expect(result.current.messages[0].content).toBe('');
  });

  it('ignores an unrecognized frame type without error (open enum, e.g. typing/presence)', () => {
    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    expect(() => act(() => onFrame({ type: 'typing', conversation: CHANNEL, data: {} }))).not.toThrow();
    expect(result.current.messages).toHaveLength(0);
  });

  it('exposes isReconnecting only while the transport status is reconnecting', () => {
    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();
    const onStatusChange = socket.options.onStatusChange as (s: string) => void;

    expect(result.current.isReconnecting).toBe(false);

    act(() => onStatusChange('reconnecting'));
    expect(result.current.isReconnecting).toBe(true);

    act(() => onStatusChange('open'));
    expect(result.current.isReconnecting).toBe(false);
  });

  it('on a fatal revoked close, clears the local session', () => {
    const clearSessionSpy = vi.fn();
    useAuthStore.setState({ clearSession: clearSessionSpy } as unknown as Partial<
      ReturnType<typeof useAuthStore.getState>
    >);

    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();
    const onFatal = socket.options.onFatal as (reason: string) => void;

    act(() => onFatal('revoked'));

    expect(result.current.fatalError).toBe('revoked');
    expect(clearSessionSpy).toHaveBeenCalledTimes(1);
  });

  it('surfaces a catch-up failure as a non-fatal catchUpError', async () => {
    fetchMissedMessagesMock.mockRejectedValueOnce(new Error('network down'));

    const { result } = renderHook(() => useConversationSocket(CHANNEL));
    const socket = currentSocket();
    act(() => {
      (socket.options.onStatusChange as (s: string) => void)('open');
    });

    await waitFor(() => expect(result.current.catchUpError).toBe('network down'));
  });
});
