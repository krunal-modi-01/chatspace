import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MyChannelSummary } from '../api/types';
import { useAuthStore } from '../store/authStore';

const { listMyChannelsMock, socketConstructorSpy, socketInstances } = vi.hoisted(() => ({
  listMyChannelsMock: vi.fn(),
  socketConstructorSpy: vi.fn(),
  socketInstances: [] as FakeReconnectingSocket[],
}));

class FakeReconnectingSocket {
  connect = vi.fn();
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

vi.mock('../api/httpClient', () => ({
  refreshAccessToken: vi.fn().mockResolvedValue('new-token'),
}));

vi.mock('../api/channelsApi', () => ({
  listMyChannels: listMyChannelsMock,
}));

// Imported after the mocks above so the hook picks up the mocked modules.
const { useChannelMembershipSocket } = await import('./useChannelMembershipSocket');
const { useMyChannelsStore } = await import('../store/myChannelsStore');

function currentSocket(): FakeReconnectingSocket {
  const socket = socketInstances.at(-1);
  if (!socket) throw new Error('no socket constructed');
  return socket;
}

function channel(overrides: Partial<MyChannelSummary> = {}): MyChannelSummary {
  return {
    id: 'chan-1',
    name: 'engineering',
    is_private: false,
    created_by: 'user-1',
    created_at: '2026-07-01T00:00:00.000Z',
    member_count: 3,
    my_role: 'member',
    ...overrides,
  };
}

const FIXTURE_ACCESS_TOKEN = ['access', 'token', 'fixture'].join('-');
const FIXTURE_REFRESH_TOKEN = ['refresh', 'token', 'fixture'].join('-');

describe('useChannelMembershipSocket', () => {
  beforeEach(() => {
    socketInstances.length = 0;
    socketConstructorSpy.mockClear();
    listMyChannelsMock.mockReset();
    listMyChannelsMock.mockResolvedValue({ items: [], next_cursor: null });
    useAuthStore.setState({
      accessToken: FIXTURE_ACCESS_TOKEN,
      refreshToken: FIXTURE_REFRESH_TOKEN,
      user: null,
      isBootstrapping: false,
    });
    useMyChannelsStore.setState({
      channels: [],
      isLoading: true,
      error: null,
      viewedChannelId: null,
      removedChannelId: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does not open a connection when there is no session', () => {
    useAuthStore.setState({ accessToken: null, refreshToken: null });

    renderHook(() => useChannelMembershipSocket());

    expect(socketConstructorSpy).not.toHaveBeenCalled();
  });

  it('connects once a session exists, and tears the socket down on unmount', () => {
    const { unmount } = renderHook(() => useChannelMembershipSocket());

    const socket = currentSocket();
    expect(socket.connect).toHaveBeenCalledTimes(1);

    unmount();
    expect(socket.destroy).toHaveBeenCalledTimes(1);
  });

  it('idempotently upserts a channel on a channel.member_added frame (F74)', () => {
    renderHook(() => useChannelMembershipSocket());
    const onFrame = currentSocket().options.onFrame as (frame: unknown) => void;

    act(() => {
      onFrame({
        type: 'channel.member_added',
        conversation: { kind: 'channel', channel_id: 'chan-1' },
        data: {
          channel: {
            id: 'chan-1',
            name: 'leadership',
            is_private: true,
            created_by: 'user-9',
            created_at: '2026-07-10T00:00:00.000Z',
            member_count: 5,
          },
          user_id: 'user-1',
          role: 'admin',
          joined_at: '2026-07-14T00:00:00.000Z',
        },
      });
    });

    expect(useMyChannelsStore.getState().channels).toEqual([
      {
        id: 'chan-1',
        name: 'leadership',
        is_private: true,
        created_by: 'user-9',
        created_at: '2026-07-10T00:00:00.000Z',
        member_count: 5,
        my_role: 'admin',
      },
    ]);

    // A duplicate/replayed event for the same id is idempotent, not a second row.
    act(() => {
      onFrame({
        type: 'channel.member_added',
        conversation: { kind: 'channel', channel_id: 'chan-1' },
        data: {
          channel: {
            id: 'chan-1',
            name: 'leadership',
            is_private: true,
            created_by: 'user-9',
            created_at: '2026-07-10T00:00:00.000Z',
            member_count: 6,
          },
          user_id: 'user-1',
          role: 'admin',
          joined_at: '2026-07-14T00:00:00.000Z',
        },
      });
    });

    expect(useMyChannelsStore.getState().channels).toHaveLength(1);
    expect(useMyChannelsStore.getState().channels[0].member_count).toBe(6);
  });

  it('removes a channel by id on a channel.member_removed frame (F75)', () => {
    useMyChannelsStore.setState({ channels: [channel({ id: 'chan-1' }), channel({ id: 'chan-2' })] });

    renderHook(() => useChannelMembershipSocket());
    const onFrame = currentSocket().options.onFrame as (frame: unknown) => void;

    act(() => {
      onFrame({
        type: 'channel.member_removed',
        conversation: { kind: 'channel', channel_id: 'chan-1' },
        data: { channel_id: 'chan-1', user_id: 'user-1' },
      });
    });

    expect(useMyChannelsStore.getState().channels.map((c) => c.id)).toEqual(['chan-2']);
  });

  it('raises the removal notice when the removed channel is the one currently open', () => {
    useMyChannelsStore.setState({ channels: [channel({ id: 'chan-1' })], viewedChannelId: 'chan-1' });

    renderHook(() => useChannelMembershipSocket());
    const onFrame = currentSocket().options.onFrame as (frame: unknown) => void;

    act(() => {
      onFrame({
        type: 'channel.member_removed',
        conversation: { kind: 'channel', channel_id: 'chan-1' },
        data: { channel_id: 'chan-1', user_id: 'user-1' },
      });
    });

    expect(useMyChannelsStore.getState().removedChannelId).toBe('chan-1');
  });

  it('tolerates a malformed channel.member_added payload without throwing', () => {
    renderHook(() => useChannelMembershipSocket());
    const onFrame = currentSocket().options.onFrame as (frame: unknown) => void;

    expect(() =>
      act(() => {
        onFrame({ type: 'channel.member_added', conversation: null, data: { channel: {} } });
      }),
    ).not.toThrow();
    expect(useMyChannelsStore.getState().channels).toEqual([]);
  });

  it('tolerates a malformed channel.member_removed payload without throwing', () => {
    useMyChannelsStore.setState({ channels: [channel({ id: 'chan-1' })] });
    renderHook(() => useChannelMembershipSocket());
    const onFrame = currentSocket().options.onFrame as (frame: unknown) => void;

    expect(() =>
      act(() => {
        onFrame({ type: 'channel.member_removed', data: {} });
      }),
    ).not.toThrow();
    expect(useMyChannelsStore.getState().channels).toHaveLength(1);
  });

  it('ignores unrecognized frame types without error (open enum, e.g. message.*/typing/presence)', () => {
    renderHook(() => useChannelMembershipSocket());
    const onFrame = currentSocket().options.onFrame as (frame: unknown) => void;

    expect(() => act(() => onFrame({ type: 'typing', data: {} }))).not.toThrow();
    expect(() => act(() => onFrame({ type: 'message.created', data: {} }))).not.toThrow();
    expect(useMyChannelsStore.getState().channels).toEqual([]);
  });

  it('refetches the my-channels list on every WS open, including reconnects (no-replay catch-up)', async () => {
    listMyChannelsMock.mockResolvedValueOnce({ items: [channel({ id: 'chan-1' })], next_cursor: null });

    renderHook(() => useChannelMembershipSocket());
    const onStatusChange = currentSocket().options.onStatusChange as (status: string) => void;

    act(() => onStatusChange('open'));
    await waitFor(() => expect(useMyChannelsStore.getState().channels).toHaveLength(1));
    expect(listMyChannelsMock).toHaveBeenCalledTimes(1);

    listMyChannelsMock.mockResolvedValueOnce({
      items: [channel({ id: 'chan-1' }), channel({ id: 'chan-2' })],
      next_cursor: null,
    });

    // Reconnect after a drop — membership events have no replay (contract
    // line 725), so this refetch is the sole recovery path.
    act(() => onStatusChange('reconnecting'));
    act(() => onStatusChange('open'));
    await waitFor(() => expect(useMyChannelsStore.getState().channels).toHaveLength(2));
    expect(listMyChannelsMock).toHaveBeenCalledTimes(2);
  });

  it('on a fatal revoked/deactivated close, clears the local session', () => {
    const clearSessionSpy = vi.fn();
    useAuthStore.setState({ clearSession: clearSessionSpy } as unknown as Partial<
      ReturnType<typeof useAuthStore.getState>
    >);

    renderHook(() => useChannelMembershipSocket());
    const onFatal = currentSocket().options.onFatal as (reason: string) => void;

    act(() => onFatal('revoked'));

    expect(clearSessionSpy).toHaveBeenCalledTimes(1);
  });

  it('does not clear the session on a non-terminal fatal reason (auth-failed)', () => {
    const clearSessionSpy = vi.fn();
    useAuthStore.setState({ clearSession: clearSessionSpy } as unknown as Partial<
      ReturnType<typeof useAuthStore.getState>
    >);

    renderHook(() => useChannelMembershipSocket());
    const onFatal = currentSocket().options.onFatal as (reason: string) => void;

    act(() => onFatal('auth-failed'));

    expect(clearSessionSpy).not.toHaveBeenCalled();
  });
});
