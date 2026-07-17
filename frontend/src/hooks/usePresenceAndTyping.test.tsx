import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationTarget } from '../api/types';
import { useAuthStore } from '../store/authStore';

const { socketConstructorSpy, socketInstances } = vi.hoisted(() => ({
  socketConstructorSpy: vi.fn(),
  socketInstances: [] as FakeReconnectingSocket[],
}));

class FakeReconnectingSocket {
  connect = vi.fn();
  join = vi.fn();
  leave = vi.fn();
  destroy = vi.fn();
  sendTyping = vi.fn();
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

vi.mock('../api/httpClient', () => ({
  refreshAccessToken: vi.fn().mockResolvedValue('new-token'),
}));

const { usePresenceAndTyping } = await import('./usePresenceAndTyping');

const CHANNEL_ID = '01J0CHANNEL0000000000000000';
const CHANNEL: ConversationTarget = { kind: 'channel', channel_id: CHANNEL_ID };

function currentSocket(): FakeReconnectingSocket {
  const socket = socketInstances.at(-1);
  if (!socket) throw new Error('no socket constructed');
  return socket;
}

const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');
const FIXTURE_REFRESH_TOKEN = ['refresh', 'token', 'fixture'].join('-');

describe('usePresenceAndTyping', () => {
  beforeEach(() => {
    socketInstances.length = 0;
    socketConstructorSpy.mockClear();
    vi.useFakeTimers();
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: null,
      isBootstrapping: false,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('connects and joins the given conversation', () => {
    const { unmount } = renderHook(() => usePresenceAndTyping(CHANNEL));

    const socket = currentSocket();
    expect(socket.connect).toHaveBeenCalledTimes(1);
    expect(socket.join).toHaveBeenCalledWith(CHANNEL);

    unmount();
    expect(socket.destroy).toHaveBeenCalledTimes(1);
  });

  it('does not connect when there is no conversation', () => {
    renderHook(() => usePresenceAndTyping(null));
    expect(socketConstructorSpy).not.toHaveBeenCalled();
  });

  it('applies a typing frame and exposes the typer', () => {
    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({ type: 'typing', conversation: CHANNEL, data: { user_id: 'user-2', conversation: CHANNEL } });
    });

    expect(result.current.typingUserIds).toEqual(['user-2']);
  });

  it('auto-expires a typing indicator 5s after the last frame (F56)', () => {
    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({ type: 'typing', conversation: CHANNEL, data: { user_id: 'user-2', conversation: CHANNEL } });
    });
    expect(result.current.typingUserIds).toEqual(['user-2']);

    act(() => {
      vi.advanceTimersByTime(4_999);
    });
    expect(result.current.typingUserIds).toEqual(['user-2']);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.typingUserIds).toEqual([]);
  });

  it('refreshes the expiry on a repeat typing frame instead of clearing early', () => {
    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({ type: 'typing', conversation: CHANNEL, data: { user_id: 'user-2', conversation: CHANNEL } });
    });
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    act(() => {
      onFrame({ type: 'typing', conversation: CHANNEL, data: { user_id: 'user-2', conversation: CHANNEL } });
    });
    act(() => {
      vi.advanceTimersByTime(3_000);
    });

    // 6s have elapsed since the first frame, but only 3s since the second —
    // the indicator must still be showing.
    expect(result.current.typingUserIds).toEqual(['user-2']);

    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(result.current.typingUserIds).toEqual([]);
  });

  it('ignores a typing frame for a different conversation than the one joined', () => {
    const OTHER_CHANNEL: ConversationTarget = { kind: 'channel', channel_id: '01J0OTHERCHANNEL000000000' };
    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({
        type: 'typing',
        conversation: OTHER_CHANNEL,
        data: { user_id: 'user-2', conversation: OTHER_CHANNEL },
      });
    });

    expect(result.current.typingUserIds).toEqual([]);
  });

  it('applies a presence frame', () => {
    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    act(() => {
      onFrame({ type: 'presence', conversation: null, data: { user_id: 'user-2', state: 'online', last_seen: null } });
    });

    expect(result.current.presenceByUserId.get('user-2')).toEqual({ state: 'online', lastSeen: null });
  });

  it('ignores an unrecognized frame type without error', () => {
    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();
    const onFrame = socket.options.onFrame as (f: unknown) => void;

    expect(() =>
      act(() => onFrame({ type: 'message.created', conversation: CHANNEL, data: { id: '01J8AAAA' } })),
    ).not.toThrow();
    expect(result.current.typingUserIds).toEqual([]);
    expect(result.current.presenceByUserId.size).toBe(0);
  });

  it('sendTyping forwards to the socket for the current conversation', () => {
    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();

    act(() => result.current.sendTyping());

    expect(socket.sendTyping).toHaveBeenCalledWith(CHANNEL);
  });

  it('sendTyping is a no-op without a conversation', () => {
    const { result } = renderHook(() => usePresenceAndTyping(null));
    act(() => result.current.sendTyping());
    expect(socketConstructorSpy).not.toHaveBeenCalled();
  });

  it('on a fatal revoked close, clears the local session', () => {
    const clearSessionSpy = vi.fn();
    useAuthStore.setState({ clearSession: clearSessionSpy } as unknown as Partial<
      ReturnType<typeof useAuthStore.getState>
    >);

    const { result } = renderHook(() => usePresenceAndTyping(CHANNEL));
    const socket = currentSocket();
    const onFatal = socket.options.onFatal as (reason: string) => void;

    act(() => onFatal('revoked'));

    expect(result.current.fatalError).toBe('revoked');
    expect(clearSessionSpy).toHaveBeenCalledTimes(1);
  });
});
